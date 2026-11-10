"""Seed a private mtl_retail Azure SQL database from a throwaway Fabric loader workspace (sql.network = "private").

When the server only accepts private-endpoint traffic (for example because Azure Policy forces public network access
off), data is loaded through a Fabric managed private endpoint (MPE) by a notebook that runs as the signed-in admin.
The MPE lives in an isolated loader workspace so the demo workspace keeps Spark starter pools. After loading, the MPE
and the loader workspace are deleted.
"""
import json
import shutil
import subprocess
import time
from urllib.request import Request, urlopen

import fabric as f
import mtl_data as d
import settings
from azure_sql import DDL, database, fqdn

MPE_NAME = "mpe-mtl-retail-sql"


def server_id():
    return settings.sql_server_id()


def provision():
    f.use_loader()
    if not f.exists("loader-workspace.json"):
        if any(w["displayName"] == f.LOADER_WORKSPACE for w in f.listing("/workspaces")):
            raise RuntimeError("Untracked loader workspace exists; refusing to adopt it")
        f.save("loader-workspace.json", f.api("/workspaces", "POST", f.loader_body()))
    workspace = f.api(f.path())
    if workspace["displayName"] != f.LOADER_WORKSPACE or workspace.get("capacityId", "").lower() != f.CAPACITY.lower():
        raise RuntimeError("Loader workspace drifted")
    f.save("loader-workspace.json", workspace)
    lakehouse = f.item("loader-lakehouse", "lakehouses", "SeedLoader")
    return {"workspace": workspace["id"], "lakehouse": lakehouse["id"]}


def az(*args):
    output = subprocess.check_output([shutil.which("az"), *args, "--subscription", f.SUBSCRIPTION, "-o", "json"],
                                     text=True)
    return json.loads(output) if output.strip() else None


def mpe():
    f.use_loader()
    endpoints = f.listing(f.path() + "/managedPrivateEndpoints")
    current = next((e for e in endpoints if e["name"] == MPE_NAME), None)
    if not current:
        current = f.api(f.path() + "/managedPrivateEndpoints", "POST", {
            "name": MPE_NAME, "targetPrivateLinkResourceId": server_id(), "targetSubresourceType": "sqlServer",
            "requestMessage": "Maison MTL Retail IQ synthetic seed load (temporary)"})
    for _ in range(60):
        current = f.api(f.path() + "/managedPrivateEndpoints/" + current["id"])
        if current.get("provisioningState") == "Succeeded":
            break
        if current.get("provisioningState") == "Failed":
            raise RuntimeError(json.dumps(current))
        time.sleep(20)
    status = (current.get("connectionState") or {}).get("status")
    if status != "Approved":
        connections = az("network", "private-endpoint-connection", "list", "--id", server_id())
        pending = [c for c in connections if c["properties"]["privateLinkServiceConnectionState"]["status"] == "Pending"
                   and "Maison MTL" in (c["properties"]["privateLinkServiceConnectionState"].get("description") or "")]
        if len(pending) != 1:
            raise RuntimeError(f"Expected one pending Maison MTL connection, found {len(pending)}")
        az("network", "private-endpoint-connection", "approve", "--id", pending[0]["id"],
           "--description", "Approved for the synthetic Maison MTL seed load (temporary)")
        for _ in range(40):
            current = f.api(f.path() + "/managedPrivateEndpoints/" + current["id"])
            if (current.get("connectionState") or {}).get("status") == "Approved":
                break
            time.sleep(15)
    f.save("loader-mpe.json", current)
    return current


NOTEBOOK = r'''
import json, os, sys, time
from decimal import Decimal
spark.conf.set("spark.sql.session.timeZone", "UTC")
os.makedirs("/tmp/mtl_gen", exist_ok=True)
for name, source in SOURCES.items():
    with open("/tmp/mtl_gen/" + name, "w", encoding="utf-8") as handle:
        handle.write(source)
sys.path.insert(0, "/tmp/mtl_gen")
import mtl_data as d
tables, dq = d.raw_tables()
truth = d.truth()
assert {k: len(v) for k, v in tables.items()} == EXPECTED_ROWS, "Generator drifted from the local build"

URL = ("jdbc:sqlserver://" + SERVER + ":1433;database=" + DATABASE + ";encrypt=true;trustServerCertificate=false;"
       "hostNameInCertificate=*.database.windows.net;loginTimeout=90")
jvm = spark._sc._gateway.jvm

def token():
    errors = []
    for audience in ("https://database.windows.net/", "https://database.windows.net", "sql"):
        try:
            return notebookutils.credentials.getToken(audience)
        except Exception as error:
            errors.append(str(error)[:120])
    raise RuntimeError("No Azure SQL token: " + " | ".join(errors))

def connection():
    props = jvm.java.util.Properties()
    props.setProperty("accessToken", token())
    return jvm.java.sql.DriverManager.getConnection(URL, props)

def execute(statement):
    conn = connection()
    try:
        conn.createStatement().execute(statement)
    finally:
        conn.close()

def query(statement):
    conn = connection()
    try:
        rs = conn.createStatement().executeQuery(statement)
        columns = rs.getMetaData().getColumnCount()
        rows = []
        while rs.next():
            rows.append([None if rs.getObject(i) is None else str(rs.getObject(i)) for i in range(1, columns + 1)])
        return rows
    finally:
        conn.close()

identity = query("SELECT SUSER_SNAME(), DB_NAME(), CAST(SERVERPROPERTY('EngineEdition') AS int)")
print("Connected through the managed private endpoint as", identity[0][0], "to", identity[0][1])
'''

