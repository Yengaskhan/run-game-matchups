import { useMemo, useState, type ReactNode } from 'react';
import { bandFor } from './edge';
import { formatCell, formatDate, formatKickoff } from './format';
import type { HashState, Update } from './MatchupApp';
import { TeamLogo, teamName } from './TeamLogo';
import type { BandKey, MatchupRow, Metrics, SchemeSide, SeasonBlock, WeekReport } from './types';
import { EdgeBadge, RankLine, Select, SortTh, Stat, type SortState } from './ui';

type SplitKey = 'all' | 'left' | 'middle' | 'right' | 'zone' | 'gap';
type SortKey = 'offense' | 'defense' | 'off_sr' | 'off_ypc' | 'def_sr' | 'def_ypc' | 'share' | 'edge';
const SPLITS: [SplitKey, string][] = [['all', 'All runs'], ['left', 'Left'], ['middle', 'Middle'], ['right', 'Right'], ['zone', 'Zone runs (Data Suite)'], ['gap', 'Man/gap runs (Data Suite)']];

interface Summary {
  b: SeasonBlock;
  off: Pick<Metrics, 'att' | 'sr' | 'ypc' | 'ranks'> | null;
  def: Pick<Metrics, 'att' | 'sr' | 'ypc' | 'ranks'> | null;
  share: { label: string; share: number; att: number } | null;
  edge: number | null;
  small: boolean;
  band: BandKey;
}

