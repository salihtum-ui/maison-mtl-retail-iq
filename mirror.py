"""Mirror the mtl_retail Azure SQL database into Fabric.

- private network mode: the connection goes through the configured VNet data gateway.
- public network mode: a cloud (ShareableCloud) connection; the server's "Allow Azure services" rule must be on.

The connection authenticates with the dedicated service principal. Its client secret is minted in memory, sent only to
the Fabric connection API and never printed or written to disk.
"""
import base64
import json
import time

import fabric as f
import mtl_data as d
import settings
import spn
from azure_sql import DDL, database, fqdn

MIRROR_NAME = "MtlRetail_MirroredSQL"
TABLES = list(DDL)


def gateway():
    return settings.get()["privateNetwork"]["gatewayId"] if settings.is_private() else None


def connection_body(app_id, secret):
    body = {
        "connectivityType": "VirtualNetworkGateway" if gateway() else "ShareableCloud",
        "displayName": f.cfg()["mirroring"]["connectionName"],
        "connectionDetails": {"type": "SQL", "creationMethod": "Sql", "parameters": [
            {"dataType": "Text", "name": "server", "value": fqdn()},
            {"dataType": "Text", "name": "database", "value": database()}]},
        "privacyLevel": "Organizational",
        "credentialDetails": {"singleSignOnType": "None", "connectionEncryption": "Encrypted",
                              "skipTestConnection": False,
                              "credentials": {"credentialType": "ServicePrincipal",
                                              "servicePrincipalClientId": app_id,
                                              "servicePrincipalSecret": secret, "tenantId": f.cfg()["tenantId"]}}}
    if gateway():
        body["gatewayId"] = gateway()
    return body


def connection():
    name = f.cfg()["mirroring"]["connectionName"]
    if f.exists("connection.json"):
        current = f.api("/connections/" + f.load("connection.json")["id"])
        if current["displayName"] != name or current.get("gatewayId") != gateway():
            raise RuntimeError("Tracked connection drifted")
        return current
    if any(c["displayName"] == name for c in f.listing("/connections")):
        raise RuntimeError("Untracked connection with the same name exists; refusing to adopt it")
    principal = spn.create()
    key_id, secret = spn.new_secret(f.cfg()["mirroring"]["secretLifetimeDays"])
    body = connection_body(principal["appId"], secret)
    try:
        last = None
        for attempt in range(6):
            try:
                current = f.api("/connections", "POST", body)
                break
            except RuntimeError as error:
                last = str(error).replace(secret, "***")
                print(f"Connection test not ready (attempt {attempt + 1}): {last[:300]}", flush=True)
                time.sleep(45)
        else:
            raise RuntimeError("Connection creation failed: " + (last or "")[:1500])
    except BaseException:
        spn.remove_secret(key_id)
        raise
    finally:
        body = secret = None
    f.save("connection.json", {key: current.get(key) for key in
                               ("id", "displayName", "gatewayId", "connectivityType", "connectionDetails",
                                "privacyLevel")} | {"credentialType": "ServicePrincipal",
                                                    "servicePrincipalAppId": principal["appId"],
                                                    "secretKeyId": key_id})
    return current


def definition():
    mirroring = {"properties": {
        "source": {"type": "AzureSqlDatabase",
                   "typeProperties": {"connection": f.load("connection.json")["id"], "database": database()}},
        "target": {"type": "MountedRelationalDatabase", "typeProperties": {"defaultSchema": "dbo", "format": "Delta"}}}}
    return {"parts": [f.part("mirroring.json", mirroring)]}


def create():
    current = f.item("mirror", "mirroredDatabases", MIRROR_NAME, definition())
    readback = f.api(f.path() + "/mirroredDatabases/" + current["id"] + "/getDefinition", "POST")
    parts = {p["path"]: json.loads(base64.b64decode(p["payload"])) for p in readback["definition"]["parts"]
             if p["path"].endswith(".json")}
    f.save("mirror-definition.json", parts)
    return current


def start():
    base = f.path() + "/mirroredDatabases/" + f.load("mirror.json")["id"]
    for _ in range(40):
        state = f.api(base + "/getMirroringStatus", "POST")
        if state.get("status") != "Initializing":
            break
        time.sleep(15)
    if state.get("status") in ("Initialized", "Stopped"):
        f.request(base + "/startMirroring", "POST")
    elif state.get("status") not in ("Starting", "Running"):
        raise RuntimeError("Unexpected mirroring state: " + json.dumps(state))
    time.sleep(30)
    return f.api(base + "/getMirroringStatus", "POST")


def status(polls=60):
    base = f.path() + "/mirroredDatabases/" + f.load("mirror.json")["id"]
    previous = None
    for _ in range(polls):
        overall = f.api(base + "/getMirroringStatus", "POST")
        tables = f.api(base + "/getTablesMirroringStatus", "POST").get("data", [])
        summary = {t["sourceTableName"]: (t["status"], (t.get("metrics") or {}).get("processedRows"))
                   for t in tables}
        snapshot = json.dumps([overall.get("status"), summary], sort_keys=True)
        if snapshot != previous:
            print(overall.get("status"), summary, flush=True)
            previous = snapshot
        f.save("mirror-status.json", {"overall": overall, "tables": tables})
        if overall.get("status") == "Running" and len(tables) == len(TABLES) and \
                all(t["status"] == "Replicating" for t in tables):
            return {"overall": overall, "tables": summary}
        if any(t["status"] == "Failed" for t in tables):
            raise RuntimeError(json.dumps(tables)[:3000])
        time.sleep(30)
    raise TimeoutError("Mirroring is not yet replicating every table")


def verify(polls=40):
    """Read back row counts through the mirrored database SQL analytics endpoint."""
    mirror = f.api(f.path() + "/mirroredDatabases/" + f.load("mirror.json")["id"])
    f.save("mirror.json", mirror)
    endpoint = mirror["properties"]["sqlEndpointProperties"]
    if not f.exists("expected.json"):
        f.save("expected.json", d.truth())
    expected = f.load("expected.json")["rawRows"]
    counts = {}
    for _ in range(polls):
        conn = f.sql_connect(endpoint["connectionString"], mirror["displayName"], app="MtlMirrorVerify")
        counts = {}
        for table in TABLES:
            try:
                counts[table] = conn.cursor().execute(f"SELECT COUNT_BIG(*) FROM dbo.{table}").fetchval()
            except Exception as error:
                counts[table] = "unavailable: " + str(error)[:80]
        conn.close()
        print(counts, flush=True)
        if counts == expected:
            break
        time.sleep(30)
    evidence = {"mirroredDatabase": mirror["id"], "sqlEndpoint": endpoint["id"], "rows": counts, "expected": expected,
                "matches": counts == expected, "oneLakeTablesPath": mirror["properties"].get("oneLakeTablesPath")}
    f.save("mirror-verification.json", evidence)
    if not evidence["matches"]:
        raise RuntimeError("Mirrored row counts differ from the source")
    return evidence


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["connection", "create", "start", "status", "verify"])
    command = parser.parse_args().command
    result = {"connection": lambda: {k: v for k, v in connection().items() if k != "credentialDetails"},
              "create": create, "start": start, "status": status, "verify": verify}[command]()
    print(json.dumps(result, indent=2, default=str))
