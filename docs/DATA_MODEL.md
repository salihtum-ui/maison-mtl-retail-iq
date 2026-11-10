# Data model

All data is synthetic and deterministic (`SEED = 20261103` in `mtl_reference.py`). Re-running the generator always
produces the same rows, so every figure below can be checked after any redeployment.

## Synthetic source (`mtl_data.py`)

- **Stores:** 10 fictional Maison MTL stores in Quebec cities: Vieux-Québec (QC-VQ), Sainte-Foy (QC-SF), Montréal
  Centre-Ville (MT-CV), Laval (LV-CL), Brossard Rive-Sud (BR-RS), St-Bruno (SB-PR), Sherbrooke (SH-ES), Gatineau
  (GA-OU), Trois-Rivières (TR-MA) and Lévis (LE-CA), plus the Québec City distribution centre **DC-QC**.
- **Products:** 60 SKUs across Women, Men, Kids, Home and Accessories, with fictional brands (Boréale, Atelier 31,
  Ligne Urbaine, Twill & Co., Rivage, Nordik, Petits Flocons, Maison Laurentienne) and 8 fictional suppliers. Each has
  unit cost and price, case pack, lead time, reorder point and safety stock.
- **History:** daily sales, inventory and replenishment from 2024-11-04 to the **2026-11-03** snapshot, from a store
  and DC replenishment simulation. It includes seasonality (outerwear Nov–Jan, swimwear in summer, back-to-school,
  holiday gifting), Black Friday, Boxing Week, clearance markdowns and closed holidays.
- **Story:** an early cold snap from 2026-10-22 lifts demand for winter items while Nordik boots and Boréale parkas
  have late supplier POs. The DC runs dry and stores start stocking out, which the ML step flags.

## Bronze: raw operational tables

Azure SQL `dbo` tables, mirrored and exposed in `MTL_Bronze` through OneLake shortcuts. Every table has a primary key.

| Table | Raw rows | Clean (Silver) rows | Primary key |
|---|---:|---:|---|
| stores | 11 | 11 | store_id |
| suppliers | 8 | 8 | supplier_id |
| products | 63 | 60 | product_id |
| sales_daily | 243,893 | 242,359 | sales_id |
| inventory_daily | 483,268 | 481,800 | snapshot_id |
| replenishment_orders | 27,901 | 27,878 | order_id |

`app_reorder_requests` is a further Bronze shortcut to the Fabric App's replicated `ReorderRequests` table.

## Silver: data-quality rules

`02_Silver_Cleanse_and_Conform` standardizes, quarantines and deduplicates, then writes `dq_events` (one row per rule
with the affected row count) and `dq_quarantine` (the rejected rows). These counts are asserted in the notebook and
proven reversible by `tests/test_mtl_data.py`.

| Table | Rule | Action | Rows |
|---|---|---|---:|
| sales_daily | Store code standardized (lower case, `_` instead of `-`, spaces) | Standardized | 6,131 |
| sales_daily | SKU standardized | Standardized | 3,677 |
| sales_daily | Duplicate POS resend removed (latest `loaded_at` wins) | Deduplicated | 1,444 |
| sales_daily | Negative quantity quarantined | Quarantined | 36 |
| sales_daily | Null quantity quarantined | Quarantined | 24 |
| sales_daily | Unknown product quarantined (orphan SKU) | Quarantined | 18 |
| sales_daily | Unknown store quarantined (training store) | Quarantined | 12 |
| inventory_daily | Location code standardized | Standardized | 9,750 |
| inventory_daily | Duplicate snapshot removed | Deduplicated | 1,420 |
| inventory_daily | Null on-hand quarantined | Quarantined | 30 |
| inventory_daily | Negative on-hand quarantined | Quarantined | 18 |
| replenishment_orders | Location code standardized | Standardized | 557 |
| replenishment_orders | Receipt before order date quarantined | Quarantined | 14 |
| replenishment_orders | Duplicate order line removed | Deduplicated | 9 |
| products | Category casing and spacing standardized | Standardized | 6 |
| products | Brand whitespace trimmed | Standardized | 4 |
| products | Stale product version removed | Deduplicated | 3 |
| stores | Province standardized to QC | Standardized | 4 |
| suppliers | Country name standardized | Standardized | 1 |
| **Total** | 152 quarantined, 2,876 deduplicated, 20,130 standardized | | **23,158** |

## Gold: star schema, KPIs and ML outputs

