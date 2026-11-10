"""Direct Lake semantic model over the MTL_Gold lakehouse with governed retail, inventory, ML and reorder measures."""
import json
import time
import uuid

import fabric as f

MODEL_NAME = "Maison MTL Retail IQ Model"
TABLES = {  # model table -> (gold table, description)
    "Date": ("dim_date", "Calendar 2024-11-04 to 2026-12-31. Actuals end 2026-11-03; the next 28 days are the ML forecast period."),
    "Store": ("dim_store", "Ten illustrative Quebec stores plus the Québec City distribution centre (DC-QC)."),
    "Region": ("dim_region", "Quebec administrative regions grouped into markets."),
    "Product": ("dim_product", "Synthetic 60-SKU assortment across Women, Men, Kids, Home and Accessories."),
    "Category": ("dim_category", "Merchandise categories and category groups."),
    "Brand": ("dim_brand", "Fictional house and partner brands."),
    "Supplier": ("dim_supplier", "Fictional suppliers with planned lead time and actual PO on-time performance."),
    "Sales": ("fact_sales", "Daily POS sales by store and SKU after Silver cleansing and deduplication (CAD)."),
    "Inventory": ("fact_inventory", "Daily end-of-day inventory snapshots for stores and the DC. Semi-additive: use the latest date."),
    "Replenishment": ("fact_replenishment", "DC-to-store transfers and supplier purchase orders."),
    "Forecast": ("ml_sales_forecast_daily", "LightGBM 28-day daily unit forecast per store and SKU with P10/P90 range."),
    "Stock Risk": ("ml_stock_risk", "ML low-stock prediction per store-SKU position at the 2026-11-03 snapshot."),
    "Reorder Requests": ("reorder_requests", "Reorder requests written by employees in the Fabric App, validated in Silver."),
    "Model Metrics": ("ml_model_metrics", "Holdout evaluation metrics for the registered ML models."),
    "Data Quality": ("dq_events", "Data-quality rules applied between Bronze and Silver with affected row counts."),
    "Lineage": ("medallion_lineage", "Row counts by entity across Bronze, Silver and Gold."),
}
RELATIONSHIPS = [
    ("Sales", "DateKey", "Date", "DateKey"), ("Sales", "StoreCode", "Store", "StoreCode"), ("Sales", "SKU", "Product", "SKU"),
    ("Inventory", "DateKey", "Date", "DateKey"), ("Inventory", "StoreCode", "Store", "StoreCode"),
    ("Inventory", "SKU", "Product", "SKU"), ("Replenishment", "SKU", "Product", "SKU"),
    ("Forecast", "DateKey", "Date", "DateKey"), ("Forecast", "StoreCode", "Store", "StoreCode"), ("Forecast", "SKU", "Product", "SKU"),
    ("Stock Risk", "StoreCode", "Store", "StoreCode"), ("Stock Risk", "SKU", "Product", "SKU"),
    ("Reorder Requests", "StoreCode", "Store", "StoreCode"), ("Reorder Requests", "SKU", "Product", "SKU"),
    ("Reorder Requests", "DateKey", "Date", "DateKey"),
    ("Store", "Region", "Region", "Region"), ("Product", "Category", "Category", "Category"),
    ("Product", "Brand", "Brand", "Brand"), ("Product", "SupplierCode", "Supplier", "SupplierCode"),
]
SORT_BY = {("Date", "MonthName"): "MonthNumber", ("Date", "MonthLabel"): "YearMonth", ("Date", "DayName"): "DayOfWeekNumber",
           ("Stock Risk", "RiskLevel"): "RiskRank"}
