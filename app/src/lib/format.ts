const cad0 = new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', maximumFractionDigits: 0 });
const int = new Intl.NumberFormat('en-CA', { maximumFractionDigits: 0 });

export const money = (value?: number | null) => (value === null || value === undefined ? '—' : cad0.format(value));
export const units = (value?: number | null) => (value === null || value === undefined ? '—' : int.format(value));
export const pct = (value?: number | null, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value) ? '—' : `${value.toFixed(digits)}%`;
export const signedPct = (value?: number | null) =>
  value === null || value === undefined || Number.isNaN(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
export const compactMoney = (value: number) =>
  value >= 1_000_000 ? `$${(value / 1_000_000).toFixed(2)}M` : value >= 1_000 ? `$${(value / 1_000).toFixed(0)}K` : money(value);
export const day = (value?: string | Date | null) => {
  if (!value) return '—';
  const text = value instanceof Date ? value.toISOString().slice(0, 10) : String(value).slice(0, 10);
  return new Date(`${text}T12:00:00Z`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' });
};
export const RISK_ORDER: Record<string, number> = { Critical: 1, High: 2, Medium: 3, Low: 4 };
