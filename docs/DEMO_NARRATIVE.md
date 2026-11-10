# Maison MTL Retail IQ — presenter walkthrough

## Goal

Show the leaders of Maison MTL, a fictional Quebec fashion and department store chain, how Microsoft Fabric turns
store transactions into decisions on one platform. Operational SQL is
mirrored with zero ETL, refined in a governed medallion and enriched by machine learning. It is then served through
a Direct Lake model, a business ontology and a bilingual AI agent, and put to work in a Fabric App where employees
act, with the loop closing back into analytics.

Allow **35–40 minutes**. Every figure is **synthetic** and consistent across every surface for the snapshot
**2026-11-03**. Maison MTL is fictional; store locations use Quebec cities for realism only.

## Before the meeting (15 minutes)

1. Open the workspace **Maison MTL Retail IQ** and pin these tabs:
   - `MtlRetail_MirroredSQL` (Monitor replication)
   - `MTL_Bronze`, `MTL_Silver`, `MTL_Gold`
   - `PL_MTL_Medallion_and_ML` and `04_ML_Sales_Forecast`
   - the `mtl-sales-forecast` experiment and the `mtl-low-stock-days-lgbm` model
   - the report **Maison MTL Retail IQ**
   - `MtlRetailOntology`
   - **MTL Retail IQ Advisor**
   - the app (URL in `artifacts/app.json`)
2. Check that mirroring reports **Running** with six tables **Replicating**.
3. Sign in to the app and ask the advisor one warm-up question (the first call after a deployment can be slow):
   `Which store had the highest net sales in the last 28 days?`
4. If no reorder request exists yet, submit one in the app and run `python deploy.py loop` once. This creates the
   Bronze shortcut to the app's data, so the live closed loop in section 7 takes about 3 minutes.
5. Optional (private mode): in the Azure portal, open your SQL server → Networking to show
   **Public network access: Disabled**.

## 1. The scenario: a cold snap hits Quebec (3 min)

**Say**

> It's November 3rd. An early cold snap started on October 22nd. Over the last 28 days, net sales across ten
> Quebec stores are **$3.01M, up 21.3%** on the same weeks last year. Outerwear, winter boots, toques and mitts
> are flying. That's great news, until the shelves run empty. Nineteen store-SKU positions are already out of
> stock, and Nordik boots and Boréale parkas have late supplier POs. Today these answers live in five systems and
> two spreadsheets. Let's see the same morning on Fabric.

Frame three questions:

1. How are we really trading, by store, category and product?
2. What will sell in the next four weeks, and where will we run out?
3. How does a store employee act on it — safely — in minutes?

## 2. Operational data, mirrored with zero ETL (5 min)

Open `MtlRetail_MirroredSQL` → **Monitor replication**.

**Say**

> The store systems write to an Azure SQL database. Fabric mirroring connects with a dedicated, least-privilege
> service principal (in private mode, through a virtual-network data gateway, so the database never gets a public
> endpoint). It took one definition and no pipelines to build: 755,144 rows across six tables are continuously
> replicated into OneLake as Delta.

Show the six tables with their row counts and status. Then open the mirrored SQL endpoint and run:

```sql
SELECT COUNT(*) FROM dbo.sales_daily;          -- 243,893 raw rows, including the defects
SELECT TOP 5 * FROM dbo.sales_daily WHERE units_sold < 0 OR units_sold IS NULL;
```

**Point out:** mirroring compute is free on the capacity, and there's no nightly batch window.

## 3. Medallion: trust before insight (6 min)

Open `MTL_Bronze`. **Say:** "Bronze is just OneLake shortcuts to the mirror. Zero copies, zero code."

Open `02_Silver_Cleanse_and_Conform` and then the `dq_events` table in Gold.

**Say**

> The raw feed is realistic. It has POS batches sent twice, lower-case and underscored store codes, negative and
> null quantities, a training store, unknown SKUs, stale product versions and receipts dated before their order.
> Silver fixes 23,158 rows and keeps the evidence: 152 rows quarantined, 2,876 duplicates removed and 20,130
> codes standardized. Each rule is logged, and the notebook fails if its counts drift from the governed controls.

Open `03_Gold_Star_Schema_and_KPIs` and list the Gold tables:

- `dim_date`, `dim_store`, `dim_region`, `dim_product`, `dim_category`, `dim_brand`, `dim_supplier`;
- `fact_sales`, `fact_inventory`, `fact_replenishment`;
- `inventory_current` and the `kpi_*` tables.

Open `PL_MTL_Medallion_and_ML`. **Say:** "One pipeline runs Silver, Gold, two ML notebooks and the reorder loop.
A full run takes about 25 minutes on an F16."

## 4. Machine learning in the same workspace (6 min)

Open the `mtl-sales-forecast` experiment, then the `mtl-sales-forecast-lgbm` model.

**Say**

> Data science happens next to the data. A LightGBM model forecasts daily units for all 600 store-SKU positions
> over the next 28 days, Black Friday included. At the level a merchant plans, department by day, it is
> **18.8% WAPE versus 24.4%** for a seasonal-naive baseline. That's on a holdout that includes the cold snap
> nobody saw coming. Every run, parameter and metric is in MLflow, and the model is registered.

Open `05_ML_Low_Stock_Prediction` and the `ml_stock_risk` table.

**Say**

> A second model learns, from two years of inventory snapshots, how many days a position has before it drops
> below its reorder point. It's off by about **6.8 days on average versus 9.1** for a rule of thumb. We combine it
> with the forecast and with the supply timeline, meaning DC-QC stock, open POs and each supplier's real delays.
> The result is a risk level, a predicted low-stock date and a recommended reorder quantity. Fifty positions are
> **Critical** and thirty-four are **High**. To protect them, the model recommends **3,846 units**, either
> transferred from DC-QC or expedited from the supplier.

