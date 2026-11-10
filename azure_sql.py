"""Create and load the SYNTHETIC Maison MTL operational database (Azure SQL Database, serverless).

Two network modes, chosen with `sql.network` in config.json:

- public:  the server accepts public traffic. `run` adds a firewall rule for this machine's public IP, loads the data
           with Entra token auth, creates the mirroring user and verifies, then always removes that rule. The
           "Allow Azure services" rule is kept so Fabric mirroring can reach the server without a gateway.
           With `sql.createServer: true` the resource group and an Entra-only server (deployer as Entra admin,
           system-assigned identity) are created first.
- private: the server is reachable only through a private endpoint (for example when Azure Policy forces public
           network access off). `create` makes the database; the seed load runs from a throwaway Fabric workspace
           through a managed private endpoint (seed_loader.py) and mirroring uses a VNet data gateway.
"""
import base64
import json
import shutil
import subprocess
import time
from urllib.request import urlopen

import fabric as f
import mtl_data as d
import settings
import spn

RULE = "mtl-retail-iq-deployer"
AZURE_SERVICES_RULE = "AllowAllWindowsAzureIps"
TAGS = ["demo=maison-mtl-retail-iq", "data=synthetic"]


def sql_cfg():
    return settings.get()["sql"]


def rg():
    return sql_cfg()["resourceGroup"]


def server_name():
    return sql_cfg()["serverName"]


def fqdn():
    return settings.sql_fqdn()


def database():
    return sql_cfg()["database"]


DDL = {
    "stores": """CREATE TABLE dbo.stores (store_id INT NOT NULL CONSTRAINT pk_stores PRIMARY KEY,
        store_code NVARCHAR(20) NOT NULL, store_name NVARCHAR(100) NOT NULL, city NVARCHAR(60) NOT NULL,
        region NVARCHAR(60) NOT NULL, province NVARCHAR(20) NULL, store_format NVARCHAR(40) NOT NULL,
        opened_year INT NOT NULL, selling_area_sqft INT NOT NULL, latitude DECIMAL(9,6) NOT NULL,
        longitude DECIMAL(9,6) NOT NULL, location_type NVARCHAR(30) NOT NULL, traffic_index DECIMAL(4,2) NOT NULL,
        dc_transfer_days INT NOT NULL, updated_at DATETIME2(3) NOT NULL)""",
    "suppliers": """CREATE TABLE dbo.suppliers (supplier_id INT NOT NULL CONSTRAINT pk_suppliers PRIMARY KEY,
        supplier_code NVARCHAR(20) NOT NULL, supplier_name NVARCHAR(100) NOT NULL, country NVARCHAR(60) NULL,
        lead_time_days INT NOT NULL, on_time_pct DECIMAL(5,2) NOT NULL, updated_at DATETIME2(3) NOT NULL)""",
    "products": """CREATE TABLE dbo.products (product_id INT NOT NULL CONSTRAINT pk_products PRIMARY KEY,
        sku NVARCHAR(20) NOT NULL, product_name NVARCHAR(120) NOT NULL, department NVARCHAR(40) NOT NULL,
        category NVARCHAR(60) NULL, subcategory NVARCHAR(60) NULL, brand NVARCHAR(60) NULL,
        supplier_code NVARCHAR(20) NOT NULL, unit_cost DECIMAL(10,2) NOT NULL, unit_price DECIMAL(10,2) NOT NULL,
        season_profile NVARCHAR(30) NOT NULL, case_pack INT NOT NULL, lead_time_days INT NOT NULL,
        reorder_point INT NOT NULL, safety_stock INT NOT NULL, is_active BIT NOT NULL, updated_at DATETIME2(3) NOT NULL)""",
    "sales_daily": """CREATE TABLE dbo.sales_daily (sales_id BIGINT NOT NULL CONSTRAINT pk_sales_daily PRIMARY KEY,
        sale_date DATE NOT NULL, store_code NVARCHAR(20) NOT NULL, sku NVARCHAR(20) NOT NULL, units_sold INT NULL,
        gross_sales DECIMAL(12,2) NULL, discount_amount DECIMAL(12,2) NULL, net_sales DECIMAL(12,2) NULL,
        pos_batch_id NVARCHAR(40) NOT NULL, loaded_at DATETIME2(3) NOT NULL)""",
    "inventory_daily": """CREATE TABLE dbo.inventory_daily (snapshot_id BIGINT NOT NULL CONSTRAINT pk_inventory_daily
        PRIMARY KEY, snapshot_date DATE NOT NULL, store_code NVARCHAR(20) NOT NULL, sku NVARCHAR(20) NOT NULL,
        on_hand_units INT NULL, on_order_units INT NOT NULL, received_units INT NOT NULL,
        reorder_point_units INT NOT NULL, safety_stock_units INT NOT NULL, loaded_at DATETIME2(3) NOT NULL)""",
    "replenishment_orders": """CREATE TABLE dbo.replenishment_orders (order_id INT NOT NULL CONSTRAINT
        pk_replenishment_orders PRIMARY KEY, order_number NVARCHAR(30) NOT NULL, order_type NVARCHAR(30) NOT NULL,
        sku NVARCHAR(20) NOT NULL, from_location NVARCHAR(20) NOT NULL, to_location NVARCHAR(20) NOT NULL,
        order_date DATE NOT NULL, expected_date DATE NOT NULL, received_date DATE NULL, ordered_units INT NOT NULL,
        received_units INT NOT NULL, status NVARCHAR(20) NOT NULL, loaded_at DATETIME2(3) NOT NULL)""",
}


