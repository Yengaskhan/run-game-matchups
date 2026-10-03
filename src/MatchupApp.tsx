import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { defaultWeek, listSeasons, loadWeek } from './data';
import { formatCell, formatDate, formatKickoff } from './format';
import { TeamLogo, teamName } from './TeamLogo';
import type { BandKey, MatchupRow, Metrics, Rank, SeasonBlock, Split, WeekReport } from './types';

/** True when the page runs inside an iframe (e.g. embedded on a website-builder page). */
const embedded = (() => {
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
})();

type SplitKey = 'all' | 'left' | 'middle' | 'right';
type SortKey = 'offense' | 'defense' | 'off_sr' | 'off_ypc' | 'def_sr' | 'def_ypc' | 'share' | 'edge';

/** Selection lives in the URL hash so a view can be linked directly. */
function readHash() {
  const p = new URLSearchParams(window.location.hash.slice(1));
  return { week: Number(p.get('week')) || null, season: p.get('season'), split: (p.get('split') as SplitKey) || 'all', open: p.get('open') };
}

// ------------------------------------------------------------------------------------------------
// Small pieces
// ------------------------------------------------------------------------------------------------

const BAND_STYLE: Record<BandKey, string> = {
  big_edge: 'bg-edge-good/30 text-edge-good border-edge-good/60',
  small_edge: 'bg-edge-good/10 text-edge-good border-edge-good/30',
  neutral: 'bg-raise text-ink-2 border-line-2',
  small_disadvantage: 'bg-edge-bad/10 text-edge-bad border-edge-bad/30',
  big_disadvantage: 'bg-edge-bad/30 text-edge-bad border-edge-bad/60',
};

function bandFor(edge: number | null, bands: WeekReport['edge']['bands']): BandKey {
  if (edge == null) return 'neutral';
  return bands.find((b) => edge >= b.min)?.key ?? 'neutral';
}

function EdgeBadge({ edge, band, small, title }: { edge: number | null; band: BandKey; small?: boolean; title?: string }) {
  if (edge == null) return <span className="text-ink-3" title="Not ranked: one side is below the rank qualifier">—</span>;
  return (
    <span
      title={title ?? (small ? 'Small sample: too few ranked runs to shade' : undefined)}
      className={`num inline-flex h-6 min-w-[2.5rem] items-center justify-center rounded border px-1.5 text-[12.5px] font-semibold ${BAND_STYLE[small ? 'neutral' : band]} ${small ? 'border-dashed' : ''}`}
    >
      {edge}
    </span>
  );
}

/** "rank/peer · n=att" under a value. `unrankable` values (e.g. shares) show only n. Unranked = "—". */
function RankLine({ rank, n, unrankable }: { rank?: Rank; n?: number; unrankable?: boolean }) {
  const top = rank && rank[1] > 1 && (rank[0] - 1) / (rank[1] - 1) <= 0.25;
  return (
    <span className="block text-[10.5px] leading-3 text-ink-3">
      {!unrankable && (rank ? <span className={top ? 'text-accent' : ''}>{rank[0]}/{rank[1]}</span> : '—')}
      {n != null && <>{unrankable ? '' : ' · '}n={n}</>}
    </span>
  );
}

function Stat({ v, fmt, rank, n }: { v: number | null | undefined; fmt: Parameters<typeof formatCell>[1]; rank?: Rank; n?: number }) {
  return (
    <>
      <span className="block">{formatCell(v, fmt)}</span>
      {(rank || n != null) && <RankLine rank={rank} n={n} />}
    </>
  );
}

// ------------------------------------------------------------------------------------------------
// Page
// ------------------------------------------------------------------------------------------------

