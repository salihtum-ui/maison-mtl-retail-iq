import { useMemo, useState } from 'react';

import { LineChart } from '@/components/charts';
import { compactMoney, day, pct, units } from '@/lib/format';
import type { RetailData } from '@/services/retail';

import type { ReorderPrefill } from './Reorders';

const LEVELS = ['Critical', 'High', 'Medium', 'Low'];

export function Forecast({ data, onReorder }: { data: RetailData; onReorder: (value: ReorderPrefill) => void }) {
  const [department, setDepartment] = useState('All');
  const [levels, setLevels] = useState<string[]>(['Critical', 'High']);
  const [store, setStore] = useState('All');
  const s = data.snapshot;
  const chart = useMemo(() => {
    const points = data.demand.filter(d => d.department === department);
    const days = [...new Set(points.map(p => p.day))].sort();
    const get = (d: string, kind: string) => points.find(p => p.day === d && p.kind === kind);
    const lastActual = days.filter(d => get(d, 'Actual')).length - 1;
    return { labels: days.map(d => new Date(`${d}T12:00:00Z`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })),
      actual: days.map(d => get(d, 'Actual')?.units ?? null), forecast: days.map(d => get(d, 'Forecast')?.units ?? null),
      low: days.map(d => get(d, 'Forecast')?.unitsLow ?? null), high: days.map(d => get(d, 'Forecast')?.unitsHigh ?? null), lastActual };
  }, [data.demand, department]);
  const risks = data.risks.filter(r => levels.includes(r.riskLevel) && (store === 'All' || r.storeCode === store) &&
    (department === 'All' || r.department === department))
    .sort((a, b) => a.riskRank - b.riskRank || (a.predictedDaysToLow ?? 99) - (b.predictedDaysToLow ?? 99));
  const counts = LEVELS.map(l => ({ level: l, count: data.risks.filter(r => r.riskLevel === l).length }));
  const toggle = (level: string) => setLevels(c => (c.includes(level) ? c.filter(x => x !== level) : [...c, level]));
  return (
    <>
      <section className="kpi-grid">
        <div className="kpi-card"><span>Forecast units · 28 days</span><strong>{units(s?.forecastUnits28)}</strong><small>4 Nov – 1 Dec 2026, incl. Black Friday</small></div>
        <div className="kpi-card"><span>Forecast net sales</span><strong>{compactMoney(s?.forecastNetSales28 ?? 0)}</strong><small>at planned prices and markdowns</small></div>
        <div className="kpi-card good"><span>Forecast error (WAPE)</span><strong>{pct(s?.forecastWapePct)}</strong><small>vs {pct(s?.baselineWapePct)} seasonal-naive · department-day holdout</small></div>
        {counts.slice(0, 3).map(c => (
          <div key={c.level} className={`kpi-card ${c.level === 'Medium' ? '' : 'risk'}`}><span>{c.level} risk</span><strong>{c.count}</strong>
            <small>store-SKU positions</small></div>))}
      </section>
      <section className="panel">
        <div className="panel-title">
          <div><h2>Daily units: actual vs ML forecast</h2><p>LightGBM model registered in Fabric · last 8 weeks actual, next 28 days forecast with P10–P90 range</p></div>
          <label className="inline-select">Department
            <select value={department} onChange={e => setDepartment(e.target.value)}>
              {['All', 'Women', 'Men', 'Kids', 'Home', 'Accessories'].map(d => <option key={d}>{d}</option>)}
            </select>
          </label>
        </div>
        <LineChart ariaLabel="Actual and forecast daily units" labels={chart.labels} marker={chart.lastActual}
          series={[{ name: 'Actual units', color: '#00573F', values: chart.actual },
                   { name: 'Forecast units', color: '#C8553D', values: chart.forecast, dashed: true }]}
          band={{ low: chart.low, high: chart.high, color: '#E3A33B' }} />
      </section>
      <section className="panel">
        <div className="panel-title">
          <div><h2>Low-stock predictions and reorder recommendations</h2>
            <p>Days-to-low-stock model + forecast projection · recommended quantity covers transfer lead time + 14 days, rounded to case pack</p></div>
          <div className="filters">
            {LEVELS.map(l => <button key={l} type="button" className={`chip ${levels.includes(l) ? 'on' : ''} ${l.toLowerCase()}`} onClick={() => toggle(l)}>{l}</button>)}
            <select aria-label="Store filter" value={store} onChange={e => setStore(e.target.value)}>
              <option value="All">All stores</option>
              {data.stores.map(st => <option key={st.storeCode} value={st.storeCode}>{st.storeName.replace('Maison MTL ', '')}</option>)}
            </select>
          </div>
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>Risk</th><th>Store</th><th>Product</th><th>On hand</th><th>Reorder point</th><th>Forecast 28d</th><th>Low-stock date</th><th>Recommended</th><th>Action</th><th /></tr></thead>
          <tbody>{risks.slice(0, 150).map(r => (
            <tr key={r.positionId}><td><span className={`pill ${r.riskLevel.toLowerCase()}`}>{r.riskLevel}</span></td>
              <td>{r.storeName.replace('Maison MTL ', '')}</td><td><strong>{r.productName}</strong><br /><small>{r.sku}</small></td>
              <td>{r.onHandUnits}</td><td>{r.reorderPointUnits}</td><td>{r.forecast28Units.toFixed(0)}</td>
              <td>{r.predictedDaysToLow === 0 ? 'Now' : day(r.predictedLowStockDate)}</td><td><b>{r.recommendedReorderQty}</b></td>
              <td><small>{r.recommendedAction}</small></td>
              <td>{r.recommendedReorderQty > 0 && <button type="button" className="link" onClick={() => onReorder({ storeCode: r.storeCode, sku: r.sku,
                quantity: r.recommendedReorderQty, urgency: r.riskLevel === 'Critical' ? 'Critical' : r.riskLevel === 'High' ? 'Urgent' : 'Standard' })}>Request</button>}</td></tr>))}
          </tbody></table></div>
        {risks.length > 150 && <p className="muted">Showing 150 of {risks.length} positions.</p>}
      </section>
    </>
  );
}
