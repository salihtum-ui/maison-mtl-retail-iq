"""Fabric IQ ontology for the SYNTHETIC Maison MTL Retail IQ demo, bound to MTL_Gold tables."""
import base64
import json
import time
import uuid
from urllib.parse import urlparse

import fabric as f
from model import columns

NAME = "MtlRetailOntology"
SNAPSHOT = "2026-11-03"

# name, gold table, key column, display column, synonyms (EN + FR), description
ENTITIES = [
    ("Region", "dim_region", "Region", "Region", ["Administrative region", "Market area", "Région", "Région administrative"],
     "A Quebec administrative region grouped into a market (Québec City metro, Greater Montréal, Regional Quebec)."),
    ("Store", "dim_store", "StoreCode", "StoreName",
     ["Location", "Shop", "Branch", "Magasin", "Succursale", "Boutique", "Centre de distribution"],
     "An illustrative Maison MTL store in Quebec, or the DC-QC distribution centre (LocationType)."),
    ("Category", "dim_category", "Category", "Category", ["Merchandise category", "Product category", "Catégorie", "Rayon"],
     "A merchandise category such as Outerwear, Footwear or Cold-weather accessories, with its category group."),
    ("Brand", "dim_brand", "Brand", "Brand", ["Label", "Marque", "Griffe"], "A fictional house or partner brand."),
    ("Supplier", "dim_supplier", "SupplierCode", "SupplierName", ["Vendor", "Manufacturer", "Fournisseur"],
     "A fictional supplier with planned lead time, PO on-time performance and open purchase orders."),
    ("Product", "dim_product", "SKU", "ProductName", ["Item", "SKU", "Article", "Produit"],
     "A synthetic SKU with department, category, brand, supplier, unit cost, unit price, case pack and lead time."),
    ("ChainPerformance", "kpi_chain_summary", "ChainId", "ChainId",
     ["Company totals", "Chain KPIs", "Total Quebec stores", "Indicateurs de la chaîne", "Total de la chaîne"],
     "One row of chain-wide KPIs at the 2026-11-03 snapshot: last 28 days, same 28 days last year, YTD, stock."),
    ("StorePerformance", "kpi_store_summary", "StoreCode", "StoreName",
     ["Store KPIs", "Store scorecard", "Performance du magasin", "Tableau de bord magasin"],
     "Per-store KPIs at the snapshot: last-28-day and YTD net sales with last-year comparison, margin and stock health."),
    ("CategoryPerformance", "kpi_category_summary", "CategoryPerformanceId", "CategoryPerformanceId",
     ["Category KPIs", "Department performance", "Performance par catégorie", "Performance par rayon"],
     "Per department and category KPIs at the snapshot, including sell-through and weeks of supply."),
    ("MonthlySales", "sales_month_store_category", "SalesMonthId", "SalesMonthId",
     ["Monthly sales", "Sales history", "Ventes mensuelles", "Historique des ventes"],
     "Net sales, units and gross margin by month, store, department and category (Nov 2024 to Nov 2026)."),
    ("InventoryPosition", "inventory_current", "PositionId", "PositionId",
     ["Stock", "On hand", "Inventory", "Stock en magasin", "Inventaire"],
     "Current store x SKU stock position at the 2026-11-03 snapshot with velocity, days of supply and stock status."),
    ("SalesForecast", "ml_forecast_summary", "PositionId", "PositionId",
     ["Demand forecast", "28-day forecast", "Prévision des ventes", "Prévision de la demande"],
     "LightGBM sales forecast per store x SKU for the next 7, 14 and 28 days (2026-11-04 to 2026-12-01)."),
    ("DailyForecast", "ml_sales_forecast_daily", "ForecastId", "ForecastId",
     ["Daily forecast", "Forecast by day", "Prévision quotidienne"],
     "Daily ML forecast units (with P10/P90 range) and forecast net sales per store x SKU for the next 28 days."),
    ("StockRisk", "ml_stock_risk", "PositionId", "PositionId",
     ["Low-stock risk", "Reorder recommendation", "Stockout risk", "Risque de rupture", "Recommandation de réapprovisionnement"],
     "ML prediction of when a store x SKU falls below its reorder point, with risk level and recommended reorder quantity."),
    ("ReorderRequest", "reorder_requests", "RequestId", "RequestId",
     ["Replenishment request", "Reorder", "Demande de réapprovisionnement", "Demande de commande"],
     "A reorder request written by a Maison MTL employee in the Fabric App and validated in Silver; awaiting buyer approval."),
]