CUR, PCT, INT, DEC1 = r"\$#,0", "0.0%", "#,0", "#,0.0"
L28 = "REMOVEFILTERS('Date'), 'Date'[IsLast28Days] = TRUE()"
LY28 = "REMOVEFILTERS('Date'), 'Date'[IsLast28DaysLY] = TRUE()"
LAST = "VAR LastDay = CALCULATE(MAX(Inventory[Date]), REMOVEFILTERS(Store), REMOVEFILTERS(Product)) RETURN "
STORES = "Inventory[LocationType] = \"Store\""
MEASURES = {
    "Sales": [
        ("Net Sales", "SUM(Sales[NetSales])", CUR, "Gross sales minus markdown discounts, CAD."),
        ("Gross Sales", "SUM(Sales[GrossSales])", CUR, "Units at regular price, CAD."),
        ("Markdown Amount", "SUM(Sales[DiscountAmount])", CUR, "Promotional and clearance markdowns, CAD."),
        ("Markdown %", "DIVIDE([Markdown Amount], [Gross Sales])", PCT, "Markdown amount divided by gross sales."),
        ("Units Sold", "SUM(Sales[UnitsSold])", INT, "Units sold."),
        ("Cost of Goods Sold", "SUM(Sales[CostOfGoods])", CUR, "Units sold times unit cost, CAD."),
        ("Gross Margin", "SUM(Sales[GrossMargin])", CUR, "Net sales minus cost of goods sold, CAD."),
        ("Gross Margin %", "DIVIDE([Gross Margin], [Net Sales])", PCT, "Gross margin divided by net sales."),
        ("Average Selling Price", "DIVIDE([Net Sales], [Units Sold])", r"\$#,0.00", "Net sales per unit, CAD."),
        ("Net Sales LY", "CALCULATE([Net Sales], DATEADD('Date'[Date], -364, DAY))", CUR,
         "Net sales on the same weekdays 364 days earlier."),
        ("Net Sales YoY %", "DIVIDE([Net Sales] - [Net Sales LY], [Net Sales LY])", PCT, "Growth versus the same weekdays last year."),
        ("Units Sold LY", "CALCULATE([Units Sold], DATEADD('Date'[Date], -364, DAY))", INT, "Units on the same weekdays last year."),
        ("Net Sales Last 28 Days", f"CALCULATE([Net Sales], {L28})", CUR, "Net sales 2026-10-07 to 2026-11-03."),
        ("Net Sales Last 28 Days LY", f"CALCULATE([Net Sales], {LY28})", CUR, "Net sales for the same 28 weekdays last year."),
        ("Last 28 Days YoY %", "DIVIDE([Net Sales Last 28 Days] - [Net Sales Last 28 Days LY], [Net Sales Last 28 Days LY])", PCT,
         "Last-28-day growth versus the same weekdays last year."),
        ("Units Last 28 Days", f"CALCULATE([Units Sold], {L28})", INT, "Units sold in the last 28 days."),
        ("Gross Margin % Last 28 Days", f"CALCULATE([Gross Margin %], {L28})", PCT, "Gross margin % in the last 28 days."),
        ("Net Sales YTD", "CALCULATE([Net Sales], REMOVEFILTERS('Date'), 'Date'[IsYTD] = TRUE())", CUR, "2026 net sales through 2026-11-03."),
        ("Net Sales LYTD", "CALCULATE([Net Sales], REMOVEFILTERS('Date'), 'Date'[IsLYTD] = TRUE())", CUR, "2025 net sales through 2025-11-03."),
        ("YTD Growth %", "DIVIDE([Net Sales YTD] - [Net Sales LYTD], [Net Sales LYTD])", PCT, "Year-to-date growth."),
        ("Avg Daily Units Last 28 Days", "DIVIDE([Units Last 28 Days], 28)", "#,0.00", "Average daily units over the last 28 days."),
    ],
    "Inventory": [
        ("On Hand Units", LAST + f"CALCULATE(SUM(Inventory[OnHandUnits]), Inventory[Date] = LastDay, {STORES})", INT,
         "Store on-hand units at the latest snapshot in context."),
        ("On Order Units", LAST + f"CALCULATE(SUM(Inventory[OnOrderUnits]), Inventory[Date] = LastDay, {STORES})", INT,
         "Units in transit to stores at the latest snapshot."),
        ("DC On Hand Units", LAST + "CALCULATE(SUM(Inventory[OnHandUnits]), Inventory[Date] = LastDay, "
         "Inventory[LocationType] = \"Distribution centre\", REMOVEFILTERS(Store))", INT, "Distribution centre DC-QC on-hand units."),
        ("Inventory Cost", LAST + f"CALCULATE(SUM(Inventory[InventoryCost]), Inventory[Date] = LastDay, {STORES})", CUR,
         "Store inventory at cost, CAD."),
        ("Store Positions", LAST + f"CALCULATE(COUNTROWS(Inventory), Inventory[Date] = LastDay, {STORES})", INT,
         "Store-SKU positions at the latest snapshot."),
        ("Out of Stock Positions", LAST + f"CALCULATE(COUNTROWS(Inventory), Inventory[Date] = LastDay, {STORES}, "
         "Inventory[IsOutOfStock] = TRUE())", INT, "Store-SKU positions with zero on hand."),
        ("Below Reorder Point Positions", LAST + f"CALCULATE(COUNTROWS(Inventory), Inventory[Date] = LastDay, {STORES}, "
         "Inventory[IsBelowReorderPoint] = TRUE())", INT, "Positions where on hand is below the reorder point (includes out of stock)."),
        ("In-Stock %", "1 - DIVIDE([Out of Stock Positions], [Store Positions])", PCT, "Share of store-SKU positions with stock."),
        ("Days of Supply", "DIVIDE([On Hand Units], [Avg Daily Units Last 28 Days])", DEC1,
         "On-hand units divided by average daily units of the last 28 days."),
        ("Sell-Through % Last 28 Days", "DIVIDE([Units Last 28 Days], [Units Last 28 Days] + [On Hand Units])", PCT,
         "Units sold in 28 days divided by units sold plus ending on hand."),
        ("Stockout Position Days", f"CALCULATE(COUNTROWS(Inventory), {STORES}, Inventory[IsOutOfStock] = TRUE())", INT,
         "Number of store-SKU-days ending with zero stock in the selected period."),
    ],
    "Replenishment": [
        ("Open Supplier POs", "CALCULATE(COUNTROWS(Replenishment), Replenishment[OrderType] = \"Supplier PO\", Replenishment[IsOpen] = TRUE())",
         INT, "Supplier purchase orders not yet received."),
        ("Supplier On-Time %", "1 - DIVIDE(CALCULATE(COUNTROWS(Replenishment), Replenishment[OrderType] = \"Supplier PO\", "
         "Replenishment[IsLate] = TRUE()), CALCULATE(COUNTROWS(Replenishment), Replenishment[OrderType] = \"Supplier PO\", "
         "NOT ISBLANK(Replenishment[ReceivedDate])))", PCT, "Received supplier POs delivered by the expected date."),
    ],
    "Forecast": [
        ("Forecast Units", "SUM(Forecast[ForecastUnits])", INT, "ML forecast units (next 28 days, 2026-11-04 to 2026-12-01)."),
        ("Forecast Units P10", "SUM(Forecast[ForecastUnitsLow])", INT, "Lower (P10) forecast range."),
        ("Forecast Units P90", "SUM(Forecast[ForecastUnitsHigh])", INT, "Upper (P90) forecast range."),
        ("Forecast Net Sales", "SUM(Forecast[ForecastNetSales])", CUR, "Forecast units times planned net price, CAD."),
        ("Forecast vs Last 28 Days %", "DIVIDE([Forecast Units] - [Units Last 28 Days], [Units Last 28 Days])", PCT,
         "Next-28-day forecast units versus the last 28 days of actual units."),
        ("Units Actual or Forecast", "IF(ISBLANK([Forecast Units]), [Units Sold], [Forecast Units])", INT,
         "Actual units through the snapshot and forecast units afterwards (for trend charts)."),
    ],
    "Stock Risk": [
        ("Critical Risk Positions", "CALCULATE(COUNTROWS('Stock Risk'), 'Stock Risk'[RiskLevel] = \"Critical\") + 0", INT,
         "Out of stock now or projected to stock out within the transfer lead time."),
        ("High Risk Positions", "CALCULATE(COUNTROWS('Stock Risk'), 'Stock Risk'[RiskLevel] IN {\"Critical\", \"High\"}) + 0", INT,
         "Critical or High risk positions (below reorder point now or predicted within 7 days)."),
        ("Low Stock Within 7 Days", "CALCULATE(COUNTROWS('Stock Risk'), 'Stock Risk'[PredictedDaysToLow] <= 7)", INT,
         "Positions predicted below reorder point within 7 days (0 = already below)."),
        ("Recommended Reorder Units", "SUM('Stock Risk'[RecommendedReorderQty])", INT, "ML-recommended reorder quantity, units."),
        ("Risk Positions", "COUNTROWS('Stock Risk')", INT, "Store-SKU positions scored by the low-stock model."),
        ("Recommended Reorder Units (High Risk)", "CALCULATE([Recommended Reorder Units], 'Stock Risk'[RiskLevel] IN {\"Critical\", \"High\"})",
         INT, "Recommended units for Critical and High risk positions."),
        ("Forecast 28 Day Units (Positions)", "SUM('Stock Risk'[Forecast28Units])", INT, "Forecast units per position for the next 28 days."),
    ],
    "Reorder Requests": [
        ("Reorder Requests", "COUNTROWS('Reorder Requests') + 0", INT, "Requests submitted in the Fabric App."),
        ("Pending Reorders", "CALCULATE(COUNTROWS('Reorder Requests'), 'Reorder Requests'[IsPending] = TRUE()) + 0", INT,
         "Valid requests awaiting buyer approval."),
        ("Pending Reorder Units", "CALCULATE(SUM('Reorder Requests'[Quantity]), 'Reorder Requests'[IsPending] = TRUE()) + 0", INT,
         "Units on pending reorder requests."),
        ("Invalid Reorder Requests", "CALCULATE(COUNTROWS('Reorder Requests'), 'Reorder Requests'[ValidationStatus] = \"Invalid\") + 0", INT,
         "Requests rejected by Silver validation."),
    ],
    "Model Metrics": [
        ("Forecast WAPE %", "CALCULATE(MAX('Model Metrics'[Value]), 'Model Metrics'[Metric] = \"WAPE\", "
         "'Model Metrics'[Segment] = \"Holdout (department-day)\") / 100", PCT, "Forecast WAPE on chain department-day totals over the 28-day holdout (planning level)."),
        ("Baseline WAPE %", "CALCULATE(MAX('Model Metrics'[BaselineValue]), 'Model Metrics'[Metric] = \"WAPE\", "
         "'Model Metrics'[Segment] = \"Holdout (department-day)\") / 100", PCT, "Seasonal-naive WAPE on the same holdout."),
        ("Low-Stock Recall %", "CALCULATE(MAX('Model Metrics'[Value]), 'Model Metrics'[Metric] = \"Recall_low_within_7d\") / 100",
         PCT, "Share of real low-stock events within 7 days that the model flagged."),
        ("Low-Stock Precision %", "CALCULATE(MAX('Model Metrics'[Value]), 'Model Metrics'[Metric] = \"Precision_low_within_7d\") / 100",
         PCT, "Share of 7-day low-stock alerts that were correct."),
    ],
    "Data Quality": [
        ("Rows Affected", "SUM('Data Quality'[AffectedRows])", INT, "Rows touched by data-quality rules."),
        ("Rows Quarantined", "CALCULATE([Rows Affected], 'Data Quality'[Action] = \"Quarantined\")", INT, "Invalid rows held back."),
        ("Rows Deduplicated", "CALCULATE([Rows Affected], 'Data Quality'[Action] = \"Deduplicated\")", INT, "Duplicate rows removed."),
        ("Rows Standardized", "CALCULATE([Rows Affected], 'Data Quality'[Action] = \"Standardized\")", INT, "Codes and names standardized."),
        ("DQ Rules", "COUNTROWS('Data Quality')", INT, "Number of data-quality rules that fired."),
    ],
    "Lineage": [
        ("Bronze Rows", "CALCULATE(SUM(Lineage[RowCount]), Lineage[Layer] = \"Bronze\")", INT, "Rows mirrored into Bronze."),
        ("Silver Rows", "CALCULATE(SUM(Lineage[RowCount]), Lineage[Layer] = \"Silver\")", INT, "Clean rows in Silver."),
        ("Gold Rows", "CALCULATE(SUM(Lineage[RowCount]), Lineage[Layer] = \"Gold\")", INT, "Rows in the Gold star schema."),
        ("Layer Rows", "SUM(Lineage[RowCount])", INT, "Rows for the selected entity and layer."),
    ],
}
TYPES = {"int": "int64", "bigint": "int64", "smallint": "int64", "decimal": "decimal", "float": "double", "real": "double",
         "bit": "boolean", "date": "dateTime", "datetime2": "dateTime", "varchar": "string", "char": "string"}

