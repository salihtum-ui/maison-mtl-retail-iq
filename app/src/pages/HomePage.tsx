import { useCallback, useEffect, useState } from 'react';

import { Advisor } from '@/components/Advisor';
import { useAuth } from '@/hooks/AuthContext';
import { day } from '@/lib/format';
import { loadRetailData, type RetailData } from '@/services/retail';
import { About } from '@/views/About';
import { Forecast } from '@/views/Forecast';
import { Inventory } from '@/views/Inventory';
import { Overview } from '@/views/Overview';
import { Reorders, type ReorderPrefill } from '@/views/Reorders';
import { Sales } from '@/views/Sales';

const TABS = [
  { id: 'overview', label: 'Overview', icon: 'OV' },
  { id: 'sales', label: 'Sales', icon: 'SA' },
  { id: 'inventory', label: 'Inventory health', icon: 'IN' },
  { id: 'forecast', label: 'Forecast & stock risk', icon: 'ML', badge: 'AI' },
  { id: 'reorders', label: 'Reorder requests', icon: 'RO' },
  { id: 'advisor', label: 'Ask MTL IQ', icon: 'IQ', badge: 'AGENT' },
  { id: 'about', label: 'How it works', icon: '?' },
] as const;
export type Tab = (typeof TABS)[number]['id'];

export function HomePage({ initialData, initialTab = 'overview' }: { initialData?: RetailData; initialTab?: Tab }) {
  const { user, signOut } = useAuth();
  const [tab, setTab] = useState<Tab>(initialTab);
  const [data, setData] = useState<RetailData | null>(initialData ?? null);
  const [error, setError] = useState<string | null>(null);
  const [prefill, setPrefill] = useState<ReorderPrefill | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await loadRetailData());
    } catch (caught) {
      console.error('Failed to load MTL Retail IQ data', caught);
      setError(caught instanceof Error ? caught.message : 'The retail data could not be loaded.');
    }
  }, []);

  useEffect(() => {
    if (!initialData) void load();
  }, [initialData, load]);

  const requestReorder = (value: ReorderPrefill) => {
    setPrefill(value);
    setTab('reorders');
  };
  const current = TABS.find(t => t.id === tab)!;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>S</span>
          <div><strong>MAISON MTL</strong><small>Retail IQ · Microsoft Fabric</small></div>
        </div>
        <nav aria-label="Sections">
          {TABS.map(item => (
            <button key={item.id} type="button" className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>
              <i>{item.icon}</i><span>{item.label}</span>{'badge' in item && <em>{item.badge}</em>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span>SYNTHETIC DATA</span>
          <strong>10 Quebec stores + DC-QC</strong>
          <small>Illustrative only — fictional retailer</small>
        </div>
      </aside>
      <main className="main">
        <header>
          <div>
            <span>MTL RETAIL IQ</span>
            <strong>{current.label}</strong>
          </div>
          <div className="user">
            <div><b>{user?.name ?? 'Maison MTL employee'}</b><span>Snapshot {day(data?.snapshot?.snapshotDate ?? '2026-11-03')}</span></div>
            <button type="button" onClick={() => void signOut()}>Sign out</button>
          </div>
        </header>
        <div className="content">
          {error && (
            <div className="alert error" role="alert">
              {error} <button type="button" className="button secondary" onClick={() => void load()}>Retry</button>
            </div>
          )}
          {!data && !error && <div className="empty-state" role="status"><b>Loading Gold data from Fabric…</b></div>}
          {data && tab === 'overview' && <Overview data={data} onNavigate={setTab} onReorder={requestReorder} />}
          {data && tab === 'sales' && <Sales data={data} />}
          {data && tab === 'inventory' && <Inventory data={data} onReorder={requestReorder} />}
          {data && tab === 'forecast' && <Forecast data={data} onReorder={requestReorder} />}
          {data && tab === 'reorders' && <Reorders data={data} prefill={prefill} onPrefillUsed={() => setPrefill(null)} />}
          {tab === 'advisor' && <Advisor />}
          {tab === 'about' && <About />}
        </div>
      </main>
    </div>
  );
}
