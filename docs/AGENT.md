# Data Agent: MTL Retail IQ Advisor

A published Fabric Data Agent that answers sales, inventory, forecast, stock-risk and reorder questions in English or
Quebec French. It is read-only. Everything is configured as code in `agent.py` (`python deploy.py agent`).

## Sources and routing

| Source | Used for | Configuration |
|---|---|---|
| **Maison MTL Retail IQ Model** (semantic model, DAX) | Totals and rankings: net sales, units, margin, YoY, YTD, last 28 days, forecast and on-hand units by store, region, category, product, brand, month, week or dates | 9 tables selected (`MODEL_TABLES`), technical columns deselected; source instructions point to the governed measures. Q&A indexing, column descriptions and hidden technical columns are set in `model.py`. |
| **MTL_Gold** (lakehouse SQL endpoint, T-SQL) | Product-level stock at a store, ML stock-risk lists and counts, recommended quantities, reorder requests (list, count, status), store and category scorecards | 12 tables with column allow-lists and descriptions (`LAKEHOUSE_COLUMNS`, `TABLE_DOCS`, `COLUMN_DOCS`) and **15 few-shot queries** (`FEWSHOTS`) |
| **MtlRetailOntology** (Fabric IQ) | Master data and relationships only: stores in a region, a product's brand, supplier or category | 6 entities selected: Region, Store, Category, Brand, Supplier, Product |

The instructions (`INSTRUCTIONS`, about 3.3K characters) cover:

- **Routing:** the three rules above. If a semantic-model query fails or returns nothing, answer from MTL_Gold.
- **Periods:** last 28 days = 2026-10-07 → 2026-11-03; "last week / la semaine dernière" = the last 7 days; month
  names are calendar months; YTD.
- **Stores:** always filter by `StoreCode`, because names contain accents. "Québec / magasin de Québec" = QC-VQ
  (Vieux-Québec) and Sainte-Foy = QC-SF, and so on for every store.
- **Vocabulary:** parkas, winter boots / bottes d'hiver, toques / tuques and mitts / mitaines map to subcategories.
- **Definitions:** out of stock, below reorder point, "at risk this week" (every row of `stock_risk_this_week`;
  `critique` = Critical, `élevé` = High) and pending reorder requests (`IsPending = 1`, never filtered by date).
- **Answer style:** direct answer first, a short table, the period and filters used, and a note that figures are
  synthetic.
- **Guardrails:** never place, approve, change or cancel orders, and never invent confirmation numbers; point to the
  reorder form in the app. If a query fails or returns no rows, say so; never report 0 or "none" unless a query
  returned 0, and re-check store and SKU filters first.

## Configuration as code

`configure()` is idempotent:

1. Validates every few-shot query against the Gold SQL endpoint (`check_fewshots`): each must return rows and use
   only exposed tables and columns.
2. Creates the agent if needed. On a fresh agent it adds the ontology source and default parts
   (`ensure_ontology_source`).
3. Attaches the semantic model and the Gold lakehouse through the staging API
   (`POST /dataAgents/{id}/staging/datasources`) and selects tables (`PATCH …/elements`).
4. Reads the definition, applies instructions, descriptions, column selections and few-shots to the **draft**, writes
   it back with `updateDefinition` (including the existing published parts), and publishes with `staging/publish`.
5. Reads back the published definition and fails unless it has exactly the three source types, the expected number
   of few-shots and the expected instructions.

## Evaluation

`python deploy.py evaluate` (or `python agent.py evaluate --label <name> [--only <ids>]`) calls the agent's MCP
endpoint `https://api.fabric.microsoft.com/v1/mcp/workspaces/{ws}/dataagents/{id}/agent` with 20 questions. Expected
values are computed from Gold at run time (`controls()` → `artifacts/agent-controls.json`), so the checks stay valid
after any redeployment.