# Column descriptions read by the Data Agent DAX generator (and Copilot); values are exactly as stored.
COLUMN_DOCS = {
    ("Date", "Date"): "Calendar day. Actual sales and inventory run to 2026-11-03; later dates are the ML forecast period.",
    ("Date", "YearMonth"): "Year and month as a number, e.g. 202610 = October 2026.",
    ("Date", "MonthLabel"): "Month label such as 'Oct 2026'.",
    ("Date", "WeekStart"): "Monday that starts the calendar week.",
    ("Date", "IsLast28Days"): "True for 2026-10-07 to 2026-11-03 (the last 28 days of actuals).",
    ("Date", "IsLast28DaysLY"): "True for the same 28 weekdays one year earlier (2025-10-08 to 2025-11-04).",
    ("Date", "IsYTD"): "True for 2026-01-01 to 2026-11-03.",
    ("Date", "IsLYTD"): "True for 2025-01-01 to 2025-11-03.",
    ("Date", "IsActual"): "True up to the 2026-11-03 snapshot (actual data).",
    ("Date", "IsForecastPeriod"): "True for the 28 forecast days 2026-11-04 to 2026-12-01.",
    ("Store", "StoreCode"): "Store code, e.g. MT-CV, QC-VQ, LV-CL; DC-QC is the distribution centre.",
    ("Store", "StoreName"): "Store name, e.g. 'Maison MTL Laval', 'Maison MTL Vieux-Québec', 'Maison MTL Sherbrooke'.",
    ("Store", "City"): "City, e.g. Québec, Montréal, Laval, Sherbrooke, Gatineau, Trois-Rivières, Lévis, Brossard.",
    ("Store", "LocationType"): "'Store' for the ten selling stores or 'Distribution centre' for DC-QC.",
    ("Store", "IsSellingStore"): "True for the ten selling stores.",
    ("Product", "SKU"): "Product SKU such as W-OUT-101.",
    ("Product", "ProductName"): "Product name, e.g. \"Women's Long Down Parka\", \"Kids' Snow Boot\".",
    ("Product", "Department"): "Women, Men, Kids, Home or Accessories.",
    ("Product", "Category"): "Merchandise category, e.g. Outerwear, Footwear, Knitwear, Cold-weather accessories, Bedding.",
    ("Product", "Subcategory"): "Subcategory, e.g. Parkas, Winter boots, Toques, Mitts, Sweaters, Jeans, Swimsuits.",
    ("Product", "Brand"): "Fictional brand, e.g. Boréale, Nordik, Atelier 31, Petits Flocons.",
    ("Sales", "Date"): "Sale date.",
    ("Inventory", "Date"): "Snapshot date; on-hand values are end-of-day stock.",
    ("Forecast", "Date"): "Forecast day (2026-11-04 to 2026-12-01).",
}
HIDDEN = {("Sales", "DateKey"), ("Sales", "MarkdownPct"), ("Inventory", "DateKey"), ("Forecast", "DateKey"),
          ("Forecast", "ForecastId"), ("Forecast", "RunId"), ("Forecast", "ModelName"), ("Forecast", "ModelVersion"),
          ("Forecast", "GeneratedAt"), ("Stock Risk", "RunId"), ("Stock Risk", "ModelName"), ("Stock Risk", "ModelVersion"),
          ("Stock Risk", "GeneratedAt"), ("Stock Risk", "ModelDaysToLow"), ("Stock Risk", "ForecastDaysToLow"),
          ("Reorder Requests", "DateKey"), ("Date", "DateKey")}


