"""Silver notebook source: cleanse, conform, deduplicate and quarantine the mirrored Bronze data."""

SILVER = r'''
import datetime, json
from pyspark.sql import functions as F, Window
spark.conf.set("spark.sql.session.timeZone", "UTC")
assert spark.conf.get("trident.workspace.id") == WORKSPACE
RUN_AT = datetime.datetime.utcnow().replace(microsecond=0)
RUN_ID = RUN_AT.strftime("silver-%Y%m%dT%H%M%SZ")
events, quarantined = [], []

def bronze(table):
    return spark.read.format("delta").load(f"{ONELAKE}/{BRONZE}/Tables/{table}")

def code(column):
    return F.upper(F.regexp_replace(F.trim(F.col(column)), "_", "-"))

def event(entity, rule, count):
    count = int(count)
    if count:
        action = "Quarantined" if "quarantined" in rule else "Deduplicated" if "removed" in rule else "Standardized"
        events.append((entity, rule, action, count))

def quarantine(entity, frame, key):
    quarantined.append(frame.select(F.lit(entity).alias("Entity"), F.col("reason").alias("Reason"),
                                    F.col(key).cast("string").alias("SourceKey"),
                                    F.to_json(F.struct(*[c for c in frame.columns if c != "reason"])).alias("RawRecord")))

def latest(frame, keys, order):
    ranked = frame.withColumn("_rn", F.row_number().over(Window.partitionBy(*keys).orderBy(*order)))
    return ranked.filter("_rn = 1").drop("_rn"), ranked.filter("_rn > 1").count()

def write(frame, name):
    frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    return spark.table(name).count()

counts = {}

# Stores and distribution centre ------------------------------------------------------------------------------------
raw = bronze("stores")
province = F.when(F.upper(F.trim("province")).isin("QC", "QUÉBEC", "QUEBEC"), F.lit("QC")).otherwise(F.upper(F.trim("province")))
event("stores", "Province standardized to QC", raw.filter(F.col("province") != province).count())
stores = raw.select(F.col("store_id").cast("int").alias("StoreId"), code("store_code").alias("StoreCode"),
                    F.trim("store_name").alias("StoreName"), F.trim("city").alias("City"), F.trim("region").alias("Region"),
                    province.alias("Province"), F.col("store_format").alias("StoreFormat"),
                    F.col("opened_year").cast("int").alias("OpenedYear"), F.col("selling_area_sqft").cast("int").alias("SellingAreaSqFt"),
                    F.col("latitude").cast("double").alias("Latitude"), F.col("longitude").cast("double").alias("Longitude"),
                    F.col("location_type").alias("LocationType"), F.col("traffic_index").cast("double").alias("TrafficIndex"),
                    F.col("dc_transfer_days").cast("int").alias("DcTransferDays"))
counts["stores"] = write(stores, "stores")
selling = [r.StoreCode for r in stores.filter("LocationType = 'Store'").collect()]
locations = [r.StoreCode for r in stores.collect()]

# Suppliers -------------------------------------------------------------------------------------------------------------
raw = bronze("suppliers")
country = F.initcap(F.trim("country"))
event("suppliers", "Country name standardized", raw.filter(F.col("country") != country).count())
suppliers = raw.select(F.col("supplier_id").cast("int").alias("SupplierId"), code("supplier_code").alias("SupplierCode"),
                       F.trim("supplier_name").alias("SupplierName"), country.alias("Country"),
                       F.col("lead_time_days").cast("int").alias("LeadTimeDays"), F.col("on_time_pct").cast("double").alias("OnTimePct"))
counts["suppliers"] = write(suppliers, "suppliers")

# Products: canonical category casing, trimmed brands, latest version per SKU ----------------------------------------
raw = bronze("products")
canon = (raw.groupBy(F.lower(F.trim("category")).alias("k"), F.trim("category").alias("v")).count()
         .withColumn("r", F.row_number().over(Window.partitionBy("k").orderBy(F.desc("count"), "v")))
         .filter("r = 1").select("k", F.col("v").alias("CategoryStd")))
products = raw.join(canon, F.lower(F.trim(raw.category)) == canon.k, "left")
event("products", "Category casing and spacing standardized", products.filter(F.col("category") != F.col("CategoryStd")).count())
event("products", "Brand whitespace trimmed", raw.filter(F.col("brand") != F.trim("brand")).count())
products = products.withColumn("SKU", code("sku"))
products, removed = latest(products, ["SKU"], [F.col("updated_at").desc(), F.col("product_id").desc()])
event("products", "Stale product version removed", removed)
products = products.select("SKU", F.trim("product_name").alias("ProductName"), F.trim("department").alias("Department"),
                           F.col("CategoryStd").alias("Category"), F.trim("subcategory").alias("Subcategory"),
                           F.trim("brand").alias("Brand"), code("supplier_code").alias("SupplierCode"),
                           F.col("unit_cost").cast("decimal(10,2)").alias("UnitCost"),
                           F.col("unit_price").cast("decimal(10,2)").alias("UnitPrice"),
                           F.col("season_profile").alias("SeasonProfile"), F.col("case_pack").cast("int").alias("CasePack"),
                           F.col("lead_time_days").cast("int").alias("LeadTimeDays"),
                           F.col("reorder_point").cast("int").alias("ReorderPoint"),
                           F.col("safety_stock").cast("int").alias("SafetyStock"))
counts["products"] = write(products, "products")
skus = [r.SKU for r in products.collect()]

# Daily POS sales -------------------------------------------------------------------------------------------------------
raw = bronze("sales_daily")
event("sales_daily", "Store code standardized", raw.filter(F.col("store_code") != code("store_code")).count())
event("sales_daily", "SKU standardized", raw.filter(F.col("sku") != code("sku")).count())
sales = (raw.withColumn("StoreCode", code("store_code")).withColumn("SKU", code("sku"))
         .withColumn("reason", F.when(F.col("units_sold").isNull(), "Null quantity quarantined")
                     .when(F.col("units_sold") <= 0, "Negative quantity quarantined")
                     .when(~F.col("SKU").isin(skus), "Unknown product quarantined")
                     .when(~F.col("StoreCode").isin(selling), "Unknown store quarantined")))
for row in sales.filter("reason IS NOT NULL").groupBy("reason").count().collect():
    event("sales_daily", row["reason"], row["count"])
quarantine("sales_daily", sales.filter("reason IS NOT NULL"), "sales_id")
sales, removed = latest(sales.filter("reason IS NULL"), ["sale_date", "StoreCode", "SKU"],
                        [F.col("loaded_at").desc(), F.col("sales_id").desc()])
event("sales_daily", "Duplicate POS resend removed", removed)
sales = sales.select(F.col("sale_date").alias("SaleDate"), "StoreCode", "SKU", F.col("units_sold").cast("int").alias("UnitsSold"),
                     F.col("gross_sales").cast("decimal(12,2)").alias("GrossSales"),
                     F.col("discount_amount").cast("decimal(12,2)").alias("DiscountAmount"),
                     F.col("net_sales").cast("decimal(12,2)").alias("NetSales"),
                     F.col("pos_batch_id").alias("PosBatchId"), F.col("loaded_at").alias("LoadedAt"))
counts["sales_daily"] = write(sales, "sales_daily")

# Daily inventory snapshots ---------------------------------------------------------------------------------------------
raw = bronze("inventory_daily")
event("inventory_daily", "Location code standardized", raw.filter(F.col("store_code") != code("store_code")).count())
inventory = (raw.withColumn("StoreCode", code("store_code")).withColumn("SKU", code("sku"))
             .withColumn("reason", F.when(F.col("on_hand_units").isNull(), "Null on-hand quarantined")
                         .when(F.col("on_hand_units") < 0, "Negative on-hand quarantined")
                         .when(~F.col("SKU").isin(skus), "Unknown product quarantined")
                         .when(~F.col("StoreCode").isin(locations), "Unknown location quarantined")))
for row in inventory.filter("reason IS NOT NULL").groupBy("reason").count().collect():
    event("inventory_daily", row["reason"], row["count"])
quarantine("inventory_daily", inventory.filter("reason IS NOT NULL"), "snapshot_id")
inventory, removed = latest(inventory.filter("reason IS NULL"), ["snapshot_date", "StoreCode", "SKU"],
                            [F.col("loaded_at").desc(), F.col("snapshot_id").desc()])
event("inventory_daily", "Duplicate snapshot removed", removed)
inventory = inventory.select(F.col("snapshot_date").alias("SnapshotDate"), "StoreCode", "SKU",
                             F.col("on_hand_units").cast("int").alias("OnHandUnits"),
                             F.col("on_order_units").cast("int").alias("OnOrderUnits"),
                             F.col("received_units").cast("int").alias("ReceivedUnits"),
                             F.col("reorder_point_units").cast("int").alias("ReorderPointUnits"),
                             F.col("safety_stock_units").cast("int").alias("SafetyStockUnits"),
                             F.col("loaded_at").alias("LoadedAt"))
counts["inventory_daily"] = write(inventory, "inventory_daily")

# Replenishment: DC-to-store transfers and supplier purchase orders -----------------------------------------------------
raw = bronze("replenishment_orders")
event("replenishment_orders", "Location code standardized",
      raw.filter((F.col("from_location") != code("from_location")) | (F.col("to_location") != code("to_location"))).count())
orders = (raw.withColumn("FromLocation", code("from_location")).withColumn("ToLocation", code("to_location"))
          .withColumn("reason", F.when(F.col("received_date").isNotNull() & (F.col("received_date") < F.col("order_date")),
                                       "Receipt before order date quarantined")))
for row in orders.filter("reason IS NOT NULL").groupBy("reason").count().collect():
    event("replenishment_orders", row["reason"], row["count"])
quarantine("replenishment_orders", orders.filter("reason IS NOT NULL"), "order_id")
orders, removed = latest(orders.filter("reason IS NULL"), ["order_number"], [F.col("loaded_at").desc(), F.col("order_id").desc()])
event("replenishment_orders", "Duplicate order line removed", removed)
orders = orders.select(F.col("order_number").alias("OrderNumber"), F.col("order_type").alias("OrderType"), code("sku").alias("SKU"),
                       "FromLocation", "ToLocation", F.col("order_date").alias("OrderDate"),
                       F.col("expected_date").alias("ExpectedDate"), F.col("received_date").alias("ReceivedDate"),
                       F.col("ordered_units").cast("int").alias("OrderedUnits"), F.col("received_units").cast("int").alias("ReceivedUnits"),
                       F.col("status").alias("Status"))
counts["replenishment_orders"] = write(orders, "replenishment_orders")

# Evidence --------------------------------------------------------------------------------------------------------------
dq = spark.createDataFrame(events, "Entity string, Rule string, Action string, AffectedRows long") \
    .withColumn("Layer", F.lit("Silver")).withColumn("RunId", F.lit(RUN_ID)).withColumn("RunAt", F.lit(RUN_AT))
write(dq, "dq_events")
q = quarantined[0]
for frame in quarantined[1:]:
    q = q.unionByName(frame)
write(q.withColumn("RunId", F.lit(RUN_ID)), "dq_quarantine")
observed = {f"{e}|{r}": c for e, r, _, c in events}
assert counts == EXPECTED["silverRows"], (counts, EXPECTED["silverRows"])
assert observed == EXPECTED["dqEvents"], {k: (observed.get(k), EXPECTED["dqEvents"].get(k))
                                         for k in set(observed) | set(EXPECTED["dqEvents"]) if observed.get(k) != EXPECTED["dqEvents"].get(k)}
print("MTL_SILVER_VERIFIED", json.dumps({"rows": counts, "dqEvents": len(events), "affectedRows": sum(observed.values())}))
'''
