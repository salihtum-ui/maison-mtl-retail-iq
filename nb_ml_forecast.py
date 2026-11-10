"""ML notebook source: 28-day daily sales forecast per store x product (direct multi-horizon gradient boosting)."""

FORECAST = r'''
import datetime, json, warnings
import numpy as np, pandas as pd, mlflow
from pyspark.sql import functions as F
warnings.filterwarnings("ignore")
spark.conf.set("spark.sql.session.timeZone", "UTC")
assert spark.conf.get("trident.workspace.id") == WORKSPACE
mlflow.autolog(disable=True)
SNAP = pd.Timestamp(EXPECTED["snapshotDate"])
H, SEED = 28, 20261103
rng = np.random.default_rng(SEED)
try:
    import lightgbm as lgb
    ALGORITHM = "LightGBM"
except ImportError:
    from sklearn.ensemble import HistGradientBoostingRegressor
    ALGORITHM = "HistGradientBoosting"

sales = spark.table("fact_sales").select("Date", "StoreCode", "SKU", "UnitsSold").toPandas()
positions = spark.table("inventory_current").select("StoreCode", "SKU").orderBy("StoreCode", "SKU").toPandas()
products = spark.table("dim_product").select("SKU", "Department", "Category", "SeasonProfile", "UnitPrice").toPandas()
stores = spark.table("dim_store").select("StoreCode", "TrafficIndex").toPandas()
cal = spark.table("dim_date").toPandas()
cal["Date"] = pd.to_datetime(cal["Date"])
sales["Date"] = pd.to_datetime(sales["Date"])
start = cal["Date"].min()
T = int((SNAP - start).days) + 1
series = positions.merge(products, on="SKU").merge(stores, on="StoreCode")
sid = {(r.StoreCode, r.SKU): i for i, r in enumerate(series.itertuples())}
S = len(series)
Y = np.zeros((S, T + H), dtype=np.float32)
idx = sales.assign(s=[sid[(a, b)] for a, b in zip(sales.StoreCode, sales.SKU)], t=(sales.Date - start).dt.days)
Y[idx.s.values, idx.t.values] = idx.UnitsSold.values
C = np.concatenate([np.zeros((S, 1)), np.cumsum(Y.astype(np.float64), axis=1)], axis=1)  # C[s, k] = sum Y[s, :k]

def window_mean(s, end, length):
    end = np.asarray(end); begin = end - length + 1
    ok = begin >= 0
    out = np.full(end.shape, np.nan)
    out[ok] = (C[s[ok], end[ok] + 1] - C[s[ok], begin[ok]]) / length
    return out

cal = cal.set_index("Date").reindex(pd.date_range(start, periods=T + H)).reset_index().rename(columns={"index": "Date"})
bf_days = set()
for x in BLACK_FRIDAY:
    day = pd.Timestamp(x)
    bf_days |= {day, day + pd.Timedelta(days=1), day + pd.Timedelta(days=2)}

def planned_markdown(profile, dates):
    d = pd.DatetimeIndex(dates)
    pct = np.zeros(len(d))
    month, day = d.month.values, d.day.values
    if profile in ("Winter", "FallWinter"):
        pct = np.where(((month == 1) & (day >= 2)) | (month == 2), 0.30, pct)
    if profile == "Summer":
        pct = np.where(((month == 7) & (day >= 10)) | (month == 8), 0.40, pct)
    if profile == "Spring":
        pct = np.where(month == 6, 0.30, pct)
    if profile in ("Winter", "FallWinter", "Holiday", "HolidayPeak"):
        pct = np.where((month == 12) & (day >= 26), np.maximum(pct, 0.25), pct)
    return np.where(d.isin(list(bf_days)), np.maximum(pct, 0.20), pct)

MD = np.vstack([planned_markdown(p, cal["Date"]) for p in series.SeasonProfile])
codes = {c: series[c].astype("category").cat.codes.values for c in ["StoreCode", "SKU", "Department", "Category", "SeasonProfile"]}
flags = {c: cal[c].fillna(False).astype(int).values for c in ["IsStoreClosed", "IsBlackFridayWeekend", "IsBoxingWeek",
                                                                "IsWinterClearance", "IsSummerClearance", "IsSpringClearance"]}
doy = cal["Date"].dt.dayofyear.values; dow = cal["Date"].dt.dayofweek.values; month = cal["Date"].dt.month.values
xmas = (pd.to_datetime(cal["Date"].dt.year.astype(str) + "-12-25") - cal["Date"]).dt.days.values

def features(s, t, h):
    o = t - h
    last7, last28, last91 = window_mean(s, o, 7), window_mean(s, o, 28), window_mean(s, o, 91)
    ly28 = window_mean(s, o - 364, 28)
    lyw = window_mean(s, t - 361, 7)
    lyn = window_mean(s, o - 364 + 28, 28)
    X = pd.DataFrame({
        "h": h, "last7": last7, "last28": last28, "last91": last91, "ly28_origin": ly28, "ly_week_target": lyw,
        "ly_next28": lyn, "trend_ratio": np.where(ly28 > 0, last28 / np.where(ly28 > 0, ly28, 1), np.nan),
        "ly_scaled": lyw * np.where(ly28 > 0, last28 / np.where(ly28 > 0, ly28, 1), 1.0),
        "dow": dow[t], "month": month[t], "doy": doy[t], "days_to_xmas": xmas[t], "markdown": MD[s, t],
        "price": series.UnitPrice.values[s].astype(float), "traffic": series.TrafficIndex.values[s].astype(float),
        **{k: v[t] for k, v in flags.items()}, **{k.lower(): v[s] for k, v in codes.items()}})
    return X

CATS = ["storecode", "sku", "department", "category", "seasonprofile"]

def train(X, y, objective="regression", alpha=None, rounds=500):
    if ALGORITHM == "LightGBM":
        params = dict(objective=objective, n_estimators=rounds, learning_rate=0.05, num_leaves=63, min_child_samples=40,
                      subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=SEED, verbose=-1)
        if alpha is not None:
            params["alpha"] = alpha
        model = lgb.LGBMRegressor(**params)
        model.fit(X, y, categorical_feature=CATS)
        return model
    loss = "quantile" if objective == "quantile" else "poisson"
    model = HistGradientBoostingRegressor(loss=loss, quantile=alpha, max_iter=rounds, learning_rate=0.06, random_state=SEED) \
        if loss == "quantile" else HistGradientBoostingRegressor(loss=loss, max_iter=rounds, learning_rate=0.06, random_state=SEED)
    model.fit(X, y)
    return model

def training_rows(last_target):
    targets = np.arange(120, last_target + 1)
    s = np.repeat(np.arange(S), len(targets) * 2)
    t = np.tile(np.repeat(targets, 2), S)
    h = rng.integers(1, H + 1, size=len(t))
    keep = ~flags["IsStoreClosed"][t].astype(bool)
    return s[keep], t[keep], h[keep]

def metrics(actual, predicted):
    err = predicted - actual
    return {"MAE": float(np.mean(np.abs(err))), "RMSE": float(np.sqrt(np.mean(err ** 2))),
            "WAPE": float(np.sum(np.abs(err)) / max(np.sum(actual), 1e-9) * 100), "Bias%": float(np.sum(err) / max(np.sum(actual), 1e-9) * 100)}

# Holdout: forecast the last 28 actual days from origin 2026-10-06 (includes the unplanned cold snap)
origin = T - 1 - H
s_tr, t_tr, h_tr = training_rows(origin)
model = train(features(s_tr, t_tr, h_tr), Y[s_tr, t_tr])
s_te = np.repeat(np.arange(S), H); t_te = np.tile(np.arange(origin + 1, T), S); h_te = t_te - origin
pred = np.clip(model.predict(features(s_te, t_te, h_te)), 0, None)
actual = Y[s_te, t_te]
naive = np.nan_to_num(window_mean(s_te, np.full(len(s_te), origin), 28))
seasonal = np.nan_to_num(window_mean(s_te, t_te - 361, 7))
holdout = {"model": metrics(actual, pred), "naive_last28": metrics(actual, naive), "seasonal_naive": metrics(actual, seasonal)}
totals = {"model": metrics(actual.reshape(S, H).sum(1), pred.reshape(S, H).sum(1)),
          "seasonal_naive": metrics(actual.reshape(S, H).sum(1), seasonal.reshape(S, H).sum(1))}
dept_codes = series.Department.values[s_te]
dept_day = {}
for name, values in (("model", pred), ("seasonal_naive", seasonal)):
    frame = pd.DataFrame({"d": dept_codes, "t": t_te, "a": actual, "p": values}).groupby(["d", "t"]).sum()
    dept_day[name] = metrics(frame.a.values, frame.p.values)
by_dept = {}
for dept in sorted(series.Department.unique()):
    m = series.Department.values[s_te] == dept
    by_dept[dept] = metrics(actual[m], pred[m])
print("holdout", json.dumps(holdout, indent=1))

# Final models on all history, forecast origin = snapshot date
s_all, t_all, h_all = training_rows(T - 1)
X_all, y_all = features(s_all, t_all, h_all), Y[s_all, t_all]
final = train(X_all, y_all)
low = train(X_all, y_all, "quantile", 0.1, 250)
high = train(X_all, y_all, "quantile", 0.9, 250)
s_f = np.repeat(np.arange(S), H); t_f = np.tile(np.arange(T, T + H), S); h_f = t_f - (T - 1)
X_f = features(s_f, t_f, h_f)
closed = flags["IsStoreClosed"][t_f].astype(bool)
point = np.where(closed, 0, np.clip(final.predict(X_f), 0, None))
lo = np.minimum(np.where(closed, 0, np.clip(low.predict(X_f), 0, None)), point)
hi = np.maximum(np.where(closed, 0, np.clip(high.predict(X_f), 0, None)), point)

MODEL_NAME = "mtl-sales-forecast-lgbm" if ALGORITHM == "LightGBM" else "mtl-sales-forecast-hgb"
mlflow.set_experiment("mtl-sales-forecast")
with mlflow.start_run(run_name=f"{ALGORITHM.lower()}-direct-28d-{SNAP:%Y%m%d}") as run:
    mlflow.log_params({"algorithm": ALGORITHM, "horizon_days": H, "series": S, "training_rows": len(y_all),
                       "holdout_origin": str((start + pd.Timedelta(days=origin)).date()), "snapshot": str(SNAP.date()),
                       "features": ",".join(X_all.columns), "data": "SYNTHETIC Maison MTL"})
    for name, values in holdout.items():
        mlflow.log_metrics({f"{name}_{k.replace('%', 'pct')}": v for k, v in values.items()})
    for name, values in totals.items():
        mlflow.log_metrics({f"position28d_{name}_{k.replace('%', 'pct')}": v for k, v in values.items()})
    for name, values in dept_day.items():
        mlflow.log_metrics({f"department_day_{name}_{k.replace('%', 'pct')}": v for k, v in values.items()})
    for dept, values in by_dept.items():
        mlflow.log_metric(f"wape_{dept.lower()}", values["WAPE"])
    from mlflow.models.signature import infer_signature
    signature = infer_signature(X_f.head(50), point[:50])
    if ALGORITHM == "LightGBM":
        mlflow.lightgbm.log_model(final, "model", signature=signature, registered_model_name=MODEL_NAME)
    else:
        mlflow.sklearn.log_model(final, "model", signature=signature, registered_model_name=MODEL_NAME)
    RUN_ID = run.info.run_id
client = mlflow.tracking.MlflowClient()
VERSION = max(int(v.version) for v in client.search_model_versions(f"name='{MODEL_NAME}'"))
GENERATED = datetime.datetime.utcnow().replace(microsecond=0)

dates_f = cal["Date"].values[t_f]
price = series.UnitPrice.values[s_f].astype(float) * (1 - MD[s_f, t_f])
forecast = pd.DataFrame({
    "ForecastId": pd.to_datetime(dates_f).strftime("%Y-%m-%d") + "|" + series.StoreCode.values[s_f] + "|" + series.SKU.values[s_f],
    "Date": pd.to_datetime(dates_f).date, "DateKey": pd.to_datetime(dates_f).strftime("%Y%m%d").astype(int),
    "StoreCode": series.StoreCode.values[s_f], "SKU": series.SKU.values[s_f], "HorizonDays": h_f.astype(int),
    "ForecastUnits": point.round(3), "ForecastUnitsLow": lo.round(3), "ForecastUnitsHigh": hi.round(3),
    "PlannedMarkdownPct": MD[s_f, t_f].round(2), "ForecastNetSales": (point * price).round(2),
    "ModelName": MODEL_NAME, "ModelVersion": str(VERSION), "RunId": RUN_ID, "GeneratedAt": GENERATED})
spark.createDataFrame(forecast).write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("ml_sales_forecast_daily")

last28 = np.array([Y[i, T - 28:T].sum() for i in range(S)])
summary = pd.DataFrame({"PositionId": series.StoreCode + "|" + series.SKU, "StoreCode": series.StoreCode, "SKU": series.SKU,
                        "ActualUnitsLast28": last28})
agg = forecast.groupby(["StoreCode", "SKU"]).apply(lambda g: pd.Series({
    "Forecast7Units": g.loc[g.HorizonDays <= 7, "ForecastUnits"].sum(), "Forecast14Units": g.loc[g.HorizonDays <= 14, "ForecastUnits"].sum(),
    "Forecast28Units": g.ForecastUnits.sum(), "Forecast28UnitsLow": g.ForecastUnitsLow.sum(), "Forecast28UnitsHigh": g.ForecastUnitsHigh.sum(),
    "Forecast28NetSales": g.ForecastNetSales.sum()})).reset_index()
summary = summary.merge(agg, on=["StoreCode", "SKU"])
summary["ForecastVsLast28Pct"] = np.where(summary.ActualUnitsLast28 > 0, (summary.Forecast28Units / summary.ActualUnitsLast28 - 1) * 100, np.nan).round(1)
summary = summary.round(2)
summary["ModelVersion"] = str(VERSION)
spark.createDataFrame(summary).write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("ml_forecast_summary")

# Chart-ready actual (56 days) vs forecast (28 days) by department and chain
dept_of = series.Department.values
chart = []
for dept in ["All"] + sorted(set(dept_of)):
    m = np.ones(S, bool) if dept == "All" else dept_of == dept
    for t in range(T - 56, T):
        chart.append((cal["Date"].iloc[t].date(), dept, "Actual", float(Y[m, t].sum()), None, None))
    sub = forecast[np.isin(forecast.StoreCode + "|" + forecast.SKU, (series.StoreCode + "|" + series.SKU)[m])]
    daily = sub.groupby("Date")[["ForecastUnits", "ForecastUnitsLow", "ForecastUnitsHigh"]].sum()
    for day, r in daily.iterrows():
        chart.append((day, dept, "Forecast", float(r.ForecastUnits), float(r.ForecastUnitsLow), float(r.ForecastUnitsHigh)))
spark.createDataFrame(pd.DataFrame(chart, columns=["Date", "Department", "Kind", "Units", "UnitsLow", "UnitsHigh"])) \
    .write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("ml_forecast_chart")

rows = [(MODEL_NAME, "Holdout (store-SKU-day)", k, round(v, 4), round(holdout["seasonal_naive"][k], 4), "Seasonal naive")
        for k, v in holdout["model"].items()]
rows += [(MODEL_NAME, "Holdout (store-SKU 28-day total)", k, round(totals["model"][k], 4), round(totals["seasonal_naive"][k], 4),
          "Seasonal naive") for k in ("WAPE", "Bias%")]
rows += [(MODEL_NAME, "Holdout (department-day)", k, round(dept_day["model"][k], 4), round(dept_day["seasonal_naive"][k], 4),
          "Seasonal naive") for k in ("WAPE", "Bias%")]
rows += [(MODEL_NAME, "Holdout (store-SKU-day) - " + d, "WAPE", round(v["WAPE"], 4), None, None) for d, v in by_dept.items()]
metrics_df = spark.createDataFrame(pd.DataFrame(rows, columns=["Model", "Segment", "Metric", "Value", "BaselineValue", "Baseline"])) \
    .withColumn("ModelVersion", F.lit(str(VERSION))).withColumn("RunId", F.lit(RUN_ID)).withColumn("GeneratedAt", F.lit(GENERATED))
if spark.catalog.tableExists("ml_model_metrics"):
    spark.sql(f"DELETE FROM ml_model_metrics WHERE Model LIKE 'mtl-sales-forecast%'")
    metrics_df.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable("ml_model_metrics")
else:
    metrics_df.write.format("delta").mode("overwrite").saveAsTable("ml_model_metrics")
assert spark.table("ml_sales_forecast_daily").count() == S * H
assert holdout["model"]["WAPE"] < holdout["naive_last28"]["WAPE"], holdout
print("MTL_FORECAST_VERIFIED", json.dumps({"algorithm": ALGORITHM, "model": MODEL_NAME, "version": VERSION, "runId": RUN_ID,
      "holdout": holdout, "forecastUnits28": float(point.sum()), "forecastNetSales28": float((point * price).sum())}))
'''