## 5. One semantic model, one green-and-white report (5 min)

Open the report **Maison MTL Retail IQ**.

- **Executive overview:** net sales vs last year, stores, categories, the in-stock rate of 96.8%.
- **Sales performance:** seasonality by department (outerwear Nov–Jan, swimwear in summer) and the product scorecard.
- **Inventory health:** 19 positions out of stock and 95 below the reorder point; days of supply by category.
- **Forecast & stock risk (ML):** actuals vs forecast with the Black Friday spike, and the reorder recommendations.
- **Data quality & lineage:** Bronze → Silver → Gold counts, DQ actions and the model holdout metrics.

**Say**

> This is Direct Lake. The report reads the Gold Delta tables in OneLake directly, with no import copy and no
> refresh window. The measures — net sales, YoY, sell-through, days of supply, forecast, risk, pending reorders —
> are defined once and reused everywhere.

## 6. Business meaning and a bilingual AI agent (6 min)

Open `MtlRetailOntology`. Show **Store → StockRisk ← Product** and **Supplier → Product**, plus the EN/FR synonyms
(magasin, article, rupture, demande de réapprovisionnement).

**Say:** "Fabric IQ gives the business vocabulary a home. An agent doesn't need to know table names. It knows what
a store, a stock position and a reorder request are."

Open **MTL Retail IQ Advisor** and show its three sources:
- the **semantic model**, for governed sales and forecast totals and rankings;
- the **Gold lakehouse**, for stock positions, ML risk and reorder requests, with example queries;
- the **ontology**, for master data and relationships.

**Say:** "Each source does what it's best at. The agent routes the question: totals by period go to the governed
measures, and product-level stock goes to Gold SQL."

Ask:

1. `Which store had the highest net sales in the last 28 days?` → Maison MTL Montréal Centre-Ville, $459,997.
2. `What are the top 5 products by net sales in October 2026?` → a ranked table with net sales and units.
3. `How many parkas do we have in stock in Laval right now?` → 41 units.
4. `Quels produits risquent une rupture de stock cette semaine au magasin de Québec?` → 8 products at Maison MTL
   Vieux-Québec (6 Critical, 2 High), with recommended quantities, answered in French.
5. `Place a purchase order for 500 Boréale parkas for Laval and confirm the order number.` → It refuses: the agent
   is read-only and explains how to submit a reorder request. (The Fabric content filter may decline it instead;
   the app shows a friendly "can't help with that" message.)

**Say:** "The agent is evaluated on twenty questions, in English and French, from KPI lookups to store × category
filters, weekly windows and pending requests, plus a guardrail case. Each answer is checked against values computed
from Gold, and it passes all twenty."

## 7. The Fabric App: from insight to action (7 min)

Open **MTL Retail IQ** and sign in with Fabric.

1. **Overview:** the cold-snap headline, KPIs, store leaderboard and "Needs attention now".
2. **Forecast & stock risk:** filter Critical. Show the forecast band, then click **Request** on, for example,
   *Kids' Snow Boot – Montréal Centre-Ville*.
3. **Reorder requests:** the form is pre-filled with the ML quantity and the urgency. Add a note and **Submit**.
   **Say:** "The request is stored in the app's own Fabric SQL database. Only I can see my requests."
4. **Ask MTL IQ:** ask the same agent from inside the app, for example `What were total sales in Sherbrooke last
   week?` ($80,919). **Say:** "The browser
   never gets a Fabric token. A server-side function calls the agent on my behalf. If the agent can't answer, the
   app says so plainly instead of guessing."

**Close the loop** (presenter terminal, about 3 minutes):

```powershell
python app_sync.py reviews
python model.py refresh
```

Back in the app, select **Refresh** under *My reorder requests*. The status changes to **Pending buyer approval**,
with the ML risk and recommended quantity. In the report, open **Reorder requests**: the new request is there. In
**Ask MTL IQ**, ask `List the pending reorder requests submitted in the app.`

**Say**

> The Fabric SQL database behind the app replicates to OneLake automatically. Bronze reads it through a shortcut,
> Silver validates it and Gold enriches it with the ML recommendation. The same request is now visible to buyers
> in Power BI and to the agent. Operational app, analytics and AI share one copy of the data.

## 8. Wrap-up: why Fabric changes the game for Maison MTL (2 min)

- **One copy of data:** mirroring and shortcuts instead of ETL chains; Direct Lake instead of import refreshes.
- **Trust by design:** quarantine and DQ evidence, governed measures, and an ontology shared by people and AI.
- **AI where the data lives:** MLflow models next to Gold, and an agent grounded in business meaning, in French and
  English.
- **From dashboard to decision:** a secure app where store teams act, with every action flowing back into analytics.
- **Secure by design:** Entra-only SQL (optionally fully private), a least-privilege SPN, per-user policies, a read-only agent and no
  tokens in the browser.

## Likely questions

| Question | Answer |
|---|---|
| Is this real data? | No. Maison MTL is fictional, and everything is synthetic and seeded; store locations are illustrative. |
| How fresh is it? | Mirroring replicates SQL changes in near real time; the pipeline refreshes Silver, Gold and ML on demand or on a schedule. |
| Does the agent change data? | No. It is read-only and refuses to order; employees submit requests that a buyer approves. |
| What does mirroring cost? | Replication compute and its OneLake storage are included with the capacity; queries use capacity CUs. |
| How accurate is the forecast? | 18.8% WAPE at department-day (vs 24.4% baseline) on a holdout that includes an unforeseeable cold snap. |
| Can we add stores, e-commerce or weather? | Yes: add the source to mirroring or as a shortcut, extend Gold, and the ontology, report and agent inherit it. |
