# Troubleshooting

Start with `python deploy.py check`. Every step writes its state and evidence to `artifacts/`; failed notebook runs
also write their traceback to `Files/_logs/<notebook>.txt` in the lakehouse, which `medallion.py` prints on failure.

## Azure SQL

### Public network access is forced off (Azure Policy)

**Symptom:** `ensure_server` fails with "Public network access is disabled on the server", or the network setting
reverts to *Disabled* a few minutes after you enable it.

**Cause:** many enterprise subscriptions assign a policy (often with a *Modify* or *Deny* effect) that keeps Azure
SQL servers private.

**Fix:** use the private path. Set `sql.network` to `"private"` and `sql.createServer` to `false`, point
`sql.serverName` at a server with a private endpoint, and set `privateNetwork.gatewayId` to a VNet data gateway that
can reach it ([DEPLOYMENT.md](DEPLOYMENT.md#private-network-path)). Do not try to work around the policy.

### Login failed / `CREATE USER … FROM EXTERNAL PROVIDER` fails

- You must be the server's Entra admin (or in the admin group). With `createServer: true` the deployer is set as admin.
- If the server cannot resolve the service principal in Entra (missing *Directory Readers* for the server identity),
  the scripts fall back to `CREATE USER … WITH SID = <appId>, TYPE = E`, which needs no directory lookup.
- Error 18456 from Python: run `az login --tenant <tenantId>`; tokens come from the subscription in `config.json`.

### Serverless database is paused

**Symptom:** the first connection times out or reports error 40613 ("database is not currently available").

**Cause:** the serverless database auto-pauses after `sql.autoPauseDelayMinutes`.

**Fix:** nothing. `fabric.sql_connect` retries transient errors for several minutes while the database resumes.
Mirroring stays *Running* while the database is paused and picks up changes once it is active again.

### ODBC driver missing

Install *ODBC Driver 18 for SQL Server*. `deploy.py check` verifies it.

## Mirroring

### Connection creation fails or tables stay "Initializing"

- **Public mode:** the server must have *Allow Azure services and resources to access this server*
  (`AllowAllWindowsAzureIps`), which `seed` adds. Check with `python azure_sql.py status`.
- **Private mode:** the VNet data gateway must resolve `<server>.database.windows.net` to the private endpoint IP:
  link the private DNS zone `privatelink.database.windows.net` to the gateway's VNet. The deployer must be an admin
  or user of the gateway.
- The server's system-assigned managed identity must be enabled, and it must be a Contributor on the workspace (the
  `identity` step does this).
- The connection test can fail for a minute after a new client secret is created; `mirror.py` retries six times.

### Mirroring is stopped or paused

Run `python mirror.py start` then `python mirror.py status`. If a table shows *Failed*, check that the table still has
a primary key and that the service principal still has `ALTER ANY EXTERNAL MIRROR`. A paused Fabric capacity stops
replication; it resumes when the capacity resumes.

### The connection secret expired

The connection's client secret lasts `mirroring.secretLifetimeDays` (180 by default). `python spn.py credentials`
lists expiry dates. Mint a new secret and update the connection credentials in Fabric (*Manage connections and
gateways*), or delete the connection and `artifacts/connection.json` and run `python deploy.py mirror`.

## Private seed load

- **Managed private endpoint stuck in *Pending*:** the deployer needs rights to approve private endpoint connections
  on the server. `seed_loader.py mpe` approves the one whose description contains "Maison MTL"; approve it manually
  in the portal if needed and re-run `python deploy.py seed`.
- **Spark session is slow to start:** expected in the loader workspace, which has a managed VNet. The demo workspace
  never gets a managed private endpoint, so it keeps starter pools.
- **Loader workspace left behind:** run `python seed_loader.py cleanup`, or `python deploy.py teardown` (it deletes a
  leftover loader workspace).

## Medallion and ML

- **Pipeline activity failed:** open the pipeline run in Fabric to see which notebook failed, or run that notebook
  alone with `python medallion.py silver|gold|forecast|stock|reorders`, which prints its traceback from
  `Files/_logs`. Notebook assertions compare row counts and KPIs with `artifacts/expected.json`; a mismatch usually
  means the mirror had not finished replicating. Check `python mirror.py verify`, then run
  `python deploy.py all --from medallion`.
- **LightGBM import error:** the notebooks fall back to scikit-learn HistGradientBoosting and register `-hgb` models.

## Semantic model, report and ontology

- **DAX verification fails with 401/403:** enable the *Semantic model Execute Queries REST API* tenant setting.
- **New Gold tables missing from the model or the agent:** the SQL endpoint metadata sync can lag behind the
  pipeline. Run `python -c "import model; model.refresh_sql_endpoint()"`, then `python deploy.py model`.
- **Ontology deploy fails with "ValueType is immutable":** a property ID was reused with another type. IDs derive from
  column ordinals in the full Gold table; keep `ontology.py` unchanged or delete and recreate the ontology.
- **Graph refresh takes long:** 5–15 minutes is normal; `python ontology.py ready` polls without starting a new refresh.

## Data Agent

### Cold start

The first question after a deployment, or after the capacity resumes, can take 60 seconds or more or fail once. The
app's function retries once. Ask a warm-up question before a demo.

### "Context size exceeded", "tool interface is failing", "not able to run the query"

These come from the agent's query tools when the prompt is too large or a generated query fails. This deployment
avoids them by design:

- aggregations are routed to the semantic model and stock and reorder lists to Gold SQL with few-shots;
- the agent's ontology source is limited to 6 entities, and ontology bindings to business properties;
- instructions are kept to about 3.3K characters.

If you extend the agent, keep these limits. Add few-shots to `FEWSHOTS` rather than long instructions, and run
`python agent.py evaluate`. In the app, such failures appear as a friendly "couldn't retrieve the data" message, never
as an answer. See [AGENT.md](AGENT.md#lessons-learned).

### The evaluation scores 18 or 19 out of 20

Answers are LLM-generated. Re-run the failing cases with `python agent.py evaluate --label retry --only <id>`, and
inspect the raw MCP response in `artifacts/agent-eval/`. `python agent.py rescore --label <label>` re-applies the
checks to saved answers without calling the agent.

### "There's content here I can't work with"

That is the Fabric content filter declining the request (typical for the purchase-order guardrail). The evaluation
accepts it as a refusal and the app shows a friendly `declined` message.

### Few-shot validation fails in `configure`

Every example query must run on the Gold SQL endpoint and use only the columns exposed in `LAKEHOUSE_COLUMNS`. Run
`python agent.py fewshots` to see which one fails. Queries on `reorder_requests` may return no rows on a fresh
deployment.

## Fabric App

### Headless E2E fails with "External Entra exchange is not enabled"

That is expected: the app normally accepts interactive Fabric sign-in only. Temporarily add
`externalEntraExchange: true` under `services.auth.fabric` in `app/rayfin/rayfin.yml`, run `python deploy.py app`, run
`node scripts/verify-e2e.mjs`, then remove the flag and deploy again. Confirm that the app URL returns 401 without
sign-in.

### `rayfin up` asks to sign in or fails with an auth error

Run `npx rayfin login --tenant <tenantId>` from `app/` (`npx rayfin login status` shows the account). Use
`--encryption-fallback-enabled` only on systems without an OS keychain.

### The advisor says it is "not configured yet"

`app/rayfin/functions/src/fabric_config.ts` still has placeholder IDs. Run `python deploy.py app`; it regenerates the
file from `artifacts/agent.json`, `artifacts/ontology.json` and the agent's MCP tool list, then redeploys.

### The app shows no data

Run `python app_sync.py status`. If the snapshot tables are empty, run `python app_sync.py publish` (it needs
`artifacts/app.json`, written by `python app_sync.py discover`).

### `npm ci` fails with `EALLOWREMOTE` or 401 from a registry

The lockfiles resolve packages from `registry.npmjs.org`. If your machine must use a private registry or proxy,
configure it with `npm config set registry <url>`. npm rewrites the default registry host automatically.

## Teardown

- **Dry run first:** `python deploy.py teardown` prints the plan without deleting anything.
- **Interrupted teardown:** re-run it; deleted resources are skipped.
- **Resource group kept:** teardown deletes a resource group only when the deployment created it and it is empty.
