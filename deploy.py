"""Ordered, resumable deployment entrypoint for the Maison MTL Retail IQ demo.

    python deploy.py check                      # validate config, tools and sign-in (read-only)
    python deploy.py all                        # run every step in order, skipping steps already completed
    python deploy.py all --from medallion       # re-run from a given step onwards
    python deploy.py <step> [<step> ...]        # run selected steps (always re-run)
    python deploy.py loop                       # closed loop after the first reorder request exists in the app
    python deploy.py teardown                   # show what teardown would delete (dry run)
    python deploy.py teardown --yes             # delete everything this deployment created

Every step is idempotent. State (non-secret IDs and evidence) is tracked in artifacts/, which is git-ignored.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import fabric as f
import settings

LAKEHOUSES = {"lakehouse_bronze": "MTL_Bronze", "lakehouse_silver": "MTL_Silver", "lakehouse_gold": "MTL_Gold"}
APP_DIR = f.ROOT / "app"
PROGRESS = "deploy-progress.json"


def provision():
    """Workspace on the configured capacity plus the Bronze, Silver and Gold lakehouses."""
    if not f.exists("workspace.json"):
        if any(w["displayName"].lower() == f.WORKSPACE.lower() for w in f.listing("/workspaces")):
            raise RuntimeError(f"An untracked workspace named {f.WORKSPACE!r} exists; refusing to adopt it. "
                               "Rename fabric.workspaceName in config.json or delete that workspace.")
        f.save("workspace.json", f.api("/workspaces", "POST", f.workspace_body()))
    workspace = f.api(f.path())
    if workspace["displayName"] != f.WORKSPACE or workspace.get("capacityId", "").lower() != f.CAPACITY.lower():
        raise RuntimeError("Workspace name or capacity mismatch")
    f.save("workspace.json", workspace)
    items = {key: f.item(key, "lakehouses", name)["id"] for key, name in LAKEHOUSES.items()}
    return {"workspace": workspace["id"], **items}


def grant_sql_identity():
    """Mirroring needs the Azure SQL server's managed identity to write to OneLake (workspace Contributor)."""
    identity = f.load("azure-sql-server.json")["identityPrincipalId"]
    match = [a for a in f.listing(f.path() + "/roleAssignments") if a["principal"]["id"] == identity]
    if not match:
        f.api(f.path() + "/roleAssignments", "POST",
              {"principal": {"id": identity, "type": "ServicePrincipal"}, "role": "Contributor"})
        match = [a for a in f.listing(f.path() + "/roleAssignments") if a["principal"]["id"] == identity]
    if not match or match[0]["role"] not in ("Contributor", "Member", "Admin"):
        raise RuntimeError("SQL server managed identity lacks workspace write access")
    f.save("sql-identity-role.json", {"principalId": identity, "role": match[0]["role"],
                                       "principal": match[0]["principal"].get("displayName")})
    return match[0]


# ---------------------------------------------------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------------------------------------------------

def tool(name):
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} is not on PATH")
    return found


def run_command(args, cwd, env=None):
    print("$", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, **(env or {})})


def step_check():
    cfg = settings.get()
    result = {"config": str(settings.config_path()), "network": cfg["sql"]["network"]}
    tool("az")
    result["tools"] = {name: bool(shutil.which(name)) for name in ("az", "node", "npm", "npx")}
    missing = [name for name, ok in result["tools"].items() if not ok]
    if missing:
        raise RuntimeError("Missing tools: " + ", ".join(missing))
    for module in ("pyodbc", "httpx", "mcp"):
        if importlib.util.find_spec(module) is None:
            raise RuntimeError(f"Python package {module} is missing: pip install -r requirements.txt")
    import pyodbc
    if "ODBC Driver 18 for SQL Server" not in pyodbc.drivers():
        raise RuntimeError("ODBC Driver 18 for SQL Server is required (SQL endpoint and Azure SQL access)")
    f.token()
    capacities = {c["id"].lower(): c for c in f.listing("/capacities")}
    capacity = capacities.get(cfg["fabric"]["capacityId"].lower())
    if not capacity:
        raise RuntimeError("fabric.capacityId is not visible to the signed-in user (needs capacity admin or contributor)")
    if capacity.get("state") != "Active":
        raise RuntimeError(f"Capacity {capacity['displayName']} is {capacity.get('state')}; resume it first")
    result["capacity"] = {"name": capacity["displayName"], "sku": capacity.get("sku"), "region": capacity.get("region")}
    if settings.is_private():
        gateways = {g["id"].lower(): g for g in f.listing("/gateways")}
        gateway = gateways.get(cfg["privateNetwork"]["gatewayId"].lower())
        if not gateway or gateway.get("type") != "VirtualNetwork":
            raise RuntimeError("privateNetwork.gatewayId is not a VNet data gateway visible to the signed-in user")
        result["gateway"] = gateway.get("displayName")
    return result


def step_spn():
    import spn
    saved = spn.create()
    return {"appId": saved["appId"], "displayName": saved["displayName"]}


def step_sql():
    import azure_sql
    return azure_sql.create()


def step_workspace():
    return provision()


def step_identity():
    return grant_sql_identity()


def step_seed():
    if settings.is_private():
        import seed_loader
        if f.exists("loader-cleanup.json"):
            return {"seeded": "already (loader workspace deleted)", "evidence": f.load("azure-sql-verification.json")}
        seed_loader.provision()
        seed_loader.mpe()
        seed_loader.build()
        seed_loader.run()
        evidence = seed_loader.verify()
        seed_loader.cleanup()
        return {"rows": evidence["rows"], "cleanNetSales2025": evidence["cleanNetSales2025"]}
    import azure_sql
    return azure_sql.run()


