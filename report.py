"""Six-page PBIR report in Maison MTL green and white, with DAX binding checks and server-side page renders."""
import io
import json
import time
import zipfile
from urllib.request import Request, urlopen

import fabric as f
from model import dax

REPORT_NAME = "Maison MTL Retail IQ"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
GREEN, DEEP, MINT, TINT, INK, MUTED, PAGE_BG = "#00573F", "#003D2C", "#5FA37E", "#E6F2EC", "#1F2A24", "#5E6B64", "#F4F8F5"
M, C = True, False
CARDS_Y, CHART_Y, BOTTOM_Y = 100, 214, 500


def cards(specs):
    width = (1232 - 12 * (len(specs) - 1)) / len(specs)
    return [(f"card{i}", "card", label, 24 + i * (width + 12), CARDS_Y, width, 100, {"Values": [(table, measure, M)]})
            for i, (table, measure, label) in enumerate(specs)]


def slicers(*fields):
    return [(f"slicer{i}", "slicer", label, 860 + i * 204, 14, 192, 72, {"Values": [(table, column, C)]})
            for i, (table, column, label) in enumerate(fields)]


PAGES = [
    ("executive", "Executive overview", "How are Quebec stores trading right now, and where is stock at risk?",
     slicers(("Region", "Market", "Market")) + cards([
         ("Sales", "Net Sales Last 28 Days", "Net sales, last 28 days"), ("Sales", "Last 28 Days YoY %", "vs same 28 days LY"),
         ("Sales", "Net Sales YTD", "Net sales YTD"), ("Sales", "YTD Growth %", "YTD growth"),
         ("Sales", "Gross Margin % Last 28 Days", "Gross margin %, 28 days"), ("Inventory", "In-Stock %", "In-stock %")]) + [
         ("trend", "lineChart", "Net sales vs last year by month", 24, CHART_Y, 760, 270,
          {"Category": [("Date", "MonthLabel", C)], "Y": [("Sales", "Net Sales", M), ("Sales", "Net Sales LY", M)]}),
         ("stores", "clusteredBarChart", "Net sales by store, last 28 days", 796, CHART_Y, 460, 270,
          {"Category": [("Store", "StoreName", C)], "Y": [("Sales", "Net Sales Last 28 Days", M)]}),
         ("categories", "clusteredColumnChart", "Net sales by category, last 28 days vs last year", 24, BOTTOM_Y, 760, 280,
          {"Category": [("Product", "Category", C)], "Y": [("Sales", "Net Sales Last 28 Days", M), ("Sales", "Net Sales Last 28 Days LY", M)]}),
         ("scorecard", "tableEx", "Store scorecard", 796, BOTTOM_Y, 460, 280,
          {"Values": [("Store", "StoreName", C), ("Sales", "Net Sales Last 28 Days", M), ("Sales", "Last 28 Days YoY %", M),
                      ("Inventory", "Out of Stock Positions", M), ("Stock Risk", "High Risk Positions", M)]})]),
    ("sales", "Sales performance", "Which stores, departments and products drive growth and margin?",
     slicers(("Date", "Year", "Year"), ("Store", "Region", "Region")) + cards([
         ("Sales", "Net Sales", "Net sales"), ("Sales", "Net Sales YoY %", "YoY growth"), ("Sales", "Units Sold", "Units sold"),
         ("Sales", "Average Selling Price", "Avg selling price"), ("Sales", "Gross Margin %", "Gross margin %"),
         ("Sales", "Markdown %", "Markdown %")]) + [
         ("depttrend", "lineChart", "Net sales by month and department (seasonality)", 24, CHART_Y, 760, 270,
          {"Category": [("Date", "MonthLabel", C)], "Series": [("Product", "Department", C)], "Y": [("Sales", "Net Sales", M)]}),
         ("region", "clusteredBarChart", "Net sales by region", 796, CHART_Y, 460, 270,
          {"Category": [("Store", "Region", C)], "Y": [("Sales", "Net Sales", M)]}),
         ("products", "tableEx", "Product scorecard", 24, BOTTOM_Y, 1232, 280,
          {"Values": [("Product", "ProductName", C), ("Product", "Department", C), ("Product", "Category", C),
                      ("Product", "Brand", C), ("Sales", "Net Sales", M), ("Sales", "Net Sales YoY %", M),
                      ("Sales", "Units Sold", M), ("Sales", "Gross Margin %", M), ("Sales", "Markdown %", M)]})]),
    ("inventory", "Inventory health", "Are shelves full where customers shop, and how much cover do we have?",
     slicers(("Product", "Department", "Department"), ("Store", "Region", "Region")) + cards([
         ("Inventory", "On Hand Units", "Store on hand"), ("Inventory", "In-Stock %", "In-stock %"),
         ("Inventory", "Out of Stock Positions", "Out of stock"), ("Inventory", "Below Reorder Point Positions", "Below reorder point"),
         ("Inventory", "Days of Supply", "Days of supply"), ("Inventory", "DC On Hand Units", "DC-QC on hand")]) + [
         ("status", "clusteredColumnChart", "Store-SKU positions by stock status", 24, CHART_Y, 400, 270,
          {"Category": [("Stock Risk", "StockStatus", C)], "Y": [("Stock Risk", "Risk Positions", M)]}),
         ("oosdays", "lineChart", "Stockout position-days by month", 436, CHART_Y, 400, 270,
          {"Category": [("Date", "MonthLabel", C)], "Y": [("Inventory", "Stockout Position Days", M)]}),
         ("cover", "clusteredBarChart", "Days of supply by category", 848, CHART_Y, 408, 270,
          {"Category": [("Product", "Category", C)], "Y": [("Inventory", "Days of Supply", M)]}),
         ("positions", "tableEx", "Positions below reorder point", 24, BOTTOM_Y, 1232, 280,
          {"Values": [("Store", "StoreName", C), ("Product", "ProductName", C), ("Stock Risk", "StockStatus", C),
                      ("Stock Risk", "OnHandUnits", C), ("Stock Risk", "OnOrderUnits", C), ("Stock Risk", "ReorderPointUnits", C),
                      ("Stock Risk", "DaysOfSupply", C), ("Stock Risk", "DcOnHandUnits", C)]})]),
    ("forecast", "Forecast & stock risk (ML)", "What will sell in the next 28 days, and what must be reordered now?",
     slicers(("Product", "Department", "Department"), ("Store", "StoreName", "Store")) + cards([
         ("Forecast", "Forecast Units", "Forecast units, next 28 days"), ("Forecast", "Forecast Net Sales", "Forecast net sales"),
         ("Forecast", "Forecast vs Last 28 Days %", "vs last 28 days"), ("Stock Risk", "Critical Risk Positions", "Critical positions"),
         ("Stock Risk", "High Risk Positions", "Critical + high risk"),
         ("Stock Risk", "Recommended Reorder Units (High Risk)", "Units to reorder now")]) + [
         ("demand", "lineChart", "Daily units: actual (last 12 weeks) and ML forecast (next 28 days)", 24, CHART_Y, 760, 270,
          {"Category": [("Date", "Date", C)], "Y": [("Sales", "Units Sold", M), ("Forecast", "Forecast Units", M),
                                                   ("Forecast", "Forecast Units P90", M)]}),
         ("riskcat", "clusteredBarChart", "Critical and high risk positions by category", 796, CHART_Y, 460, 270,
          {"Category": [("Product", "Category", C)], "Y": [("Stock Risk", "High Risk Positions", M)]}),
         ("risktable", "tableEx", "ML reorder recommendations (sorted by risk)", 24, BOTTOM_Y, 1232, 280,
          {"Values": [("Stock Risk", "RiskLevel", C), ("Store", "StoreName", C), ("Product", "ProductName", C),
                      ("Stock Risk", "OnHandUnits", C), ("Stock Risk", "ReorderPointUnits", C), ("Stock Risk", "Forecast28Units", C),
                      ("Stock Risk", "PredictedLowStockDate", C), ("Stock Risk", "RecommendedReorderQty", C),
                      ("Stock Risk", "RecommendedAction", C)]})]),
    ("reorders", "Reorder requests", "Which reorders have employees requested from the app, and do they match the ML advice?",
     slicers(("Store", "Region", "Region")) + cards([
         ("Reorder Requests", "Reorder Requests", "Requests"), ("Reorder Requests", "Pending Reorders", "Pending approval"),
         ("Reorder Requests", "Pending Reorder Units", "Pending units"), ("Reorder Requests", "Invalid Reorder Requests", "Rejected"),
         ("Stock Risk", "High Risk Positions", "High-risk positions"),
         ("Stock Risk", "Recommended Reorder Units (High Risk)", "ML recommended units")]) + [
         ("bystore", "clusteredBarChart", "Pending reorder units by store", 24, CHART_Y, 616, 270,
          {"Category": [("Store", "StoreName", C)], "Y": [("Reorder Requests", "Pending Reorder Units", M)]}),
         ("recbystore", "clusteredBarChart", "ML recommended units (high risk) by store", 652, CHART_Y, 604, 270,
          {"Category": [("Store", "StoreName", C)], "Y": [("Stock Risk", "Recommended Reorder Units (High Risk)", M)]}),
         ("requests", "tableEx", "Reorder requests from the MTL Retail IQ app", 24, BOTTOM_Y, 1232, 280,
          {"Values": [("Reorder Requests", "SubmittedAt", C), ("Store", "StoreName", C), ("Product", "ProductName", C),
                      ("Reorder Requests", "Quantity", C), ("Reorder Requests", "Urgency", C), ("Reorder Requests", "RiskLevel", C),
                      ("Reorder Requests", "RecommendedReorderQty", C), ("Reorder Requests", "WorkflowStatus", C),
                      ("Reorder Requests", "RequestedBy", C)]})]),
    ("quality", "Data quality & lineage", "Can we trust the numbers? What the medallion fixed between Bronze and Gold.",
     slicers(("Data Quality", "Action", "DQ action")) + cards([
         ("Lineage", "Bronze Rows", "Bronze rows (mirrored)"), ("Lineage", "Silver Rows", "Silver rows"),
         ("Data Quality", "Rows Quarantined", "Quarantined"), ("Data Quality", "Rows Deduplicated", "Deduplicated"),
         ("Data Quality", "Rows Standardized", "Standardized"), ("Model Metrics", "Forecast WAPE %", "Forecast WAPE")]) + [
         ("layers", "clusteredColumnChart", "Rows by entity and medallion layer", 24, CHART_Y, 616, 270,
          {"Category": [("Lineage", "Entity", C)], "Series": [("Lineage", "Layer", C)], "Y": [("Lineage", "Layer Rows", M)]}),
         ("dqaction", "clusteredBarChart", "Affected rows by data-quality action", 652, CHART_Y, 604, 270,
          {"Category": [("Data Quality", "Action", C)], "Y": [("Data Quality", "Rows Affected", M)]}),
         ("dqtable", "tableEx", "Data-quality rules applied in Silver", 24, BOTTOM_Y, 616, 280,
          {"Values": [("Data Quality", "Entity", C), ("Data Quality", "Rule", C), ("Data Quality", "Action", C),
                      ("Data Quality", "Rows Affected", M)]}),
         ("mlmetrics", "tableEx", "ML model holdout metrics (MLflow)", 652, BOTTOM_Y, 604, 280,
          {"Values": [("Model Metrics", "Model", C), ("Model Metrics", "Segment", C), ("Model Metrics", "Metric", C),
                      ("Model Metrics", "Value", C), ("Model Metrics", "BaselineValue", C)]})]),
]
SORTS = {"stores": (("Sales", "Net Sales Last 28 Days"), True, "Descending"),
         "scorecard": (("Sales", "Net Sales Last 28 Days"), True, "Descending"),
         "region": (("Sales", "Net Sales"), True, "Descending"), "products": (("Sales", "Net Sales"), True, "Descending"),
         "riskcat": (("Stock Risk", "High Risk Positions"), True, "Descending"),
         "risktable": (("Stock Risk", "RiskRank"), False, "Ascending"),
         "positions": (("Stock Risk", "OnHandUnits"), False, "Ascending"),
         "bystore": (("Reorder Requests", "Pending Reorder Units"), True, "Descending"),
         "recbystore": (("Stock Risk", "Recommended Reorder Units (High Risk)"), True, "Descending"),
         "requests": (("Reorder Requests", "SubmittedAt"), False, "Descending"),
         "dqaction": (("Data Quality", "Rows Affected"), True, "Descending"),
         "dqtable": (("Data Quality", "Rows Affected"), True, "Descending")}
