# Architecture

Maison MTL Retail IQ is one Fabric workspace plus one Azure SQL database. Everything the business sees, from the
report and the agent to the app, reads the same Gold Delta tables in OneLake.

## Components

| Layer | Fabric / Azure item | Created by |
|---|---|---|
| Source | Azure SQL Database `mtl_retail` (serverless GP Gen5, Entra-only auth, system-assigned identity on the server) | `azure_sql.py` |
| Seed (private mode only) | Throwaway workspace *Maison MTL Seed Loader* with a lakehouse, a managed private endpoint and notebook `00_Seed_mtl_retail_Azure_SQL`; deleted after the load | `seed_loader.py` |
| Identity | Entra app `sp-fabric-mirror-mtl-retail`: contained database user with the mirroring permissions only | `spn.py`, `azure_sql.py` / seed notebook |
| Ingestion | Fabric connection (cloud or VNet gateway) and mirrored database `MtlRetail_MirroredSQL` | `mirror.py` |
| Bronze | Lakehouse `MTL_Bronze`: OneLake shortcuts to the six mirrored tables and to the app's `ReorderRequests` table, no copies | `medallion.py` |
| Silver | Lakehouse `MTL_Silver`: notebook `02_Silver_Cleanse_and_Conform` writes clean tables, `dq_events` and `dq_quarantine` | `nb_silver.py` |
| Gold | Lakehouse `MTL_Gold`: notebook `03_Gold_Star_Schema_and_KPIs` builds dimensions, facts and KPI tables | `nb_gold.py` |
| ML | Notebooks `04_ML_Sales_Forecast` and `05_ML_Low_Stock_Prediction`, MLflow experiments `mtl-sales-forecast` and `mtl-low-stock-prediction`, ML models `mtl-sales-forecast-lgbm` and `mtl-low-stock-days-lgbm` | `nb_ml_*.py` |
| Closed loop | Notebook `06_Gold_Reorder_Requests`: validates app requests, enriches them with ML risk, publishes `stock_risk_this_week` | `nb_reorders.py` |
| Orchestration | Data pipeline `PL_MTL_Medallion_and_ML` (Silver → Gold → forecast → low-stock → reorders) | `medallion.py` |
| Semantic | Direct Lake model `Maison MTL Retail IQ Model` (16 tables, governed measures, Q&A indexing, column descriptions) | `model.py` |
| BI | Report `Maison MTL Retail IQ` (six pages, green and white theme `MaisonMtlGreen`) | `report.py` |
| Knowledge | Fabric IQ ontology `MtlRetailOntology` (15 entities, 18 relationships, EN/FR synonyms) and its managed graph | `ontology.py` |
| AI | Data Agent `MTL Retail IQ Advisor` with three sources: semantic model, Gold lakehouse, ontology | `agent.py` |
| App | Rayfin Fabric App `mtl-retail-iq` (AppBackend item with its own Fabric SQL database, User Data Function and protected static hosting) | `app/`, `app_sync.py` |

## Data flow

1. **Operational source.** `mtl_data.py` generates two years of daily sales, inventory snapshots and replenishment
   orders for 10 stores and a distribution centre. The raw tables deliberately include defects such as duplicates,
   inconsistent codes, negative or null quantities and orphan keys. Every table has a primary key, which mirroring
   requires.
2. **Mirroring.** Fabric replicates the six tables to OneLake as Delta through the connection, authenticated by the
   dedicated service principal. The SQL server's managed identity is a Contributor on the workspace.
3. **Bronze.** Shortcuts expose the mirrored tables without copying them.
4. **Silver.** Standardizes codes and casing, quarantines invalid rows, removes duplicates, enforces types and keys,
   and records every rule that fired in `dq_events`.
5. **Gold.** Builds the star schema, the current stock position per store and SKU, and the KPI tables, and asserts
   the governed controls (see [DATA_MODEL.md](DATA_MODEL.md)).
6. **ML.** Forecasts 28 days of units for all 600 store × SKU positions and predicts when each position will fall
   below its reorder point. Outputs land in Gold (`ml_*` tables, `stock_risk_this_week`).
7. **Semantic layer.** The Direct Lake model reads Gold directly. The ontology binds business entities to Gold
   tables, and its managed graph is refreshed after each pipeline run.
8. **Consumption.** The report, the agent and the app all read Gold-derived data. The app's read-only entities are
   refreshed from Gold by `app_sync.py publish` in one transaction.
9. **Action and write-back.** A reorder request is written to the app's SQL database. That database replicates to
   OneLake automatically, Bronze reads it through a shortcut, `06_Gold_Reorder_Requests` validates and enriches it,
   and `app_sync.py reviews` writes the outcome back to the requester. The report and the agent see the request too.

## Security model

- **Least privilege for ingestion.** The mirroring service principal has `SELECT`, `ALTER ANY EXTERNAL MIRROR`,
  `VIEW DATABASE PERFORMANCE STATE` and `VIEW DATABASE SECURITY STATE` on `mtl_retail` only. Its secret is never
  written to disk.
- **Entra-only SQL.** No SQL logins. The deployer is the server's Entra admin (when the deployment creates the
  server) and loads data with an access token.
- **Network.** In public mode the deployer's firewall rule exists only during the load. In private mode the server
  never opens to the internet: the seed load uses a managed private endpoint in a separate, deleted workspace, and
  mirroring uses the VNet data gateway.
- **Scoped automation.** `fabric.py` refuses any write outside the tracked workspace, any workspace creation other
  than the configured one, and any delete outside an explicit teardown.
- **App.** Static hosting is protected (sign-in required). Entities use per-user row policies: a user creates and
  reads only their own reorder requests and reviews. The browser never holds a Fabric token. The agent proxy runs
  server-side with `ctx.Tokens.Fabric`.
- **Read-only AI.** The agent instructions forbid placing, approving or changing orders; employees use the reorder
  form instead, and a buyer approves.

## Design decisions

- **Direct Lake over import:** no refresh windows; the report reflects Gold as soon as the pipeline finishes.
- **Three agent sources with routing:** the semantic model answers aggregations with governed measures, the Gold
  lakehouse answers product-level stock, risk and reorder lists with validated example queries, and the ontology is
  limited to master data and relationships. An ontology-only agent exceeded the model context on everyday questions
  (see [AGENT.md](AGENT.md#lessons-learned)).
- **`stock_risk_this_week` table:** "at risk" questions become a structural lookup instead of depending on the agent
  writing the right `RiskLevel` filter.
- **Separate loader workspace (private mode):** a managed private endpoint gives a workspace a managed VNet
  permanently, which disables Spark starter pools. Keeping it out of the demo workspace preserves fast notebook starts.
- **Rayfin app with its own SQL database:** the operational write path (reorder requests) is transactional and
  per-user, and still lands in OneLake without any extra integration.
