"""Bronze shortcuts, Silver/Gold notebooks and the orchestration pipeline for the Maison MTL medallion."""
import json
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

import fabric as f
import mtl_data as d
from nb_gold import GOLD
from nb_ml_forecast import FORECAST
from nb_ml_stock import STOCK
from nb_reorders import REORDERS
from nb_silver import SILVER
from mtl_reference import BLACK_FRIDAY, BRANDS, REGIONS

SOURCE_TABLES = ["stores", "suppliers", "products", "sales_daily", "inventory_daily", "replenishment_orders"]
PIPELINE = "PL_MTL_Medallion_and_ML"


def onelake_list(item_id, directory):
    url = (f"https://onelake.dfs.fabric.microsoft.com/{f.ws()}?resource=filesystem&recursive=false"
           f"&directory={quote(item_id + '/' + directory)}")
    request = Request(url, headers={"Authorization": "Bearer " + f.token("https://storage.azure.com/")})
    with urlopen(request, timeout=60) as response:
        return [p["name"].split("/", 1)[1] for p in json.loads(response.read()).get("paths", [])]


def shortcut(name, target_item, target_path):
    lakehouse = f.load("lakehouse_bronze.json")["id"]
    base = f.path() + "/items/" + lakehouse + "/shortcuts"
    existing = {s["name"]: s for s in f.api(base).get("value", [])}
    target = {"oneLake": {"workspaceId": f.ws(), "itemId": target_item, "path": target_path}}
    if name in existing:
        if existing[name]["target"]["oneLake"]["path"] != target_path:
            raise RuntimeError("Shortcut target drifted: " + name)
        return existing[name]
    return f.api(base, "POST", {"path": "Tables", "name": name, "target": target})


def shortcuts():
    mirror = f.load("mirror.json")["id"]
    available = onelake_list(mirror, "Tables")
    prefix = "Tables/dbo/" if any(p.startswith("Tables/dbo") for p in available) else "Tables/"
    created = [shortcut(table, mirror, prefix + table) for table in SOURCE_TABLES]
    f.save("bronze-shortcuts.json", created)
    return {"targetPrefix": prefix, "shortcuts": [s["name"] for s in created]}


def app_shortcut():
    """Land app reorder requests (Fabric SQL database auto-replicates to OneLake) into Bronze without copying."""
    app = f.load("app.json")
    available = onelake_list(app["sqlDatabaseId"], "Tables/dbo")
    table = next((p for p in available if p.lower().endswith("/reorderrequests")), None)
    if not table:
        raise RuntimeError("ReorderRequests is not yet replicated to OneLake: " + json.dumps(available))
    result = shortcut("app_reorder_requests", app["sqlDatabaseId"], table)
    f.save("bronze-app-shortcut.json", result)
    return result


LOG_HOOK = r'''
import traceback
def _mtl_log_failure(shell, etype, value, tb, tb_offset=None):
    try:
        notebookutils.fs.put("Files/_logs/" + NOTEBOOK_KEY + ".txt", "".join(traceback.format_exception(etype, value, tb))[-20000:], True)
    finally:
        shell.showtraceback((etype, value, tb), tb_offset=tb_offset)
get_ipython().set_custom_exc((Exception,), _mtl_log_failure)
'''


def common(key):
    expected = d.truth()
    f.save("expected.json", expected)
    return ("import json\nNOTEBOOK_KEY = " + repr(key) + "\nWORKSPACE = " + repr(f.ws()) +
            "\nONELAKE = 'abfss://' + WORKSPACE + '@onelake.dfs.fabric.microsoft.com'" +
            "\nBRONZE = " + repr(f.load("lakehouse_bronze.json")["id"]) +
            "\nSILVER = " + repr(f.load("lakehouse_silver.json")["id"]) +
            "\nGOLD = " + repr(f.load("lakehouse_gold.json")["id"]) +
            "\nEXPECTED = json.loads(" + repr(json.dumps(expected, ensure_ascii=False)) + ")" +
            "\nREGIONS = " + repr(REGIONS) + "\nBRANDS = " + repr(BRANDS) +
            "\nBLACK_FRIDAY = " + repr([x.isoformat() for x in sorted(BLACK_FRIDAY)]) + "\n" + LOG_HOOK)