# Visual-level filters: (table, column, literal value)
FILTERS = {"demand": ("Date", "IsRecentWindow", "true"), "trend": ("Date", "IsActual", "true"),
           "depttrend": ("Date", "IsActual", "true"), "oosdays": ("Date", "IsActual", "true"),
           "positions": ("Stock Risk", "IsBelowReorderPoint", "true"),
           "mlmetrics": ("Model Metrics", "Segment", ["'Holdout (department-day)'", "'Holdout (store-SKU 28-day total)'",
                                                       "'Holdout (store-SKU-day)'", "'Holdout (last 90 days)'"])}
DEFAULT_SLICER = {("Date", "Year"): "2026L"}


def literal(value):
    return {"expr": {"Literal": {"Value": value}}}


def color(hexcode):
    return {"solid": {"color": literal("'" + hexcode + "'")}}


def field(table, prop, measure):
    return {("Measure" if measure else "Column"): {"Expression": {"SourceRef": {"Entity": table}}, "Property": prop}}


def projection(table, prop, measure):
    return {"field": field(table, prop, measure), "queryRef": table + "." + prop, "nativeQueryRef": prop}


def in_filter(table, column, value):
    values = value if isinstance(value, list) else [value]
    return {"Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}],
                "Values": [[{"Literal": {"Value": v}}] for v in values]}}}]}