export default function MatchupApp() {
  const index = useMemo(() => listSeasons()[0] ?? null, []);
  const initial = useMemo(readHash, []);
  const [week, setWeek] = useState<number | null>(() =>
    index ? (index.weeks.some((w) => w.week === initial.week) ? initial.week : defaultWeek(index)) : null,
  );
  const [report, setReport] = useState<WeekReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [season, setSeason] = useState<string | null>(initial.season);
  const [split, setSplit] = useState<SplitKey>(initial.split);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'edge', desc: true });
  const [open, setOpen] = useState<string | null>(initial.open);

  useEffect(() => {
    const w = index?.weeks.find((x) => x.week === week);
    if (!w) return;
    let live = true;
    loadWeek(w.path)
      .then((r) => {
        if (!live) return;
        setReport(r);
        setError(null);
        // Keep the chosen season if this week has it; otherwise the current season, or the prior one when it's empty.
        setSeason((s) => (r.seasons.some((x) => String(x.season) === s) ? s : String((r.seasons.find((x) => x.current && !x.empty) ?? r.seasons[1]).season)));
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [week]);

  useEffect(() => {
    if (!week || !season) return;
    const p = new URLSearchParams({ week: String(week), season, split });
    if (open) p.set('open', open);
    history.replaceState(null, '', `#${p}`);
  }, [week, season, split, open]);

  const seasonMeta = report?.seasons.find((s) => String(s.season) === season) ?? null;
  const games = useMemo(() => new Map(report?.games.map((g) => [g.game_id, g]) ?? []), [report]);

  /** The numbers the main table shows for a row: overall, or one direction when a split is picked. */
  const summary = (row: MatchupRow) => {
    const b = season ? row.seasons[season] : null;
    if (!b) return null;
    if (split === 'all') {
      return { b, off: b.overall.off as Metrics, def: b.overall.def as Metrics, share: b.top_direction, edge: b.run_edge, small: b.small_sample, band: b.band };
    }
    const s = b.splits.find((x) => x.group === 'direction' && x.key === split);
    if (!s) return null;
    return { b, off: s.off, def: s.def, share: { key: s.key, label: s.label, share: s.off.share ?? 0, att: s.off.att }, edge: s.edge, small: false, band: bandFor(s.edge, report!.edge.bands) };
  };

  const rows = useMemo(() => {
    if (!report) return [];
    const q = query.trim().toUpperCase();
    const list = report.rows
      .filter((r) => !q || r.offense.includes(q) || r.defense.includes(q) || (r.starter?.name.toUpperCase().includes(q) ?? false))
      .map((r) => ({ r, s: summary(r) }));
    const val = (x: (typeof list)[number]): number | string | null => {
      switch (sort.key) {
        case 'offense':
          return x.r.starter?.name ?? x.r.offense;
        case 'defense':
          return x.r.defense;
        case 'off_sr':
          return x.s?.off.sr ?? null;
        case 'off_ypc':
          return x.s?.off.ypc ?? null;
        // Defense columns: lower allowed is better, so sorting "best first" means ascending.
        case 'def_sr':
          return x.s?.def.sr == null ? null : -x.s.def.sr;
        case 'def_ypc':
          return x.s?.def.ypc == null ? null : -x.s.def.ypc;
        case 'share':
          return x.s?.share?.share ?? null;
        case 'edge':
          return x.s?.edge ?? null;
      }
    };
    return list.sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      if (va == null) return 1; // blanks always last
      if (vb == null) return -1;
      const c = typeof va === 'string' ? va.localeCompare(vb as string) : va - (vb as number);
      return sort.desc ? -c : c;
    });
  }, [report, season, split, query, sort]);

  const Th = ({ k, children, className = '' }: { k?: SortKey; children: ReactNode; className?: string }) => (
    <th scope="col" className={`whitespace-nowrap px-3 py-2 text-[10.5px] font-medium uppercase tracking-wider text-ink-3 ${className}`} aria-sort={k && sort.key === k ? (sort.desc ? 'descending' : 'ascending') : undefined}>
      {k ? (
        <button type="button" onClick={() => setSort((s) => ({ key: k, desc: s.key === k ? !s.desc : k !== 'offense' && k !== 'defense' }))} className="inline-flex items-center gap-1 rounded border border-line-2 bg-panel-2 px-1.5 py-0.5 uppercase hover:border-ink-3 hover:text-ink">
          {children}
          <span aria-hidden className={sort.key === k ? 'text-accent' : 'text-ink-3/60'}>{sort.key === k ? (sort.desc ? '▼' : '▲') : '↕'}</span>
        </button>
      ) : (
        children
      )}
    </th>
  );

  const splitLabel = split === 'all' ? null : split[0].toUpperCase() + split.slice(1);

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-line bg-bg/95 px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-sm bg-accent" aria-hidden />
          <span className="text-[13px] font-semibold tracking-tight">
            ClevAnalytics <span className="font-normal text-ink-2">Run Game Matchups</span>
          </span>
          {embedded && (
            <a href={window.location.href} target="_blank" rel="noopener" className="ml-auto text-[12px] text-accent hover:underline">
              Open full screen ↗
            </a>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1320px] flex-1 px-4 py-5">
        {!index && <p className="text-ink-2">No reports yet. Run the pipeline (see README) and commit data/.</p>}
        {error && <p className="text-bad">{error}</p>}

        {index && (
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                {index.season} Week {week} preview
              </p>
              <h1 className="text-[22px] font-semibold tracking-tight">Run Game Matchup Report</h1>
              <p className="text-[12px] text-ink-2">Each team's starting RB, on his own carries, against the opponent's run defense, by where he runs.</p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <Select label="Week" value={String(week ?? '')} onChange={(v) => (setWeek(Number(v)), setOpen(null))}
                options={index.weeks.map((w) => [String(w.week), `Week ${w.week} · ${formatDate(w.first_gameday, { month: 'short', day: 'numeric' })}`])} />
              {report && (
                <Select label="Season" value={season ?? ''} onChange={setSeason} options={report.seasons.map((s) => [String(s.season), s.label])} />
              )}
              <Select label="Split" value={split} onChange={(v) => setSplit(v as SplitKey)}
                options={[['all', 'All runs'], ['left', 'Left'], ['middle', 'Middle'], ['right', 'Right']]} />
              <label className="flex flex-col gap-1 text-[10.5px] font-medium uppercase tracking-wider text-ink-3">
                Find team or RB
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Team or RB" className="h-8 w-32 rounded border border-line-2 bg-panel-2 px-2 text-[13px] normal-case tracking-normal text-ink placeholder:text-ink-3" />
              </label>
            </div>
          </div>
        )}

        {report && (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-1.5 text-[11px]">
              {report.edge.bands.map((b) => (
                <span key={b.key} className={`rounded border px-2 py-1 ${BAND_STYLE[b.key]}`}>
                  {b.key === 'neutral' ? 'Neutral / small sample' : b.label}
                </span>
              ))}
              <span className="ml-1 text-ink-3">
                Run Edge 0–100, 50 = even. Data as of {formatDate(report.data_as_of, { month: 'short', day: 'numeric', year: 'numeric' })}. Left / right = the offense's left / right.
              </span>
            </div>

            {seasonMeta && !seasonMeta.current && (
              <p className="mt-3 rounded-md border border-line-2 bg-panel-2 px-3 py-2 text-[12px] text-ink-2">
                <span className="font-semibold text-ink">Prior season: {seasonMeta.label}.</span> This week's matchups scored with last season's numbers
                only, not this season's. Rosters and schemes have changed since.
              </p>
            )}
            {seasonMeta?.empty ? (
              <p className="mt-4 rounded-md border border-line bg-panel px-3 py-3 text-[12.5px] text-ink-2">{seasonMeta.empty}</p>
            ) : (
              <div className="mt-3 overflow-x-auto rounded-md border border-line bg-panel">
                <table className="num w-full min-w-[1040px] border-collapse text-[12.5px]">
                  <thead className="border-b border-line bg-panel-2/60">
                    <tr className="text-left">
                      <Th k="offense" className="sticky left-0 z-10 bg-panel-2">Starting RB</Th>
                      <Th k="defense" className="hidden sm:table-cell">Opponent</Th>
                      <Th k="off_sr" className="text-right">{splitLabel ? `RB Succ. · ${splitLabel}` : 'RB Success'}</Th>
                      <Th k="off_ypc" className="text-right">{splitLabel ? `RB YPC · ${splitLabel}` : 'RB YPC'}</Th>
                      <Th k="def_sr" className="text-right">{splitLabel ? `Def Succ. al. · ${splitLabel}` : 'Def Succ. allowed'}</Th>
                      <Th k="def_ypc" className="text-right">{splitLabel ? `Def YPC al. · ${splitLabel}` : 'Def YPC allowed'}</Th>
                      <Th k="share" className="text-right">{splitLabel ? `${splitLabel} share` : 'Main direction'}</Th>
                      <Th k="edge" className="text-center">Run edge</Th>
                      <Th className="text-center">View</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(({ r, s }) => {
                      const id = `${r.offense}`;
                      const isOpen = open === id;
                      const g = games.get(r.game_id);
                      return (
                        <Fragment key={id}>
                          <tr className={`border-t border-line/70 ${isOpen ? 'bg-panel-2/60' : 'hover:bg-panel-2/40'}`}>
                            <th scope="row" className={`sticky left-0 z-10 px-3 py-2 text-left font-semibold ${isOpen ? 'bg-[#141a23]' : 'bg-panel'}`}>
                              <span className="flex items-center justify-between gap-3">
                                <span className="flex items-center gap-2.5" title={teamName(r.offense)}>
                                  <TeamLogo team={r.offense} size={28} />
                                  <span>
                                    <span className="block whitespace-nowrap text-[14px] leading-tight">{r.starter?.name ?? `${r.offense} (no RB listed)`}</span>
                                    <span className="block whitespace-nowrap text-[11px] font-normal text-ink-2">
                                      {r.offense}
                                      {starterLine(r, s?.b ?? null)}
                                    </span>
                                  </span>
                                </span>
                                {/* Phones: the edge column is off-screen, so show the badge here too. */}
                                <span className="sm:hidden">{s ? <EdgeBadge edge={s.edge} band={s.band} small={s.small} /> : null}</span>
                              </span>
                              <span className="block pl-[38px] text-[10.5px] font-normal text-ink-3">
                                <span className="sm:hidden">{r.home ? 'vs' : '@'} {r.defense} · </span>
                                {g ? `${formatDate(g.gameday, { weekday: 'short' })} ${formatKickoff(g.gametime)}` : ''}
                              </span>
                            </th>
                            <td className="hidden px-3 py-2 text-ink-2 sm:table-cell">
                              <span className="inline-flex items-center gap-1.5" title={teamName(r.defense)}>
                                {r.home ? 'vs' : '@'} <TeamLogo team={r.defense} size={20} /> <span className="font-semibold text-ink">{r.defense}</span>
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right">{s ? <Stat v={s.off.sr} fmt="pct" rank={s.off.ranks.sr} n={s.off.att} /> : '—'}</td>
                            <td className="px-3 py-2 text-right">{s ? <Stat v={s.off.ypc} fmt="dec1" rank={s.off.ranks.ypc} /> : '—'}</td>
                            <td className="px-3 py-2 text-right">{s ? <Stat v={s.def.sr} fmt="pct" rank={s.def.ranks.sr} n={s.def.att} /> : '—'}</td>
                            <td className="px-3 py-2 text-right">{s ? <Stat v={s.def.ypc} fmt="dec1" rank={s.def.ranks.ypc} /> : '—'}</td>
                            <td className="px-3 py-2 text-right">
                              {s?.share ? (
                                <>
                                  <span className="block">{split === 'all' ? `${s.share.label} ${formatCell(s.share.share, 'pct')}` : formatCell(s.share.share, 'pct')}</span>
                                  <RankLine n={s.share.att} unrankable />
                                </>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="px-3 py-2 text-center">{s ? <EdgeBadge edge={s.edge} band={s.band} small={s.small} /> : '—'}</td>
                            <td className="px-3 py-2 text-center">
                              <button
                                type="button"
                                aria-expanded={isOpen}
                                onClick={() => setOpen(isOpen ? null : id)}
                                className={`inline-flex h-7 items-center gap-1 whitespace-nowrap rounded border px-2.5 text-[12px] ${isOpen ? 'border-accent/70 bg-accent/10 text-ink' : 'border-line-2 text-ink-2 hover:border-ink-3 hover:text-ink'}`}
                              >
                                {isOpen ? 'Hide ▴' : 'View ▾'}
                              </button>
                            </td>
                          </tr>
                          {isOpen && s && (
                            <tr>
                              <td colSpan={9} className="border-t border-line bg-bg/60 p-0">
                                {/* Pinned to the visible width, so on phones it doesn't scroll sideways with the list. */}
                                <div className="sticky left-0 max-w-[calc(100vw-2rem-2px)]">
                                  <Detail row={r} b={s.b} report={report} onClose={() => setOpen(null)} />
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                    {!rows.length && (
                      <tr>
                        <td colSpan={9} className="px-3 py-6 text-center text-ink-3">
                          No team matches "{query}".
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
            <Footer report={report} />
          </>
        )}
      </main>
    </div>
  );
}

/** " · 40 carries, 82% of runs" for the starter in the selected season ("in 2025" for the prior season, any team). */
function starterLine(r: MatchupRow, b: SeasonBlock | null): string {
  if (!r.starter || !b) return '';
  const p = b.rushers.find((x) => x.id === r.starter!.id);
  const current = b.rushers.some((x) => x.kind === 'total'); // only current-season blocks carry a team total row
  if (!p?.att) return current ? ' · no carries yet' : ` · no ${b.season} carries`;
  return current ? ` · ${p.att} carries, ${formatCell(p.carry_share ?? null, 'pct')} of runs` : ` · ${p.att} carries in ${b.season}`;
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className="flex flex-col gap-1 text-[10.5px] font-medium uppercase tracking-wider text-ink-3">
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

// ------------------------------------------------------------------------------------------------
// Detail (the "View" row)
// ------------------------------------------------------------------------------------------------

function Detail({ row, b, report, onClose }: { row: MatchupRow; b: SeasonBlock; report: WeekReport; onClose: () => void }) {
  const g = report.games.find((x) => x.game_id === row.game_id);
  const meta = report.seasons.find((s) => s.season === b.season)!;
  // PFR (YBC / YAC) can trail play-by-play by a day or two; say which weeks it covers when it does.
  const pw = meta.pfr_weeks ?? meta.weeks;
  const pfrNote = pw.length === meta.weeks.length ? null : pw.length ? `YBC/YAC: ${pw.length === 1 ? `week ${pw[0]}` : `weeks ${pw[0]}–${pw[pw.length - 1]}`} (PFR not yet updated)` : 'YBC/YAC not yet available';
  const off = row.offense;
  const dfn = row.defense;
  const o = b.overall.off;
  const d = b.overall.def;
  const rb = b.subject?.name ?? teamName(off);
  const groups: [Split['group'], string][] = [
    ['direction', 'Direction'],
    ['gap', 'Gap'],
    ['box', 'Box count (FTN)'],
  ];
  return (
    <div className="px-3 py-3 sm:px-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[16px] font-semibold">
            <TeamLogo team={off} size={28} /> {rb} <span className="text-[13px] font-normal text-ink-3">({off})</span> <span className="text-ink-3">{row.home ? 'vs' : '@'}</span>
            <TeamLogo team={dfn} size={28} /> {teamName(dfn)} run defense
          </h2>
          <p className="text-[11.5px] text-ink-3">
            {g && `${formatDate(g.gameday)} · ${formatKickoff(g.gametime)}${g.stadium ? ` · ${g.stadium}` : ''} · `}
            <span className={meta.current ? 'text-accent' : 'text-ink-2'}>{meta.current ? `Current season: ${meta.label}` : `Prior season: ${meta.label}`}</span>
            {' · '}designed runs only; ranks are rank/peer group, n = attempts
          </p>
        </div>
        <button type="button" onClick={onClose} className="h-7 rounded border border-line-2 px-2.5 text-[12px] text-ink-2 hover:border-ink-3 hover:text-ink">
          Close
        </button>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-2">
        <StatStrip title={rb} m={o} kind="offense" pfrNote={pfrNote} team={off} />
        <StatStrip title={`${dfn} defense allowed`} m={d} kind="defense" pfrNote={pfrNote} team={dfn} />
      </div>

      <div className="mt-3 overflow-x-auto rounded border border-line">
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
            {groups.map(([grp, label]) => {
              const splits = b.splits.filter((s) => s.group === grp);
              if (!splits.length) return null;
              return (
                <Fragment key={grp}>
                  <tr className="border-t border-line bg-panel-2/40">
                    <th colSpan={10} scope="rowgroup" className="sticky left-0 px-3 py-1 text-left text-[10.5px] font-semibold uppercase tracking-wider text-ink-3">
                      {label}
                    </th>
                  </tr>
                  {splits.map((s) => (
                    <tr key={s.key} className="border-t border-line/50">
                      <th scope="row" className="sticky left-0 z-10 bg-panel px-3 py-1.5 text-left font-medium">{s.label}</th>
                      <SplitCells m={s.off} first />
                      <SplitCells m={s.def} first />
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

      {b.takeaways.length > 0 && (
        <ul className="mt-3 list-disc space-y-0.5 pl-5 text-[12px] text-ink-2 marker:text-ink-3">
          {b.takeaways.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
      )}

      <Backs b={b} team={off} current={meta.current} />
    </div>
  );
}

function SplitCells({ m, first }: { m: Metrics; first?: boolean }) {
  return (
    <>
      <td className={`px-2 py-1.5 text-right text-ink-2 ${first ? 'border-l border-line' : ''}`}>{m.att}</td>
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

function StatStrip({ title, m, kind, pfrNote, team }: { title: string; m: SeasonBlock['overall']['off']; kind: 'offense' | 'defense'; pfrNote: string | null; team: string }) {
  const items: [string, number | null, Parameters<typeof formatCell>[1], Rank | undefined][] = [
    ['Success', m.sr, 'pct', m.ranks.sr],
    ['YPC', m.ypc, 'dec1', m.ranks.ypc],
    ['Explosive', m.expl, 'pct', m.ranks.expl],
    [kind === 'offense' ? 'Stuffed' : 'Stuffs', m.stuff, 'pct', m.ranks.stuff],
    ['YBC/att', m.ybc_att, 'dec1', m.ranks.ybc_att],
  ];
  if (kind === 'offense') items.push(['YAC/att', m.yac_att, 'dec1', m.ranks.yac_att]);
  return (
    <div className="rounded border border-line bg-panel px-3 py-2">
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
        {pfrNote && <span className="text-warn"> · {pfrNote}</span>}
      </p>
      <dl className="num mt-1 grid grid-cols-4 gap-x-3 gap-y-1.5 sm:grid-cols-7">
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

function Backs({ b, team, current }: { b: SeasonBlock; team: string; current: boolean }) {
  const rows = b.rushers.filter((r) => current || r.att > 0);
  if (!rows.length) return null;
  const cols: [string, string][] = current
    ? [['Role', ''], ['Att', ''], ['Carry %', 'Share of the team’s designed runs'], ['Snap %', 'Share of offensive snaps'], ['Success', ''], ['YPC', ''], ['YBC', 'Yards before contact per carry (PFR)'], ['YAC', 'Yards after contact per carry (PFR)']]
    : [['Team', ''], ['Att', ''], ['Success', ''], ['YPC', ''], ['YBC', 'Yards before contact per carry (PFR)'], ['YAC', 'Yards after contact per carry (PFR)']];
  return (
    <div className="mt-3">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
        {current ? `${team} backs` : `${team}'s current backs, ${b.season} line`}
      </h3>
      <div className="mt-1 overflow-x-auto rounded border border-line">
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
            {rows.map((r) => (
              <tr key={r.id} className={`border-t border-line/50 ${r.kind === 'total' ? 'border-line-2 font-semibold' : ''} ${r.kind === 'qb' ? 'text-ink-2' : ''}`}>
                <th scope="row" className="sticky left-0 z-10 bg-panel px-3 py-1.5 text-left font-medium">
                  {r.name}
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
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[10.5px] text-ink-3">
        Rusher ranks: non-QB rushers who meet the qualifier. {current ? 'RBs in depth-chart order; QB rows are unranked and show no YBC/YAC (PFR includes scrambles).' : 'Each player’s full prior-season line, whichever team he played for.'}
      </p>
    </div>
  );
}

function Footer({ report }: { report: WeekReport }) {
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
          {block('Run Edge', [report.edge.definition, ...report.edge.bands.map((b) => `${b.label}: ${b.min}+`)])}
          {block('Notes', report.notes)}
          {block('Filters (designed runs)', report.filters)}
          {block('Rank qualifiers', report.qualifiers)}
          {block('Data source: nflverse', report.sources)}
          {block('Validation checks run for this week', report.checks)}
        </div>
      </details>
      <p className="mt-2 text-[11px] text-ink-3">Generated {report.generated_at.replace('T', ' ').replace('Z', ' UTC')}. Small samples are noisy; read every rate next to its attempts.</p>
    </footer>
  );
}