def step_mirror():
    import mirror
    mirror.connection()
    mirror.create()
    mirror.start()
    mirror.status()
    return mirror.verify()


def step_medallion():
    import medallion
    shortcuts = medallion.shortcuts()
    notebooks = medallion.notebooks()
    pipeline = medallion.pipeline()
    run = medallion.run_pipeline()
    return {"shortcuts": shortcuts["shortcuts"], "notebooks": notebooks, "pipeline": pipeline, "run": run["status"]}


def step_model():
    import model
    model.build()
    model.refresh()
    return model.verify()


def step_report():
    import report
    report.build()
    # Page renders need the "Export reports as image files" tenant setting; run `python report.py verify` for them.
    return report.verify(export=False)


def step_ontology():
    import ontology
    ontology.deploy()
    return ontology.refresh()


def step_agent():
    import agent
    summary = agent.configure()
    tools = asyncio.run(agent.mcp())
    return {**summary, "mcpTools": [t["name"] for t in tools["tools"]]}


def step_app():
    import app_sync
    app_sync.config()
    npm = tool("npm")
    npx = tool("npx")
    run_command([npm, "ci"], APP_DIR)
    run_command([npm, "ci"], APP_DIR / "rayfin" / "functions")
    run_command([npx, "rayfin", "up", "--workspace-id", f.ws(), "--tenant", settings.get()["tenantId"], "--yes"],
                APP_DIR, env={"CI": "1"})
    app = app_sync.discover()
    published = app_sync.publish()
    return {"url": app["url"], "rows": published["rows"]}


def step_evaluate():
    import agent
    result = asyncio.run(agent.evaluate("deploy"))
    return {"passed": result["passed"], "total": result["total"]}


def step_loop():
    """Land app reorder requests into Bronze, conform them in Gold, write reviews back and refresh the semantic layers."""
    import app_sync
    import medallion
    import model
    import ontology
    shortcut = medallion.app_shortcut()
    reviews = app_sync.reviews()
    model.refresh()
    ontology.refresh()
    return {"shortcut": shortcut.get("name"), "reviews": reviews}


STEPS = [
    ("check", step_check, "Validate config, tools, Azure CLI sign-in, capacity and (private) gateway"),
    ("spn", step_spn, "Entra app registration used only by the mirroring connection"),
    ("sql", step_sql, "Azure SQL serverless database (and server in public mode with createServer)"),
    ("workspace", step_workspace, "Fabric workspace and Bronze/Silver/Gold lakehouses"),
    ("identity", step_identity, "SQL server managed identity as workspace Contributor"),
    ("seed", step_seed, "Load the synthetic raw data (public: firewall + Entra; private: MPE loader workspace)"),
    ("mirror", step_mirror, "Fabric connection, mirrored database, replication and row counts"),
    ("medallion", step_medallion, "Bronze shortcuts, Silver/Gold/ML notebooks, pipeline run"),
    ("model", step_model, "Direct Lake semantic model, refresh, DAX controls"),
    ("report", step_report, "Power BI report and binding checks"),
    ("ontology", step_ontology, "Fabric IQ ontology and managed graph refresh"),
    ("agent", step_agent, "Data Agent sources, instructions, few-shots, publish, MCP tool list"),
    ("app", step_app, "Rayfin Fabric App deploy and Gold snapshot publish"),
    ("evaluate", step_evaluate, "20-question MCP evaluation of the Data Agent"),
]
EXTRA = {"loop": (step_loop, "Closed loop after the first reorder request (shortcut, review write-back, refresh)")}


def progress():
    return f.load(PROGRESS) if f.exists(PROGRESS) else {}


def execute(name, function):
    started = time.time()
    print(f"\n=== {name} ===", flush=True)
    result = function()
    state = progress()
    state[name] = {"completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "seconds": round(time.time() - started)}
    f.save(PROGRESS, state)
    print(json.dumps(result, indent=2, default=str)[:4000], flush=True)
    return result


def main(argv):
    import argparse
    names = [name for name, _, _ in STEPS]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("commands", nargs="+", help="all | teardown | list | " + " | ".join(names + list(EXTRA)))
    parser.add_argument("--from", dest="start", choices=names, help="with `all`: re-run from this step onwards")
    parser.add_argument("--yes", action="store_true", help="with `teardown`: really delete")
    parser.add_argument("--keep-sql", action="store_true", help="with `teardown`: keep the Azure SQL database/server")
    args = parser.parse_args(argv)
    if args.commands == ["list"]:
        for name, _, description in STEPS:
            print(f"{name:10} {description}")
        for name, (_, description) in EXTRA.items():
            print(f"{name:10} {description} (not part of `all`)")
        return
    if args.commands == ["teardown"]:
        import teardown
        teardown.main(yes=args.yes, keep_sql=args.keep_sql)
        return
    functions = {name: function for name, function, _ in STEPS} | {k: v[0] for k, v in EXTRA.items()}
    if args.commands == ["all"]:
        done = progress()
        start = names.index(args.start) if args.start else 0
        for index, (name, function, _) in enumerate(STEPS):
            if name != "check" and index < start:
                continue
            if name != "check" and not args.start and name in done:
                print(f"=== {name}: already completed at {done[name]['completedAt']} (use --from {name} to re-run)")
                continue
            execute(name, function)
        print("\nDeployment complete. Next: open the app URL in artifacts/app.json, submit a reorder request, "
              "then run `python deploy.py loop`.")
        return
    unknown = [name for name in args.commands if name not in functions]
    if unknown:
        parser.error("unknown step(s): " + ", ".join(unknown))
    for name in args.commands:
        execute(name, functions[name])


if __name__ == "__main__":
    main(sys.argv[1:])
