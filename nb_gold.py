"""Gold notebook source: business-ready star schema, current stock positions and governed KPI tables."""

GOLD = r'''
import datetime, json
from pyspark.sql import functions as F, Window
spark.conf.set("spark.sql.session.timeZone", "UTC")
assert spark.conf.get("trident.workspace.id") == WORKSPACE
SNAP = datetime.date.fromisoformat(EXPECTED["snapshotDate"])
snap = F.lit(SNAP)

def silver(table):
    return spark.read.format("delta").load(f"{ONELAKE}/{SILVER}/Tables/{table}")

def bronze(table):
    return spark.read.format("delta").load(f"{ONELAKE}/{BRONZE}/Tables/{table}")

def write(frame, name):
    if not name.startswith("fact_"):
        frame = frame.select(*[F.col(c.name).cast("double").alias(c.name) if c.dataType.typeName() == "decimal" else F.col(c.name)
                               for c in frame.schema.fields])
    frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    return spark.table(name).count()

rows = {}

# Calendar --------------------------------------------------------------------------------------------------------------
d = spark.sql("SELECT explode(sequence(to_date('2024-11-04'), to_date('2026-12-31'), interval 1 day)) AS Date")
md = F.month("Date") * 100 + F.dayofmonth("Date")
black_friday = F.col("Date").isin([datetime.date.fromisoformat(x) for x in BLACK_FRIDAY])
bf_weekend = F.lit(False)
for x in BLACK_FRIDAY:
    day = datetime.date.fromisoformat(x)
    bf_weekend = bf_weekend | F.col("Date").between(F.lit(day), F.lit(day + datetime.timedelta(days=3)))
event = (F.when(black_friday, "Black Friday").when(md == 1226, "Boxing Day").when(md == 1225, "Christmas Day (closed)")
         .when(md == 101, "New Year's Day (closed)").when(md == 624, "Fête nationale (closed)")
         .when(md == 701, "Canada Day (closed)").when(md.between(1215, 1224), "Holiday gifting")
         .when(md.between(1227, 1231), "Boxing Week"))
dim_date = d.select(
    (F.year("Date") * 10000 + F.month("Date") * 100 + F.dayofmonth("Date")).cast("int").alias("DateKey"), "Date",
    F.year("Date").alias("Year"), F.concat(F.lit("Q"), F.quarter("Date")).alias("Quarter"),
    F.month("Date").alias("MonthNumber"), F.date_format("Date", "MMMM").alias("MonthName"),
    F.date_format("Date", "MMM yyyy").alias("MonthLabel"), F.trunc("Date", "month").alias("MonthStart"),
    (F.year("Date") * 100 + F.month("Date")).alias("YearMonth"), F.date_trunc("week", "Date").cast("date").alias("WeekStart"),
    (((F.dayofweek("Date") + 5) % 7) + 1).alias("DayOfWeekNumber"), F.date_format("Date", "EEEE").alias("DayName"),
    F.dayofweek("Date").isin(1, 7).alias("IsWeekend"), md.isin(101, 624, 701, 1225).alias("IsStoreClosed"),
    event.alias("EventName"), bf_weekend.alias("IsBlackFridayWeekend"), md.between(1226, 1231).alias("IsBoxingWeek"),
    (md.between(102, 229)).alias("IsWinterClearance"), (md.between(710, 831)).alias("IsSummerClearance"),
    (F.month("Date") == 6).alias("IsSpringClearance"),
    F.when(F.month("Date").isin(12, 1, 2), "Winter").when(F.month("Date").isin(3, 4, 5), "Spring")
     .when(F.month("Date").isin(6, 7, 8), "Summer").otherwise("Fall").alias("SeasonName"),
    (F.col("Date") <= snap).alias("IsActual"),
    ((F.col("Date") > snap) & (F.col("Date") <= F.date_add(snap, 28))).alias("IsForecastPeriod"),
    F.col("Date").between(F.date_sub(snap, 27), snap).alias("IsLast28Days"),
    F.col("Date").between(F.date_sub(snap, 364 + 27), F.date_sub(snap, 364)).alias("IsLast28DaysLY"),
    ((F.year("Date") == SNAP.year) & (F.col("Date") <= snap)).alias("IsYTD"),
    ((F.year("Date") == SNAP.year - 1) & (F.col("Date") <= F.add_months(snap, -12))).alias("IsLYTD"),
    F.datediff("Date", snap).alias("DaysFromSnapshot"),
    F.datediff("Date", snap).between(-83, 28).alias("IsRecentWindow"))
rows["dim_date"] = write(dim_date, "dim_date")

# Dimensions ------------------------------------------------------------------------------------------------------------
stores, suppliers, products = silver("stores"), silver("suppliers"), silver("products")
regions = spark.createDataFrame([(k, v[0], v[1]) for k, v in REGIONS.items()], "Region string, Market string, RegionCode string")
dim_store = stores.join(regions, "Region", "left").select(
    "StoreCode", "StoreName", "City", "Region", "Market", "RegionCode", "Province", "StoreFormat", "OpenedYear",
    "SellingAreaSqFt", "Latitude", "Longitude", "LocationType", "TrafficIndex", "DcTransferDays",
    F.when(F.col("LocationType") == "Store", F.lit(True)).otherwise(F.lit(False)).alias("IsSellingStore"))
rows["dim_store"] = write(dim_store, "dim_store")
dim_region = regions.join(dim_store.filter("IsSellingStore").groupBy("Region").agg(F.count("*").alias("StoreCount")), "Region", "left") \
    .fillna(0, ["StoreCount"]).withColumn("Province", F.lit("QC"))
rows["dim_region"] = write(dim_region, "dim_region")
group = (F.when(F.col("Category") == "Footwear", "Footwear")
         .when(F.col("Category").isin("Accessories", "Cold-weather accessories", "Bags", "Sun accessories", "Jewellery"), "Accessories")
         .when(F.col("Category").isin("Bedding", "Bath", "Décor", "Kitchen"), "Home").otherwise("Apparel"))
dim_product = products.join(suppliers.select("SupplierCode", "SupplierName"), "SupplierCode", "left").select(
    "SKU", "ProductName", "Department", "Category", group.alias("CategoryGroup"), "Subcategory", "Brand", "SupplierCode",
    "SupplierName", "SeasonProfile", "UnitCost", "UnitPrice",
    F.round((F.col("UnitPrice") - F.col("UnitCost")) / F.col("UnitPrice") * 100, 2).cast("double").alias("InitialMarginPct"),
    "CasePack", "LeadTimeDays", "ReorderPoint", "SafetyStock")
rows["dim_product"] = write(dim_product, "dim_product")
dim_category = dim_product.groupBy("Category", "CategoryGroup").agg(
    F.count("*").alias("ProductCount"), F.concat_ws(", ", F.sort_array(F.collect_set("Department"))).alias("Departments"))
rows["dim_category"] = write(dim_category, "dim_category")
brands = spark.createDataFrame(list(BRANDS.items()), "Brand string, Positioning string")
dim_brand = brands.join(dim_product.groupBy("Brand").agg(F.count("*").alias("ProductCount")), "Brand", "left")
rows["dim_brand"] = write(dim_brand, "dim_brand")

# Facts -----------------------------------------------------------------------------------------------------------------
cost = dim_product.select("SKU", "UnitCost", "UnitPrice")
key = (F.year("Date") * 10000 + F.month("Date") * 100 + F.dayofmonth("Date")).cast("int")
fact_sales = silver("sales_daily").withColumnRenamed("SaleDate", "Date").join(cost, "SKU").select(
    key.alias("DateKey"), "Date", "StoreCode", "SKU", "UnitsSold", "GrossSales", "DiscountAmount", "NetSales",
    (F.col("UnitsSold") * F.col("UnitCost")).cast("decimal(14,2)").alias("CostOfGoods"),
    (F.col("NetSales") - F.col("UnitsSold") * F.col("UnitCost")).cast("decimal(14,2)").alias("GrossMargin"),
    F.round(F.col("DiscountAmount") / F.col("GrossSales"), 4).cast("double").alias("MarkdownPct"))
rows["fact_sales"] = write(fact_sales, "fact_sales")
fact_inventory = silver("inventory_daily").withColumnRenamed("SnapshotDate", "Date").join(cost, "SKU").join(
    dim_store.select("StoreCode", "LocationType"), "StoreCode").select(
    key.alias("DateKey"), "Date", "StoreCode", "SKU", "LocationType", "OnHandUnits", "OnOrderUnits", "ReceivedUnits",
    "ReorderPointUnits", "SafetyStockUnits", (F.col("OnHandUnits") == 0).alias("IsOutOfStock"),
    (F.col("OnHandUnits") < F.col("ReorderPointUnits")).alias("IsBelowReorderPoint"),
    (F.col("OnHandUnits") * F.col("UnitCost")).cast("decimal(14,2)").alias("InventoryCost"),
    (F.col("OnHandUnits") * F.col("UnitPrice")).cast("decimal(14,2)").alias("InventoryRetailValue"))
rows["fact_inventory"] = write(fact_inventory, "fact_inventory")
fact_replenishment = silver("replenishment_orders").select(
    "OrderNumber", "OrderType", "SKU", "FromLocation", "ToLocation", "OrderDate", "ExpectedDate", "ReceivedDate",
    "OrderedUnits", "ReceivedUnits", "Status",
    F.when(F.col("OrderType") == "Supplier PO", F.col("FromLocation")).alias("SupplierCode"),
    F.datediff("ExpectedDate", "OrderDate").alias("PlannedLeadDays"), F.datediff("ReceivedDate", "OrderDate").alias("ActualLeadDays"),
    F.datediff("ReceivedDate", "ExpectedDate").alias("DaysLate"),
    (F.col("ReceivedDate") > F.col("ExpectedDate")).alias("IsLate"), F.col("ReceivedDate").isNull().alias("IsOpen"))
rows["fact_replenishment"] = write(fact_replenishment, "fact_replenishment")
po = fact_replenishment.filter("OrderType = 'Supplier PO'").groupBy("SupplierCode").agg(
    F.count("*").alias("PurchaseOrders"), F.sum(F.col("IsOpen").cast("int")).alias("OpenPurchaseOrders"),
    F.round(100 * F.avg(F.when(F.col("ReceivedDate").isNotNull(), (~F.col("IsLate")).cast("int"))), 1).alias("ActualOnTimePct"),
    F.round(F.avg("DaysLate"), 1).alias("AvgDaysLate"))
dim_supplier = suppliers.join(po, "SupplierCode", "left").join(
    dim_product.groupBy("SupplierCode").agg(F.count("*").alias("ProductCount")), "SupplierCode", "left")
rows["dim_supplier"] = write(dim_supplier, "dim_supplier")

# Current stock positions ---------------------------------------------------------------------------------------------
recent = fact_sales.filter(F.col("Date").between(F.date_sub(snap, 27), snap)).groupBy("StoreCode", "SKU").agg(
    F.sum("UnitsSold").alias("UnitsLast28"), F.sum("NetSales").alias("NetSalesLast28"))
week = fact_sales.filter(F.col("Date").between(F.date_sub(snap, 6), snap)).groupBy("StoreCode", "SKU").agg(
    F.sum("UnitsSold").alias("UnitsLast7"))
dc = fact_inventory.filter((F.col("Date") == snap) & (F.col("LocationType") == "Distribution centre")).select(
    "SKU", F.col("OnHandUnits").alias("DcOnHandUnits"), F.col("OnOrderUnits").alias("DcOnOrderUnits"))
current = (fact_inventory.filter((F.col("Date") == snap) & (F.col("LocationType") == "Store"))
           .join(recent, ["StoreCode", "SKU"], "left").join(week, ["StoreCode", "SKU"], "left").join(dc, "SKU", "left")
           .fillna(0, ["UnitsLast28", "UnitsLast7"]).fillna(0, ["NetSalesLast28"]))
velocity = F.col("UnitsLast28") / F.lit(28.0)
current = current.select(
    F.concat_ws("|", "StoreCode", "SKU").alias("PositionId"), F.col("Date").alias("SnapshotDate"), "StoreCode", "SKU",
    "OnHandUnits", "OnOrderUnits", "ReorderPointUnits", "SafetyStockUnits", "UnitsLast7", "UnitsLast28", "NetSalesLast28",
    F.round(velocity, 3).alias("AvgDailyUnits28"),
    F.when(velocity > 0, F.round(F.col("OnHandUnits") / velocity, 1)).alias("DaysOfSupply"),
    F.when(F.col("OnHandUnits") == 0, "Out of stock").when(F.col("OnHandUnits") < F.col("ReorderPointUnits"), "Below reorder point")
     .when((velocity > 0) & (F.col("OnHandUnits") / velocity > 120), "Overstock").otherwise("Healthy").alias("StockStatus"),
    "IsOutOfStock", "IsBelowReorderPoint", "InventoryCost", "InventoryRetailValue", "DcOnHandUnits", "DcOnOrderUnits")
rows["inventory_current"] = write(current, "inventory_current")

# KPI tables ------------------------------------------------------------------------------------------------------------
dates = spark.table("dim_date").select("Date", "IsLast28Days", "IsLast28DaysLY", "IsYTD", "IsLYTD")
s = fact_sales.join(dates, "Date").join(dim_product.select("SKU", "Department", "Category"), "SKU")
def kpis(keys):
    return s.groupBy(*keys).agg(
        F.sum(F.when(F.col("IsLast28Days"), F.col("NetSales"))).alias("NetSalesLast28"),
        F.sum(F.when(F.col("IsLast28DaysLY"), F.col("NetSales"))).alias("NetSalesLast28LY"),
        F.sum(F.when(F.col("IsLast28Days"), F.col("UnitsSold"))).alias("UnitsLast28"),
        F.sum(F.when(F.col("IsLast28Days"), F.col("GrossMargin"))).alias("GrossMarginLast28"),
        F.sum(F.when(F.col("IsYTD"), F.col("NetSales"))).alias("NetSalesYTD"),
        F.sum(F.when(F.col("IsLYTD"), F.col("NetSales"))).alias("NetSalesLYTD")
    ).withColumn("Last28GrowthPct", F.round((F.col("NetSalesLast28") / F.col("NetSalesLast28LY") - 1) * 100, 2).cast("double")) \
     .withColumn("GrossMarginPctLast28", F.round(F.col("GrossMarginLast28") / F.col("NetSalesLast28") * 100, 2).cast("double")) \
     .withColumn("YTDGrowthPct", F.round((F.col("NetSalesYTD") / F.col("NetSalesLYTD") - 1) * 100, 2).cast("double"))
stock = current.groupBy("StoreCode").agg(F.sum("OnHandUnits").alias("OnHandUnits"), F.sum("InventoryCost").alias("InventoryCost"),
    F.sum(F.col("IsOutOfStock").cast("int")).alias("OutOfStockPositions"),
    F.sum(F.col("IsBelowReorderPoint").cast("int")).alias("BelowReorderPointPositions"))
store_kpi = kpis(["StoreCode"]).join(stock, "StoreCode").join(dim_store.select("StoreCode", "StoreName", "City", "Region"), "StoreCode")
rows["kpi_store_summary"] = write(store_kpi, "kpi_store_summary")
cat_stock = current.join(dim_product.select("SKU", "Department", "Category"), "SKU").groupBy("Department", "Category").agg(
    F.sum("OnHandUnits").alias("OnHandUnits"), F.sum(F.col("IsOutOfStock").cast("int")).alias("OutOfStockPositions"),
    F.sum(F.col("IsBelowReorderPoint").cast("int")).alias("BelowReorderPointPositions"))
cat_kpi = kpis(["Department", "Category"]).join(cat_stock, ["Department", "Category"]).withColumn(
    "SellThroughPctLast28", F.round(F.col("UnitsLast28") / (F.col("UnitsLast28") + F.col("OnHandUnits")) * 100, 2).cast("double")
).withColumn("WeeksOfSupply", F.round(F.col("OnHandUnits") / (F.col("UnitsLast28") / 4), 1).cast("double")) \
 .withColumn("CategoryPerformanceId", F.concat_ws("|", "Department", "Category"))
rows["kpi_category_summary"] = write(cat_kpi, "kpi_category_summary")
monthly = fact_sales.join(dim_product.select("SKU", "Department", "Category"), "SKU").groupBy(
    F.trunc("Date", "month").alias("MonthStart"), "StoreCode", "Department", "Category").agg(
    F.sum("NetSales").alias("NetSales"), F.sum("UnitsSold").alias("UnitsSold"), F.sum("GrossMargin").alias("GrossMargin"))
monthly = monthly.withColumn("YearMonth", (F.year("MonthStart") * 100 + F.month("MonthStart")).cast("int")).withColumn(
    "SalesMonthId", F.concat_ws("|", F.date_format("MonthStart", "yyyy-MM"), "StoreCode", "Department", "Category"))
rows["sales_month_store_category"] = write(monthly, "sales_month_store_category")
chain = kpis([]).crossJoin(current.agg(
    F.sum("OnHandUnits").alias("StoreOnHandUnits"), F.sum("OnOrderUnits").alias("StoreOnOrderUnits"),
    F.sum("InventoryCost").alias("InventoryCost"), F.count("*").alias("Positions"),
    F.sum(F.col("IsOutOfStock").cast("int")).alias("OutOfStockPositions"),
    F.sum(F.col("IsBelowReorderPoint").cast("int")).alias("BelowReorderPointPositions"))).crossJoin(
    dc.agg(F.sum("DcOnHandUnits").alias("DcOnHandUnits"))).withColumn("SnapshotDate", snap).withColumn("ChainId", F.lit("MTL-QC"))
rows["kpi_chain_summary"] = write(chain, "kpi_chain_summary")

# Medallion lineage evidence ------------------------------------------------------------------------------------------
lineage = []
for entity, gold in [("stores", "dim_store"), ("suppliers", "dim_supplier"), ("products", "dim_product"), ("sales_daily", "fact_sales"),
                     ("inventory_daily", "fact_inventory"), ("replenishment_orders", "fact_replenishment")]:
    lineage += [(entity, "Bronze", bronze(entity).count()), (entity, "Silver", silver(entity).count()), (entity, "Gold", rows[gold])]
write(spark.createDataFrame(lineage, "Entity string, Layer string, RowCount long"), "medallion_lineage")
dq = silver("dq_events")
write(dq, "dq_events")

# Governed controls -----------------------------------------------------------------------------------------------------
c = spark.table("kpi_chain_summary").first()
year2025 = fact_sales.filter(F.year("Date") == 2025).agg(F.sum("NetSales").alias("n"), F.sum("UnitsSold").alias("u")).first()
checks = {
    "netSales2025": (float(year2025["n"]), EXPECTED["netSales2025"]), "units2025": (int(year2025["u"]), EXPECTED["units2025"]),
    "netSalesYtd2026": (float(c["NetSalesYTD"]), EXPECTED["netSalesYtd2026"]),
    "netSalesYtd2025": (float(c["NetSalesLYTD"]), EXPECTED["netSalesYtd2025"]),
    "netSalesLast28": (float(c["NetSalesLast28"]), EXPECTED["netSalesLast28"]),
    "netSalesLast28LY": (float(c["NetSalesLast28LY"]), EXPECTED["netSalesLast28LY"]),
    "unitsLast28": (int(c["UnitsLast28"]), EXPECTED["unitsLast28"]),
    "storeOnHandUnits": (int(c["StoreOnHandUnits"]), EXPECTED["storeOnHandUnits"]),
    "dcOnHandUnits": (int(c["DcOnHandUnits"]), EXPECTED["dcOnHandUnits"]),
    "outOfStockPositions": (int(c["OutOfStockPositions"]), EXPECTED["outOfStockPositions"]),
    "belowReorderPointPositions": (int(c["BelowReorderPointPositions"]), EXPECTED["belowReorderPointPositions"]),
}
failed = {k: v for k, v in checks.items() if abs(v[0] - v[1]) > 0.05}
top = spark.table("kpi_store_summary").orderBy(F.desc("NetSalesLast28")).first()
assert top["StoreCode"] == EXPECTED["topStoreLast28"]["code"], top
assert not failed, failed
print("MTL_GOLD_VERIFIED", json.dumps({"rows": rows, "checks": {k: v[0] for k, v in checks.items()}}, default=str))
'''
