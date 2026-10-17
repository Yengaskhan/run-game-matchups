import type { ReactNode } from 'react';
import { formatCell } from './format';
import type { BandKey, Rank } from './types';

export const BAND_STYLE: Record<BandKey, string> = {
  big_edge: 'bg-edge-good/30 text-edge-good border-edge-good/60',
  small_edge: 'bg-edge-good/10 text-edge-good border-edge-good/30',
  neutral: 'bg-raise text-ink-2 border-line-2',
  small_disadvantage: 'bg-edge-bad/10 text-edge-bad border-edge-bad/30',
  big_disadvantage: 'bg-edge-bad/30 text-edge-bad border-edge-bad/60',
};

export function EdgeBadge({ edge, band, small, lg, title }: { edge: number | null; band: BandKey; small?: boolean; lg?: boolean; title?: string }) {
  if (edge == null) return <span className="text-ink-3" title="Not ranked: one side is below the rank qualifier">—</span>;
  return (
    <span
      title={title ?? (small ? 'Small sample: too few ranked runs to shade' : undefined)}
      className={`num inline-flex items-center justify-center rounded border font-semibold ${BAND_STYLE[small ? 'neutral' : band]} ${small ? 'border-dashed' : ''} ${lg ? 'h-10 min-w-[3.5rem] px-2 text-[22px]' : 'h-6 min-w-[2.5rem] px-1.5 text-[12.5px]'}`}
    >
      {edge}
    </span>
  );
}

/** "rank/peer · n=att" under a value. `unrankable` values (e.g. shares) show only n. Unranked = "—". */
export function RankLine({ rank, n, unrankable }: { rank?: Rank; n?: number | null; unrankable?: boolean }) {
  const top = rank && rank[1] > 1 && (rank[0] - 1) / (rank[1] - 1) <= 0.25;
  return (
    <span className="block text-[10.5px] leading-3 text-ink-3">
      {!unrankable && (rank ? <span className={top ? 'text-accent' : ''}>{rank[0]}/{rank[1]}</span> : '—')}
      {n != null && <>{unrankable ? '' : ' · '}n={n}</>}
    </span>
  );
}

export function Stat({ v, fmt, rank, n }: { v: number | null | undefined; fmt: Parameters<typeof formatCell>[1]; rank?: Rank; n?: number | null }) {
  return (
    <>
      <span className="block">{formatCell(v, fmt)}</span>
      {(rank || n != null) && <RankLine rank={rank} n={n} />}
    </>
  );
}

export function Select({ label, value, onChange, options, className = '' }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][]; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 text-[10.5px] font-medium uppercase tracking-wider text-ink-3 ${className}`}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="h-8 rounded border border-line-2 px-1.5 text-[13px] normal-case tracking-normal text-ink">
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Panel({ title, note, children, className = '' }: { title: ReactNode; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-md border border-line bg-panel ${className}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-line px-3 py-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-ink-2">{title}</h2>
        {note && <span className="text-[11px] text-ink-3">{note}</span>}
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Card({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-panel px-3 py-2.5">
      <p className="text-[10.5px] font-medium uppercase tracking-wider text-ink-3">{label}</p>
      <div className="mt-1">{children}</div>
      {sub && <p className="mt-1 text-[11.5px] leading-snug text-ink-2">{sub}</p>}
    </div>
  );
}

export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'good' | 'bad' | 'neutral' | 'warn' }) {
  const cls = {
    good: 'border-edge-good/40 text-edge-good',
    bad: 'border-edge-bad/40 text-edge-bad',
    warn: 'border-warn/40 text-warn',
    neutral: 'border-line-2 text-ink-2',
  }[tone];
  return <span className={`inline-flex items-center rounded border px-1.5 py-px text-[10.5px] font-semibold uppercase tracking-wide ${cls}`}>{children}</span>;
}

export type SortState<K extends string> = { key: K; desc: boolean };

export function SortTh<K extends string>({ k, sort, setSort, children, className = '', textKeys = [] }: {
  k?: K; sort: SortState<K>; setSort: (f: (s: SortState<K>) => SortState<K>) => void; children: ReactNode; className?: string; textKeys?: K[];
}) {
  return (
    <th scope="col" className={`whitespace-nowrap px-3 py-2 text-[10.5px] font-medium uppercase tracking-wider text-ink-3 ${className}`} aria-sort={k && sort.key === k ? (sort.desc ? 'descending' : 'ascending') : undefined}>
      {k ? (
        <button type="button" onClick={() => setSort((s) => ({ key: k, desc: s.key === k ? !s.desc : !textKeys.includes(k) }))} className="inline-flex items-center gap-1 rounded border border-line-2 bg-panel-2 px-1.5 py-0.5 uppercase hover:border-ink-3 hover:text-ink">
          {children}
          <span aria-hidden className={sort.key === k ? 'text-accent' : 'text-ink-3/60'}>{sort.key === k ? (sort.desc ? '▼' : '▲') : '↕'}</span>
        </button>
      ) : (
        children
      )}
    </th>
  );
}

/** "3rd of 32" style phrase for a rank. */
export function rankPhrase(r: Rank | undefined, unit = ''): string {
  if (!r) return 'unranked';
  const [k, n] = r;
  const suf = k % 100 >= 11 && k % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[k % 10] ?? 'th';
  return `${k}${suf} of ${n}${unit ? ` ${unit}` : ''}`;
}