def container(name, kind, title, x, y, w, h, z):
    return {"$schema": SCHEMA + "visualContainer/2.0.0/schema.json", "name": name,
            "position": {"x": round(x, 2), "y": y, "width": round(w, 2), "height": h, "z": z, "tabOrder": z},
            "visual": {"visualType": kind, "drillFilterOtherVisuals": True, "visualContainerObjects": {
                "title": [{"properties": {"show": literal("true" if title else "false"),
                                          "text": literal("'" + title.replace("'", "''") + "'"),
                                          "fontSize": literal("11D"), "fontColor": color(DEEP)}}],
                "background": [{"properties": {"show": literal("true"), "color": color("#FFFFFF"), "transparency": literal("0D")}}],
                "border": [{"properties": {"show": literal("true"), "color": color("#CFE3D7"), "radius": literal("8D")}}]}}}


def build_visual(spec, z):
    name, kind, title, x, y, w, h, roles = spec
    v = container(name, kind, title, x, y, w, h, z)
    v["visual"]["query"] = {"queryState": {role: {"projections": [projection(*x_) for x_ in fields]}
                                           for role, fields in roles.items()}}
    if name in SORTS:
        (table, prop), measure, direction = SORTS[name]
        v["visual"]["query"]["sortDefinition"] = {"sort": [{"field": field(table, prop, measure), "direction": direction}],
                                                  "isDefaultSort": False}
    if name in FILTERS:
        table, column, value = FILTERS[name]
        v["filterConfig"] = {"filters": [{"name": "f" + name, "field": field(table, column, False), "type": "Categorical",
                                          "filter": in_filter(table, column, value), "howCreated": "User"}]}
    if kind == "slicer":
        table, column, _ = roles["Values"][0]
        general = {"properties": {}}
        if (table, column) in DEFAULT_SLICER:
            general["properties"]["filter"] = {"filter": in_filter(table, column, DEFAULT_SLICER[(table, column)])}
        v["visual"]["objects"] = {"data": [{"properties": {"mode": literal("'Dropdown'")}}],
                                  "header": [{"properties": {"show": literal("true")}}], "general": [general]}
    if kind == "card":
        v["visual"]["visualContainerObjects"]["title"][0]["properties"]["show"] = literal("false")
        v["visual"]["visualContainerObjects"]["background"][0]["properties"]["color"] = color(TINT)
        v["visual"]["objects"] = {"labels": [{"properties": {"fontSize": literal("22D"), "color": color(GREEN)}}],
                                  "categoryLabels": [{"properties": {"show": literal("true"), "fontSize": literal("10D"),
                                                                     "color": color(MUTED)}}]}
        v["visual"]["query"]["queryState"]["Values"]["projections"][0]["displayName"] = title
    if kind == "tableEx":
        v["visual"]["objects"] = {"columnHeaders": [{"properties": {"fontSize": literal("9D"), "backColor": color(GREEN),
                                                                    "fontColor": color("#FFFFFF"), "wordWrap": literal("true")}}],
                                  "values": [{"properties": {"fontSize": literal("9D"), "wordWrap": literal("true"),
                                                             "backColorSecondary": color(TINT)}}]}
    if kind in ("lineChart", "clusteredBarChart", "clusteredColumnChart"):
        v["visual"]["objects"] = {"legend": [{"properties": {"show": literal("true"), "position": literal("'Top'")}}]}
    return v