RELATIONS = [
    ("RegionHasStore", "Region", "Store", "dim_store", "Region", "StoreCode"),
    ("CategoryHasProduct", "Category", "Product", "dim_product", "Category", "SKU"),
    ("BrandHasProduct", "Brand", "Product", "dim_product", "Brand", "SKU"),
    ("SupplierSuppliesProduct", "Supplier", "Product", "dim_product", "SupplierCode", "SKU"),
    ("StoreHasPerformance", "Store", "StorePerformance", "kpi_store_summary", "StoreCode", "StoreCode"),
    ("CategoryHasPerformance", "Category", "CategoryPerformance", "kpi_category_summary", "Category", "CategoryPerformanceId"),
    ("StoreHasMonthlySales", "Store", "MonthlySales", "sales_month_store_category", "StoreCode", "SalesMonthId"),
    ("CategoryHasMonthlySales", "Category", "MonthlySales", "sales_month_store_category", "Category", "SalesMonthId"),
    ("StoreHoldsInventory", "Store", "InventoryPosition", "inventory_current", "StoreCode", "PositionId"),
    ("ProductHasInventory", "Product", "InventoryPosition", "inventory_current", "SKU", "PositionId"),
    ("PositionHasForecast", "InventoryPosition", "SalesForecast", "ml_forecast_summary", "PositionId", "PositionId"),
    ("PositionHasStockRisk", "InventoryPosition", "StockRisk", "ml_stock_risk", "PositionId", "PositionId"),
    ("StoreHasStockRisk", "Store", "StockRisk", "ml_stock_risk", "StoreCode", "PositionId"),
    ("ProductHasStockRisk", "Product", "StockRisk", "ml_stock_risk", "SKU", "PositionId"),
    ("StoreHasDailyForecast", "Store", "DailyForecast", "ml_sales_forecast_daily", "StoreCode", "ForecastId"),
    ("ProductHasDailyForecast", "Product", "DailyForecast", "ml_sales_forecast_daily", "SKU", "ForecastId"),
    ("StoreHasReorderRequest", "Store", "ReorderRequest", "reorder_requests", "StoreCode", "RequestId"),
    ("ProductHasReorderRequest", "Product", "ReorderRequest", "reorder_requests", "SKU", "RequestId"),
]

# Business-relevant properties bound per entity (keeps the NL-to-GQL context small; Gold keeps every column).
PROPERTIES = {
    "Region": ["Region", "Market", "RegionCode", "StoreCount"],
    "Store": ["StoreCode", "StoreName", "City", "Region", "Market", "StoreFormat", "LocationType", "IsSellingStore"],
    "Category": ["Category", "CategoryGroup", "ProductCount", "Departments"],
    "Brand": ["Brand", "Positioning", "ProductCount"],
    "Supplier": ["SupplierCode", "SupplierName", "Country", "LeadTimeDays", "ActualOnTimePct", "AvgDaysLate",
                 "OpenPurchaseOrders"],
    "Product": ["SKU", "ProductName", "Department", "Category", "Subcategory", "Brand", "SupplierCode", "SupplierName",
                "UnitPrice", "SeasonProfile", "CasePack"],
    "ChainPerformance": ["ChainId", "NetSalesLast28", "NetSalesLast28LY", "Last28GrowthPct", "UnitsLast28",
                         "GrossMarginPctLast28", "NetSalesYTD", "YTDGrowthPct", "StoreOnHandUnits", "DcOnHandUnits",
                         "OutOfStockPositions", "BelowReorderPointPositions"],
    "StorePerformance": ["StoreCode", "StoreName", "City", "NetSalesLast28", "Last28GrowthPct", "UnitsLast28",
                         "NetSalesYTD", "YTDGrowthPct", "OnHandUnits", "OutOfStockPositions", "BelowReorderPointPositions"],
    "CategoryPerformance": ["CategoryPerformanceId", "Department", "Category", "NetSalesLast28", "Last28GrowthPct",
                            "UnitsLast28", "SellThroughPctLast28", "WeeksOfSupply", "OutOfStockPositions"],
    "MonthlySales": ["SalesMonthId", "MonthStart", "StoreCode", "Department", "Category", "NetSales", "UnitsSold"],
    "InventoryPosition": ["PositionId", "StoreCode", "SKU", "OnHandUnits", "OnOrderUnits", "ReorderPointUnits",
                          "DaysOfSupply", "StockStatus"],
    "SalesForecast": ["PositionId", "StoreCode", "SKU", "Forecast7Units", "Forecast28Units", "Forecast28NetSales"],
    "DailyForecast": ["ForecastId", "Date", "StoreCode", "SKU", "ForecastUnits", "ForecastNetSales"],
    "StockRisk": ["PositionId", "StoreCode", "StoreName", "SKU", "ProductName", "OnHandUnits", "ReorderPointUnits",
                  "PredictedLowStockDate", "RiskLevel", "RecommendedReorderQty", "RecommendedAction"],
    "ReorderRequest": ["RequestId", "SubmittedAt", "StoreCode", "StoreName", "SKU", "ProductName", "Quantity", "Urgency",
                       "WorkflowStatus", "IsPending", "RecommendedReorderQty"],
}

