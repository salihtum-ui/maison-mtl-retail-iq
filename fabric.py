"""Scoped Fabric operator for the synthetic Maison MTL Retail IQ workspace.

Every write is fail-closed: only the exact workspace creation, writes inside the tracked workspace, the creation of
one named connection, and Power BI calls against the tracked workspace are allowed. Deleting the tracked demo
workspace or connection is only possible after `allow_teardown()` (used by `deploy.py teardown`).
"""
import base64
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import settings

ROOT = Path(__file__).resolve().parent
ART = Path(os.environ.get("MTL_ARTIFACTS") or ROOT / "artifacts")
BASE = "https://api.fabric.microsoft.com/v1"
PBI = "https://api.powerbi.com/v1.0/myorg"
DESCRIPTION = ("SYNTHETIC Maison MTL retail demo (fictional Quebec retailer): Azure SQL mirroring, medallion lakehouses, "
               "ML forecasting, Direct Lake model, Fabric IQ ontology, Data Agent and Fabric App. Illustrative data only.")
LOADER_DESCRIPTION = ("TEMPORARY loader workspace for the SYNTHETIC Maison MTL Azure SQL database: managed private "
                      "endpoint + seed notebook. Isolated so the demo workspace keeps Spark starter pools.")
_tokens = {}
_active = {"file": "workspace.json", "teardown": False}

# Environment values resolved lazily from settings so modules can be imported (and unit tested) without a config.
_SETTINGS = {
    "TENANT": lambda c: c["tenantId"],
    "SUBSCRIPTION": lambda c: c["subscriptionId"],
    "CAPACITY": lambda c: c["fabric"]["capacityId"],
    "WORKSPACE": lambda c: c["fabric"]["workspaceName"],
    "LOADER_WORKSPACE": lambda c: c["fabric"]["loaderWorkspaceName"],
    "CONNECTION_NAME": lambda c: c["mirroring"]["connectionName"],
}


def __getattr__(name):
    if name in _SETTINGS:
        return _SETTINGS[name](settings.get())
    raise AttributeError(name)


def cfg():
    return settings.get()


def use_loader(enabled=True):
    """Switch the scoped operator between the demo workspace and the throwaway loader workspace."""
    _active["file"] = "loader-workspace.json" if enabled else "workspace.json"


def allow_teardown(enabled=True):
    """Permit DELETE of the tracked demo workspace and connection (teardown only)."""
    _active["teardown"] = enabled


def save(name, value):
    target = ART / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8")


def load(name):
    return json.loads((ART / name).read_text(encoding="utf-8"))


def exists(name):
    return (ART / name).exists()


def token(resource="https://api.fabric.microsoft.com"):
    """Tokens come from the Azure CLI account of the configured subscription; the default az account may differ."""
    if resource == "https://api.fabric.microsoft.com" and os.environ.get("FABRIC_TOKEN"):
        return os.environ["FABRIC_TOKEN"]
    if resource not in _tokens or _tokens[resource]["expires_on"] < time.time() + 300:
        result = json.loads(subprocess.check_output([shutil.which("az"), "account", "get-access-token",
            "--subscription", cfg()["subscriptionId"], "--resource", resource, "-o", "json"], text=True))
        if result.get("tenant", "").lower() != cfg()["tenantId"].lower():
            raise RuntimeError("Azure CLI token is not for the configured tenant; run `az login --tenant <tenantId>`")
        result["expires_on"] = int(result["expires_on"])
        _tokens[resource] = result
    return _tokens[resource]["accessToken"]


def ws():
    return load(_active["file"])["id"]


def path():
    return "/workspaces/" + ws()


def workspace_body():
    return {"displayName": cfg()["fabric"]["workspaceName"], "capacityId": cfg()["fabric"]["capacityId"],
            "description": DESCRIPTION}


def loader_body():
    return {"displayName": cfg()["fabric"]["loaderWorkspaceName"], "capacityId": cfg()["fabric"]["capacityId"],
            "description": LOADER_DESCRIPTION}


