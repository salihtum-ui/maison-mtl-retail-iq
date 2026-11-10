"""Reorder-request conformance: app SQL database (via OneLake shortcut in Bronze) -> Silver validation -> Gold."""

REORDERS = r'''
import datetime, json
from pyspark.sql import functions as F, Window, types as T
spark.conf.set("spark.sql.session.timeZone", "UTC")
assert spark.conf.get("trident.workspace.id") == WORKSPACE
URGENCY = ["Standard", "Urgent", "Critical"]
schema = T.StructType([T.StructField(n, t, True) for n, t in [
    ("id", T.StringType()), ("storeCode", T.StringType()), ("sku", T.StringType()), ("productName", T.StringType()),
    ("quantity", T.IntegerType()), ("urgency", T.StringType()), ("neededBy", T.TimestampType()), ("note", T.StringType()),
    ("source", T.StringType()), ("submittedAt", T.TimestampType()), ("submittedByName", T.StringType())]])
try:
    raw = spark.read.format("delta").load(f"{ONELAKE}/{BRONZE}/Tables/app_reorder_requests")
    landed = True
except Exception as error:
    print("No app reorder requests landed yet:", str(error)[:160])
    raw, landed = spark.createDataFrame([], schema), False
raw = raw.select(*[F.col(c).cast(schema[c].dataType).alias(c) for c in schema.fieldNames()])
stores = spark.table("dim_store").filter("IsSellingStore").select("StoreCode", "StoreName")
products = spark.table("dim_product").select("SKU", F.col("ProductName").alias("CatalogProductName"), "Department", "Category", "CasePack")
risk = spark.table("ml_stock_risk").select("StoreCode", "SKU", "RiskLevel", "RecommendedReorderQty", "OnHandUnits", "DcOnHandUnits",
                                           "PredictedLowStockDate")
code = lambda c: F.upper(F.regexp_replace(F.trim(F.col(c)), "_", "-"))
r = (raw.withColumn("RequestId", F.lower(F.col("id"))).withColumn("StoreCode", code("storeCode")).withColumn("SKU", code("sku"))
     .withColumn("_rn", F.row_number().over(Window.partitionBy("RequestId").orderBy(F.col("submittedAt").desc()))).filter("_rn = 1")
     .join(stores, "StoreCode", "left").join(products, "SKU", "left").join(risk, ["StoreCode", "SKU"], "left"))
reason = (F.when(F.col("StoreName").isNull(), "Unknown or non-selling store")
          .when(F.col("CatalogProductName").isNull(), "Unknown SKU")
          .when((F.col("quantity").isNull()) | (F.col("quantity") < 1) | (F.col("quantity") > 1000), "Quantity must be 1-1000")
          .when(~F.col("urgency").isin(URGENCY), "Unknown urgency"))
warning = F.when(F.col("RecommendedReorderQty").isNotNull() & (F.col("RecommendedReorderQty") > 0) &
                 (F.col("quantity") > 3 * F.col("RecommendedReorderQty")), "Quantity is more than 3x the ML recommendation") \
           .when((F.col("RecommendedReorderQty") == 0), "ML sees 2+ weeks of cover; buyer to confirm need")
silver = r.select("RequestId", F.col("submittedAt").alias("SubmittedAt"), "StoreCode", "SKU", F.col("quantity").alias("Quantity"),
                  F.col("urgency").alias("Urgency"), F.col("neededBy").cast("date").alias("NeededBy"), F.col("note").alias("Note"),
                  F.coalesce(F.col("source"), F.lit("Manual")).alias("Source"), F.col("submittedByName").alias("RequestedBy"),
                  F.when(reason.isNull(), "Valid").otherwise("Invalid").alias("ValidationStatus"),
                  F.coalesce(reason, warning, F.lit("Passed validation")).alias("ValidationMessage"))
silver.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(f"{ONELAKE}/{SILVER}/Tables/reorder_requests")
gold = silver.join(r.select("RequestId", "StoreName", "CatalogProductName", "Department", "Category", "RiskLevel",
                            "RecommendedReorderQty", "OnHandUnits", "DcOnHandUnits", "PredictedLowStockDate"), "RequestId", "left").select(
    "RequestId", "SubmittedAt", F.col("SubmittedAt").cast("date").alias("SubmittedDate"),
    (F.year("SubmittedAt") * 10000 + F.month("SubmittedAt") * 100 + F.dayofmonth("SubmittedAt")).cast("int").alias("DateKey"),
    "StoreCode", "StoreName", "SKU", F.col("CatalogProductName").alias("ProductName"), "Department", "Category", "Quantity", "Urgency",
    "NeededBy", "Note", "Source", "RequestedBy", "ValidationStatus", "ValidationMessage",
    F.when(F.col("ValidationStatus") == "Valid", "Pending buyer approval").otherwise("Rejected - invalid request").alias("WorkflowStatus"),
    (F.col("ValidationStatus") == "Valid").alias("IsPending"), "RiskLevel", "RecommendedReorderQty",
    F.when(F.col("RecommendedReorderQty") > 0, F.round(F.col("Quantity") / F.col("RecommendedReorderQty") * 100, 1)).cast("double").alias("QuantityVsRecommendedPct"),
    "OnHandUnits", "DcOnHandUnits", "PredictedLowStockDate")
gold.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("reorder_requests")

# Reorder candidates: only positions at risk this week (Critical/High), so "at risk" questions cannot return Low rows.
at_risk = spark.table("ml_stock_risk").filter(F.col("RiskLevel").isin("Critical", "High")).select(
    "StoreCode", "StoreName", "SKU", "ProductName", "Department", "Category", "RiskLevel", "RiskRank", "OnHandUnits",
    "OnOrderUnits", "ReorderPointUnits", "PredictedDaysToLow", "PredictedLowStockDate", "RecommendedReorderQty",
    "RecommendedAction", "DcOnHandUnits")
at_risk.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("stock_risk_this_week")
assert spark.table("stock_risk_this_week").count() == spark.table("ml_stock_risk").filter(F.col("RiskLevel").isin("Critical", "High")).count()
summary = {"landed": landed, "requests": gold.count(), "atRiskThisWeek": spark.table("stock_risk_this_week").count(),
           "pending": gold.filter("IsPending").count(), "invalid": gold.filter("ValidationStatus = 'Invalid'").count()}
print("MTL_REORDERS_CONFORMED", json.dumps(summary))
'''