MEANINGS = {
    "NetSalesLast28": "Net sales CAD for 2026-10-07 to 2026-11-03 (last 28 days).",
    "NetSalesLast28LY": "Net sales CAD for the same 28 weekdays one year earlier (2025-10-08 to 2025-11-04).",
    "Last28GrowthPct": "Percent growth of last-28-day net sales versus the same 28 weekdays last year (percentage points).",
    "NetSalesYTD": "Net sales CAD from 2026-01-01 to 2026-11-03.",
    "NetSalesLYTD": "Net sales CAD from 2025-01-01 to 2025-11-03.",
    "YTDGrowthPct": "Year-to-date growth in percent.",
    "GrossMarginPctLast28": "Gross margin percent of net sales over the last 28 days.",
    "OnHandUnits": "Units physically on hand at the end of 2026-11-03.",
    "OnOrderUnits": "Units in transit from the DC to the store.",
    "ReorderPointUnits": "Reorder point: replenishment is due when on hand falls below this level.",
    "DaysOfSupply": "On-hand units divided by average daily units of the last 28 days.",
    "StockStatus": "Out of stock, Below reorder point, Healthy or Overstock at the snapshot.",
    "RiskLevel": "ML risk: Critical (out of stock or stockout within transfer lead time), High (below reorder point or "
                 "predicted within 7 days), Medium (8-14 days), Low (later or not within 28 days).",
    "PredictedDaysToLow": "Days from 2026-11-03 until on hand is predicted below the reorder point (0 = already below).",
    "PredictedLowStockDate": "Predicted date the position falls below its reorder point.",
    "ProjectedStockoutDate": "Date the forecast projection reaches zero on hand.",
    "RecommendedReorderQty": "Recommended units to reorder now (rounded to case pack) to cover transfer lead time plus 14 days.",
    "RecommendedAction": "Transfer from DC-QC, partial transfer plus expedited supplier PO, or no action.",
    "Forecast28Units": "Forecast units for 2026-11-04 to 2026-12-01.",
    "Forecast28NetSales": "Forecast net sales CAD for 2026-11-04 to 2026-12-01.",
    "ForecastUnits": "Forecast units for the ForecastId day.",
    "WorkflowStatus": "Pending buyer approval or Rejected - invalid request. The agent cannot approve or place orders.",
    "IsPending": "True when a valid request is awaiting buyer approval.",
    "SellThroughPctLast28": "Units sold in 28 days divided by units sold plus ending on hand, in percent.",
    "WeeksOfSupply": "On-hand units divided by average weekly units sold over the last 28 days.",
    "DcOnHandUnits": "Units on hand at the Québec City distribution centre DC-QC for the SKU.",
}


def guid(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "maison-mtl-iq/ontology/" + value))


def value_type(sql_type):
    return {"int64": "BigInt", "double": "Double", "decimal": "Double", "boolean": "Boolean",
            "dateTime": "DateTime"}.get(sql_type, "String")


def unit(column):
    lowered = column.lower()
    if any(x in lowered for x in ("sales", "cost", "margin", "price", "value")) and "pct" not in lowered:
        return "CAD"
    if "pct" in lowered:
        return "percent"
    if "units" in lowered or "qty" in lowered:
        return "units"
    if "days" in lowered:
        return "days"
    return "business attribute"


