import { useMemo } from 'react';

export type Series = { name: string; color: string; values: (number | null)[]; dashed?: boolean };

type LineChartProps = {
  labels: string[];
  series: Series[];
  band?: { low: (number | null)[]; high: (number | null)[]; color: string };
  height?: number;
  format?: (value: number) => string;
  marker?: number;
  ariaLabel: string;
};

export function LineChart({ labels, series, band, height = 240, format = v => String(Math.round(v)), marker, ariaLabel }: LineChartProps) {
  const width = 760;
  const pad = { top: 14, right: 16, bottom: 30, left: 62 };
  const all = useMemo(() => [
    ...series.flatMap(s => s.values), ...(band ? [...band.low, ...band.high] : []),
  ].filter((v): v is number => v !== null && Number.isFinite(v)), [series, band]);
  const max = Math.max(1, ...all) * 1.08;
  const x = (i: number) => pad.left + (labels.length <= 1 ? 0 : (i / (labels.length - 1)) * (width - pad.left - pad.right));
  const y = (v: number) => pad.top + (1 - v / max) * (height - pad.top - pad.bottom);
  const path = (values: (number | null)[]) => values.reduce((acc, v, i) => {
    if (v === null || !Number.isFinite(v)) return acc;
    const prev = i > 0 ? values[i - 1] : null;
    return acc + `${prev === null || prev === undefined || acc === '' ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
  }, '');
  const area = band ? (() => {
    const idx = band.high.map((v, i) => (v === null ? -1 : i)).filter(i => i >= 0);
    if (!idx.length) return '';
    const top = idx.map(i => `${x(i).toFixed(1)},${y(band.high[i] as number).toFixed(1)}`);
    const bottom = [...idx].reverse().map(i => `${x(i).toFixed(1)},${y((band.low[i] ?? 0) as number).toFixed(1)}`);
    return `M${top.join(' L')} L${bottom.join(' L')} Z`;
  })() : '';
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => t * max);
  const step = Math.max(1, Math.ceil(labels.length / 8));
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        {ticks.map(t => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={pad.left - 8} y={y(t) + 4} textAnchor="end" className="axis">{format(t)}</text>
          </g>
        ))}
        {labels.map((label, i) => (i % step === 0 || (i === labels.length - 1 && (labels.length - 1) % step > step / 2)) && (
          <text key={label + i} x={x(i)} y={height - 8} textAnchor="middle" className="axis">{label}</text>
        ))}
        {marker !== undefined && <line x1={x(marker)} x2={x(marker)} y1={pad.top} y2={height - pad.bottom} className="marker" />}
        {area && <path d={area} fill={band!.color} opacity={0.18} />}
        {series.map(s => (
          <path key={s.name} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2.4}
            strokeDasharray={s.dashed ? '6 5' : undefined} strokeLinejoin="round" strokeLinecap="round" />
        ))}
      </svg>
      <div className="legend">
        {series.map(s => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}
        {band && <span><i style={{ background: band.color, opacity: 0.35 }} />P10–P90 range</span>}
      </div>
    </div>
  );
}

export type BarItem = { key: string; label: string; value: number; sub?: string; tone?: 'good' | 'risk' | 'neutral' };

export function BarList({ items, format, max }: { items: BarItem[]; format: (v: number) => string; max?: number }) {
  const top = max ?? Math.max(1, ...items.map(i => i.value));
  return (
    <div className="bar-list">
      {items.map(item => (
        <div className="bar-row" key={item.key}>
          <div><strong>{item.label}</strong>{item.sub && <span>{item.sub}</span>}</div>
          <div className="bar-track"><i className={item.tone ?? ''} style={{ width: `${Math.max(2, (item.value / top) * 100)}%` }} /></div>
          <b>{format(item.value)}</b>
        </div>
      ))}
    </div>
  );
}
