"""ML notebook source: predict when each store x product will fall below its reorder point and what to reorder."""

STOCK = r'''
import datetime, json, math, warnings
import numpy as np, pandas as pd, mlflow
from pyspark.sql import functions as F
warnings.filterwarnings("ignore")
spark.conf.set("spark.sql.session.timeZone", "UTC")
assert spark.conf.get("trident.workspace.id") == WORKSPACE
mlflow.autolog(disable=True)
SNAP = pd.Timestamp(EXPECTED["snapshotDate"])
HORIZON, CENSOR, SEED = 28, 36, 20261103
try:
    import lightgbm as lgb
    ALGORITHM = "LightGBM"
except ImportError:
    from sklearn.ensemble import HistGradientBoostingRegressor
    ALGORITHM = "HistGradientBoosting"

inv = spark.table("fact_inventory").filter("LocationType = 'Store'").select(
    "Date", "StoreCode", "SKU", "OnHandUnits", "OnOrderUnits", "ReorderPointUnits", "SafetyStockUnits").toPandas()
dcinv = spark.table("fact_inventory").filter("LocationType = 'Distribution centre'").select("Date", "SKU", "OnHandUnits").toPandas()
sales = spark.table("fact_sales").select("Date", "StoreCode", "SKU", "UnitsSold").toPandas()
series = spark.table("inventory_current").select("StoreCode", "SKU").orderBy("StoreCode", "SKU").toPandas() \
    .merge(spark.table("dim_product").select("SKU", "Department", "Category", "SeasonProfile", "CasePack", "SupplierCode",
                                             "ProductName").toPandas(), on="SKU") \
    .merge(spark.table("dim_store").select("StoreCode", "StoreName", "TrafficIndex", "DcTransferDays").toPandas(), on="StoreCode")
for frame in (inv, dcinv, sales):
    frame["Date"] = pd.to_datetime(frame["Date"])
start = inv.Date.min()
T = int((SNAP - start).days) + 1
S = len(series)
sid = {(r.StoreCode, r.SKU): i for i, r in enumerate(series.itertuples())}
skus = sorted(series.SKU.unique()); kid = {k: i for i, k in enumerate(skus)}

def matrix(frame, value, keys):
    M = np.zeros((S if keys == "pos" else len(skus), T), dtype=np.float64)
    rows = [sid[(a, b)] for a, b in zip(frame.StoreCode, frame.SKU)] if keys == "pos" else [kid[k] for k in frame.SKU]
    M[np.array(rows), (frame.Date - start).dt.days.values] = frame[value].values
    return M

OH, OO = matrix(inv, "OnHandUnits", "pos"), matrix(inv, "OnOrderUnits", "pos")
ROP, SS = matrix(inv, "ReorderPointUnits", "pos"), matrix(inv, "SafetyStockUnits", "pos")
Y = matrix(sales, "UnitsSold", "pos")
DC = matrix(dcinv, "OnHandUnits", "sku")
C = np.concatenate([np.zeros((S, 1)), np.cumsum(Y, axis=1)], axis=1)
# Low stock = on hand below the reorder point: the learned target is the next date a position needs replenishment.
below = OH < ROP
sku_of = np.array([kid[k] for k in series.SKU])
CS = np.zeros((len(skus), C.shape[1]))
np.add.at(CS, sku_of, C)

def chain_rate(k, t, length=7):
    begin = np.maximum(t - length + 1, 0)
    return (CS[k, t + 1] - CS[k, begin]) / np.maximum(t - begin + 1, 1)

def mean(s, end, length):
    begin = end - length + 1
    out = np.full(np.shape(end), np.nan)
    ok = begin >= 0
    out[ok] = (C[s[ok], end[ok] + 1] - C[s[ok], begin[ok]]) / length
    return out

def label(s, t):
    out = np.full(len(s), CENSOR, dtype=np.float64)
    for k in range(CENSOR - 1, 0, -1):
        hit = below[s, np.minimum(t + k, T - 1)] & (t + k <= T - 1)
        out = np.where(hit, k, out)
    return out

season = series.SeasonProfile.astype("category").cat.codes.values
category = series.Category.astype("category").cat.codes.values
store = series.StoreCode.astype("category").cat.codes.values
sku_code = series.SKU.astype("category").cat.codes.values
sku_index = np.array([kid[k] for k in series.SKU])

def features(s, t):
    last7, last28 = mean(s, t, 7), mean(s, t, 28)
    ly28, lynext = mean(s, t - 364, 28), mean(s, t - 364 + 28, 28)
    velocity = np.maximum(np.nan_to_num(last7), 0.05)
    return pd.DataFrame({
        "on_hand": OH[s, t], "on_order": OO[s, t], "reorder_point": ROP[s, t], "safety_stock": SS[s, t],
        "gap_to_rop": OH[s, t] - ROP[s, t], "position_gap": OH[s, t] + OO[s, t] - ROP[s, t],
        "last7": last7, "last28": last28, "ly_next28": lynext,
        "ly_ratio": np.where(ly28 > 0, last28 / np.where(ly28 > 0, ly28, 1), np.nan),
        "days_of_supply7": OH[s, t] / velocity, "position_cover7": (OH[s, t] + OO[s, t] - ROP[s, t]) / velocity,
        "dc_on_hand": DC[sku_index[s], t],
        "dc_cover_days": DC[sku_index[s], t] / np.maximum(chain_rate(sku_index[s], t), 0.1),
        "transfer_days": series.DcTransferDays.values[s].astype(float),
        "traffic": series.TrafficIndex.values[s].astype(float), "month": ((start + pd.to_timedelta(t, "D")).month).values,
        "season": season[s], "category": category[s], "store": store[s], "sku": sku_code[s]})

CATS = ["season", "category", "store", "sku"]
t_grid = np.arange(120, T - CENSOR, 2)
s_all = np.repeat(np.arange(S), len(t_grid)); t_all = np.tile(t_grid, S)
keep = ~below[s_all, t_all]
s_all, t_all = s_all[keep], t_all[keep]
X_all, y_all = features(s_all, t_all), label(s_all, t_all)

def train(X, y):
    if ALGORITHM == "LightGBM":
        model = lgb.LGBMRegressor(objective="l1", n_estimators=600, learning_rate=0.05, num_leaves=63, min_child_samples=30,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=SEED, verbose=-1)
        model.fit(X, y, categorical_feature=CATS)
        return model
    model = HistGradientBoostingRegressor(loss="absolute_error", max_iter=600, learning_rate=0.06, random_state=SEED)
    model.fit(X, y)
    return model

split = T - CENSOR - 90
train_mask = t_all < split
model = train(X_all[train_mask], y_all[train_mask])
pred = np.clip(model.predict(X_all[~train_mask]), 0, CENSOR)
actual = y_all[~train_mask]
p7, a7 = pred <= 7, actual <= 7
tp = float(np.sum(p7 & a7)); precision = tp / max(np.sum(p7), 1); recall = tp / max(np.sum(a7), 1)
naive = np.clip(np.nan_to_num((X_all[~train_mask].gap_to_rop.values + 1) / np.maximum(X_all[~train_mask].last28.values, 0.05)), 0, CENSOR)
holdout = {"MAE_days": float(np.mean(np.abs(pred - actual))), "MAE_days_naive": float(np.mean(np.abs(naive - actual))),
           "Precision_low_within_7d": precision * 100, "Recall_low_within_7d": recall * 100,
           "F1_low_within_7d": 2 * precision * recall / max(precision + recall, 1e-9) * 100,
           "Accuracy_low_within_7d": float(np.mean(p7 == a7) * 100), "Test_positions": int(len(actual))}
print("holdout", json.dumps(holdout, indent=1))
final = train(X_all, y_all)

MODEL_NAME = "mtl-low-stock-days-lgbm" if ALGORITHM == "LightGBM" else "mtl-low-stock-days-hgb"
mlflow.set_experiment("mtl-low-stock-prediction")
with mlflow.start_run(run_name=f"{ALGORITHM.lower()}-days-to-low-{SNAP:%Y%m%d}") as run:
    mlflow.log_params({"algorithm": ALGORITHM, "label": "days until on-hand < reorder point (censored at 36)",
                       "training_rows": len(y_all), "snapshot": str(SNAP.date()), "data": "SYNTHETIC Maison MTL"})
    mlflow.log_metrics({k: v for k, v in holdout.items()})
    from mlflow.models.signature import infer_signature
    sample = X_all.head(50)
    if ALGORITHM == "LightGBM":
        mlflow.lightgbm.log_model(final, "model", signature=infer_signature(sample, final.predict(sample)), registered_model_name=MODEL_NAME)
    else:
        mlflow.sklearn.log_model(final, "model", signature=infer_signature(sample, final.predict(sample)), registered_model_name=MODEL_NAME)
    RUN_ID = run.info.run_id
VERSION = max(int(v.version) for v in mlflow.tracking.MlflowClient().search_model_versions(f"name='{MODEL_NAME}'"))
GENERATED = datetime.datetime.utcnow().replace(microsecond=0)

# Score the current snapshot and combine with the sales forecast projection --------------------------------------------
now = np.full(S, T - 1)
model_days = np.clip(final.predict(features(np.arange(S), now)), 0, CENSOR)
fc = spark.table("ml_sales_forecast_daily").select("StoreCode", "SKU", "HorizonDays", "ForecastUnits").toPandas()
F_ = np.zeros((S, HORIZON))
F_[[sid[(a, b)] for a, b in zip(fc.StoreCode, fc.SKU)], fc.HorizonDays.values - 1] = fc.ForecastUnits.values
open_orders = spark.table("fact_replenishment").filter("IsOpen AND OrderType = 'Store transfer'").select(
    "ToLocation", "SKU", "ExpectedDate", "OrderedUnits").toPandas()
R = np.zeros((S, HORIZON))
next_receipt = {}
for r in open_orders.itertuples():
    k = (r.ToLocation, r.SKU)
    if k in sid:
        day = int((pd.Timestamp(r.ExpectedDate) - SNAP).days)
        if 1 <= day <= HORIZON:
            R[sid[k], day - 1] += r.OrderedUnits
        next_receipt[k] = min(next_receipt.get(k, pd.Timestamp.max), pd.Timestamp(r.ExpectedDate))
projected = OH[:, T - 1][:, None] + np.cumsum(R - F_, axis=1)
rop_now, ss_now, oh_now, oo_now = ROP[:, T - 1], SS[:, T - 1], OH[:, T - 1], OO[:, T - 1]
def first_day(mask):
    any_ = mask.any(axis=1)
    return np.where(any_, mask.argmax(axis=1) + 1, np.nan)
dc_now = DC[sku_index, T - 1]
pos = spark.table("fact_replenishment").filter((F.col("OrderType") == "Supplier PO") & F.col("IsOpen")) \
    .join(spark.table("dim_supplier").select(F.col("SupplierCode"), F.coalesce(F.col("AvgDaysLate"), F.lit(0.0)).alias("late")),
          "SupplierCode", "left").select("SKU", "ExpectedDate", "late").toPandas()
next_po_day = np.full(len(skus), np.nan)
for r in pos.itertuples():
    if r.SKU in kid:
        # Overdue POs are assumed to land after the supplier's average delay (at least 3 more days).
        due = max((pd.Timestamp(r.ExpectedDate) - SNAP).days, 0) + max(round(float(r.late or 0)), 3 if pd.Timestamp(r.ExpectedDate) <= SNAP else 0)
        next_po_day[kid[r.SKU]] = np.fmin(next_po_day[kid[r.SKU]], max(due, 1))
chain_daily = np.zeros(len(skus))
np.add.at(chain_daily, sku_index, F_.mean(axis=1))
dc_cover_days = np.round(dc_now / np.maximum(chain_daily[sku_index], 0.1), 1)
lead = series.DcTransferDays.values.astype(float)
# Earliest day new stock can reach the store: a DC transfer when DC-QC holds 7+ days of chain demand, else the next PO + transfer.
replenish_day = np.where(dc_cover_days >= 7, lead, np.nan_to_num(next_po_day[sku_index] + lead, nan=99.0))
forecast_days = first_day(projected < rop_now[:, None])
stockout_days = first_day(projected <= 0)
currently_below = oh_now < rop_now
model_round = np.where(model_days >= CENSOR - 0.5, np.nan, np.round(model_days))
combined = np.where(currently_below, 0, np.fmin(model_round, forecast_days))
soon, later = combined <= 7, combined <= 14
below_ss = oh_now < ss_now
stock_gap = stockout_days < replenish_day
secured = ~stock_gap & ~((combined <= 14) & (replenish_day > combined + 3) & (oo_now == 0))
risk = np.where((oh_now == 0) | (stock_gap & (stockout_days <= 7)), "Critical",
       np.where(stock_gap | (soon & ~secured), "High", np.where((later & ~secured) | below_ss, "Medium", "Low")))
rank = pd.Series(risk).map({"Critical": 1, "High": 2, "Medium": 3, "Low": 4}).values
cover = (lead + 14).astype(int)
demand = np.array([F_[i, :cover[i]].sum() for i in range(S)])
case = series.CasePack.values.astype(float)
raw_qty = np.maximum(0, demand + ss_now - oh_now - oo_now)
qty = np.where((raw_qty > 0) & ((risk != "Low") | later), np.ceil(raw_qty / case) * case, 0).astype(int)
action = np.where(qty == 0, "No action - replenishment on track",
         np.where(secured & (risk == "Low"), "Routine DC-QC transfer",
         np.where(dc_now >= qty, "Transfer from DC-QC",
         np.where(dc_now > 0, "Partial DC-QC transfer + expedite supplier PO", "Expedite supplier PO"))))
def to_date(days):
    return [None if np.isnan(x) else (SNAP + pd.Timedelta(days=int(x))).date() for x in days]
risk_df = pd.DataFrame({
    "PositionId": series.StoreCode + "|" + series.SKU, "SnapshotDate": SNAP.date(), "StoreCode": series.StoreCode,
    "StoreName": series.StoreName, "SKU": series.SKU, "ProductName": series.ProductName, "Department": series.Department,
    "Category": series.Category, "SupplierCode": series.SupplierCode, "OnHandUnits": oh_now.astype(int),
    "OnOrderUnits": oo_now.astype(int), "ReorderPointUnits": rop_now.astype(int), "SafetyStockUnits": ss_now.astype(int),
    "AvgDailyUnits7": np.round(Y[:, T - 7:T].mean(axis=1), 3), "AvgDailyUnits28": np.round(Y[:, T - 28:T].mean(axis=1), 3),
    "Forecast7Units": np.round(F_[:, :7].sum(axis=1), 2), "Forecast28Units": np.round(F_.sum(axis=1), 2),
    "ModelDaysToLow": np.round(model_days, 1), "ForecastDaysToLow": forecast_days, "PredictedDaysToLow": combined,
    "PredictedLowStockDate": to_date(combined), "ProjectedStockoutDate": to_date(stockout_days),
    "NextReceiptDate": [next_receipt.get((a, b), pd.NaT) for a, b in zip(series.StoreCode, series.SKU)],
    "IsBelowReorderPoint": currently_below, "IsAvailableBelowReorderPoint": (oh_now + oo_now) < rop_now, "IsOutOfStock": oh_now == 0,
    "ReplenishmentSecured": secured, "DcCoverDays": dc_cover_days, "RiskLevel": risk, "RiskRank": rank.astype(int),
    "RecommendedReorderQty": qty, "RecommendedAction": action, "DcOnHandUnits": dc_now.astype(int),
    "ModelName": MODEL_NAME, "ModelVersion": str(VERSION), "RunId": RUN_ID, "GeneratedAt": GENERATED})
risk_df["NextReceiptDate"] = [None if pd.isna(x) else pd.Timestamp(x).date() for x in risk_df.NextReceiptDate]
risk_df["ForecastDaysToLow"] = risk_df.ForecastDaysToLow.astype("float")
risk_df["PredictedDaysToLow"] = risk_df.PredictedDaysToLow.astype("float")
status = spark.table("inventory_current").select("StoreCode", "SKU", "StockStatus", "DaysOfSupply").toPandas()
risk_df = risk_df.merge(status, on=["StoreCode", "SKU"], how="left")
risk_df["DaysOfSupply"] = risk_df.DaysOfSupply.astype("float")
spark.createDataFrame(risk_df).write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("ml_stock_risk")

rows = [(MODEL_NAME, "Holdout (last 90 days)", k, round(float(v), 4)) for k, v in holdout.items()]
metrics_df = spark.createDataFrame(pd.DataFrame(rows, columns=["Model", "Segment", "Metric", "Value"])) \
    .withColumn("BaselineValue", F.when(F.col("Metric") == "MAE_days", F.lit(round(holdout["MAE_days_naive"], 4))).cast("double")) \
    .withColumn("Baseline", F.when(F.col("Metric") == "MAE_days", F.lit("Days-of-cover heuristic"))) \
    .withColumn("ModelVersion", F.lit(str(VERSION))).withColumn("RunId", F.lit(RUN_ID)).withColumn("GeneratedAt", F.lit(GENERATED))
spark.sql("DELETE FROM ml_model_metrics WHERE Model LIKE 'mtl-low-stock%'")
metrics_df.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable("ml_model_metrics")
counts = risk_df.RiskLevel.value_counts().to_dict()
assert len(risk_df) == S and counts.get("Critical", 0) >= EXPECTED["outOfStockPositions"], counts
print("MTL_STOCK_RISK_VERIFIED", json.dumps({"algorithm": ALGORITHM, "model": MODEL_NAME, "version": VERSION, "runId": RUN_ID,
      "holdout": holdout, "riskLevels": counts, "recommendedUnits": int(qty[rank <= 2].sum())}))
'''