def build():
    found = columns()
    missing = sorted({t for _, t, *_ in ENTITIES} - set(found))
    if missing:
        raise RuntimeError("Gold tables missing: " + ", ".join(missing))
    definitions = {"definition.json": {}, ".platform": {"metadata": {"type": "Ontology", "displayName": NAME}}}
    ids = {}
    workspace, lakehouse = f.ws(), f.load("lakehouse_gold.json")["id"]
    report_id = f.load("report.json")["id"] if f.exists("report.json") else None
    for index, (name, table, key, display, synonyms, description) in enumerate(ENTITIES, 1):
        entity_id = str(1000 + index)
        ordinal = {column: number for number, (column, _) in enumerate(found[table], 1)}
        cols = [c for c in found[table] if c[0] in PROPERTIES[name]]
        if {c for c, _ in cols} != set(PROPERTIES[name]) or key not in PROPERTIES[name] or display not in PROPERTIES[name]:
            raise RuntimeError(f"{name}: allow-listed properties missing from {table}")
        # IDs follow the full Gold column order so trimming never re-assigns an existing (immutable) property ID.
        properties = {column: str(100000 + index * 100 + ordinal[column]) for column, _ in cols}
        ids[name] = {"id": entity_id, "key": properties[key], "properties": properties, "table": table}
        values = [{"id": properties[column], "name": column, "valueType": value_type(kind),
                   "semanticEnrichment": {"description": MEANINGS.get(column, f"{column} of the {name}."),
                                          "customAttributes": {"dataClassification": "Synthetic", "unit": unit(column)}}}
                  for column, kind in cols]
        entity = {"id": entity_id, "namespace": "usertypes", "namespaceType": "Custom", "name": name, "visibility": "Visible",
                  "entityIdParts": [properties[key]], "displayNamePropertyId": properties[display], "properties": values,
                  "timeseriesProperties": [],
                  "semanticEnrichment": {"description": description, "synonyms": synonyms,
                                         "customAttributes": {"businessOwner": "Merchandising and Supply Chain",
                                                              "dataClassification": "Synthetic",
                                                              "scenarioAsOfDate": SNAPSHOT}}}
        base = "EntityTypes/" + entity_id
        binding = guid(name + "-binding")
        definitions[base + "/DataBindings/" + binding + ".json"] = {
            "id": binding, "dataBindingConfiguration": {"dataBindingType": "NonTimeSeries",
                "sourceTableProperties": {"sourceType": "LakehouseTable", "workspaceId": workspace, "itemId": lakehouse,
                                          "sourceTableName": table},
                "propertyBindings": [{"sourceColumnName": c, "targetPropertyId": p} for c, p in properties.items()]}}
        definitions[base + "/definition.json"] = entity
        if report_id and name in ("Store", "Product", "StockRisk", "ReorderRequest"):
            definitions[base + "/ResourceLinks/definition.json"] = {"resourceLinks": [
                {"type": "PowerBIReport", "workspaceId": workspace, "itemId": report_id}]}
    for index, (name, source, target, table, source_column, target_column) in enumerate(RELATIONS, 1):
        relation_id = str(2000 + index)
        context = guid(name)
        base = "RelationshipTypes/" + relation_id
        definitions[base + "/definition.json"] = {
            "id": relation_id, "namespace": "usertypes", "namespaceType": "Custom", "name": name,
            "source": {"entityTypeId": ids[source]["id"]}, "target": {"entityTypeId": ids[target]["id"]},
            "semanticEnrichment": {"description": f"{source} connects to {target} ({name}); descriptive, not causal."}}
        definitions[base + "/Contextualizations/" + context + ".json"] = {
            "id": context, "dataBindingTable": {"sourceType": "LakehouseTable", "workspaceId": workspace, "itemId": lakehouse,
                                                "sourceTableName": table},
            "sourceKeyRefBindings": [{"sourceColumnName": source_column, "targetPropertyId": ids[source]["key"]}],
            "targetKeyRefBindings": [{"sourceColumnName": target_column, "targetPropertyId": ids[target]["key"]}]}
    return definitions, ids