def header(title, question, note):
    v = container("header", "textbox", "", 24, 10, 824, 82, 0)
    v["visual"]["objects"] = {"general": [{"properties": {"paragraphs": [
        {"textRuns": [{"value": "MAISON MTL RETAIL IQ  |  " + title.upper(),
                       "textStyle": {"fontSize": "17pt", "fontWeight": "bold", "color": GREEN}}]},
        {"textRuns": [{"value": question, "textStyle": {"fontSize": "10pt", "color": INK, "fontWeight": "bold"}}]},
        {"textRuns": [{"value": note, "textStyle": {"fontSize": "8pt", "color": MUTED}}]}]}}]}
    v["visual"]["visualContainerObjects"]["background"][0]["properties"]["show"] = literal("false")
    v["visual"]["visualContainerObjects"]["border"][0]["properties"]["show"] = literal("false")
    return v


NOTE = ("SYNTHETIC illustrative data, fictional retailer | CAD | Sales and inventory through 2026-11-03 | "
        "ML forecast 2026-11-04 to 2026-12-01 | Direct Lake on MTL_Gold")


def theme():
    return {"name": "MaisonMtlGreen",
            "dataColors": [GREEN, MINT, "#A7D1B9", INK, "#C8553D", "#E3A33B", "#7A8C82", "#2E7D5B"],
            "background": "#FFFFFF", "foreground": INK, "tableAccent": GREEN, "good": GREEN, "neutral": "#E3A33B",
            "bad": "#C8553D", "visualStyles": {"*": {"*": {"title": [{"fontFamily": "Segoe UI Semibold"}]}}}}


