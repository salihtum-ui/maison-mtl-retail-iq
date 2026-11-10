"""Dedicated Entra service principal used only by the Fabric mirroring connection to the mtl_retail database.

The client secret is minted in memory by `new_secret()` and handed straight to the Fabric connection API; it is never
printed, logged or written to disk. Only non-secret identifiers are saved in artifacts/spn.json.
"""
from datetime import datetime, timedelta, timezone
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import fabric as f

GRAPH = "https://graph.microsoft.com/v1.0"
_teardown = {"enabled": False}
NOTES = "Maison MTL Retail IQ demo: Fabric mirroring of the synthetic mtl_retail Azure SQL database only."


def name():
    return f.cfg()["mirroring"]["servicePrincipalName"]


def graph(endpoint, method="GET", body=None):
    if method != "GET":
        tracked = "/applications/" + f.load("spn.json")["applicationObjectId"] if f.exists("spn.json") else None
        allowed = (method == "POST" and endpoint in ("/applications", "/servicePrincipals")) or (
            tracked and method == "POST" and endpoint in (tracked + "/addPassword", tracked + "/removePassword")) or (
            tracked and method == "DELETE" and endpoint == tracked and _teardown["enabled"])
        if not allowed:
            raise ValueError("Refusing an unexpected Microsoft Graph write")
    request = Request(GRAPH + endpoint, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer " + f.token("https://graph.microsoft.com"),
                               "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        raise RuntimeError(f"Graph {method} {endpoint}: HTTP {error.code}: {error.read().decode()[:1000]}") from None


def create():
    if f.exists("spn.json"):
        saved = f.load("spn.json")
        app = graph("/applications/" + saved["applicationObjectId"] + "?$select=id,appId,displayName")
        if app["appId"] != saved["appId"] or app["displayName"] != name():
            raise RuntimeError("Tracked application drifted")
        return saved
    existing = graph("/applications?$filter=displayName%20eq%20'" + name() + "'&$select=id,appId")["value"]
    if existing:
        raise RuntimeError("Untracked application with the same name exists; refusing to adopt it")
    app = graph("/applications", "POST", {"displayName": name(), "signInAudience": "AzureADMyOrg", "notes": NOTES})
    sp = graph("/servicePrincipals", "POST", {"appId": app["appId"], "notes": NOTES})
    saved = {"displayName": name(), "appId": app["appId"], "applicationObjectId": app["id"],
             "servicePrincipalObjectId": sp["id"], "tenantId": f.cfg()["tenantId"],
             "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    f.save("spn.json", saved)
    return saved


def new_secret(days=180):
    """Return (keyId, secretText). The caller must never persist or print secretText."""
    saved = f.load("spn.json")
    end = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = graph("/applications/" + saved["applicationObjectId"] + "/addPassword", "POST",
                   {"passwordCredential": {"displayName": "fabric-mirroring-connection", "endDateTime": end}})
    return result["keyId"], result["secretText"]


def remove_secret(key_id):
    saved = f.load("spn.json")
    graph("/applications/" + saved["applicationObjectId"] + "/removePassword", "POST", {"keyId": key_id})


def delete():
    """Teardown only: delete the tracked app registration (its service principal and secrets go with it)."""
    if not f.exists("spn.json"):
        return {"deleted": None}
    saved = f.load("spn.json")
    _teardown["enabled"] = True
    try:
        graph("/applications/" + saved["applicationObjectId"], "DELETE")
    except RuntimeError as error:
        if "HTTP 404" not in str(error):
            raise
    finally:
        _teardown["enabled"] = False
    return {"deleted": saved["appId"], "displayName": saved["displayName"]}


def credentials():
    saved = f.load("spn.json")
    app = graph("/applications/" + saved["applicationObjectId"] + "?$select=passwordCredentials")
    return [{"keyId": c["keyId"], "displayName": c["displayName"], "endDateTime": c["endDateTime"]}
            for c in app["passwordCredentials"]]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create", "credentials"])
    command = parser.parse_args().command
    print(json.dumps(create() if command == "create" else credentials(), indent=2))
