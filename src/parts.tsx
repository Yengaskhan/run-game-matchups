import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { bandFor } from './edge';
import { formatCell, formatDate } from './format';
import { TeamLogo } from './TeamLogo';
import type { Metrics, Overall, PlayerEntry, Rusher, SchemeRow, Split, WeekReport } from './types';
import { EdgeBadge, Stat } from './ui';

/*
 * Pieces shared by the player and defense pages: the split table, run-scheme table, stat strips,
 * backfield table, player picker and the methods footer.
 */

export const GROUP_LABEL: Record<Split['group'], string> = { direction: 'Direction', gap: 'Gap', box: 'Box count (FTN)' };

/** RB vs defense, split by split: his own carries on the left, the defense's allowed on the right. */
export function SplitTable({ splits, rb, dfn, report }: { splits: Split[]; rb: string; dfn: string; report: WeekReport }) {
  return (
    <div className="overflow-x-auto rounded border border-line">
      <table className="num w-full min-w-[820px] border-collapse text-[12px]">
        <thead className="bg-panel-2/70 text-[10.5px] uppercase tracking-wider text-ink-3">
          <tr>
            <th rowSpan={2} className="sticky left-0 z-10 bg-panel-2 px-3 py-1.5 text-left font-medium">Split</th>
            <th colSpan={4} className="border-l border-line px-2 py-1.5 font-medium text-ink-2" title="His own carries only; ranks are among RBs">{rb}</th>
            <th colSpan={4} className="border-l border-line px-2 py-1.5 font-medium text-ink-2">{dfn} defense</th>
            <th rowSpan={2} className="border-l border-line px-2 py-1.5 font-medium" title={report.edge.definition}>Edge</th>
          </tr>
          <tr className="text-right">
            {['Att', 'Share', 'Success', 'YPC', 'Faced', 'Share', 'Succ. al.', 'YPC al.'].map((h, i) => (
              <th key={i} className={`px-2 pb-1.5 font-medium ${i === 0 || i === 4 ? 'border-l border-line' : ''}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(['direction', 'gap', 'box'] as const).map((grp) => {
            const rows = splits.filter((s) => s.group === grp);
            if (!rows.length) return null;
            return (
              <Fragment key={grp}>
                <tr className="border-t border-line bg-panel-2/40">
                  <th colSpan={10} scope="rowgroup" className="sticky left-0 px-3 py-1 text-left text-[10.5px] font-semibold uppercase tracking-wider text-ink-3">
                    {GROUP_LABEL[grp]}
                  </th>
                </tr>
                {rows.map((s) => (
                  <tr key={s.key} className="border-t border-line/50">
                    <th scope="row" className="sticky left-0 z-10 bg-panel px-3 py-1.5 text-left font-medium">{s.label}</th>
                    <SplitCells m={s.off} />
                    <SplitCells m={s.def} />
                    <td className="border-l border-line px-2 py-1.5 text-center">
                      <EdgeBadge edge={s.edge} band={bandFor(s.edge, report.edge.bands)} />
                    </td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SplitCells({ m }: { m: Metrics }) {
  return (
    <>
      <td className="border-l border-line px-2 py-1.5 text-right text-ink-2">{m.att}</td>
      <td className="px-2 py-1.5 text-right">{formatCell(m.share ?? null, 'pct')}</td>
      <td className="px-2 py-1.5 text-right">
        <Stat v={m.sr} fmt="pct" rank={m.ranks.sr} />
      </td>
      <td className="px-2 py-1.5 text-right">
        <Stat v={m.ypc} fmt="dec1" rank={m.ranks.ypc} />
      </td>
    </>
  );
}

/** Zone vs man/gap (Data Suite). The defense side stays blank until a run-defense export is added. */
export function SchemeTable({ rows, rb, dfn, report }: { rows: SchemeRow[]; rb: string; dfn: string; report: WeekReport }) {
  return (
    <div className="overflow-x-auto rounded border border-line">
      <table className="num w-full min-w-[640px] border-collapse text-[12px]">
        <thead className="bg-panel-2/70 text-[10.5px] uppercase tracking-wider text-ink-3">
          <tr>
            <th rowSpan={2} className="sticky left-0 z-10 bg-panel-2 px-3 py-1.5 text-left font-medium">Scheme</th>
            <th colSpan={4} className="border-l border-line px-2 py-1.5 font-medium text-ink-2">{rb}</th>
            <th rowSpan={2} className="border-l border-line px-2 py-1.5 font-medium" title="League-average success rate on this run type (Data Suite)">Lg succ.</th>
            <th colSpan={2} className="border-l border-line px-2 py-1.5 font-medium text-ink-2">{dfn} defense</th>
            <th rowSpan={2} className="border-l border-line px-2 py-1.5 font-medium" title={report.edge.definition}>Edge</th>
          </tr>
          <tr className="text-right">
            {['Att', 'Share', 'Success', 'YPC', 'Succ. al.', 'YPC al.'].map((h, i) => (
              <th key={i} className={`px-2 pb-1.5 font-medium ${i === 0 || i === 4 ? 'border-l border-line' : ''}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-line/50">
              <th scope="row" className="sticky left-0 z-10 bg-panel px-3 py-1.5 text-left font-medium">{r.label}</th>
              <td className="border-l border-line px-2 py-1.5 text-right text-ink-2">{r.off.att}</td>
              <td className="px-2 py-1.5 text-right">{formatCell(r.off.share, 'pct')}</td>
              <td className="px-2 py-1.5 text-right"><Stat v={r.off.sr} fmt="pct" rank={r.off.ranks.sr} /></td>
              <td className="px-2 py-1.5 text-right"><Stat v={r.off.ypc} fmt="dec1" rank={r.off.ranks.ypc} /></td>
              <td className="border-l border-line px-2 py-1.5 text-right text-ink-2">{formatCell(r.league?.sr ?? null, 'pct')}</td>
              {r.def ? (
                <>
                  <td className="border-l border-line px-2 py-1.5 text-right"><Stat v={r.def.sr} fmt="pct" rank={r.def.ranks.sr} /></td>
                  <td className="px-2 py-1.5 text-right"><Stat v={r.def.ypc} fmt="dec1" rank={r.def.ranks.ypc} /></td>
                </>
              ) : (
                <td colSpan={2} className="border-l border-line px-2 py-1.5 text-center text-[11px] text-ink-3">needs defense export</td>
              )}
              <td className="border-l border-line px-2 py-1.5 text-center">
                <EdgeBadge edge={r.edge} band={bandFor(r.edge, report.edge.bands)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** YBC / YAC can trail play-by-play by a day or two; say which weeks they cover when they do. */
export function pfrNote(report: WeekReport, season: string): string | null {
  const meta = report.seasons.find((s) => String(s.season) === season);
  if (!meta) return null;
  const pw = meta.pfr_weeks ?? meta.weeks;
  if (pw.length === meta.weeks.length) return null;
  return pw.length ? `YBC/YAC: ${pw.length === 1 ? `week ${pw[0]}` : `weeks ${pw[0]}–${pw[pw.length - 1]}`} (PFR not yet updated)` : 'YBC/YAC not yet available';
}

export function StatStrip({ title, m, kind, note, team }: { title: string; m: Overall; kind: 'offense' | 'defense'; note: string | null; team: string }) {
  const items: [string, number | null | undefined, Parameters<typeof formatCell>[1], Metrics['ranks'][keyof Metrics['ranks']]][] = [
    ['Success', m.sr, 'pct', m.ranks.sr],
    ['YPC', m.ypc, 'dec1', m.ranks.ypc],
    ['Explosive', m.expl, 'pct', m.ranks.expl],
    [kind === 'offense' ? 'Stuffed' : 'Stuffs', m.stuff, 'pct', m.ranks.stuff],
    ['YBC/att', m.ybc_att, 'dec1', m.ranks.ybc_att],
  ];
  if (kind === 'offense') items.push(['YAC/att', m.yac_att, 'dec1', m.ranks.yac_att]);
  return (
    <div className="rounded-md border border-line bg-panel px-3 py-2">
      <p className="text-[11px] text-ink-3">
        <span className="font-semibold text-ink">{title}</span>
        {kind === 'offense' ? (
          <>
            {' '}· {m.att} carries{m.games ? `, ${m.games} games` : ''}
            {m.carry_share != null && ` · ${formatCell(m.carry_share, 'pct')} of ${team} designed runs`}
            {m.snap_share != null && `, ${formatCell(m.snap_share, 'pct')} of snaps`} · ranks among RBs
          </>
        ) : (
          <>
            {' '}· {m.att} designed runs faced, {m.games} games{m.qb_att ? ` (${m.qb_att} by QBs)` : ''} · ranks among defenses
          </>
        )}
        {note && <span className="text-warn"> · {note}</span>}
      </p>
      <dl className="num mt-1 grid grid-cols-3 gap-x-3 gap-y-1.5 sm:grid-cols-6">
        {items.map(([k, v, f, r]) => (
          <div key={k}>
            <dt className="text-[10px] uppercase tracking-wider text-ink-3">{k}</dt>
            <dd className="text-[13px]">
              <Stat v={v} fmt={f} rank={r} />
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** A team's backfield: depth-chart RBs, other rushers, QB runs and the team total (current season), or this season's backs' prior-season lines. */
export function Backs({ rows, current, onPick, selected }: { rows: Rusher[]; current: boolean; onPick: (id: string) => void; selected?: string }) {
  const list = rows.filter((r) => current || r.att > 0);
  if (!list.length) return <p className="text-[12px] text-ink-3">No carries for these backs in this season.</p>;
  const cols: [string, string][] = current
    ? [['Role', ''], ['Att', ''], ['Carry %', 'Share of the team’s designed runs'], ['Snap %', 'Share of offensive snaps'], ['Success', ''], ['YPC', ''], ['YBC', 'Yards before contact per carry (PFR)'], ['YAC', 'Yards after contact per carry (PFR)']]
    : [['Team', ''], ['Att', ''], ['Success', ''], ['YPC', ''], ['YBC', 'Yards before contact per carry (PFR)'], ['YAC', 'Yards after contact per carry (PFR)']];
  return (
    <>
      <div className="overflow-x-auto rounded border border-line">
        <table className="num w-full min-w-[640px] border-collapse text-[12px]">
          <thead className="bg-panel-2/70 text-[10.5px] uppercase tracking-wider text-ink-3">
            <tr>
              <th className="sticky left-0 z-10 bg-panel-2 px-3 py-1.5 text-left font-medium">Player</th>
              {cols.map(([h, t]) => (
                <th key={h} title={t || undefined} className="px-2 py-1.5 text-right font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list.map((r) => {
              const pickable = r.kind === 'rb' || r.kind === 'other';
              return (
                <tr key={r.id} className={`border-t border-line/50 ${r.kind === 'total' ? 'border-line-2 font-semibold' : ''} ${r.kind === 'qb' ? 'text-ink-2' : ''}`}>
                  <th scope="row" className="sticky left-0 z-10 bg-panel px-3 py-1.5 text-left font-medium">
                    {pickable && r.id !== selected ? (
                      <button type="button" onClick={() => onPick(r.id)} className="text-left text-accent hover:underline">
                        {r.name}
                      </button>
                    ) : (
                      <span className={r.id === selected ? 'text-accent' : ''}>{r.name}{r.id === selected ? ' ◂' : ''}</span>
                    )}
                    {r.note && <span className="block text-[10.5px] font-normal text-ink-3">{r.note}</span>}
                  </th>
                  <td className="px-2 py-1.5 text-right text-ink-2">{r.role}</td>
                  <td className="px-2 py-1.5 text-right">{r.att}</td>
                  {current && <td className="px-2 py-1.5 text-right">{formatCell(r.carry_share ?? null, 'pct')}</td>}
                  {current && <td className="px-2 py-1.5 text-right">{formatCell(r.snap_share ?? null, 'pct')}</td>}
                  <td className="px-2 py-1.5 text-right"><Stat v={r.sr} fmt="pct" rank={r.ranks.sr} /></td>
                  <td className="px-2 py-1.5 text-right"><Stat v={r.ypc} fmt="dec1" rank={r.ranks.ypc} /></td>
                  <td className="px-2 py-1.5 text-right">{formatCell(r.ybc_att, 'dec1')}</td>
                  <td className="px-2 py-1.5 text-right">{formatCell(r.yac_att, 'dec1')}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[10.5px] text-ink-3">
        Rusher ranks: non-QB rushers who meet the qualifier. {current ? 'RBs in depth-chart order; QB rows are unranked and show no YBC/YAC (PFR includes scrambles).' : 'Each player’s full prior-season line, whichever team he played for.'}
      </p>
    </>
  );
}

export function PlayerPicker({ players, value, onChange }: { players: PlayerEntry[]; value: PlayerEntry; onChange: (p: PlayerEntry) => void }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const matches = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = s ? players.filter((p) => `${p.name} ${p.team} ${p.pos}`.toLowerCase().includes(s)) : players;
    return list.slice(0, 40);
  }, [q, players]);
  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const pick = (p: PlayerEntry) => {
    onChange(p);
    setQ('');
    setOpen(false);
  };
  const tag = (p: PlayerEntry) => `${p.team} ${p.depth ?? p.pos}`;
  return (
    <div ref={box} className="relative">
      <label className="flex flex-col gap-1 text-[10.5px] font-medium uppercase tracking-wider text-ink-3">
        Player
        <input
          role="combobox"
          aria-expanded={open}
          aria-controls="player-list"
          value={open ? q : `${value.name} · ${tag(value)}`}
          onFocus={() => {
            setOpen(true);
            setHi(0);
          }}
          onChange={(e) => {
            setQ(e.target.value);
            setHi(0);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') setHi((h) => Math.min(h + 1, matches.length - 1));
            else if (e.key === 'ArrowUp') setHi((h) => Math.max(h - 1, 0));
            else if (e.key === 'Enter' && matches[hi]) pick(matches[hi]);
            else if (e.key === 'Escape') setOpen(false);
          }}
          placeholder="Search RB or team"
          className="h-8 w-[min(20rem,calc(100vw-2rem))] rounded border border-line-2 bg-panel-2 px-2 text-[13px] normal-case tracking-normal text-ink placeholder:text-ink-3"
        />
      </label>
      {open && (
        <ul id="player-list" role="listbox" className="absolute z-30 mt-1 max-h-80 w-[min(20rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-line-2 bg-panel-2 py-1 shadow-lg">
          {matches.length === 0 && <li className="px-3 py-2 text-ink-3">No match</li>}
          {matches.map((p, i) => (
            <li key={p.id} role="option" aria-selected={i === hi}>
              <button type="button" onMouseEnter={() => setHi(i)} onClick={() => pick(p)} className={`flex w-full items-center gap-2 px-3 py-1.5 text-left ${i === hi ? 'bg-raise' : ''}`}>
                <TeamLogo team={p.team} size={18} />
                <span className="flex-1 truncate">{p.name}</span>
                <span className="text-[11px] text-ink-3">{tag(p)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Footer({ report }: { report: WeekReport }) {
  const block = (title: string, items: string[]) => (
    <div>
      <h3 className="mb-1 text-[11px] uppercase tracking-wider text-ink-3">{title}</h3>
      <ul className="list-disc space-y-0.5 pl-4 text-[11.5px] leading-relaxed text-ink-2 marker:text-ink-3">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
  return (
    <footer className="mt-6 border-t border-line pt-4">
      <details>
        <summary className="cursor-pointer text-[12px] text-ink-2 hover:text-ink">How to read this · data, filters and qualifiers</summary>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          {block('Run Edge', [report.edge.definition, ...report.edge.bands.map((b) => `${b.label}: ${b.min}+`), 'The player page scores any RB against any defense the same way, from the same numbers.'])}
          {block('Notes', report.notes)}
          {block('Filters (designed runs)', report.filters)}
          {block('Rank qualifiers', report.qualifiers)}
          {block('Data sources', report.sources)}
          {report.scheme && block('Run scheme (Data Suite)', [report.scheme.status ?? `Export of ${report.scheme.exported_at?.replace('T', ' ').replace('Z', ' UTC')} used for this week.`, ...(report.scheme.note ? [report.scheme.note] : []), report.scheme.qualifier])}
          {block('Validation checks run for this week', report.checks)}
        </div>
      </details>
      <p className="mt-2 text-[11px] text-ink-3">
        Generated {report.generated_at.replace('T', ' ').replace('Z', ' UTC')} · data as of {formatDate(report.data_as_of, { month: 'short', day: 'numeric', year: 'numeric' })}. Small samples are noisy; read every rate next to its attempts.
      </p>
    </footer>
  );
}
