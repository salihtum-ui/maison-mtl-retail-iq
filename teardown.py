"""Teardown for the Maison MTL Retail IQ demo.

Deletes only what this deployment created and tracked in artifacts/ (never resources it merely used):

- the loader workspace and managed private endpoint (private mode, if still present);
- the demo Fabric workspace, which removes every item in it (mirrored database, lakehouses, notebooks, pipeline,
  ML experiments and models, semantic model, report, ontology, Data Agent and the Fabric App with its SQL database);
- the Fabric connection used by mirroring;
- the mirroring app registration (and with it the service principal and its secret);
- the Azure SQL database, or the whole server (and an empty resource group) when the deployment created them;
- local generated state, which is archived to artifacts-teardown-<timestamp>/.

    python deploy.py teardown                 # dry run: print the plan
    python deploy.py teardown --yes           # execute the plan
    python deploy.py teardown --yes --keep-sql
"""
import json
from pathlib import Path
import re
import time

import fabric as f

APP_DIR = f.ROOT / "app"
AZURE_SERVICES_RULE = "AllowAllWindowsAzureIps"
DEPLOYER_RULE = "mtl-retail-iq-deployer"
GENERATED = [APP_DIR / "rayfin" / ".env", APP_DIR / "rayfin" / ".deployments.json", APP_DIR / ".env.local",
             APP_DIR / "rayfin" / "functions" / "src" / "fabric_config.ts"]
HOSTED_REDIRECT = re.compile(r"^\s*-\s*https://[^\s]+\.fabricapps\.net/?\s*$")


def tracked(name):
    return f.load(name) if f.exists(name) else None


def resource_group(resource_id):
    match = re.search(r"/resourceGroups/([^/]+)/", resource_id or "", re.I)
    return match.group(1) if match else None


def plan(keep_sql=False):
    actions = []
    loader = tracked("loader-workspace.json")
    if loader and not f.exists("loader-cleanup.json"):
        actions.append({"action": "delete-loader-workspace", "target": loader["id"],
                        "detail": f"{loader.get('displayName')} and its managed private endpoint"})
    workspace = tracked("workspace.json")
    if workspace:
        actions.append({"action": "delete-workspace", "target": workspace["id"],
                        "detail": f"{workspace.get('displayName')} and every item in it, including the Fabric App"})
    connection = tracked("connection.json")
    if connection:
        actions.append({"action": "delete-connection", "target": connection["id"],
                        "detail": connection.get("displayName")})
    principal = tracked("spn.json")
    if principal:
        actions.append({"action": "delete-app-registration", "target": principal["appId"],
                        "detail": principal.get("displayName")})
    if not keep_sql:
        server = tracked("azure-sql-server.json") or {}
        database = tracked("azure-sql.json")
        firewall = tracked("sql-firewall.json") or {}
        if server.get("serverCreatedByDeploy"):
            actions.append({"action": "delete-sql-server", "target": server["id"],
                            "detail": f"{server.get('name')} (created by this deployment, with its database)"})
            if server.get("resourceGroupCreatedByDeploy"):
                actions.append({"action": "delete-resource-group-if-empty", "target": resource_group(server["id"]),
                                "detail": "only when no other resources remain"})
        else:
            if database and database.get("createdByDeploy"):
                actions.append({"action": "delete-sql-database", "target": database["id"], "detail": database["name"]})
            if server and firewall:
                rules = [DEPLOYER_RULE] + ([AZURE_SERVICES_RULE] if firewall.get("azureServicesRuleCreatedByDeploy") else [])
                for rule in rules:
                    actions.append({"action": "delete-firewall-rule", "target": server["id"], "detail": rule})
    actions.append({"action": "archive-local-state", "target": str(f.ART),
                    "detail": "move artifacts/ aside and remove generated app config and deployed redirect URIs"})
    return actions


def az(*args):
    import azure_sql
    return azure_sql.az(*args, parse=False)


def ignore_missing(function, *args):
    try:
        return function(*args)
    except Exception as error:
        text = str(error)
        if any(code in text for code in ("HTTP 404", "NotFound", "ResourceNotFound", "could not be found",
                                         "WorkspaceNotFound", "ItemNotFound", "ConnectionNotFound")):
            return "already deleted"
        raise


def strip_hosted_redirects():
    path = APP_DIR / "rayfin" / "rayfin.yml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if not HOSTED_REDIRECT.match(line)]
    if kept != lines:
        path.write_text("".join(kept), encoding="utf-8")
    return len(lines) - len(kept)


def archive():
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = f.ART.parent / f"artifacts-teardown-{stamp}"
    if f.ART.exists():
        f.ART.rename(target)
    removed = []
    for path in GENERATED:
        if path.exists():
            path.unlink()
            removed.append(str(path.relative_to(f.ROOT)))
    return {"archivedTo": str(target), "removed": removed, "redirectUrisRemoved": strip_hosted_redirects()}


def execute(action):
    kind, target = action["action"], action["target"]
    if kind == "delete-loader-workspace":
        import seed_loader
        return ignore_missing(seed_loader.cleanup)
    if kind == "delete-workspace":
        f.use_loader(False)
        return ignore_missing(f.request, "/workspaces/" + target, "DELETE")
    if kind == "delete-connection":
        return ignore_missing(f.request, "/connections/" + target, "DELETE")
    if kind == "delete-app-registration":
        import spn
        return spn.delete()
    if kind == "delete-sql-database":
        return ignore_missing(az, "sql", "db", "delete", "--ids", target, "--yes")
    if kind == "delete-firewall-rule":
        server = target.rsplit("/", 1)[1]
        return ignore_missing(az, "sql", "server", "firewall-rule", "delete", "-g", resource_group(target), "-s", server,
                              "-n", action["detail"])
    if kind == "delete-sql-server":
        return ignore_missing(az, "sql", "server", "delete", "--ids", target, "--yes")
    if kind == "delete-resource-group-if-empty":
        import azure_sql
        remaining = azure_sql.az("resource", "list", "-g", target)
        if remaining:
            return {"kept": target, "remainingResources": [r["name"] for r in remaining]}
        return ignore_missing(az, "group", "delete", "-n", target, "--yes", "--no-wait")
    if kind == "archive-local-state":
        return archive()
    raise ValueError(kind)


def main(yes=False, keep_sql=False):
    actions = plan(keep_sql)
    print(json.dumps({"dryRun": not yes, "actions": actions}, indent=2))
    if not yes:
        print("\nDry run only. Re-run with --yes to delete these resources.")
        return actions
    f.allow_teardown()
    results = []
    try:
        for action in actions:
            print(f"--> {action['action']} {action['detail']}", flush=True)
            result = execute(action)
            results.append({**action, "result": result})
    finally:
        f.allow_teardown(False)
    archived = next((r["result"]["archivedTo"] for r in results if r["action"] == "archive-local-state"), None)
    folder = Path(archived) if archived and Path(archived).exists() else f.ART
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "teardown.json").write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print("Teardown complete. Record:", folder / "teardown.json")
    return results