LOAD = r'''
from pyspark.sql import types as T
TYPES = {"int": T.IntegerType(), "bigint": T.LongType(), "text": T.StringType(), "money": T.DecimalType(12, 2),
         "date": T.DateType(), "ts": T.TimestampType(), "bit": T.BooleanType(), "geo": T.DecimalType(9, 6),
         "idx": T.DecimalType(4, 2), "pct": T.DecimalType(5, 2)}
loaded = {}
for name in ORDER:
    exists = int(query(f"SELECT COUNT(*) FROM sys.tables WHERE name = '{name}' AND schema_id = SCHEMA_ID('dbo')")[0][0])
    if not exists:
        execute(DDL[name])
    expected = len(tables[name])
    current = int(query(f"SELECT COUNT_BIG(*) FROM dbo.{name}")[0][0])
    if current != expected:
        if current:
            execute(f"TRUNCATE TABLE dbo.{name}")
        schema = T.StructType([T.StructField(column, TYPES[kind], True) for column, kind in SCHEMAS[name]])
        rows = [tuple(Decimal(str(v)) if isinstance(v, float) else v for v in row) for row in tables[name]]
        frame = spark.createDataFrame(rows, schema).repartition(4)
        started = time.time()
        (frame.write.format("jdbc").option("url", URL).option("dbtable", "dbo." + name)
            .option("accessToken", token()).option("batchsize", 10000)
            .option("driver", "com.microsoft.sqlserver.jdbc.SQLServerDriver").mode("append").save())
        print(name, "written in", round(time.time() - started), "s")
    loaded[name] = int(query(f"SELECT COUNT_BIG(*) FROM dbo.{name}")[0][0])
    assert loaded[name] == expected, f"{name}: {loaded[name]} != {expected}"
print("rows", loaded)
'''

USER = r'''
user = PRINCIPAL
if not int(query(f"SELECT COUNT(*) FROM sys.database_principals WHERE name = '{user}'")[0][0]):
    try:
        execute(f"CREATE USER [{user}] FROM EXTERNAL PROVIDER")
        method = "FROM EXTERNAL PROVIDER"
    except Exception as error:
        print("FROM EXTERNAL PROVIDER failed, using SID:", str(error)[:200])
        execute(f"CREATE USER [{user}] WITH SID = CONVERT(varbinary(16), CAST('{APP_ID}' AS uniqueidentifier)), TYPE = E")
        method = "SID"
else:
    method = "existing"
execute(f"GRANT SELECT, ALTER ANY EXTERNAL MIRROR, VIEW DATABASE PERFORMANCE STATE, VIEW DATABASE SECURITY STATE TO [{user}]")
permissions = [r[0] for r in query(f"SELECT p.permission_name FROM sys.database_permissions p JOIN sys.database_principals u "
                                   f"ON u.principal_id = p.grantee_principal_id WHERE u.name = '{user}' ORDER BY 1")]
keys = {r[0]: int(r[1]) for r in query("SELECT t.name, COUNT(*) FROM sys.tables t JOIN sys.indexes i ON i.object_id = t.object_id "
                                       "AND i.is_primary_key = 1 GROUP BY t.name")}
clean2025 = float(query("SELECT SUM(net_sales) FROM (SELECT net_sales, ROW_NUMBER() OVER (PARTITION BY sale_date, "
    "UPPER(REPLACE(LTRIM(RTRIM(store_code)), '_', '-')), UPPER(LTRIM(RTRIM(sku))) ORDER BY loaded_at DESC) rn "
    "FROM dbo.sales_daily WHERE units_sold > 0 AND YEAR(sale_date) = 2025 AND UPPER(LTRIM(RTRIM(sku))) IN "
    "(SELECT sku FROM dbo.products) AND UPPER(REPLACE(LTRIM(RTRIM(store_code)), '_', '-')) IN "
    "(SELECT store_code FROM dbo.stores WHERE location_type = 'Store')) s WHERE rn = 1")[0][0])
identities = query("SELECT CAST(identity_type AS nvarchar(40)), CAST(is_primary AS int) FROM sys.dm_server_managed_identities")
evidence = {"connectedAs": identity[0][0], "database": identity[0][1], "rows": loaded, "primaryKeys": keys,
            "mirroringUser": {"name": user, "method": method, "permissions": permissions},
            "cleanNetSales2025": round(clean2025, 2), "expectedNetSales2025": truth["netSales2025"],
            "serverManagedIdentities": identities, "verifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
assert set(keys) == set(ORDER), keys
assert abs(clean2025 - truth["netSales2025"]) < 0.05, (clean2025, truth["netSales2025"])
assert {"ALTER ANY EXTERNAL MIRROR", "SELECT", "VIEW DATABASE PERFORMANCE STATE", "VIEW DATABASE SECURITY STATE"} <= set(permissions)
notebookutils.fs.put("Files/seed/verification.json", json.dumps(evidence, indent=2), True)
print("MTL_RETAIL_SEED_VERIFIED", json.dumps(evidence))
'''

