# Fabric App: MTL Retail IQ

`app/` is a Rayfin Fabric App (Rayfin 1.36.x; version-locked docs ship in `node_modules/@microsoft/rayfin-guide`): an
`AppBackend` item with its own Fabric SQL database, a User Data Function and protected static hosting for a React front
end. It is the employee-facing surface of the demo, in Maison MTL green (`#00573F`) and white.

## Screens

| Tab | Content |
|---|---|
| Overview | Snapshot KPIs (net sales last 28 days and YoY, margin, in-stock, critical positions, forecast), store leaderboard, "Needs attention now" alerts with a one-click **Request** |
| Sales | Monthly trend vs last year by department; store, category and product tables |
| Inventory health | Stock status, cover by category, positions below the reorder point, store filter |
| Forecast & stock risk | Actual vs forecast with the P10–P90 band; ML risk table with predicted low-stock date, recommended quantity and a **Request** action |
| Reorder requests | Form (store, product, quantity, urgency, needed-by, note) pre-filled from the ML hint; **My reorder requests** with validation status |
| Ask MTL IQ | Chat with the Data Agent, with suggested everyday questions in English and French |
| How it works | Architecture and responsible-demo boundaries (synthetic data, read-only agent, human approval) |

## Project layout

| Path | Purpose |
|---|---|
| `rayfin/rayfin.yml` | App definition: Fabric auth only, protected static hosting, SQL data service, functions with application auth |
| `rayfin/data/*.ts` | Entities and row policies |
| `rayfin/functions/src/function_app.ts` | `askMtlAdvisor`: server-side Data Agent proxy over MCP |
| `rayfin/functions/src/advisor_helpers.ts` | Question validation, EN/FR failure detection, friendly messages |
| `rayfin/functions/fabric_config.example.ts` | Placeholder IDs; `python deploy.py app` writes the real `src/fabric_config.ts` (git-ignored) |
| `src/` | React UI (`views/`, `components/Advisor.tsx`, `services/retail.ts`, `services/requests.ts`) and tests |
| `scripts/verify-e2e.mjs` | Headless end-to-end check of the deployed app |

## Data entities

| Entity | Written by | Users can |
|---|---|---|
| `KpiSnapshot`, `StoreKpi`, `CategoryKpi`, `ProductKpi`, `MonthlyTrend`, `DemandPoint`, `StockRisk` | `app_sync.py publish`, from Gold in one transaction with read-back checks | read |
| `ReorderRequest` | Employees, from the reorder form | create and read **their own** rows (policy `claims.sub == item.user_id`); no update or delete |
| `ReorderReview` | `app_sync.py reviews`, after the medallion validates a request | read **their own** reviews |

## Authentication and security

- **Fabric sign-in only** (`services.auth.fabric`), password auth disabled. Static assets are `protected`:
  unauthenticated requests to the app URL get **401**.
- `allowedRedirectUris` contains only the local dev origins in the repository. `rayfin up` appends the deployed
  hosting origin locally; do not commit that change.
- The **browser never gets a Fabric token.** The front end calls `client.functions.askMtlAdvisor.invoke(question)`;
  the function calls the Data Agent's MCP endpoint with `ctx.Tokens.Fabric`, so the agent runs with the signed-in
  user's identity and permissions (the user needs at least read access to the workspace items).
- Until `fabric_config.ts` holds real IDs, the function answers "not configured" instead of calling anything.

## The advisor function

- One MCP call per attempt (105 s timeout), with up to 2 attempts.
- Response contract: `{ status, answer, message, agentName, ontologyName, generatedAt, attempts, readOnly: true }`
  with `status` = `answered` | `unavailable` | `invalid` | `declined`. The UI shows `answer` (Markdown) only when
  `answered`, and otherwise shows `message`.
- Failure prose from the agent ("not able to run the query", "context limit", "Je ne peux pas…") is never shown as an
  answer, and there is no fallback source that could return an unverified zero. See [AGENT.md](AGENT.md).

## Reorder write-back loop

```mermaid
sequenceDiagram
  participant E as Employee (app)
  participant DB as App SQL database
  participant OL as OneLake replica
  participant B as MTL_Bronze shortcut
  participant G as 06_Gold_Reorder_Requests
  participant S as app_sync.py reviews
  E->>DB: create ReorderRequest (own row)
  DB-->>OL: automatic replication
  OL-->>B: app_reorder_requests shortcut
  B->>G: validate store, SKU, quantity 1-1000, urgency; enrich with ML risk
  G->>G: reorder_requests (IsPending, WorkflowStatus) in Gold
  S->>DB: ReorderReview for the requester
  E->>DB: My requests shows "Pending buyer approval"
```

Run the loop with `python deploy.py loop` after the first request. Afterwards, the report's **Reorder requests** page
and the agent ("List the pending reorder requests") include the request. There is no buyer-approval UI; approval is
out of scope and the agent never approves.

## Local development

```powershell
cd app
npm ci
npm run dev:frontend          # Vite on http://localhost:5173 (uses .env.local from `rayfin env` after a deploy)
npm test                      # Vitest + Testing Library
npm run lint
npm run build                 # works with placeholder config
cd rayfin/functions
npm ci
npm test                      # builds (placeholder config is created if missing) and runs node:test
```

## Deploying

`python deploy.py app` runs `app_sync.py config`, `npm ci` (app and functions), `npx rayfin up --workspace-id <ws>
--tenant <tenant> --yes`, `app_sync.py discover` and `app_sync.py publish`. Sign in to the Rayfin CLI first with
`npx rayfin login --tenant <tenantId>` (from `app/`).

## End-to-end verification

`node scripts/verify-e2e.mjs` signs in with the Rayfin CLI's cached login and checks:

1. the hosting URL refuses unauthenticated access;
2. sign-in works;
3. the snapshot, 600 risk rows and 10 stores load;
4. the advisor answers a KPI question and five everyday questions, checked against `artifacts/agent-controls.json`;
5. unless `E2E_READ_ONLY=1`: a reorder request is created and listed for its owner only.

Headless sign-in needs `externalEntraExchange: true` under `services.auth.fabric` temporarily. See
[DEPLOYMENT.md](DEPLOYMENT.md#headless-end-to-end-check-of-the-app) for the exact procedure, and remove the flag
afterwards.