def az(*args, parse=True):
    output = subprocess.check_output([shutil.which("az"), *args, "--subscription", settings.get()["subscriptionId"],
                                      "-o", "json"], text=True)
    return json.loads(output) if parse and output.strip() else output


def az_optional(*args):
    """Run an az `show` command; return None when the resource does not exist."""
    result = subprocess.run([shutil.which("az"), *args, "--subscription", settings.get()["subscriptionId"], "-o", "json"],
                            capture_output=True, text=True)
    if result.returncode == 0:
        return json.loads(result.stdout) if result.stdout.strip() else None
    if any(code in result.stderr for code in ("ResourceNotFound", "ResourceGroupNotFound", "NotFound", "could not be found")):
        return None
    raise RuntimeError("az " + " ".join(args) + " failed: " + result.stderr.strip()[:800])


def deployer():
    """Object ID and UPN of the signed-in deployer, read from the Azure CLI token for the configured tenant."""
    payload = f.token("https://management.azure.com/").split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    upn = claims.get("upn") or claims.get("unique_name")
    if claims.get("idtyp") == "app" or not upn:
        raise RuntimeError("Sign in to the Azure CLI as a user: the deployer becomes the server's Entra admin")
    return {"objectId": claims["oid"], "upn": upn}


def server():
    return az("sql", "server", "show", "-g", rg(), "-n", server_name())


def ensure_server():
    """Validate (or, in public mode with createServer, create) the logical server and record what was created."""
    cfg = sql_cfg()
    state = f.load("azure-sql-server.json") if f.exists("azure-sql-server.json") else {}
    if cfg["createServer"] and az_optional("group", "show", "-n", rg()) is None:
        az("group", "create", "-n", rg(), "-l", cfg["location"], "--tags", *TAGS)
        state["resourceGroupCreatedByDeploy"] = True
    current = az_optional("sql", "server", "show", "-g", rg(), "-n", server_name())
    if current is None:
        if not cfg["createServer"]:
            raise RuntimeError(f"SQL server {server_name()} not found in {rg()}; set sql.createServer or fix the name")
        admin = deployer()
        az("sql", "server", "create", "-g", rg(), "-n", server_name(), "-l", cfg["location"], "--enable-ad-only-auth",
           "--external-admin-principal-type", "User", "--external-admin-name", admin["upn"],
           "--external-admin-sid", admin["objectId"], "--assign-identity", "--identity-type", "SystemAssigned",
           "--minimal-tls-version", "1.2")
        state["serverCreatedByDeploy"] = True
        current = server()
    identity = (current.get("identity") or {}).get("principalId")
    if not identity:
        raise RuntimeError("The SQL server has no system-assigned managed identity, which Fabric mirroring requires. "
                           f"Enable it: az sql server update -g {rg()} -n {server_name()} --assign-identity")
    if cfg["network"] == "public" and current.get("publicNetworkAccess") != "Enabled":
        raise RuntimeError("Public network access is disabled on the server (often enforced by Azure Policy). "
                           "Use sql.network = 'private' with a VNet data gateway (docs/DEPLOYMENT.md).")
    state.update({"id": current["id"], "name": current["name"], "fqdn": current["fullyQualifiedDomainName"],
                  "network": cfg["network"], "publicNetworkAccess": current.get("publicNetworkAccess"),
                  "identityPrincipalId": identity})
    state.setdefault("serverCreatedByDeploy", False)
    state.setdefault("resourceGroupCreatedByDeploy", False)
    f.save("azure-sql-server.json", state)
    return state