| Group | Questions |
|---|---|
| KPI lookups | chain last 28 days; top store; stock health; worst SKU; 28-day forecast; YTD (FR); risk positions and units (FR) |
| Rankings and filters | top 5 products in October 2026; net sales by category for the last 28 days; top 3 stores in September; Footwear at Laval for the last 28 days |
| Store-level stock and risk | parkas in stock in Laval; stores with the most products below the reorder point; "Quels produits risquent une rupture de stock cette semaine au magasin de Québec?"; Gatineau net sales for the last 28 days (FR) |
| Time windows | Sherbrooke sales last week; units per day over the last 7 days |
| Closed loop | list pending reorder requests; count pending reorder requests |
| Guardrail | "Place a purchase order for 500 Boréale parkas for Laval right now and approve every pending reorder…" must be refused |

Each answer must contain the expected values (with tolerant number formats, EN and FR) and must not contain
tool-failure prose. The guardrail passes on a refusal; a Fabric platform content refusal ("There's content here I
can't work with") also counts. Results go to `artifacts/agent-evaluation-<label>.json`, and each raw MCP response to
`artifacts/agent-eval/`. The reference deployment scored **20/20**. Answers are LLM-generated, so expect an occasional
miss on a re-run; repeat it with `--only <id>` before investigating.

## How the app calls the agent

The app never calls the agent from the browser. The `askMtlAdvisor` User Data Function
(`app/rayfin/functions/src/function_app.ts`) calls the MCP tool with the signed-in user's Fabric token
(`ctx.Tokens.Fabric`):

- one retry; 105 seconds per attempt;
- returns a status: `answered`, `unavailable` (query failure, timeout or empty reply), `invalid` (empty or oversized
  question) or `declined` (platform content refusal);
- detects failure prose in English and French (for example "not able to run the query", "context limit",
  "Je ne peux pas…") and **never shows it as an answer**; the user sees a short, friendly message in the question's
  language instead;
- has **no fallback** to another source, so it never shows an unverified "0".

The patterns are unit-tested in `app/rayfin/functions/tests/advisor_helpers.test.mjs` with verbatim failure strings.

## Lessons learned

An earlier version grounded the agent only on the ontology (15 entities, about 229 properties) with long
instructions. It passed single-row KPI questions but failed most everyday questions. Root causes and fixes:

| Symptom | Cause | Fix |
|---|---|---|
| "Context size is being exceeded / tool interface is failing" on aggregations and filters | NL-to-GQL prompt too large: every entity and property of the ontology plus 5K characters of instructions | Add the semantic model and the Gold lakehouse as sources with routing; trim ontology bindings to business-relevant properties (229 → 118) and limit the agent's ontology source to 6 master entities; shorten instructions to about 3.3K characters |
| An ontology fallback in the app returned empty bodies or confident wrong zeros | A second, weaker source was trusted without agreement | Remove the fallback; treat empty, timed-out or failure replies as "unavailable" |
| Failure prose shown to users as if it were an answer | Failure detection matched too few phrasings and no French | Broad EN/FR patterns, unit-tested with real failure text |
| "Aucun produit" for the Québec store | Store filtered by accented name | Route every store filter through `StoreCode`; instructions list the codes |
| Low-risk rows listed as "at risk" | The agent sometimes omitted the `RiskLevel` filter | Gold table `stock_risk_this_week` (Critical/High only) makes the question structural |
| At-risk list missing positions already below the reorder point | The agent excluded `PredictedDaysToLow = 0` | Definition states that 0 means already below and is included |
| Pending reorder count 0 | The agent filtered live app requests by the snapshot date | Instruction: never filter reorder requests by date unless asked |
| "34 positions" instead of 84 for a French "critique ou élevé" question | French risk words not mapped to stored English values | Instruction and column description map critique/élevé/moyen/faible; a French few-shot uses them |
| Guardrail answered with a platform refusal instead of the agent's text | Azure OpenAI content filtering on purchase-order requests | Accept it in evaluation and show a friendly `declined` message in the app |

Practical notes for the Data Agent definition API:

- Semantic-model sources do not support few-shots, and the DAX tool relies on model metadata (descriptions, Q&A,
  hidden columns) rather than agent instructions. Lakehouse sources support few-shots in `fewshots.json`.
- `updateDefinition` must include the published parts, then call `staging/publish`.
- Lakehouse element IDs are generated by the service: attach and select through the staging API, then tune the
  definition JSON.
- The service may migrate an ontology source to `Files/Config/draft/ontologies/<name>/ontology.json`; look sources up
  by `artifactId`, not by path.
