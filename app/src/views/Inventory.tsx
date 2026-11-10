import { useMemo, useState } from 'react';

import { BarList } from '@/components/charts';
import { pct, units } from '@/lib/format';
import type { RetailData } from '@/services/retail';

import type { ReorderPrefill } from './Reorders';

const STATUS_TONE: Record<string, 'risk' | 'good' | 'neutral'> = {
  'Out of stock': 'risk', 'Below reorder point': 'risk', Healthy: 'good', Overstock: 'neutral',
};

export function Inventory({ data, onReorder }: { data: RetailData; onReorder: (value: ReorderPrefill) => void }) {
  const [store, setStore] = useState('All');
  const s = data.snapshot;
  const statusCounts = useMemo(() => {
    const counts = new Map<string, number>();
    data.risks.forEach(r => counts.set(r.stockStatus, (counts.get(r.stockStatus) ?? 0) + 1));
    return ['Out of stock', 'Below reorder point', 'Healthy', 'Overstock'].map(k => ({ key: k, label: k, value: counts.get(k) ?? 0, tone: STATUS_TONE[k] }));
  }, [data.risks]);
  const cover = [...data.categories].filter(c => c.weeksOfSupply !== undefined)
    .sort((a, b) => (a.weeksOfSupply ?? 0) - (b.weeksOfSupply ?? 0)).slice(0, 8);
  const below = data.risks.filter(r => r.onHandUnits < r.reorderPointUnits && (store === 'All' || r.storeCode === store))
    .sort((a, b) => a.onHandUnits - b.onHandUnits || (a.daysOfSupply ?? 0) - (b.daysOfSupply ?? 0));
  const inStock = s ? 100 * (1 - s.outOfStockPositions / Math.max(1, s.positions)) : undefined;
  return (
    <>
      <section className="kpi-grid">
        <div className="kpi-card"><span>Store on hand</span><strong>{units(s?.storeOnHandUnits)}</strong><small>{units(s?.storeOnOrderUnits)} units in transit</small></div>
        <div className="kpi-card"><span>DC-QC on hand</span><strong>{units(s?.dcOnHandUnits)}</strong><small>Québec City distribution centre</small></div>
        <div className="kpi-card risk"><span>In-stock</span><strong>{pct(inStock)}</strong><small>{s?.positions ?? 0} store-SKU positions</small></div>
        <div className="kpi-card risk"><span>Out of stock</span><strong>{s?.outOfStockPositions ?? 0}</strong><small>positions with zero on hand</small></div>
        <div className="kpi-card risk"><span>Below reorder point</span><strong>{s?.belowReorderPointPositions ?? 0}</strong><small>includes out-of-stock positions</small></div>
        <div className="kpi-card"><span>Inventory at cost</span><strong>${((s?.inventoryCost ?? 0) / 1000).toFixed(0)}K</strong><small>stores, CAD</small></div>
      </section>
      <section className="dashboard-grid equal">
        <div className="panel">
          <div className="panel-title"><div><h2>Positions by stock status</h2><p>Store × SKU at the 2026-11-03 snapshot</p></div></div>
          <BarList format={units} items={statusCounts} />
        </div>
        <div className="panel">
          <div className="panel-title"><div><h2>Lowest cover by category</h2><p>Weeks of supply at the last-28-day sales rate</p></div></div>
          <BarList format={v => `${v.toFixed(1)} wks`} items={cover.map(c => ({ key: c.categoryId, label: c.category, sub: c.department,
            value: c.weeksOfSupply ?? 0, tone: (c.weeksOfSupply ?? 99) < 2 ? 'risk' : 'good' }))} />
        </div>
      </section>
      <section className="panel">
        <div className="panel-title">
          <div><h2>Positions below reorder point</h2><p>{below.length} positions · on hand below the store reorder point</p></div>
          <label className="inline-select">Store
            <select value={store} onChange={e => setStore(e.target.value)}>
              <option value="All">All stores</option>
              {data.stores.map(st => <option key={st.storeCode} value={st.storeCode}>{st.storeName.replace('Maison MTL ', '')}</option>)}
            </select>
          </label>
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>Store</th><th>Product</th><th>Status</th><th>On hand</th><th>Reorder point</th><th>In transit</th><th>Days of supply</th><th>DC-QC</th><th /></tr></thead>
          <tbody>{below.map(r => (
            <tr key={r.positionId}><td>{r.storeName.replace('Maison MTL ', '')}</td><td><strong>{r.productName}</strong><br /><small>{r.sku}</small></td>
              <td><span className={`pill ${r.onHandUnits === 0 ? 'danger' : 'warn'}`}>{r.stockStatus}</span></td><td>{r.onHandUnits}</td>
              <td>{r.reorderPointUnits}</td><td>{r.onOrderUnits}</td><td>{r.daysOfSupply?.toFixed(1) ?? '—'}</td><td>{units(r.dcOnHandUnits)}</td>
              <td><button type="button" className="link" onClick={() => onReorder({ storeCode: r.storeCode, sku: r.sku,
                quantity: Math.max(1, r.recommendedReorderQty), urgency: r.onHandUnits === 0 ? 'Critical' : 'Urgent' })}>Reorder</button></td></tr>))}
          </tbody></table></div>
      </section>
    </>
  );
}
