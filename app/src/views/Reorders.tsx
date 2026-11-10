import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import type { ReorderRequest } from '../../rayfin/data/ReorderRequest';
import type { ReorderReview } from '../../rayfin/data/ReorderReview';
import { useAuth } from '@/hooks/AuthContext';
import { day, units } from '@/lib/format';
import { createReorderRequest, getMyReorderRequests, getMyReorderReviews, URGENCIES } from '@/services/requests';
import type { RetailData } from '@/services/retail';

export type ReorderPrefill = { storeCode: string; sku: string; quantity: number; urgency: string };

function inDays(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

export function Reorders({ data, prefill, onPrefillUsed }: { data: RetailData; prefill: ReorderPrefill | null; onPrefillUsed: () => void }) {
  const { user } = useAuth();
  const [storeCode, setStoreCode] = useState(data.stores[0]?.storeCode ?? '');
  const [sku, setSku] = useState(data.products[0]?.sku ?? '');
  const [quantity, setQuantity] = useState('12');
  const [urgency, setUrgency] = useState<string>('Standard');
  const [neededBy, setNeededBy] = useState(inDays(7));
  const [note, setNote] = useState('');
  const [fromMl, setFromMl] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [requests, setRequests] = useState<ReorderRequest[]>([]);
  const [reviews, setReviews] = useState<ReorderReview[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [mine, mineReviews] = await Promise.all([getMyReorderRequests(), getMyReorderReviews()]);
      setRequests(mine);
      setReviews(mineReviews);
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : 'Could not load your requests.' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!prefill) return;
    setStoreCode(prefill.storeCode);
    setSku(prefill.sku);
    setQuantity(String(prefill.quantity));
    setUrgency(prefill.urgency);
    setNeededBy(inDays(prefill.urgency === 'Critical' ? 2 : prefill.urgency === 'Urgent' ? 4 : 7));
    setFromMl(true);
    onPrefillUsed();
  }, [prefill, onPrefillUsed]);

  const risk = useMemo(() => data.risks.find(r => r.storeCode === storeCode && r.sku === sku), [data.risks, storeCode, sku]);
  const product = data.products.find(p => p.sku === sku);
  const reviewFor = (id: string) => reviews.find(r => r.requestId.toLowerCase() === id.toLowerCase());

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await createReorderRequest({
        storeCode, sku, productName: product?.productName ?? sku, quantity: Number(quantity), urgency,
        neededBy: new Date(`${neededBy}T12:00:00Z`), note, source: fromMl ? 'ML recommendation' : 'Employee request',
        recommendedQty: risk?.recommendedReorderQty, riskLevel: risk?.riskLevel,
      }, user?.name ?? user?.email ?? 'Maison MTL employee');
      setMessage({ kind: 'ok', text: 'Request saved to the app SQL database. Fabric will validate it for buyer approval.' });
      setNote('');
      setFromMl(false);
      await refresh();
    } catch (error) {
      setMessage({ kind: 'error', text: error instanceof Error ? error.message : 'The request could not be saved.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="request-layout">
      <form className="panel request-form" onSubmit={submit}>
        <div className="panel-title"><div><h2>New reorder request</h2><p>Saved in the app's Fabric SQL database · a buyer approves it</p></div></div>
        <label>Store
          <select value={storeCode} onChange={e => { setStoreCode(e.target.value); setFromMl(false); }}>
            {data.stores.map(s => <option key={s.storeCode} value={s.storeCode}>{s.storeName} ({s.storeCode})</option>)}
          </select>
        </label>
        <label>Product
          <select value={sku} onChange={e => { setSku(e.target.value); setFromMl(false); }}>
            {['Women', 'Men', 'Kids', 'Home', 'Accessories'].map(dept => (
              <optgroup key={dept} label={dept}>
                {data.products.filter(p => p.department === dept).map(p => <option key={p.sku} value={p.sku}>{p.productName} · {p.sku}</option>)}
              </optgroup>))}
          </select>
        </label>
        {risk && (
          <div className={`ml-hint ${risk.riskLevel.toLowerCase()}`}>
            <div><b>ML: {risk.riskLevel} risk</b><span>{risk.onHandUnits} on hand · reorder point {risk.reorderPointUnits} ·
              {risk.predictedDaysToLow === 0 ? ' below reorder point now' : risk.predictedLowStockDate ? ` low by ${day(risk.predictedLowStockDate)}` : ' no low stock within 28 days'}</span></div>
            <button type="button" className="button secondary" disabled={!risk.recommendedReorderQty}
              onClick={() => { setQuantity(String(risk.recommendedReorderQty)); setFromMl(true); }}>Use {risk.recommendedReorderQty}</button>
          </div>
        )}
        <div className="form-row">
          <label>Quantity (units)<input type="number" min={1} max={1000} step={1} value={quantity} onChange={e => setQuantity(e.target.value)} required /></label>
          <label>Urgency<select value={urgency} onChange={e => setUrgency(e.target.value)}>{URGENCIES.map(u => <option key={u}>{u}</option>)}</select></label>
        </div>
        <label>Needed by<input type="date" value={neededBy} onChange={e => setNeededBy(e.target.value)} required /></label>
        <label>Note for the buyer<textarea rows={3} maxLength={500} value={note} onChange={e => setNote(e.target.value)}
          placeholder="e.g. Cold snap — customers asking for size 8 boots" /></label>
        {message && <p role={message.kind === 'error' ? 'alert' : 'status'} className={message.kind === 'error' ? 'alert error' : 'form-status'}>{message.text}</p>}
        <button type="submit" className="button primary" disabled={busy}>{busy ? 'Saving…' : 'Submit reorder request'}</button>
        <small className="muted">Requests are review records. They do not place a purchase order or move stock until a buyer approves them.</small>
      </form>
      <section className="panel">
        <div className="panel-title"><div><h2>My reorder requests</h2><p>Only you can see your requests · status from the Fabric validation</p></div>
          <button type="button" className="button secondary" onClick={() => void refresh()}>Refresh</button></div>
        {loading ? <div className="empty-state">Loading…</div> : requests.length === 0 ? (
          <div className="empty-state"><b>No requests yet</b><span>Use the form or the Request buttons on the Forecast & stock risk page.</span></div>
        ) : (
          <div className="request-list">
            {requests.map(r => {
              const review = reviewFor(r.id);
              const status = review?.status ?? 'Submitted';
              return (
                <article key={r.id}>
                  <div><strong>{r.productName}</strong><span>{data.stores.find(s => s.storeCode === r.storeCode)?.storeName ?? r.storeCode} · {units(r.quantity)} units · needed {day(r.neededBy)}</span></div>
                  <span className={`pill ${r.urgency.toLowerCase()}`}>{r.urgency}</span>
                  <span className={`pill status ${status.startsWith('Rejected') ? 'danger' : status === 'Submitted' ? 'neutral' : ''}`}>{status}</span>
                  <small>{review?.message ?? 'Saved in the app database; awaiting the next Fabric medallion run.'}
                    {r.recommendedQty !== undefined && r.recommendedQty !== null && ` · ML recommended ${r.recommendedQty}`} · {day(r.submittedAt)}</small>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