def check_write(method, url, body):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in ("api.fabric.microsoft.com", "api.powerbi.com"):
        raise ValueError("Unexpected API host")
    if method == "GET":
        return parsed
    if parsed.netloc == "api.powerbi.com":
        if not exists(_active["file"]) or not parsed.path.startswith("/v1.0/myorg/groups/" + ws() + "/"):
            raise ValueError("Refusing a Power BI write outside the active workspace")
        return parsed
    if parsed.path == "/v1/workspaces":
        if method != "POST" or body not in (workspace_body(), loader_body()):
            raise ValueError("Unexpected workspace creation")
        return parsed
    if method == "DELETE" and exists("loader-workspace.json") and \
            parsed.path == "/v1/workspaces/" + load("loader-workspace.json")["id"]:
        return parsed
    if method == "DELETE" and parsed.path.count("/") == 3 and parsed.path.startswith(("/v1/workspaces/", "/v1/connections/")):
        tracked = {"/v1/workspaces/" + load("workspace.json")["id"] if exists("workspace.json") else None,
                   "/v1/connections/" + load("connection.json")["id"] if exists("connection.json") else None}
        if _active["teardown"] and parsed.path in tracked:
            return parsed
        raise ValueError("Refusing to delete a workspace or connection outside an explicit teardown")
    if parsed.path == "/v1/connections":
        if method != "POST" or not body or body.get("displayName") != cfg()["mirroring"]["connectionName"]:
            raise ValueError("Unexpected connection creation")
        return parsed
    if exists("connection.json") and parsed.path.startswith("/v1/connections/" + load("connection.json")["id"] + "/"):
        return parsed
    allowed = ("/v1/workspaces/" + ws() + "/", "/v1/mcp/workspaces/" + ws() + "/") if exists(_active["file"]) else ()
    if not allowed or not parsed.path.startswith(allowed):
        raise ValueError("Refusing a write outside the active Maison MTL workspace")
    return parsed


def request(endpoint, method="GET", body=None, resource="https://api.fabric.microsoft.com", timeout=180):
    url = endpoint if endpoint.startswith("https:") else BASE + endpoint
    parsed = check_write(method, url, body)
    safe_read = method == "GET" or (method == "POST" and (parsed.path.endswith("/getDefinition")
                                                          or parsed.path.endswith("/executeQueries")))
    for attempt in range(6):
        req = Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer " + token(resource), "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=timeout) as response:
                raw = response.read()
                return response.status, {key.lower(): value for key, value in response.headers.items()}, \
                    json.loads(raw) if raw else None
        except HTTPError as error:
            if error.code == 429 and attempt < 5:
                time.sleep(min(120, max(1, int(error.headers.get("Retry-After", "15")))))
                continue
            if error.code in (500, 502, 503, 504) and safe_read and attempt < 5:
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"{method} {parsed.path}: HTTP {error.code}: {error.read().decode()[:3000]}") from error
        except (URLError, TimeoutError, ConnectionError) as error:
            if safe_read and attempt < 5:
                print(f"Read transport failure; retry {attempt + 1}: {error}", flush=True)
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("Retry limit exceeded")


def api(endpoint, method="GET", body=None, result=True):
    status, headers, data = request(endpoint, method, body)
    if status != 202:
        return data
    location = BASE + "/operations/" + headers["x-ms-operation-id"] if headers.get("x-ms-operation-id") \
        else headers.get("location")
    if not location:
        return data
    save("last-operation.json", {"endpoint": endpoint, "location": location})
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        time.sleep(min(30, max(2, int(headers.get("retry-after", "5")))))
        _, headers, state = request(location)
        if state is None:
            continue
        if state.get("status") == "Succeeded":
            if not result:
                return state
            try:
                return request(location + "/result")[2]
            except RuntimeError as error:
                if "HTTP 400" in str(error) or "HTTP 404" in str(error):
                    return state
                raise
        if state.get("status") in ("Failed", "Cancelled"):
            raise RuntimeError(json.dumps(state))
    raise TimeoutError(location)


def listing(endpoint):
    values, seen = [], set()
    while endpoint:
        if endpoint in seen:
            raise RuntimeError("Repeated continuation")
        seen.add(endpoint)
        response = api(endpoint)
        values.extend(response["value"])
        endpoint = response.get("continuationUri")
    return values


def part(name, content):
    data = content.encode() if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False).encode()
    return {"path": name, "payloadType": "InlineBase64", "payload": base64.b64encode(data).decode()}


def decode(definition):
    return {p["path"]: base64.b64decode(p["payload"]).decode("utf-8", "replace") for p in definition["definition"]["parts"]}