def stable(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "maison-mtl-iq/model/" + name))


def quote(name):
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def gold():
    lakehouse = f.api(f.path() + "/lakehouses/" + f.load("lakehouse_gold.json")["id"])
    f.save("lakehouse_gold.json", lakehouse)
    return lakehouse, lakehouse["properties"]["sqlEndpointProperties"]


def refresh_sql_endpoint():
    _, sql = gold()
    try:
        return f.api(f.path() + "/sqlEndpoints/" + sql["id"] + "/refreshMetadata", "POST", {})
    except RuntimeError as error:
        print("SQL endpoint metadata refresh unavailable:", str(error)[:200])


def gold_connection():
    lakehouse, sql = gold()
    return f.sql_connect(sql["connectionString"], lakehouse["displayName"], app="MtlModel")


def columns():
    with gold_connection() as conn:
        rows = conn.execute("SELECT t.name, c.name, ty.name FROM sys.tables t JOIN sys.columns c ON c.object_id = t.object_id "
                            "JOIN sys.types ty ON ty.user_type_id = c.user_type_id ORDER BY t.name, c.column_id").fetchall()
    found = {}
    for table, column, sqltype in rows:
        found.setdefault(table, []).append((column, TYPES[sqltype]))
    return found


def table_tmdl(name, cols):
    source, description = TABLES[name]
    text = f"/// {description}\ntable {quote(name)}\n\tlineageTag: {stable(name)}\n"
    if name == "Date":
        text += "\tdataCategory: Time\n"
    for measure, expression, fmt, doc in MEASURES.get(name, []):
        text += f"\n\t/// {doc}\n\tmeasure {quote(measure)} = {expression}\n\t\tformatString: {fmt}\n" \
                f"\t\tlineageTag: {stable(name + '.m.' + measure)}\n"
    for column, datatype in cols:
        doc = COLUMN_DOCS.get((name, column))
        text += (f"\n\t/// {doc}" if doc else "") + \
            f"\n\tcolumn {quote(column)}\n\t\tdataType: {datatype}\n\t\tsummarizeBy: none\n\t\tsourceColumn: {column}\n" \
            f"\t\tlineageTag: {stable(name + '.' + column)}\n"
        if (name, column) in HIDDEN:
            text += "\t\tisHidden\n"
        if name == "Date" and column == "Date":
            text += "\t\tisKey\n"
        if datatype == "dateTime":
            text += "\t\tformatString: yyyy-mm-dd\n"
        if (name, column) in SORT_BY:
            text += f"\t\tsortByColumn: {SORT_BY[(name, column)]}\n"
    text += f"\n\tpartition {quote(name)} = entity\n\t\tmode: directLake\n\t\tsource\n" \
            f"\t\t\tentityName: {source}\n\t\t\tschemaName: dbo\n\t\t\texpressionSource: DatabaseQuery\n"
    return text


