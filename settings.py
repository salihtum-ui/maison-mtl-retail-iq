"""Deployment settings for the Maison MTL Retail IQ demo.

Every environment-specific value (tenant, subscription, capacity, SQL server, gateway) comes from `config.json`
(copy `config.example.json`) or from the file named by the MTL_CONFIG environment variable. Nothing
environment-specific is hard-coded in the scripts.
"""
import copy
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"
GUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
SERVER_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
NETWORKS = ("public", "private")

DEFAULTS = {
    "tenantId": PLACEHOLDER,
    "subscriptionId": PLACEHOLDER,
    "fabric": {
        "capacityId": PLACEHOLDER,
        "workspaceName": "Maison MTL Retail IQ",
        "loaderWorkspaceName": "Maison MTL Seed Loader",
    },
    "sql": {
        "network": "public",
        "resourceGroup": "rg-maison-mtl-retail-iq",
        "serverName": "",
        "location": "canadacentral",
        "createServer": True,
        "database": "mtl_retail",
        "autoPauseDelayMinutes": 60,
    },
    "privateNetwork": {
        "gatewayId": "",
    },
    "mirroring": {
        "servicePrincipalName": "sp-fabric-mirror-mtl-retail",
        "connectionName": "Maison MTL Retail IQ - mtl_retail",
        "secretLifetimeDays": 180,
    },
}

_cache = {}


class ConfigError(RuntimeError):
    pass


def config_path():
    return Path(os.environ.get("MTL_CONFIG") or ROOT / "config.json")


def merge(base, override):
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key.startswith("$") or key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def errors(cfg):
    """Return a list of human-readable problems; an empty list means the config can deploy."""
    problems = []

    def guid(label, value):
        if not isinstance(value, str) or not GUID.match(value) or value == PLACEHOLDER:
            problems.append(f"{label} must be a real GUID (got {value!r})")

    guid("tenantId", cfg["tenantId"])
    guid("subscriptionId", cfg["subscriptionId"])
    guid("fabric.capacityId", cfg["fabric"]["capacityId"])
    sql = cfg["sql"]
    if sql["network"] not in NETWORKS:
        problems.append(f"sql.network must be one of {NETWORKS} (got {sql['network']!r})")
    if not SERVER_NAME.match(sql.get("serverName") or "") or "change-me" in (sql.get("serverName") or ""):
        problems.append("sql.serverName must be a lowercase Azure SQL logical server name (globally unique)")
    if not sql.get("resourceGroup"):
        problems.append("sql.resourceGroup is required")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$", sql.get("database") or ""):
        problems.append("sql.database must be a simple identifier")
    if sql.get("createServer") and sql["network"] != "public":
        problems.append("sql.createServer is only supported with sql.network = 'public'; "
                        "the private path expects an existing private-endpoint server")
    if not isinstance(sql.get("autoPauseDelayMinutes"), int) or sql["autoPauseDelayMinutes"] < 60:
        problems.append("sql.autoPauseDelayMinutes must be an integer >= 60")
    if sql["network"] == "private":
        guid("privateNetwork.gatewayId", cfg["privateNetwork"].get("gatewayId"))
    for key in ("workspaceName", "loaderWorkspaceName"):
        if not cfg["fabric"].get(key):
            problems.append(f"fabric.{key} is required")
    if cfg["fabric"]["workspaceName"] == cfg["fabric"]["loaderWorkspaceName"]:
        problems.append("fabric.loaderWorkspaceName must differ from fabric.workspaceName")
    for key in ("servicePrincipalName", "connectionName"):
        if not cfg["mirroring"].get(key):
            problems.append(f"mirroring.{key} is required")
    return problems


def load(path=None, validate=True):
    target = Path(path) if path else config_path()
    if not target.exists():
        raise ConfigError(f"{target} not found. Copy config.example.json to config.json and fill in your values "
                          "(see docs/DEPLOYMENT.md).")
    cfg = merge(DEFAULTS, json.loads(target.read_text(encoding="utf-8")))
    if validate:
        problems = errors(cfg)
        if problems:
            raise ConfigError("Invalid configuration in " + str(target) + ":\n- " + "\n- ".join(problems))
    return cfg


def get():
    """Cached, validated configuration for the current process."""
    key = str(config_path())
    if key not in _cache:
        _cache[key] = load()
    return _cache[key]


def reset():
    _cache.clear()


def sql_fqdn(cfg=None):
    return (cfg or get())["sql"]["serverName"] + ".database.windows.net"


def sql_server_id(cfg=None):
    cfg = cfg or get()
    return (f"/subscriptions/{cfg['subscriptionId']}/resourceGroups/{cfg['sql']['resourceGroup']}"
            f"/providers/Microsoft.Sql/servers/{cfg['sql']['serverName']}")


def is_private(cfg=None):
    return (cfg or get())["sql"]["network"] == "private"


if __name__ == "__main__":
    loaded = load(validate=False)
    found = errors(loaded)
    print(json.dumps({"config": str(config_path()), "valid": not found, "problems": found}, indent=2))
    raise SystemExit(1 if found else 0)