def assert_preserved(expected, actual, path=""):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise RuntimeError("Ontology type mismatch: " + path)
        for key, value in expected.items():
            if key not in actual:
                raise RuntimeError("Missing ontology field: " + path + "/" + key)
            assert_preserved(value, actual[key], path + "/" + key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise RuntimeError("Ontology list mismatch: " + path)
        for index, (left, right) in enumerate(zip(expected, actual)):
            assert_preserved(left, right, path + "/" + str(index))
    elif expected != actual:
        raise RuntimeError("Ontology value mismatch: " + path)


def deploy():
    definitions, ids = build()
    f.save("ontology-parts.json", definitions)
    f.save("ontology-ids.json", ids)
    f.item("ontology", "ontologies", NAME, {"parts": [f.part(p, v) for p, v in definitions.items()]}, True)
    return verify()


def verify():
    definitions, _ = build()
    response = f.api(f.path() + "/ontologies/" + f.load("ontology.json")["id"] + "/getDefinition", "POST")
    actual = {p["path"]: json.loads(base64.b64decode(p["payload"])) for p in response["definition"]["parts"]}
    f.save("ontology-readback.json", actual)
    for path, expected in definitions.items():
        if path == ".platform":
            continue
        if path not in actual:
            raise RuntimeError("Missing ontology definition part: " + path)
        assert_preserved(expected, actual[path], path)
    return {"entities": len(ENTITIES), "relationships": len(RELATIONS), "parts": len(definitions)}


def graph():
    ontology = f.load("ontology.json")
    name = ontology["displayName"] + "_graph_" + ontology["id"].replace("-", "")
    matches = [i for i in f.listing(f.path() + "/items") if i["type"] == "GraphModel" and i["displayName"] == name]
    if len(matches) != 1:
        raise RuntimeError("Could not identify ontology-managed graph " + name)
    f.save("graph.json", matches[0])
    return matches[0]


def ready(polls=60):
    current = graph()
    response = f.api(f.path() + "/graphModels/" + current["id"] + "/getDefinition", "POST")
    f.save("graph-definition.json", response)
    part = next(v for v in response["definition"]["parts"] if v["path"] == "dataSources.json")
    sources = json.loads(base64.b64decode(part["payload"]))["dataSources"]
    lakehouse = f.load("lakehouse_gold.json")["id"]
    expected = {lakehouse + "/Tables/" + t for t in {e[1] for e in ENTITIES} | {r[3] for r in RELATIONS}}
    actual = {urlparse(s["properties"]["path"]).path.lstrip("/") for s in sources}
    if actual != expected:
        raise RuntimeError(f"Graph paths differ: missing {sorted(expected - actual)}, extra {sorted(actual - expected)}")
    previous = None
    for _ in range(polls):
        jobs = [j for j in f.listing(f.path() + "/items/" + current["id"] + "/jobs/instances") if j["status"] != "Deduped"]
        if not jobs:
            raise RuntimeError("No graph ingestion job yet")
        state = max(jobs, key=lambda j: j["startTimeUtc"])
        f.save("graph-job-state.json", state)
        if state["status"] != previous:
            print("graph", state["status"], flush=True)
            previous = state["status"]
        if state["status"] == "Completed":
            return state
        if state["status"] in ("Failed", "Cancelled"):
            raise RuntimeError(json.dumps(state))
        time.sleep(30)
    raise TimeoutError("Graph is still running")


def refresh(polls=80):
    current = graph()
    _, headers, _ = f.request(f.path() + "/graphModels/" + current["id"] + "/jobs/refreshGraph/instances", "POST", {})
    f.save("graph-refresh.json", {"location": headers.get("location"), "graph": current["id"],
                                  "requestedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    location = headers.get("location")
    if not location:
        raise RuntimeError("Graph refresh accepted without location")
    previous = None
    for _ in range(polls):
        state = f.api(location)
        f.save("graph-refresh-state.json", state)
        if state["status"] != previous:
            print("graph refresh", state["status"], flush=True)
            previous = state["status"]
        if state["status"] == "Completed":
            return ready(polls=1)
        if state["status"] == "Deduped":
            return ready(polls=polls)
        if state["status"] in ("Failed", "Cancelled"):
            raise RuntimeError(json.dumps(state))
        time.sleep(30)
    raise TimeoutError("Graph refresh is still running")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["deploy", "verify", "ready", "refresh"])
    command = parser.parse_args().command
    print(json.dumps({"deploy": deploy, "verify": verify, "ready": ready, "refresh": refresh}[command](),
                     indent=2, default=str))
