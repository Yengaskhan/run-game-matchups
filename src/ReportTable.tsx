import { Fragment } from 'react';
import { formatCell } from './format';
import type { ReportTableData, Row } from './types';

/** Top quarter of the peer group: rank shown in the accent colour. */
const isTop = ([r, n]: [number, number]) => n > 1 && (r - 1) / (n - 1) <= 0.25;

function RankTag({ rank }: { rank?: [number, number] }) {
  if (!rank) return <span className="block text-[10.5px] leading-3 text-ink-3/60">—</span>;
  return (
    <span className={`block text-[10.5px] leading-3 ${isTop(rank) ? 'text-accent' : 'text-ink-3'}`} title={`Rank ${rank[0]} of ${rank[1]}`}>
      {rank[0]}/{rank[1]}
    </span>
  );
}

const ROW_STYLE: Record<Row['kind'], string> = {
  row: '',
  team: 'font-semibold',
  ref: 'italic text-ink-2',
  total: 'border-t border-line-2 font-semibold',
  qb: 'text-ink-2',
};

export function ReportTable({ t }: { t: ReportTableData }) {
  const prior = !t.season_label.includes('current');
  const hasRanks = t.columns.some((c) => c.rank);
  let lastGroup: string | undefined;
  return (
    <figure className="min-w-0 rounded-md border border-line bg-panel">
      <figcaption className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line px-3 py-2">
        <h4 className="text-[13px] font-semibold text-ink">{t.title}</h4>
        <span
          className={`rounded border px-1.5 py-px text-[10.5px] uppercase tracking-wider ${
            prior ? 'border-line-2 text-ink-2' : 'border-accent/50 text-accent'
          }`}
        >
          {prior ? `Prior season · ${t.season}` : `Current season · ${t.season}`}
        </span>
        <span className="text-[11px] text-ink-3">{t.caption}</span>
      </figcaption>

      <div className="overflow-x-auto">
        <table className="num w-full border-collapse text-[12px]">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wider text-ink-3">
              <th scope="col" className="sticky left-0 z-10 bg-panel px-3 py-1.5 text-left font-medium" />
              {t.columns.map((c) => (
                <th key={c.key} scope="col" title={c.title} className={`whitespace-nowrap px-2 py-1.5 text-right font-medium ${c.title ? 'cursor-help underline decoration-dotted decoration-ink-3/50 underline-offset-2' : ''}`}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {t.rows.map((r) => {
              const header = r.group && r.group !== lastGroup;
              lastGroup = r.group;
              return (
                <Fragment key={r.key}>
                  {header && (
                    <tr>
                      <th colSpan={t.columns.length + 1} scope="rowgroup" className="sticky left-0 bg-panel-2 px-3 py-1 text-left text-[11.5px] font-semibold text-ink">
                        {r.group}
                      </th>
                    </tr>
                  )}
                  <tr className={`border-t border-line/60 ${ROW_STYLE[r.kind]} ${r.flag ? 'bg-accent/5' : ''}`}>
                    <th
                      scope="row"
                      className={`sticky left-0 z-10 min-w-[7.5rem] max-w-[13rem] px-3 py-1.5 text-left align-top font-[inherit] ${r.flag ? 'border-l-2 border-accent bg-[#0f1c22]' : 'bg-panel'}`}
                    >
                      <span className="block">{r.label}</span>
                      {r.flag && (
                        <span className="block text-[10.5px] font-normal not-italic text-accent">{r.flag === 'offense' ? 'Largest offense edge' : 'Largest defense edge'}</span>
                      )}
                      {r.sub && <span className="block text-[10.5px] font-normal not-italic leading-snug text-ink-3">{r.sub}</span>}
                    </th>
                    {t.columns.map((c) => (
                      <td key={c.key} className="whitespace-nowrap px-2 py-1.5 text-right align-top">
                        <span className="block">{formatCell(r.cells[c.key], c.fmt)}</span>
                        {c.rank && r.kind !== 'ref' && r.kind !== 'total' && r.kind !== 'qb' && r.cells[c.key] != null && <RankTag rank={r.ranks[c.key]} />}
                      </td>
                    ))}
                  </tr>
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="space-y-2 border-t border-line px-3 py-2">
        <p className="text-[11px] text-ink-3">
          {t.peer}
          {hasRanks && ' Ranks read "rank/peer group"; cyan = top quarter.'}
        </p>
        {t.takeaways.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-4 text-[12px] leading-relaxed text-ink-2 marker:text-ink-3">
            {t.takeaways.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
        {t.notes.map((n, i) => (
          <p key={i} className="text-[11px] text-ink-3">
            {n}
          </p>
        ))}
      </div>
    </figure>
  );
}
