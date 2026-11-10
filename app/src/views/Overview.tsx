import { BarList } from '@/components/charts';
import { compactMoney, money, pct, signedPct, units } from '@/lib/format';
import type { RetailData } from '@/services/retail';

import type { ReorderPrefill } from './Reorders';

type Props = {
  data: RetailData;
  onNavigate: (tab: 'sales' | 'inventory' | 'forecast' | 'reorders' | 'advisor') => void;
  onReorder: (value: ReorderPrefill) => void;
};

export function Overview({ data, onNavigate, onReorder }: Props) {
  const s = data.snapshot;
  const inStock = s ? 100 * (1 - s.outOfStockPositions / Math.max(1, s.positions)) : undefined;
  const urgent = [...data.risks].filter(r => r.riskLevel === 'Critical' || r.riskLevel === 'High')
    .sort((a, b) => a.riskRank - b.riskRank || Number(b.onHandUnits === 0) - Number(a.onHandUnits === 0) ||
      (a.predictedDaysToLow ?? 99) - (b.predictedDaysToLow ?? 99) || b.recommendedReorderQty - a.recommendedReorderQty).slice(0, 6);
  const growth = [...data.categories].filter(c => c.last28GrowthPct !== undefined)
    .sort((a, b) => (b.last28GrowthPct ?? 0) - (a.last28GrowthPct ?? 0)).slice(0, 5);
  return (
    <>
      <section className="hero">
        <div>
          <span className="eyebrow">MAISON MTL · QUEBEC STORES · SYNTHETIC DEMO</span>
          <h1>Sales are up {signedPct(s?.last28GrowthPct)} — winter demand is outpacing stock.</h1>
          <p>An early cold snap lifted outerwear, winter boots and cold-weather accessories. Fabric mirrors the store
            systems, cleans the data, forecasts the next 28 days and flags positions to reorder before they run out.</p>
        </div>
        <div className="snapshot">
          <span>Data through</span><strong>3 Nov 2026</strong><small>Forecast to 1 Dec 2026</small>
        </div>
      </section>
      <section className="kpi-grid">
        <Kpi label="Net sales · last 28 days" value={compactMoney(s?.netSalesLast28 ?? 0)} note={`${signedPct(s?.last28GrowthPct)} vs same 28 days LY`} tone="good" />
        <Kpi label="Net sales · YTD" value={compactMoney(s?.netSalesYTD ?? 0)} note={`${signedPct(s?.ytdGrowthPct)} vs 2025 YTD`} tone="good" />
        <Kpi label="Gross margin · 28 days" value={pct(s?.grossMarginPctLast28)} note={`${units(s?.unitsLast28)} units sold`} />
        <Kpi label="In-stock" value={pct(inStock)} note={`${s?.outOfStockPositions ?? 0} positions out of stock`} tone="risk" />
        <Kpi label="Critical + high risk" value={units((s?.criticalPositions ?? 0) + (s?.highRiskPositions ?? 0))}
          note={`${units(s?.recommendedUnitsHighRisk)} units recommended to reorder`} tone="risk" />
        <Kpi label="ML forecast · next 28 days" value={units(s?.forecastUnits28)} note={`${compactMoney(s?.forecastNetSales28 ?? 0)} net sales`} />
      </section>
      <section className="dashboard-grid">
        <div className="panel">
          <div className="panel-title">
            <div><h2>Store performance · last 28 days</h2><p>Net sales with growth versus the same 28 days last year</p></div>
            <button type="button" className="button secondary" onClick={() => onNavigate('sales')}>Sales detail</button>
          </div>
          <BarList format={compactMoney} items={data.stores.map(st => ({
            key: st.storeCode, label: st.storeName.replace('Maison MTL ', ''), value: st.netSalesLast28,
            sub: `${signedPct(st.last28GrowthPct)} YoY · ${st.outOfStockPositions} out of stock`,
          }))} />
        </div>
        <div className="panel">
          <div className="panel-title">
            <div><h2>Needs attention now</h2><p>ML low-stock predictions with recommended reorder</p></div>
            <button type="button" className="button secondary" onClick={() => onNavigate('forecast')}>All risks</button>
          </div>
          <div className="attention-list">
            {urgent.map(r => (
              <div key={r.positionId}>
                <b className={r.riskLevel.toLowerCase()}>{r.riskLevel === 'Critical' ? '!' : '↓'}</b>
                <span>{r.productName}</span>
                <em>{r.storeName.replace('Maison MTL ', '')} · {r.onHandUnits} on hand · reorder {r.recommendedReorderQty}</em>
                <button type="button" className="link" onClick={() => onReorder({ storeCode: r.storeCode, sku: r.sku,
                  quantity: r.recommendedReorderQty, urgency: r.riskLevel === 'Critical' ? 'Critical' : 'Urgent' })}>Request</button>
              </div>
            ))}
          </div>
        </div>
      </section>
      <section className="dashboard-grid equal">
        <div className="panel">
          <div className="panel-title"><div><h2>Fastest-growing categories</h2><p>Last 28 days vs same 28 days last year</p></div></div>
          <BarList format={signedPct} items={growth.map(c => ({ key: c.categoryId, label: `${c.category}`, sub: c.department,
            value: Math.max(0, c.last28GrowthPct ?? 0) }))} />
        </div>
        <div className="panel ask-panel">
          <h2>Ask MTL IQ</h2>
          <p>The embedded Fabric Data Agent answers questions about sales, inventory, forecasts and reorders in English or French,
            grounded in the MtlRetailOntology.</p>
          <ul>
            <li>“Which store had the highest net sales in the last 28 days?”</li>
            <li>“Quels articles risquent une rupture de stock cette semaine?”</li>
          </ul>
          <button type="button" className="button primary" onClick={() => onNavigate('advisor')}>Open the advisor</button>
          <small>Inventory at cost {money(s?.inventoryCost)} · {units(s?.dcOnHandUnits)} units at DC-QC</small>
        </div>
      </section>
    </>
  );
}

function Kpi({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'good' | 'risk' }) {
  return <div className={`kpi-card ${tone ?? ''}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}
