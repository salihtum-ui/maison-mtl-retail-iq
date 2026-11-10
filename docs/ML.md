# Machine learning

Two Fabric Data Science notebooks train on Gold, track runs in MLflow, register ML model items and write predictions
back to Gold. Both run in the pipeline `PL_MTL_Medallion_and_ML` after Gold. If LightGBM is unavailable in the Spark
runtime, the notebooks fall back to scikit-learn's HistGradientBoosting (registered with an `-hgb` suffix).

## 1. Sales forecast (`04_ML_Sales_Forecast`)

| | |
|---|---|
| Question | How many units will each store sell of each SKU on each of the next 28 days? |
| Scope | All 600 store × SKU series, horizon 2026-11-04 → 2026-12-01 (includes Black Friday) |
| Model | Direct multi-horizon LightGBM regressor; P10 and P90 from LightGBM quantile models |
| MLflow | Experiment `mtl-sales-forecast`; registered model `mtl-sales-forecast-lgbm` |
| Outputs | `ml_sales_forecast_daily` (daily units, P10, P90, net sales), `ml_forecast_summary` (7/14/28-day totals per position), `ml_forecast_chart` (department actual vs forecast), `ml_model_metrics` |

**Features** (all measured at the forecast origin, so there is no leakage): horizon; mean daily units over the last
7, 28 and 91 days; last year's 28 days at the origin, the same target week last year and the following 28 days last
year; trend ratio (last 28 days vs last year) and a last-year value scaled by it; day of week, month, day of year and
days to Christmas; markdown rate, unit price and store traffic index; calendar flags (store closed, Black Friday
weekend, Boxing Week and other events); and categorical store, SKU, department, category and season profile.

**Holdout** (the last 28 actual days, which include the unplanned cold snap):

| Level | Model WAPE | Seasonal-naive WAPE |
|---|---:|---:|
| Department × day (planning level) | **18.8%** | 24.4% |
| Store × SKU, 28-day totals | 23.6% | 23.8% |
| Store × SKU × day (about 1 unit per day) | 66.3% | 69.7% |

Bias is about −15%: nobody could foresee the cold snap at the holdout origin. Forecast for the next 28 days:
**43,919 units / $4.22M**.

## 2. Low-stock prediction (`05_ML_Low_Stock_Prediction`)

| | |
|---|---|
| Question | When will each store × SKU drop below its reorder point, and how much should be reordered? |
| Model | LightGBM regressor (L1 objective) predicting days until on hand falls below the reorder point, trained on historical inventory snapshots (censored at the horizon) |
| MLflow | Experiment `mtl-low-stock-prediction`; registered model `mtl-low-stock-days-lgbm` |
| Outputs | `ml_stock_risk` (one row per position: predicted low-stock date, risk level, recommended quantity and action), `ml_model_metrics` |

**Features:** on hand, on order, reorder point, safety stock, gap to the reorder point and inventory position gap;
mean daily units over 7 and 28 days and last year's next 28 days; last-year ratio; days of supply and position cover;
DC-QC on hand and DC cover days; store transfer lead time and traffic index; month; and categorical season, category,
store and SKU.

**Combining with the forecast.** The model's predicted days are combined with a projection of on-hand stock using the
sales forecast, plus the supply timeline: DC-QC cover, open supplier POs adjusted by each supplier's actual delay,
and the DC-to-store transfer time.

**Holdout** (last 90 days): MAE **6.8 days** vs 9.1 for a days-of-cover heuristic. For "below the reorder point
within 7 days", precision is 78% and recall 53%.

**Risk levels at the snapshot:**

| Level | Positions | Meaning |
|---|---:|---|
| Critical | 50 | Out of stock now, or projected to stock out within 7 days before any replenishment can arrive |
| High | 34 | A supply gap is projected within 28 days, or the position goes low soon without secured replenishment |
| Medium | 2 | Goes low later without secured replenishment, or is below safety stock |
| Low | 514 | Replenishment on track |

Recommended reorder for Critical and High positions: **3,846 units**. Each position gets an action: transfer from
DC-QC when the DC has cover, otherwise expedite the supplier PO.

`06_Gold_Reorder_Requests` also writes `stock_risk_this_week`, the 84 Critical and High positions. It is the
reorder-candidate list used by the agent for "at risk this week" questions.

## Re-training

Run `python deploy.py medallion` (the whole pipeline) or a single notebook, for example `python medallion.py forecast`
or `python medallion.py stock`. Then refresh the downstream layers: `python deploy.py model ontology` and
`python app_sync.py publish`. Each run logs a new MLflow run and a new registered model version; the Gold tables
record the model name and version used.

## Notes

- Metrics are on synthetic data with a deliberate, unforeseeable shock (the cold snap). They show the workflow, not
  production accuracy.
- Both notebooks assert their outputs against the governed controls (for example that every out-of-stock position
  is at least Critical) and fail the pipeline otherwise.
