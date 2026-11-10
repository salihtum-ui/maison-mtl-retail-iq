import { useMemo, useState } from 'react';

import { LineChart } from '@/components/charts';
import { compactMoney, money, pct, signedPct, units } from '@/lib/format';
import type { RetailData } from '@/services/retail';

const DEPARTMENTS = ['All', 'Women', 'Men', 'Kids', 'Home', 'Accessories'];

export function Sales({ data }: { data: RetailData }) {
  const [department, setDepartment] = useState('All');
  const [search, setSearch] = useState('');
  const trend = useMemo(() => {
    const months = [...new Set(data.trends.map(t => t.month))].sort();
    const pick = (month: string, key: 'netSales' | 'netSalesLY') => {
      const rows = data.trends.filter(t => t.month === month && (department === 'All' || t.department === department));
      const values = rows.map(r => r[key]).filter((v): v is number => v !== undefined && v !== null);
      return values.length ? values.reduce((a, b) => a + b, 0) : null;
    };
    return { labels: months.map(m => new Date(`${m}-15T12:00:00Z`).toLocaleDateString('en-CA', { month: 'short', year: '2-digit' })),
      current: months.map(m => pick(m, 'netSales')), ly: months.map(m => pick(m, 'netSalesLY')) };
  }, [data.trends, department]);
  const products = data.products.filter(p => (department === 'All' || p.department === department) &&
    `${p.productName} ${p.sku} ${p.brand} ${p.category}`.toLowerCase().includes(search.toLowerCase()));
  const categories = data.categories.filter(c => department === 'All' || c.department === department);
  return (
    <>
      <section className="panel">
        <div className="panel-title">
          <div><h2>Monthly net sales vs last year</h2><p>Seasonality: outerwear peaks Nov–Jan, swimwear in summer. Nov 2026 is month-to-date.</p></div>
          <label className="inline-select">Department
            <select value={department} onChange={e => setDepartment(e.target.value)}>
              {DEPARTMENTS.map(d => <option key={d}>{d}</option>)}
            </select>
          </label>
        </div>
        <LineChart ariaLabel="Monthly net sales versus last year" labels={trend.labels} format={compactMoney}
          series={[{ name: 'Net sales', color: '#00573F', values: trend.current },
                   { name: 'Same month last year', color: '#8FBFA6', values: trend.ly, dashed: true }]} />
      </section>
      <section className="dashboard-grid equal">
        <div className="panel">
          <div className="panel-title"><div><h2>Stores · last 28 days</h2><p>Ranked by net sales</p></div></div>
          <div className="table-wrap"><table>
            <thead><tr><th>Store</th><th>Region</th><th>Net sales</th><th>YoY</th><th>Units</th><th>GM %</th><th>YTD</th></tr></thead>
            <tbody>{data.stores.map(s => (
              <tr key={s.storeCode}><td><strong>{s.storeName.replace('Maison MTL ', '')}</strong><br /><small>{s.storeCode}</small></td>
                <td>{s.region}</td><td>{money(s.netSalesLast28)}</td><td className={s.last28GrowthPct >= 0 ? 'up' : 'down'}>{signedPct(s.last28GrowthPct)}</td>
                <td>{units(s.unitsLast28)}</td><td>{pct(s.grossMarginPctLast28)}</td><td>{compactMoney(s.netSalesYTD)}</td></tr>))}
            </tbody></table></div>
        </div>
        <div className="panel">
          <div className="panel-title"><div><h2>Categories · last 28 days</h2><p>Sell-through = units sold ÷ (units sold + on hand)</p></div></div>
          <div className="table-wrap"><table>
            <thead><tr><th>Category</th><th>Net sales</th><th>YoY</th><th>GM %</th><th>Sell-through</th><th>Weeks of supply</th></tr></thead>
            <tbody>{categories.map(c => (
              <tr key={c.categoryId}><td><strong>{c.category}</strong><br /><small>{c.department}</small></td><td>{money(c.netSalesLast28)}</td>
                <td className={(c.last28GrowthPct ?? 0) >= 0 ? 'up' : 'down'}>{signedPct(c.last28GrowthPct)}</td><td>{pct(c.grossMarginPctLast28)}</td>
                <td>{pct(c.sellThroughPct)}</td><td>{c.weeksOfSupply?.toFixed(1) ?? '—'}</td></tr>))}
            </tbody></table></div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-title">
          <div><h2>Products · last 28 days</h2><p>{products.length} SKUs · chain totals across the 10 stores</p></div>
          <input className="search" placeholder="Search product, SKU, brand…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Search products" />
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>Product</th><th>Category</th><th>Brand</th><th>Price</th><th>Net sales</th><th>YoY</th><th>Units</th><th>On hand</th><th>Out of stock</th><th>Forecast 28d</th></tr></thead>
          <tbody>{products.map(p => (
            <tr key={p.sku}><td><strong>{p.productName}</strong><br /><small>{p.sku}</small></td><td>{p.category}</td><td>{p.brand}</td>
              <td>{money(p.unitPrice)}</td><td>{money(p.netSalesLast28)}</td><td className={(p.last28GrowthPct ?? 0) >= 0 ? 'up' : 'down'}>{signedPct(p.last28GrowthPct)}</td>
              <td>{units(p.unitsLast28)}</td><td>{units(p.onHandUnits)}</td>
              <td>{p.outOfStockStores ? <span className="pill danger">{p.outOfStockStores} stores</span> : '—'}</td><td>{units(p.forecastUnits28)}</td></tr>))}
          </tbody></table></div>
      </section>
    </>
  );
}
