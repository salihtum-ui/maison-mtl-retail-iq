# Deployment

This guide deploys Maison MTL Retail IQ into your own tenant. Every step is scripted, idempotent and verified.
Non-secret state (item IDs, evidence) is written to `artifacts/`, which is git-ignored. Delete nothing in it while a
deployment exists: it is how re-runs resume and how teardown knows what it created.

## Prerequisites

### Fabric

| Requirement | Notes |
|---|---|
| Paid F-SKU capacity, **Active** | Tested on F16. The Data Agent needs a paid capacity (F2 or higher; F8+ recommended for Spark and ML). |
| Capacity Contributor or Admin | Needed to create the workspace on the capacity. |
| Tenant setting: *Users can create Fabric items* | Lakehouses, notebooks, pipeline, ML items, mirrored database. |
| Tenant setting: *Mirroring* (Mirrored databases) | On by default in most tenants. |
| Tenant settings: *Copilot and Azure OpenAI Service* | Required by the Data Agent. If your capacity's region has no Azure OpenAI, also allow data to be processed outside the capacity's geography. |
| Tenant setting: *Data agent* (preview) | Create and share Data Agent items, including the MCP endpoint used by the app and the evaluation. |
| Tenant settings: *Ontology* and *Graph* (Fabric IQ, preview) | Create the ontology and its managed graph. |
| Tenant settings: *Fabric Apps* / *User data functions* (preview) | Deploy the Rayfin App backend, its SQL database and function. |
| Tenant setting: *Semantic model Execute Queries REST API* | `model.py verify` runs DAX controls through the REST API. |
| Tenant setting: *Export reports as image files* | Optional: only for `python report.py verify`, which renders the report pages to PNG. `deploy.py` skips the renders. |
| Private mode only: managed private endpoints and a VNet data gateway | See [Private network path](#private-network-path). |

Setting names change while features are in preview; search the admin portal for the feature name.

### Azure and Entra ID

| Requirement | Notes |
|---|---|
| Azure subscription and a user account | The deployer signs in with `az login`. Service-principal deployers are not supported, because the deployer becomes the SQL server's Entra admin. |
| Public mode with `createServer: true` | Contributor on the subscription or on the target resource group (the group is created if missing). |
| Existing server | You must be the server's **Entra admin** (or a member of the admin group) so you can create the contained user for mirroring. The server needs a **system-assigned managed identity**. |
| App registration | Users can register applications (default), or the Application Developer role. The service principal only signs in to Azure SQL. |
| Resource providers | `Microsoft.Sql`; private mode also `Microsoft.Network` and `Microsoft.PowerPlatform`. |

### Tools

| Tool | Tested version |
|---|---|
| Python | 3.14 (3.12+ works) with `pip install -r requirements.txt` (`pyodbc`, `httpx`, `mcp` 1.x) |
| ODBC Driver 18 for SQL Server | 18.x |
| Azure CLI | 2.92 |
| Node.js / npm | 26 / 12 (Node 20+ and npm 10+ work) |
| Rayfin CLI | 1.36.x, from `app/package.json` via `npx rayfin` |

If your organization uses a private npm registry or proxy, keep it configured. The lockfiles reference
`registry.npmjs.org`, and npm rewrites that host to your configured registry (`replace-registry-host` default).

## Configuration

```powershell
copy config.example.json config.json
python settings.py        # prints any problems; exit code 0 when valid
```

`config.json` is git-ignored. Set `MTL_CONFIG=<path>` to use another file, for example one per environment.

| Field | Default | Description |
|---|---|---|
| `tenantId` | (required) | Entra tenant ID. Azure CLI tokens are checked against it. |
| `subscriptionId` | (required) | Subscription for the SQL server; also selects the Azure CLI account. |
| `fabric.capacityId` | (required) | Fabric capacity ID (Admin portal → Capacity settings, or `GET /v1/capacities`). |
| `fabric.workspaceName` | `Maison MTL Retail IQ` | Must not already exist (the deployment refuses to adopt an untracked workspace). |
| `fabric.loaderWorkspaceName` | `Maison MTL Seed Loader` | Private mode only; created and deleted during the seed load. |
| `sql.network` | `public` | `public` or `private`; see [Choosing the network path](../README.md#choosing-the-network-path). |
| `sql.resourceGroup` | `rg-maison-mtl-retail-iq` | Resource group of the SQL server. |
| `sql.serverName` | (required) | Logical server name (globally unique, lowercase). |
| `sql.location` | `canadacentral` | Region used when creating the resource group and server. |
| `sql.createServer` | `true` | Public mode only: create the resource group and an Entra-only server if missing. |
| `sql.database` | `mtl_retail` | Database name. |
| `sql.autoPauseDelayMinutes` | `60` | Serverless auto-pause delay (minimum 60). |
| `privateNetwork.gatewayId` | (private mode) | ID of the VNet data gateway that can reach the server's private endpoint. |
| `mirroring.servicePrincipalName` | `sp-fabric-mirror-mtl-retail` | Display name of the app registration created for mirroring. |
| `mirroring.connectionName` | `Maison MTL Retail IQ - mtl_retail` | Fabric connection display name. |
| `mirroring.secretLifetimeDays` | `180` | Lifetime of the connection's client secret; rotate before it expires. |

## Sign in

```powershell
az login --tenant <tenantId>
az account set --subscription <subscriptionId>      # optional; scripts always pass --subscription
cd app; npm ci; npx rayfin login --tenant <tenantId>; cd ..
```

All REST calls use Azure CLI tokens (`az account get-access-token --subscription <subscriptionId>`). The Rayfin CLI
keeps its own login for `rayfin up`.

## Deploy

```powershell
python deploy.py check     # read-only: config, tools, ODBC driver, sign-in, capacity, gateway (private mode)
python deploy.py all       # every step below; skips steps already recorded in artifacts/deploy-progress.json
```

Useful variations:

```powershell
python deploy.py list                    # steps and descriptions
python deploy.py all --from medallion    # re-run from a step onwards
python deploy.py model report            # re-run selected steps
```

### Steps and expected outputs

Times are indicative on an F16 capacity.

| # | Step | What it does | Expected output (abridged) | Time |
|---|---|---|---|---|
| 1 | `check` | Validates config, tools, ODBC driver, token tenant, capacity state, gateway | `capacity: {name, sku: F16, region}`; private mode also `gateway` | < 1 min |
| 2 | `spn` | Creates app registration `sp-fabric-mirror-mtl-retail` and its service principal | `{appId, displayName}` | < 1 min |
| 3 | `sql` | Creates (public + `createServer`) the resource group and Entra-only server with a system-assigned identity, then database `mtl_retail` (serverless GP_S_Gen5_1) | `{name: mtl_retail, sku: GP_S_Gen5, autoPauseDelay: 60, createdByDeploy: true}` | 3–8 min |
| 4 | `workspace` | Creates the workspace on the capacity and lakehouses `MTL_Bronze`, `MTL_Silver`, `MTL_Gold` | `{workspace, lakehouse_bronze, lakehouse_silver, lakehouse_gold}` | 1 min |
| 5 | `identity` | Grants the SQL server's managed identity Contributor on the workspace | `role: Contributor` | < 1 min |
| 6 | `seed` | **public:** firewall rule for your IP, bulk load with Entra auth, contained user for the service principal, verification, rule removed. **private:** loader workspace + managed private endpoint (auto-approved), seed notebook, verification, endpoint and loader workspace deleted | rows `stores 11, suppliers 8, products 63, sales_daily 243,893, inventory_daily 483,268, replenishment_orders 27,901`; clean 2025 net sales `24,899,159.2` | 10–25 min |
| 7 | `mirror` | Creates the connection (cloud or gateway), the mirrored database `MtlRetail_MirroredSQL`, starts replication and compares row counts on its SQL endpoint | status `Running`, six tables `Replicating`, `matches: true` | 5–15 min |
| 8 | `medallion` | Bronze shortcuts, five notebooks, pipeline `PL_MTL_Medallion_and_ML`, one pipeline run | `shortcuts: [6 tables]`, `run: Completed` | 25–45 min |
| 9 | `model` | Direct Lake model, refresh, DAX controls | all controls pass (net sales last 28 days 3,010,708; 19 out of stock; …) | 2–4 min |
| 10 | `report` | Six-page report, definition read-back, executes every visual binding | 6 pages, all bindings executed (run `python report.py verify` to also render PNGs to `artifacts/report-pages/`) | 2–4 min |
| 11 | `ontology` | `MtlRetailOntology` (15 entities, 18 relationships, 118 bound properties), graph refresh | graph refresh `Completed` | 5–15 min |
| 12 | `agent` | Data Agent: attaches the model, Gold lakehouse and ontology, tunes tables and columns, instructions and 15 few-shots, publishes, lists MCP tools | `publishedSources: [lakehouse_tables, ontology, semantic_model]`, `fewShots: 15`, `mcpTools: [DataAgent_MTL_Retail_IQ_Advisor]` | 2–5 min |
| 13 | `app` | Generates `fabric_config.ts`, `npm ci`, `rayfin up`, discovers the app's SQL database, publishes the Gold snapshot | `url: https://<name>.webapp.fabricapps.net`, rows `StoreKpi 10, ProductKpi 60, StockRisk 600, …` | 5–10 min |
| 14 | `evaluate` | 20 MCP questions checked against values computed from Gold | `passed: 20, total: 20` (18+ is normal: answers are LLM-generated) | 8–12 min |

`rayfin up` appends the deployed hosting URL to `allowedRedirectUris` in `app/rayfin/rayfin.yml`. Keep that local
change out of commits; teardown removes it.

### After the deployment: the closed loop

1. Open the app URL (`artifacts/app.json`), sign in with Fabric, go to **Forecast & stock risk**, select **Request**
   on a Critical position and submit the form.
2. Run `python deploy.py loop`. It creates the Bronze shortcut to the app's replicated `ReorderRequests` table (the
   first time), runs `06_Gold_Reorder_Requests`, writes the review back to the app and refreshes the model and the
   ontology graph. The first replication to OneLake can take a few minutes; the step retries for up to 10 minutes.
3. In the app, **My reorder requests** shows *Pending buyer approval*; the report's **Reorder requests** page and the
   agent ("List the pending reorder requests") show it too.

### Refreshing data

The pipeline is on demand. After `python deploy.py medallion` (or a manual pipeline run), refresh the downstream
layers with `python deploy.py model ontology` and `python app_sync.py publish`.

## Private network path

Use `sql.network: "private"` when the server must not accept public traffic.

You provide:

1. An Azure SQL logical server with Entra-only authentication, you as Entra admin, a **system-assigned managed
   identity**, public network access disabled and a **private endpoint** with private DNS
   (`privatelink.database.windows.net`).
2. A Fabric **VNet data gateway** on a subnet that can resolve and reach that private endpoint (subnet delegated to
   `Microsoft.PowerPlatform/vnetaccesslinks`, created in Fabric under *Manage connections and gateways → Virtual
   network data gateways*). Put its ID in `privateNetwork.gatewayId`, and make sure you are an admin or user of it.
3. Rights to approve private endpoint connections on the server (Contributor on the server).

Set `sql.createServer` to `false`. The `seed` step then creates the loader workspace, a managed private endpoint
named `mpe-mtl-retail-sql`, approves the pending connection (its description contains "Maison MTL"), runs the seed
notebook as you, verifies the load, and deletes the endpoint and the loader workspace. Mirroring connects through the
gateway with the service principal.

## Headless end-to-end check of the app

`app/scripts/verify-e2e.mjs` uses the Rayfin CLI's cached login. Rayfin only accepts an external Entra token when the
app allows it, so enable it temporarily:

1. Add `externalEntraExchange: true` under `services.auth.fabric` in `app/rayfin/rayfin.yml` and run
   `python deploy.py app`.
2. `cd app; $env:E2E_READ_ONLY='1'; node scripts/verify-e2e.mjs` (omit `E2E_READ_ONLY` to also create and list a
   reorder request). Evidence goes to `artifacts/app-e2e*.json`.
3. Remove the flag and run `python deploy.py app` again. Unauthenticated requests to the app URL must return 401.

## Module commands

Each module also has its own CLI for targeted work, for example `python mirror.py status`, `python model.py verify`,
`python agent.py evaluate --only quebec_risk_fr pending_count`, `python app_sync.py status`.

## Teardown

```powershell
python deploy.py teardown            # dry run
python deploy.py teardown --yes      # delete
python deploy.py teardown --yes --keep-sql
```

See [README.md](../README.md#cleanup). Teardown never deletes a server, resource group or database it did not create.
If it was interrupted, re-run it; each action tolerates resources that are already gone.