def item(key, collection, name, definition=None, update=False, extra=None):
    body = {"displayName": name, "description": DESCRIPTION, **(extra or {})}
    if definition:
        body["definition"] = definition
    saved = key + ".json"
    if exists(saved):
        current = api(path() + "/" + collection + "/" + load(saved)["id"])
        if current["displayName"] != name:
            raise RuntimeError("Saved item name changed")
        if update and definition:
            api(path() + "/" + collection + "/" + current["id"] + "/updateDefinition",
                "POST", {"definition": definition}, result=False)
        save(saved, current)
        return current
    if any(value["displayName"] == name for value in listing(path() + "/items")
           if value["type"] not in ("SQLEndpoint", "GraphModel")):
        raise RuntimeError("Untracked same-name item exists: " + name)
    current = api(path() + "/" + collection, "POST", body)
    if current is None or "id" not in current:
        matches = [value for value in listing(path() + "/items")
                   if value["displayName"] == name and value["type"] not in ("SQLEndpoint", "GraphModel")]
        if len(matches) != 1:
            raise RuntimeError("Created item could not be identified: " + name)
        current = matches[0]
    save(saved, current)
    return current


def cell(text, markdown=False):
    value = {"cell_type": "markdown" if markdown else "code", "metadata": {}, "source": text.splitlines(True)}
    if not markdown:
        value.update(execution_count=None, outputs=[])
    return value


def notebook(key, name, cells, lakehouse_key="lakehouse_gold", extra_lakehouses=()):
    lakehouse = load(lakehouse_key + ".json")
    known = [{"id": lakehouse["id"]}] + [{"id": load(k + ".json")["id"]} for k in extra_lakehouses]
    content = {"nbformat": 4, "nbformat_minor": 5, "metadata": {
        "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark"},
        "language_info": {"name": "python"},
        "dependencies": {"lakehouse": {"default_lakehouse": lakehouse["id"],
            "default_lakehouse_name": lakehouse["displayName"], "default_lakehouse_workspace_id": ws(),
            "known_lakehouses": known}}}, "cells": cells}
    save("notebooks/" + key + ".ipynb", content)
    return item(key, "notebooks", name, {"format": "ipynb", "parts": [part("notebook-content.ipynb", content)]}, True)


def run_job(key, job_type, statefile=None, polls=240, interval=20, fresh=False):
    """Start (once) and poll an item job. The location is persisted so a timeout never resubmits the job."""
    statefile = statefile or key + "-job.json"
    if fresh and exists(statefile):
        (ART / statefile).unlink()
    if not exists(statefile):
        _, headers, _ = request(path() + "/items/" + load(key + ".json")["id"] +
                                "/jobs/instances?jobType=" + job_type, "POST", {})
        save(statefile, {"location": headers.get("location"),
                         "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    location = load(statefile)["location"]
    if not location:
        raise RuntimeError("Missing job location; inspect before retry")
    previous = None
    for _ in range(polls):
        state = api(location)
        save(statefile.replace(".json", "-state.json"), state)
        if previous != state["status"]:
            print(key, state["status"], flush=True)
            previous = state["status"]
        if state["status"] == "Completed":
            return state
        if state["status"] in ("Failed", "Cancelled", "Deduped"):
            raise RuntimeError(json.dumps(state))
        time.sleep(interval)
    raise TimeoutError("Job still running; resume polling without resubmitting")


def pbi(endpoint, method="GET", body=None):
    status, _, data = request(PBI + "/groups/" + ws() + endpoint, method, body,
                              resource="https://analysis.windows.net/powerbi/api", timeout=300)
    return data if data is not None else {"status": status}


def sql_connect(server, database, app="MaisonMtlRetailIQ", timeout=900):
    import pyodbc
    raw = token("https://database.windows.net/").encode("utf-16-le")
    for attempt in range(6):
        try:
            conn = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=" + server + ";DATABASE=" + database +
                                  ";Encrypt=yes;TrustServerCertificate=no;APP=" + app + ";",
                                  attrs_before={1256: struct.pack("<I", len(raw)) + raw}, timeout=90, autocommit=True)
            break
        except pyodbc.Error as error:
            transient = any(code in str(error) for code in ("08001", "40613", "HYT00", "08S01"))
            if attempt == 5 or not transient:
                raise
            print(f"SQL connect failure; retry {attempt + 1}: {str(error)[:160]}", flush=True)
            time.sleep(15 * (attempt + 1))
    conn.timeout = timeout
    conn.setdecoding(pyodbc.SQL_CHAR, encoding="utf-16le", ctype=pyodbc.SQL_WCHAR)
    return conn