def create():
    ensure_server()
    tracked = f.load("azure-sql.json") if f.exists("azure-sql.json") else {}
    existing = [db["name"] for db in az("sql", "db", "list", "-g", rg(), "-s", server_name())]
    created = tracked.get("createdByDeploy", False)
    if database() not in existing:
        az("sql", "db", "create", "-g", rg(), "-s", server_name(), "-n", database(), "--edition", "GeneralPurpose",
           "--family", "Gen5", "--capacity", "1", "--compute-model", "Serverless",
           "--auto-pause-delay", str(sql_cfg()["autoPauseDelayMinutes"]), "--min-capacity", "0.5",
           "--max-size", "10GB", "--backup-storage-redundancy", "Local", "--zone-redundant", "false", "--tags", *TAGS)
        created = True
    db = az("sql", "db", "show", "-g", rg(), "-s", server_name(), "-n", database())
    evidence = {"id": db["id"], "name": db["name"], "sku": db["currentSku"], "autoPauseDelay": db["autoPauseDelay"],
                "minCapacity": db["minCapacity"], "maxSizeBytes": db["maxSizeBytes"], "status": db["status"],
                "server": fqdn(), "createdByDeploy": created}
    f.save("azure-sql.json", evidence)
    return evidence


def public_ip():
    with urlopen("https://api.ipify.org", timeout=30) as response:
        return response.read().decode().strip()


def firewall_rules():
    return [r["name"] for r in az("sql", "server", "firewall-rule", "list", "-g", rg(), "-s", server_name())]


def open_firewall():
    """Public mode only: allow this machine's IP (temporary) and Azure services (for mirroring)."""
    if settings.is_private():
        raise RuntimeError("Firewall rules are only used with sql.network = 'public'")
    ip = public_ip()
    az("sql", "server", "firewall-rule", "create", "-g", rg(), "-s", server_name(), "-n", RULE,
       "--start-ip-address", ip, "--end-ip-address", ip)
    state = f.load("sql-firewall.json") if f.exists("sql-firewall.json") else {}
    if AZURE_SERVICES_RULE not in firewall_rules():
        az("sql", "server", "firewall-rule", "create", "-g", rg(), "-s", server_name(), "-n", AZURE_SERVICES_RULE,
           "--start-ip-address", "0.0.0.0", "--end-ip-address", "0.0.0.0")
        state["azureServicesRuleCreatedByDeploy"] = True
    state.update({"openedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "deployerRule": RULE,
                  "scope": "single client IP"})
    state.setdefault("azureServicesRuleCreatedByDeploy", False)
    f.save("sql-firewall.json", state)
    print("Temporary firewall rule for this machine's IP created", flush=True)
    time.sleep(30)