/** Every starting RB this week against his opponent; click a row for the player page. */
export function SlateView({ report, season, hash, update }: { report: WeekReport; season: string; hash: HashState; update: Update }) {
  const split = (SPLITS.some(([k]) => k === hash.split) ? hash.split : 'all') as SplitKey;
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SortState<SortKey>>({ key: 'edge', desc: true });
  const seasonMeta = report.seasons.find((s) => String(s.season) === season)!;
  const games = useMemo(() => new Map(report.games.map((g) => [g.game_id, g])), [report]);

  /** The numbers the table shows for a row: overall, or one direction / run scheme when a split is picked. */
  const summary = (row: MatchupRow): Summary | null => {
    const b = row.seasons[season];
    if (!b) return null;
    if (split === 'all') return { b, off: b.overall.off, def: b.overall.def, share: b.top_direction, edge: b.run_edge, small: b.small_sample, band: b.band };
    if (split === 'zone' || split === 'gap') {
      // Run scheme (Data Suite): current season only; the defense side waits for its own export.
      const sc = b.scheme?.rows.find((x) => x.key === split);
      if (!sc) return null;
      const side = (x: SchemeSide | null) => x && { att: x.att, sr: x.sr, ypc: x.ypc, ranks: x.ranks };
      return { b, off: side(sc.off), def: side(sc.def), share: { label: sc.label, share: sc.off.share ?? 0, att: sc.off.att }, edge: sc.edge, small: false, band: bandFor(sc.edge, report.edge.bands) };
    }
    const s = b.splits.find((x) => x.group === 'direction' && x.key === split);
    if (!s) return null;
    return { b, off: s.off, def: s.def, share: { label: s.label, share: s.off.share ?? 0, att: s.off.att }, edge: s.edge, small: false, band: bandFor(s.edge, report.edge.bands) };
  };

  const rows = useMemo(() => {
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
          return x.s?.off?.sr ?? null;
        case 'off_ypc':
          return x.s?.off?.ypc ?? null;
        // Defense columns: lower allowed is better, so sorting "best first" means ascending.
        case 'def_sr':
          return x.s?.def?.sr == null ? null : -x.s.def.sr;
        case 'def_ypc':
          return x.s?.def?.ypc == null ? null : -x.s.def.ypc;
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

  const Th = (props: { k?: SortKey; className?: string; children: ReactNode }) => <SortTh sort={sort} setSort={setSort} textKeys={['offense', 'defense']} {...props} />;
  const splitLabel = split === 'all' ? null : split === 'zone' ? 'Zone' : split === 'gap' ? 'Man/gap' : split[0].toUpperCase() + split.slice(1);
  const open = (r: MatchupRow) => r.starter && update({ tab: 'player', player: r.starter.id, opp: r.defense });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Split" value={split} onChange={(v) => update({ split: v === 'all' ? undefined : v })} options={SPLITS} />
        <label className="flex flex-col gap-1 text-[10.5px] font-medium uppercase tracking-wider text-ink-3">
          Find team or RB
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Team or RB" className="h-8 w-36 rounded border border-line-2 bg-panel-2 px-2 text-[13px] normal-case tracking-normal text-ink placeholder:text-ink-3" />
        </label>
        <p className="pb-1.5 text-[12px] text-ink-3">Click a back for his player page, or an opponent for its defense profile.</p>
      </div>

      {(split === 'zone' || split === 'gap') && (
        <p className="rounded-md border border-line-2 bg-panel-2 px-3 py-2 text-[12px] text-ink-2">
          <span className="font-semibold text-ink">Run scheme: {split === 'zone' ? 'zone' : 'man/gap'} runs, from Data Suite.</span>{' '}
          {!seasonMeta.current
            ? 'These splits are current season only; switch Season data back to see them.'
            : !report.scheme
              ? 'This week was built before run-scheme splits were added, so there are none for it.'
              : (report.scheme.status ?? `Each RB's success rate and YPC on ${split === 'zone' ? 'zone' : 'man/gap'} runs, ranked among RBs. The defense side and Run Edge fill in once a Data Suite run-defense export is added.`)}
          {report.scheme?.note && seasonMeta.current && <span className="block text-ink-3">{report.scheme.note}</span>}
        </p>
      )}

      <div className="overflow-x-auto rounded-md border border-line bg-panel">
        <table className="num w-full min-w-[960px] border-collapse text-[12.5px]">
          <thead className="border-b border-line bg-panel-2/60">
            <tr className="text-left">
              <Th k="offense" className="sticky left-0 z-10 bg-panel-2">Starting RB</Th>
              <Th k="defense" className="hidden sm:table-cell">Opponent</Th>
              <Th k="off_sr" className="text-right">{splitLabel ? `RB Succ. · ${splitLabel}` : 'RB Success'}</Th>
              <Th k="off_ypc" className="text-right">{splitLabel ? `RB YPC · ${splitLabel}` : 'RB YPC'}</Th>
              <Th k="def_sr" className="text-right">{splitLabel ? `Def Succ. · ${splitLabel}` : 'Def Succ. allowed'}</Th>
              <Th k="def_ypc" className="text-right">{splitLabel ? `Def YPC · ${splitLabel}` : 'Def YPC allowed'}</Th>
              <Th k="share" className="text-right">{splitLabel ? `${splitLabel} share` : 'Main direction'}</Th>
              <Th k="edge" className="text-center">Run edge</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ r, s }) => {
              const g = games.get(r.game_id);
              return (
                <tr key={r.offense} onClick={() => open(r)} className={`border-t border-line/70 ${r.starter ? 'cursor-pointer hover:bg-panel-2/40' : ''}`}>
                  <th scope="row" className="sticky left-0 z-10 bg-panel px-3 py-2 text-left font-semibold">
                    <span className="flex items-center justify-between gap-3">
                      <span className="flex items-center gap-2.5" title={teamName(r.offense)}>
                        <TeamLogo team={r.offense} size={28} />
                        <span>
                          {r.starter ? (
                            <button type="button" onClick={(e) => (e.stopPropagation(), open(r))} className="block whitespace-nowrap text-left text-[14px] leading-tight hover:text-accent">
                              {r.starter.name}
                            </button>
                          ) : (
                            <span className="block whitespace-nowrap text-[14px] leading-tight">{r.offense} (no RB listed)</span>
                          )}
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
                    <button type="button" onClick={(e) => (e.stopPropagation(), update({ tab: 'defense', team: r.defense }))} className="inline-flex items-center gap-1.5 hover:text-accent" title={`${teamName(r.defense)} defense profile`}>
                      {r.home ? 'vs' : '@'} <TeamLogo team={r.defense} size={20} /> <span className="font-semibold text-ink">{r.defense}</span>
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right">{s?.off ? <Stat v={s.off.sr} fmt="pct" rank={s.off.ranks.sr} n={s.off.att} /> : '—'}</td>
                  <td className="px-3 py-2 text-right">{s?.off ? <Stat v={s.off.ypc} fmt="dec1" rank={s.off.ranks.ypc} /> : '—'}</td>
                  <td className="px-3 py-2 text-right">{s?.def ? <Stat v={s.def.sr} fmt="pct" rank={s.def.ranks.sr} n={s.def.att} /> : '—'}</td>
                  <td className="px-3 py-2 text-right">{s?.def ? <Stat v={s.def.ypc} fmt="dec1" rank={s.def.ranks.ypc} /> : '—'}</td>
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
                </tr>
              );
            })}
            {!rows.length && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-ink-3">
                  No team matches "{query}".
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
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
