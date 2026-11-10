// End-to-end verification of the deployed MTL Retail IQ Fabric App, using the same SDK paths as the browser.
// The delegated token comes silently from the Rayfin CLI's cached MSAL login and is never printed or written.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { signInWithEntraToken } from '@microsoft/rayfin-auth-provider-fabric';
import { RayfinClient } from '@microsoft/rayfin-client';

const here = dirname(fileURLToPath(import.meta.url));
const appDir = resolve(here, '..');
const artifacts = resolve(appDir, '..', 'artifacts');
const env = Object.fromEntries(readFileSync(resolve(appDir, 'rayfin', '.env'), 'utf8').split(/\r?\n/)
  .filter(line => line.includes('=') && !line.startsWith('#')).map(line => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)]));
const app = JSON.parse(readFileSync(resolve(artifacts, 'app.json'), 'utf8'));
const evidence = { appUrl: app.url, startedAt: new Date().toISOString(), checks: {} };

async function step(name, fn) {
  try {
    const result = await fn();
    evidence.checks[name] = { passed: true, ...result };
    console.log(`PASS ${name}`, JSON.stringify(result).slice(0, 300));
  } catch (error) {
    evidence.checks[name] = { passed: false, error: String(error?.message ?? error).slice(0, 500) };
    console.log(`FAIL ${name}`, String(error?.message ?? error).slice(0, 300));
  }
}

await step('protectedHostingRequiresSignIn', async () => {
  const response = await fetch(app.url, { redirect: 'manual' });
  const body = await response.text();
  const servesBundle = /<div id="root">/.test(body) && /assets\/index-/.test(body);
  if (servesBundle && response.status === 200) throw new Error('Static assets were served without authentication');
  return { status: response.status, location: (response.headers.get('location') ?? '').split('?')[0] };
});

const cliAuth = pathToFileURL(resolve(appDir, 'node_modules/@microsoft/rayfin-cli/dist/auth/rayfin-auth.js')).href;
const { RayfinAuth } = await import(cliAuth);
const token = await new RayfinAuth({ tenantId: env.RAYFIN_PUBLIC_TENANT_ID })
  .acquireToken(['https://analysis.windows.net/powerbi/api/Item.Execute.All'], { silentOnly: true });
const entraToken = token.accessToken ?? token.token ?? token;
const client = new RayfinClient({ baseUrl: env.RAYFIN_PUBLIC_API_URL, publishableKey: env.RAYFIN_PUBLIC_PUBLISHABLE_KEY, authStorage: false });
let user = null;

await step('signIn', async () => {
  const session = await signInWithEntraToken(client.auth, { entraToken });
  if (!session.isAuthenticated || !session.user) throw new Error('No session');
  user = session.user;
  return { user: session.user.email };
});

await step('dataLoads', async () => {
  const snapshot = (await client.data.KpiSnapshot.select(['snapshotDate', 'netSalesLast28', 'outOfStockPositions', 'criticalPositions',
    'forecastUnits28']).first(5).execute())[0];
  const risks = await client.data.StockRisk.select(['positionId', 'riskLevel']).first(2000).execute();
  const stores = await client.data.StoreKpi.select(['storeCode']).first(50).execute();
  if (!snapshot || risks.length !== 600 || stores.length !== 10) throw new Error(`Unexpected rows ${risks.length}/${stores.length}`);
  return { snapshotDate: snapshot.snapshotDate, netSalesLast28: Number(snapshot.netSalesLast28),
    outOfStockPositions: snapshot.outOfStockPositions, criticalPositions: snapshot.criticalPositions, stockRiskRows: risks.length,
    storeRows: stores.length };
});

await step('advisorAnswers', async () => {
  const started = Date.now();
  const result = await client.functions.askMtlAdvisor.invoke(
    { questionInput: 'Which store had the highest net sales in the last 28 days? Give the store name and net sales.' },
    { timeoutMs: 245_000 });
  if (result.status !== 'answered' || !/Montr[ée]al|MT-CV/.test(result.answer)) {
    throw new Error('Unexpected answer: ' + (result.answer || result.message).slice(0, 200));
  }
  return { agent: result.agentName, readOnly: result.readOnly, attempts: result.attempts,
    seconds: Math.round((Date.now() - started) / 1000), answer: result.answer.slice(0, 600) };
});