def definition():
    parts = [
        f.part("definition.pbir", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                                   "version": "4.0", "datasetReference": {"byConnection": {
                                       "connectionString": "semanticmodelid=" + f.load("model.json")["id"]}}}),
        f.part("definition/version.json", {"$schema": SCHEMA + "versionMetadata/1.0.0/schema.json", "version": "2.0.0"}),
        f.part("definition/report.json", {
            "$schema": SCHEMA + "report/3.1.0/schema.json",
            "themeCollection": {
                "baseTheme": {"name": "CY24SU10", "type": "SharedResources",
                              "reportVersionAtImport": {"visual": "2.0.0", "report": "3.1.0", "page": "2.0.0"}},
                "customTheme": {"name": "MaisonMtlGreen.json", "type": "RegisteredResources",
                                "reportVersionAtImport": {"visual": "2.0.0", "report": "3.1.0", "page": "2.0.0"}}},
            "resourcePackages": [
                {"name": "SharedResources", "type": "SharedResources",
                 "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
                {"name": "RegisteredResources", "type": "RegisteredResources",
                 "items": [{"name": "MaisonMtlGreen.json", "path": "MaisonMtlGreen.json", "type": "CustomTheme"}]}],
            "annotations": [{"name": "DataClassification", "value": "SYNTHETIC illustrative data. Maison MTL is a fictional retailer."}]}),
        f.part("StaticResources/RegisteredResources/MaisonMtlGreen.json", theme()),
        f.part("definition/pages/pages.json", {"$schema": SCHEMA + "pagesMetadata/1.0.0/schema.json",
                                               "pageOrder": [p[0] for p in PAGES], "activePageName": PAGES[0][0]})]
    for page, title, question, specs in PAGES:
        base = "definition/pages/" + page
        parts.append(f.part(base + "/page.json", {
            "$schema": SCHEMA + "page/2.0.0/schema.json", "name": page, "displayName": title,
            "displayOption": "FitToPage", "width": 1280, "height": 800,
            "objects": {"background": [{"properties": {"color": color(PAGE_BG), "transparency": literal("0D")}}],
                        "outspace": [{"properties": {"color": color(PAGE_BG)}}]}}))
        for v in [header(title, question, NOTE)] + [build_visual(s, z + 1) for z, s in enumerate(specs)]:
            parts.append(f.part(base + "/visuals/" + v["name"] + "/visual.json", v))
    return {"parts": parts}