def close_firewall():
    if RULE in firewall_rules():
        az("sql", "server", "firewall-rule", "delete", "-g", rg(), "-s", server_name(), "-n", RULE, parse=False)
    remaining = firewall_rules()
    state = f.load("sql-firewall.json") if f.exists("sql-firewall.json") else {}
    state.update({"closedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "firewallRules": remaining})
    f.save("sql-firewall.json", state)
    if RULE in remaining:
        raise RuntimeError("The deployer firewall rule could not be removed")
    print("Deployer firewall rule removed", flush=True)
    return state


def connect(name=None):
    return f.sql_connect(fqdn(), name or database(), app="MtlRetailLoader")


def sql_types():
    import pyodbc
    text = (pyodbc.SQL_WVARCHAR, 120, 0)
    integer = (pyodbc.SQL_INTEGER, 0, 0)
    bigint = (pyodbc.SQL_BIGINT, 0, 0)
    money = (pyodbc.SQL_DECIMAL, 12, 2)
    day = (pyodbc.SQL_TYPE_DATE, 0, 0)
    stamp = (pyodbc.SQL_TYPE_TIMESTAMP, 23, 3)
    return {
        "stores": [integer, text, text, text, text, text, text, integer, integer, (pyodbc.SQL_DECIMAL, 9, 6),
                   (pyodbc.SQL_DECIMAL, 9, 6), text, (pyodbc.SQL_DECIMAL, 4, 2), integer, stamp],
        "suppliers": [integer, text, text, text, integer, (pyodbc.SQL_DECIMAL, 5, 2), stamp],
        "products": [integer, text, text, text, text, text, text, text, money, money, text, integer, integer,
                     integer, integer, (pyodbc.SQL_BIT, 0, 0), stamp],
        "sales_daily": [bigint, day, text, text, integer, money, money, money, text, stamp],
        "inventory_daily": [bigint, day, text, text, integer, integer, integer, integer, integer, stamp],
        "replenishment_orders": [integer, text, text, text, text, text, day, day, day, integer, integer, text, stamp],
    }


def load():
    from decimal import Decimal
    tables, _ = d.raw_tables()
    conn = connect()
    cursor = conn.cursor()
    types = sql_types()
    counts = {}
    for name, ddl in DDL.items():
        exists = cursor.execute("SELECT COUNT(*) FROM sys.tables WHERE name = ? AND schema_id = SCHEMA_ID('dbo')",
                                name).fetchval()
        expected = len(tables[name])
        if exists:
            current = cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.{name}").fetchval()
            if current == expected:
                counts[name] = current
                print(name, "already loaded", current, flush=True)
                continue
            if current:
                raise RuntimeError(f"{name} has {current} rows, expected {expected}; refusing to append")
        else:
            cursor.execute(ddl)
        columns = d.COLUMNS[name]
        rows = [tuple(Decimal(str(v)) if isinstance(v, float) else v for v in row) for row in tables[name]]
        insert = f"INSERT INTO dbo.{name} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
        conn.autocommit = False
        started = time.time()
        for start in range(0, len(rows), 20000):
            batch = conn.cursor()
            batch.fast_executemany = True
            batch.setinputsizes(types[name])
            batch.executemany(insert, rows[start:start + 20000])
            conn.commit()
        conn.autocommit = True
        counts[name] = cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.{name}").fetchval()
        print(name, counts[name], f"{time.time() - started:.0f}s", flush=True)
        if counts[name] != expected:
            raise RuntimeError(f"{name}: loaded {counts[name]}, expected {expected}")
    return counts


def create_mirroring_user():
    principal = spn.create()
    name = principal["displayName"]
    conn = connect()
    cursor = conn.cursor()
    exists = cursor.execute("SELECT COUNT(*) FROM sys.database_principals WHERE name = ?", name).fetchval()
    method = "existing"
    if not exists:
        try:
            cursor.execute(f"CREATE USER [{name}] FROM EXTERNAL PROVIDER")
            method = "FROM EXTERNAL PROVIDER"
        except Exception as error:
            print("FROM EXTERNAL PROVIDER failed; using the application ID SID:", str(error)[:200], flush=True)
            cursor.execute(f"CREATE USER [{name}] WITH SID = CONVERT(varbinary(16), CAST(? AS uniqueidentifier)), "
                           "TYPE = E", principal["appId"])
            method = "SID"
    cursor.execute(f"GRANT SELECT, ALTER ANY EXTERNAL MIRROR, VIEW DATABASE PERFORMANCE STATE, "
                   f"VIEW DATABASE SECURITY STATE TO [{name}]")
    grants = [row[0] for row in cursor.execute(
        "SELECT p.permission_name FROM sys.database_permissions p JOIN sys.database_principals u "
        "ON u.principal_id = p.grantee_principal_id WHERE u.name = ? ORDER BY 1", name).fetchall()]
    try:
        identities = [list(row) for row in cursor.execute(
            "SELECT CAST(identity_type AS nvarchar(40)), CAST(is_primary AS int) FROM sys.dm_server_managed_identities"
        ).fetchall()]
    except Exception as error:
        identities = ["unavailable: " + str(error)[:120]]
    evidence = {"user": name, "type": "Contained Entra service principal user", "method": method,
                "permissions": grants}
    f.save("sql-mirroring-user.json", evidence)
    return evidence | {"serverIdentities": identities}


def verify():
    tables, _ = d.raw_tables()
    truth = d.truth()
    conn = connect()
    cursor = conn.cursor()
    counts = {name: cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.{name}").fetchval() for name in DDL}
    keys = {row[0]: row[1] for row in cursor.execute(
        "SELECT t.name, COUNT(*) FROM sys.tables t JOIN sys.indexes i ON i.object_id = t.object_id "
        "AND i.is_primary_key = 1 GROUP BY t.name").fetchall()}
    net2025 = float(cursor.execute("SELECT SUM(net_sales) FROM (SELECT net_sales, ROW_NUMBER() OVER (PARTITION BY "
        "sale_date, UPPER(REPLACE(LTRIM(RTRIM(store_code)), '_', '-')), UPPER(LTRIM(RTRIM(sku))) ORDER BY loaded_at DESC) rn "
        "FROM dbo.sales_daily WHERE units_sold > 0 AND YEAR(sale_date) = 2025 AND UPPER(LTRIM(RTRIM(sku))) IN "
        "(SELECT sku FROM dbo.products) AND UPPER(REPLACE(LTRIM(RTRIM(store_code)), '_', '-')) IN "
        "(SELECT store_code FROM dbo.stores WHERE location_type = 'Store')) s WHERE rn = 1").fetchval())
    evidence = {"database": database(), "server": fqdn(), "rows": counts,
                "expectedRows": {name: len(rows) for name, rows in tables.items()},
                "primaryKeys": keys, "cleanNetSales2025": round(net2025, 2),
                "expectedNetSales2025": truth["netSales2025"]}
    f.save("azure-sql-verification.json", evidence)
    if counts != evidence["expectedRows"] or set(keys) != set(DDL) or abs(net2025 - truth["netSales2025"]) > 0.05:
        raise RuntimeError("Azure SQL verification failed: " + json.dumps(evidence, default=str))
    return evidence


def run():
    """Public mode: open the deployer rule, load, create the mirroring user, verify, and always remove the rule."""
    if settings.is_private():
        raise RuntimeError("sql.network is 'private': seed the database with seed_loader.py (deploy.py seed)")
    create()
    try:
        open_firewall()
        counts = load()
        user = create_mirroring_user()
        checked = verify()
    finally:
        closed = close_firewall()
    return {"rows": counts, "user": user, "verification": checked["cleanNetSales2025"], "firewall": closed}


def status():
    state = server()
    db = az_optional("sql", "db", "show", "-g", rg(), "-s", server_name(), "-n", database()) or {}
    return {"server": state["fullyQualifiedDomainName"], "publicNetworkAccess": state.get("publicNetworkAccess"),
            "firewallRules": firewall_rules(), "database": db.get("status")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create", "run", "close", "status"])
    command = parser.parse_args().command
    result = {"create": create, "run": run, "close": close_firewall, "status": status}[command]()
    print(json.dumps(result, indent=2, default=str))