// Everyday questions that failed on 2026-11-06, checked against the deterministic Gold controls.
const controls = JSON.parse(readFileSync(resolve(artifacts, 'agent-controls.json'), 'utf8'));
const digits = value => String(Math.round(value));
const normalize = text => text.replace(/[\u2019\u2018]/g, "'").replace(/(?<=\d)[\s\u00a0\u202f,](?=\d{3}\b)/g, '').toLowerCase();
const everyday = [
  ['parkas_laval', 'How many parkas do we have in stock in Laval right now?',
    a => a.includes(digits(controls.parkasLaval.reduce((s, r) => s + r[1], 0))) || a.includes(digits(controls.parkasLaval[0][1]))],
  ['top5_products_oct', 'What are the top 5 products by net sales in October 2026?',
    a => controls.top5ProductsOct.slice(0, 3).every(r => a.includes(r[0].toLowerCase()) || a.includes(r[1].toLowerCase()))],
  ['quebec_risk_fr', 'Quels produits risquent une rupture de stock cette semaine au magasin de Québec?',
    a => controls.quebecAtRisk.filter(r => a.includes(r[0].toLowerCase()) || a.includes(r[1].toLowerCase())).length >= 5],
  ['pending_list', 'List the pending reorder requests submitted in the app.',
    a => controls.pending.length > 0 && (a.includes(controls.pending[0][2].toLowerCase()) || a.includes(controls.pending[0][3].toLowerCase()))],
  ['sherbrooke_last_week', 'What were total sales in Sherbrooke last week?',
    a => a.includes(digits(controls.sherbrooke7d)) || a.includes(digits(controls.sherbrookeCalendarWeek))],
];
const failureProse = /not able to (?:run|retrieve)|context (?:size|limit)|tool interface|ne peux pas ex[ée]cuter|limite technique/i;
for (const [key, question, ok] of everyday) {
  await step('everyday_' + key, async () => {
    const started = Date.now();
    const result = await client.functions.askMtlAdvisor.invoke({ questionInput: question }, { timeoutMs: 245_000 });
    const answer = normalize(result.answer || '');
    if (result.status !== 'answered') throw new Error(`status ${result.status}: ${result.message}`);
    if (failureProse.test(result.answer)) throw new Error('Failure prose leaked: ' + result.answer.slice(0, 200));
    if (!ok(answer)) throw new Error('Answer does not match Gold controls: ' + result.answer.slice(0, 300));
    return { question, attempts: result.attempts, seconds: Math.round((Date.now() - started) / 1000),
      answer: result.answer.slice(0, 700) };
  });
}

let created = null;
const readOnly = process.env.E2E_READ_ONLY === '1';
if (!readOnly) await step('reorderCreated', async () => {
  created = await client.data.ReorderRequest.create({
    storeCode: 'MT-CV', sku: 'W-FTW-601', productName: "Women's Waterproof Winter Boot", quantity: 84, urgency: 'Critical',
    neededBy: new Date(Date.now() + 2 * 86_400_000), note: 'E2E verification: cold snap, sizes 7-9 sold out (synthetic demo).',
    source: 'ML recommendation', recommendedQty: 84, riskLevel: 'Critical', submittedAt: new Date(),
    submittedByName: 'E2E verification', user_id: user.id,
  });
  return { id: created.id };
});

if (!readOnly) await step('reorderListed', async () => {
  const mine = await client.data.ReorderRequest.select(['id', 'storeCode', 'sku', 'quantity', 'urgency', 'user_id'])
    .orderBy({ submittedAt: 'desc' }).first(100).execute();
  const found = mine.find(r => String(r.id).toLowerCase() === String(created?.id).toLowerCase());
  if (!found) throw new Error('Created request not returned');
  if (mine.some(r => r.user_id !== user.id)) throw new Error('Per-user policy returned another user\'s request');
  return { myRequests: mine.length, found: { storeCode: found.storeCode, sku: found.sku, quantity: found.quantity } };
});

client.auth.destroy?.();
evidence.finishedAt = new Date().toISOString();
evidence.passed = Object.values(evidence.checks).every(c => c.passed);
writeFileSync(resolve(artifacts, readOnly ? 'app-e2e-readonly.json' : 'app-e2e.json'), JSON.stringify(evidence, null, 2) + '\n');
console.log(evidence.passed ? 'E2E PASSED' : 'E2E FAILED');
process.exit(evidence.passed ? 0 : 1);