def definition():
    lakehouse, sql = gold()
    found = columns()
    missing = [source for source, _ in TABLES.values() if source not in found]
    if missing:
        raise RuntimeError("Gold tables missing from the SQL endpoint: " + ", ".join(missing))
    names = {c.lower() for source, _ in TABLES.values() for c, _ in found[source]}
    clashes = [m for ms in MEASURES.values() for m, *_ in ms if m.lower() in names]
    if clashes:
        raise RuntimeError("Measure names collide with columns: " + ", ".join(clashes))
    parts = [
        f.part("definition.pbism", {"version": "4.2", "settings": {"qnaEnabled": True}}),
        f.part("definition/database.tmdl", "database\n\tcompatibilityLevel: 1604\n"),
        f.part("definition/model.tmdl", "model Model\n\tculture: en-CA\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
               "\tsourceQueryCulture: en-CA\n\tdiscourageImplicitMeasures\n\n" +
               "\n".join("ref table " + quote(t) for t in TABLES) + "\n"),
        f.part("definition/expressions.tmdl", "expression DatabaseQuery =\n\t\tlet\n"
               f'\t\t    database = Sql.Database("{sql["connectionString"]}", "{sql["id"]}")\n'
               f"\t\tin\n\t\t    database\n\tlineageTag: {stable('DatabaseQuery')}\n"),
    ]
    for name, (source, _) in TABLES.items():
        parts.append(f.part(f"definition/tables/{name}.tmdl", table_tmdl(name, found[source])))
    rels = "".join(f"\nrelationship {stable('rel.' + a + b + c)}\n\tfromColumn: {quote(a)}.{b}\n\ttoColumn: {quote(c)}.{d}\n"
                   for a, b, c, d in RELATIONSHIPS)
    parts.append(f.part("definition/relationships.tmdl", rels))
    return {"parts": parts}