| Group | Tables |
|---|---|
| Dimensions | `dim_date`, `dim_store`, `dim_region`, `dim_product`, `dim_category`, `dim_brand`, `dim_supplier` |
| Facts | `fact_sales` (daily, store × SKU), `fact_inventory` (daily snapshots, semi-additive), `fact_replenishment` (DC transfers and supplier POs) |
| Current stock | `inventory_current` (one row per store × SKU at the snapshot: on hand, on order, reorder point, days of supply, status) |
| KPIs | `kpi_chain_summary`, `kpi_store_summary`, `kpi_category_summary`, `sales_month_store_category` |
| Quality and lineage | `dq_events`, `medallion_lineage` |
| ML | `ml_sales_forecast_daily`, `ml_forecast_summary`, `ml_forecast_chart`, `ml_stock_risk`, `ml_model_metrics` |
| Closed loop | `reorder_requests` (validated app requests enriched with ML risk), `stock_risk_this_week` (Critical/High positions only) |

## KPI controls (snapshot 2026-11-03, CAD)

The same values are asserted in the Silver/Gold notebooks and checked in Azure SQL, on the mirrored SQL endpoint,
with DAX against the semantic model, in the app snapshot and in the agent evaluation.

| Control | Value |
|---|---:|
| Net sales, last 28 days (2026-10-07 → 11-03) | 3,010,708 (**+21.3%** vs the same 28 weekdays last year) |
| Units / gross margin, last 28 days | 29,336 / 63.19% |
| Net sales YTD 2026 | 17,932,850 (**+6.35%** vs 2025 YTD) |
| Net sales 2025 | 24,899,159 |
| Top store, last 28 days | Maison MTL Montréal Centre-Ville (MT-CV), 459,997 |
| Top category, last 28 days | Outerwear, 1,052,599 |
| Store positions out of stock / below reorder point | **19** / 95 of 600 (in-stock 96.8%) |
| Most out-of-stock product | Women's Waterproof Winter Boot (W-FTW-601), 7 stores |
| Store on hand / on order / DC on hand (units) | 11,856 / 2,134 / 20,807 |
| Data-quality rows fixed in Silver | 23,158 |

`tests/test_mtl_data.py::test_documented_controls` pins these values to the generator.

## Semantic model

Direct Lake model `Maison MTL Retail IQ Model` on the `MTL_Gold` SQL endpoint, with 16 tables:

| Model table | Gold table |
|---|---|
| Date, Store, Region, Product, Category, Brand, Supplier | `dim_*` |
| Sales, Inventory, Replenishment | `fact_sales`, `fact_inventory`, `fact_replenishment` |
| Forecast, Stock Risk, Model Metrics | `ml_sales_forecast_daily`, `ml_stock_risk`, `ml_model_metrics` |
| Reorder Requests | `reorder_requests` |
| Data Quality, Lineage | `dq_events`, `medallion_lineage` |

Relationships run from facts to Date, Store and Product, and from Store to Region and Product to Category, Brand and
Supplier. Governed measures, defined once and reused by the report, the agent and DAX checks:

- **Sales:** Net Sales, Gross Sales, Markdown Amount and %, Units Sold, Gross Margin and %, Average Selling Price,
  Net Sales LY (364 days), Net Sales YoY %, Net Sales / Units / Gross Margin % Last 28 Days, Last 28 Days YoY %,
  Net Sales YTD / LYTD, YTD Growth %.
- **Inventory:** On Hand Units, On Order Units, DC On Hand Units, Inventory Cost, Store Positions, Out of Stock
  Positions, Below Reorder Point Positions, In-Stock %, Days of Supply, Sell-Through % Last 28 Days, Stockout
  Position Days.
- **Replenishment:** Open Supplier POs, Supplier On-Time %.
- **Forecast:** Forecast Units (P10/P90), Forecast Net Sales, Forecast vs Last 28 Days %.
- **Stock risk:** Critical Risk Positions, High Risk Positions, Low Stock Within 7 Days, Recommended Reorder Units
  (and for High Risk).
- **Reorders:** Reorder Requests, Pending Reorders, Pending Reorder Units, Invalid Reorder Requests.
- **Model quality and lineage:** Forecast WAPE %, Baseline WAPE %, Low-Stock Recall/Precision %, DQ rows by action,
  Bronze/Silver/Gold rows.

The model is AI-ready for the Data Agent: Q&A indexing is enabled, columns carry descriptions, and technical columns
(keys, run IDs, model versions) are hidden.

## Ontology

`MtlRetailOntology` binds 15 entities to Gold tables with EN/FR synonyms and descriptions:

- **Master data:** Region, Store, Category, Brand, Supplier, Product.
- **Performance:** ChainPerformance, StorePerformance, CategoryPerformance, MonthlySales.
- **Operations and ML:** InventoryPosition, SalesForecast, DailyForecast, StockRisk, ReorderRequest.

There are 18 relationships, for example RegionHasStore, CategoryHasProduct, BrandHasProduct,
SupplierSuppliesProduct, StoreHoldsInventory, PositionHasStockRisk and StoreHasReorderRequest. Only
business-relevant properties are bound: the `PROPERTIES` allow-list in `ontology.py` has 118 properties. Property
IDs derive from each column's ordinal in the full Gold table, so they stay stable when the allow-list changes.