KINDS = {
    "stores": ["int", "text", "text", "text", "text", "text", "text", "int", "int", "geo", "geo", "text", "idx", "int", "ts"],
    "suppliers": ["int", "text", "text", "text", "int", "pct", "ts"],
    "products": ["int", "text", "text", "text", "text", "text", "text", "text", "money", "money", "text", "int", "int",
                 "int", "int", "bit", "ts"],
    "sales_daily": ["bigint", "date", "text", "text", "int", "money", "money", "money", "text", "ts"],
    "inventory_daily": ["bigint", "date", "text", "text", "int", "int", "int", "int", "int", "ts"],
    "replenishment_orders": ["int", "text", "text", "text", "text", "text", "date", "date", "date", "int", "int",
                             "text", "ts"],
}


def build():
    f.use_loader()
    sources = {name: (f.ROOT / name).read_text(encoding="utf-8") for name in ("mtl_reference.py", "mtl_data.py")}
    tables, _ = d.raw_tables()
    schemas = {name: list(zip(d.COLUMNS[name], kinds)) for name, kinds in KINDS.items()}
    principal = f.load("spn.json")
    setup = ("import json\nSOURCES = json.loads(" + repr(json.dumps(sources)) + ")\nSERVER = " + repr(fqdn()) +
             "\nDATABASE = " + repr(database()) + "\nEXPECTED_ROWS = " + repr({k: len(v) for k, v in tables.items()}) +
             "\nDDL = " + repr(DDL) + "\nORDER = " + repr(list(DDL)) + "\nSCHEMAS = " + repr(schemas) +
             "\nPRINCIPAL = " + repr(principal["displayName"]) + "\nAPP_ID = " + repr(principal["appId"]))
    return f.notebook("loader-seed", "00_Seed_mtl_retail_Azure_SQL", [
        f.cell("# Seed the SYNTHETIC mtl_retail Azure SQL database\nRuns as the signed-in admin through a managed "
               "private endpoint. Regenerates the deterministic raw data (with deliberate data-quality defects).", True),
        f.cell(setup), f.cell(NOTEBOOK), f.cell(LOAD), f.cell(USER)], lakehouse_key="loader-lakehouse")


def run(fresh=False):
    f.use_loader()
    return f.run_job("loader-seed", "RunNotebook", polls=180, interval=30, fresh=fresh)


def verify():
    f.use_loader()
    lakehouse = f.load("loader-lakehouse.json")["id"]
    url = f"https://onelake.dfs.fabric.microsoft.com/{f.ws()}/{lakehouse}/Files/seed/verification.json"
    request = Request(url, headers={"Authorization": "Bearer " + f.token("https://storage.azure.com/")})
    with urlopen(request, timeout=60) as response:
        evidence = json.loads(response.read())
    f.save("azure-sql-verification.json", evidence)
    return evidence


def cleanup():
    """Delete the MPE (removes the server-side private endpoint connection) and then the loader workspace."""
    f.use_loader()
    for endpoint in f.listing(f.path() + "/managedPrivateEndpoints"):
        if endpoint["name"] == MPE_NAME and endpoint.get("provisioningState") not in ("Deleting",):
            try:
                f.request(f.path() + "/managedPrivateEndpoints/" + endpoint["id"], "DELETE")
            except RuntimeError as error:
                print("MPE delete already in progress:", str(error)[:200], flush=True)
    for _ in range(40):
        remaining = [c["name"] for c in az("network", "private-endpoint-connection", "list", "--id", server_id())
                     if "Maison MTL" in (c["properties"]["privateLinkServiceConnectionState"].get("description") or "")]
        if not remaining:
            break
        time.sleep(15)
    workspace = f.load("loader-workspace.json")
    for _ in range(60):
        if not [e for e in f.listing(f.path() + "/managedPrivateEndpoints") if e["name"] == MPE_NAME]:
            break
        time.sleep(20)
    f.request("/workspaces/" + workspace["id"], "DELETE")
    evidence = {"deletedWorkspace": workspace["id"], "deletedWorkspaceName": workspace["displayName"],
                "managedPrivateEndpoint": MPE_NAME, "serverConnectionsRemaining": remaining,
                "deletedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    f.save("loader-cleanup.json", evidence)
    return evidence


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["provision", "mpe", "build", "run", "verify", "cleanup"])
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    result = run(args.fresh) if args.command == "run" else \
        {"provision": provision, "mpe": mpe, "build": build, "verify": verify, "cleanup": cleanup}[args.command]()
    print(json.dumps(result, indent=2, default=str))