def build():
    refresh_sql_endpoint()
    model = f.item("model", "semanticModels", MODEL_NAME, definition(), True)
    return {"model": model["id"]}


def refresh():
    dataset = "/datasets/" + f.load("model.json")["id"]
    f.pbi(dataset + "/refreshes", "POST", {"type": "full"})
    for _ in range(90):
        time.sleep(10)
        latest = f.pbi(dataset + "/refreshes?$top=1")["value"][0]
        if latest["status"] in ("Completed", "Failed", "Disabled", "Cancelled"):
            f.save("model-refresh.json", latest)
            if latest["status"] != "Completed":
                raise RuntimeError("Refresh failed: " + json.dumps(latest)[:2000])
            return latest
    raise TimeoutError("Refresh did not finish")


def dax(query):
    result = f.pbi("/datasets/" + f.load("model.json")["id"] + "/executeQueries", "POST",
                   {"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}})
    if result.get("error") or any(r.get("error") for r in result.get("results", [])):
        raise RuntimeError(json.dumps(result)[:2000])
    return result["results"][0]["tables"][0]["rows"]


def verify():
    expected = f.load("expected.json")
    row = dax('EVALUATE ROW("Net2025", CALCULATE([Net Sales], \'Date\'[Year] = 2025), '
              '"Units2025", CALCULATE([Units Sold], \'Date\'[Year] = 2025), "YTD", [Net Sales YTD], "LYTD", [Net Sales LYTD], '
              '"L28", [Net Sales Last 28 Days], "L28LY", [Net Sales Last 28 Days LY], "U28", [Units Last 28 Days], '
              '"OnHand", [On Hand Units], "DC", [DC On Hand Units], "OOS", [Out of Stock Positions], '
              '"BelowROP", [Below Reorder Point Positions], "Positions", [Store Positions], "Forecast", [Forecast Units], '
              '"HighRisk", [High Risk Positions], "Critical", [Critical Risk Positions], "RecUnits", [Recommended Reorder Units (High Risk)], '
              '"WAPE", [Forecast WAPE %], "DQ", [Rows Affected], "GM2025", CALCULATE([Gross Margin %], \'Date\'[Year] = 2025))')[0]
    values = {k.strip("[]"): v for k, v in row.items()}
    checks = {"Net2025": expected["netSales2025"], "Units2025": expected["units2025"], "YTD": expected["netSalesYtd2026"],
              "LYTD": expected["netSalesYtd2025"], "L28": expected["netSalesLast28"], "L28LY": expected["netSalesLast28LY"],
              "U28": expected["unitsLast28"], "OnHand": expected["storeOnHandUnits"], "DC": expected["dcOnHandUnits"],
              "OOS": expected["outOfStockPositions"], "BelowROP": expected["belowReorderPointPositions"],
              "Positions": expected["positions"], "DQ": expected["dqAffectedRows"]}
    failures = {k: (values.get(k), v) for k, v in checks.items() if values.get(k) is None or abs(float(values[k]) - v) > 0.05}
    top = dax("EVALUATE TOPN(1, SUMMARIZECOLUMNS(Store[StoreCode], \"L28\", [Net Sales Last 28 Days]), [L28], DESC)")[0]
    if top["Store[StoreCode]"] != expected["topStoreLast28"]["code"]:
        failures["topStore"] = (top, expected["topStoreLast28"])
    evidence = {"values": values, "expected": checks, "topStoreLast28": top, "failures": failures}
    f.save("model-verification.json", evidence)
    if failures:
        raise RuntimeError("Semantic model reconciliation failed: " + json.dumps(failures, default=str))
    return values


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "refresh", "verify"])
    command = parser.parse_args().command
    print(json.dumps({"build": build, "refresh": refresh, "verify": verify}[command](), indent=2, default=str))