def build():
    return {"report": f.item("report", "reports", REPORT_NAME, definition(), True)["id"]}


def ref(table, column, measure):
    return f"[{column}]" if measure else f"'{table}'[{column}]"


def bindings():
    evidence, failures = {}, []
    for page, _, _, specs in PAGES:
        for name, kind, _, *_, roles in specs:
            fields = [x for role in roles.values() for x in role]
            columns = [ref(*x) for x in fields if not x[2]]
            measures = [f'"{x[1]}", {ref(*x)}' for x in fields if x[2]]
            query = ("EVALUATE TOPN(5, SUMMARIZECOLUMNS(" + ", ".join(columns + measures) + "))" if columns
                     else "EVALUATE ROW(" + ", ".join(measures) + ")")
            key = page + "/" + name
            try:
                rows = dax(query)
                evidence[key] = {"rows": len(rows), "sample": rows[:2]}
                if not rows and page != "reorders":
                    failures.append(key + ": no rows")
            except RuntimeError as error:
                failures.append(key + ": " + str(error)[:300])
    return evidence, failures


def export_pages():
    report_id = f.load("report.json")["id"]
    job = f.pbi(f"/reports/{report_id}/ExportTo", "POST", {"format": "PNG"})
    for _ in range(90):
        time.sleep(10)
        state = f.pbi(f"/reports/{report_id}/exports/{job['id']}")
        if state["status"] in ("Succeeded", "Failed"):
            break
    if state["status"] != "Succeeded":
        raise RuntimeError("Export failed: " + json.dumps(state)[:1000])
    req = Request(state["resourceLocation"], headers={"Authorization": "Bearer " + f.token("https://analysis.windows.net/powerbi/api")})
    with urlopen(req, timeout=300) as response:
        raw = response.read()
    out = f.ART / "report-pages"
    out.mkdir(exist_ok=True)
    files = []
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for n in archive.namelist():
                (out / n).write_bytes(archive.read(n))
                files.append(n)
    else:
        (out / "report.png").write_bytes(raw)
        files.append("report.png")
    return files


def verify(export=True):
    deployed = f.decode(f.api(f.path() + "/reports/" + f.load("report.json")["id"] + "/getDefinition", "POST"))
    visuals = [p for p in deployed if p.endswith("/visual.json")]
    pages = [p for p in deployed if p.endswith("/page.json")]
    expected = sum(len(s) + 1 for *_, s in PAGES)
    failures = [] if len(visuals) == expected and len(pages) == len(PAGES) else \
        [f"read-back {len(pages)} pages / {len(visuals)} visuals vs {len(PAGES)} / {expected}"]
    theme_part = [p for p in deployed if p.endswith("MaisonMtlGreen.json")]
    if not theme_part or GREEN not in deployed[theme_part[0]]:
        failures.append("green theme missing from read-back")
    evidence, binding_failures = bindings()
    failures += binding_failures
    exported = []
    if export:
        try:
            exported = export_pages()
        except Exception as error:
            exported = ["export unavailable: " + str(error)[:300]]
    result = {"pages": [p[1] for p in PAGES], "readBackPages": len(pages), "readBackVisuals": len(visuals),
              "bindingsChecked": len(evidence), "failures": failures, "exported": exported, "bindings": evidence}
    f.save("report-verification.json", result)
    if failures:
        raise RuntimeError("Report verification failed: " + "; ".join(failures))
    return {k: v for k, v in result.items() if k != "bindings"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build() if args.command == "build" else verify(not args.no_export), indent=2, default=str))