def notebooks():
    silver = f.notebook("nb_silver", "02_Silver_Cleanse_and_Conform", [
        f.cell("# Silver: cleanse, conform and deduplicate\nReads Bronze OneLake shortcuts to the mirrored SYNTHETIC "
               "`mtl_retail` Azure SQL database. Standardizes codes, quarantines invalid rows, removes duplicates and "
               "writes `dq_events` as data-quality evidence.", True),
        f.cell(common("nb_silver")), f.cell(SILVER)], lakehouse_key="lakehouse_silver")
    gold = f.notebook("nb_gold", "03_Gold_Star_Schema_and_KPIs", [
        f.cell("# Gold: business-ready star schema\nDate, store, region, product, category, brand and supplier dimensions; "
               "sales, inventory and replenishment facts; current stock positions and governed KPI tables.", True),
        f.cell(common("nb_gold")), f.cell(GOLD)], lakehouse_key="lakehouse_gold")
    forecast = f.notebook("nb_ml_forecast", "04_ML_Sales_Forecast", [
        f.cell("# ML: 28-day sales forecast per store x product\nDirect multi-horizon gradient boosting (LightGBM) with "
               "calendar, seasonality, promotion and lag features. Holdout metrics vs naive baselines are tracked in the "
               "`mtl-sales-forecast` MLflow experiment and the model is registered as an ML model item.", True),
        f.cell(common("nb_ml_forecast")), f.cell(FORECAST)], lakehouse_key="lakehouse_gold")
    stock = f.notebook("nb_ml_stock", "05_ML_Low_Stock_Prediction", [
        f.cell("# ML: when will each store x product fall below its reorder point?\nA days-to-low-stock model trained on "
               "historical inventory snapshots is combined with the sales forecast projection to produce a predicted "
               "low-stock date, a risk level and a recommended reorder quantity.", True),
        f.cell(common("nb_ml_stock")), f.cell(STOCK)], lakehouse_key="lakehouse_gold")
    reorders = f.notebook("nb_reorders", "06_Gold_Reorder_Requests", [
        f.cell("# Closed loop: app reorder requests\nThe Fabric App's SQL database replicates to OneLake; Bronze reads it "
               "through a shortcut. Silver validates requests and Gold enriches them with ML stock risk. Also publishes "
               "`stock_risk_this_week` (Critical/High positions) as the reorder-candidate list.", True),
        f.cell(common("nb_reorders")), f.cell(REORDERS)], lakehouse_key="lakehouse_gold")
    return {"silver": silver["id"], "gold": gold["id"], "forecast": forecast["id"], "stock": stock["id"],
            "reorders": reorders["id"]}


def activity(name, key, depends=None):
    return {"name": name, "type": "TridentNotebook",
            "dependsOn": [{"activity": depends, "dependencyConditions": ["Succeeded"]}] if depends else [],
            "policy": {"timeout": "0.02:00:00", "retry": 1, "retryIntervalInSeconds": 60, "secureOutput": False,
                       "secureInput": False},
            "typeProperties": {"notebookId": f.load(key + ".json")["id"], "workspaceId": f.ws()}}


def pipeline():
    steps = [("Silver_Cleanse_and_Conform", "nb_silver"), ("Gold_Star_Schema_and_KPIs", "nb_gold"),
             ("ML_Sales_Forecast", "nb_ml_forecast"), ("ML_Low_Stock_Prediction", "nb_ml_stock"),
             ("Gold_Reorder_Requests", "nb_reorders")]
    activities, previous = [], None
    for name, key in steps:
        if not f.exists(key + ".json"):
            continue
        activities.append(activity(name, key, previous))
        previous = name
    content = {"properties": {"description": "Medallion refresh (Silver, Gold) then ML forecasting, low-stock "
                              "prediction and reorder-request conformance for the SYNTHETIC Maison MTL demo.",
                              "activities": activities}}
    f.save("pipeline-content.json", content)
    result = f.item("pipeline", "dataPipelines", PIPELINE, {"parts": [f.part("pipeline-content.json", content)]}, True)
    return {"pipeline": result["id"], "activities": [a["name"] for a in activities]}


def failure_log(key):
    lakehouse = {"nb_silver": "lakehouse_silver"}.get(key, "lakehouse_gold")
    url = (f"https://onelake.dfs.fabric.microsoft.com/{f.ws()}/{f.load(lakehouse + '.json')['id']}/Files/_logs/{key}.txt")
    try:
        with urlopen(Request(url, headers={"Authorization": "Bearer " + f.token("https://storage.azure.com/")}), timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as error:
        return "no failure log: " + str(error)[:200]


def run(key, fresh=True):
    try:
        return f.run_job(key, "RunNotebook", polls=240, interval=20, fresh=fresh)
    except RuntimeError:
        print(failure_log(key)[-6000:], flush=True)
        raise


def run_pipeline(fresh=True):
    return f.run_job("pipeline", "Pipeline", polls=360, interval=30, fresh=fresh)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["shortcuts", "app-shortcut", "notebooks", "pipeline", "silver", "gold",
                                            "forecast", "stock", "reorders", "run-pipeline"])
    parser.add_argument("--resume", action="store_true", help="Poll an existing job instead of starting a new one")
    args = parser.parse_args()
    actions = {"shortcuts": shortcuts, "app-shortcut": app_shortcut, "notebooks": notebooks, "pipeline": pipeline,
               "silver": lambda: run("nb_silver", not args.resume), "gold": lambda: run("nb_gold", not args.resume),
               "forecast": lambda: run("nb_ml_forecast", not args.resume),
               "stock": lambda: run("nb_ml_stock", not args.resume),
               "reorders": lambda: run("nb_reorders", not args.resume),
               "run-pipeline": lambda: run_pipeline(not args.resume)}
    started = time.time()
    print(json.dumps(actions[args.command](), indent=2, default=str))
    print(f"elapsed {time.time() - started:.0f}s")
