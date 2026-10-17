import { useMemo } from 'react';
import { matchup } from './edge';
import { formatCell } from './format';
import type { HashState, Update } from './MatchupApp';
import { GROUP_LABEL, pfrNote, StatStrip } from './parts';
import { TeamLogo, teamName } from './TeamLogo';
import type { Metrics, PoolDefense, SplitGroup, WeekReport } from './types';
import { EdgeBadge, Panel, rankPhrase, Select } from './ui';

type Tone = 'good' | 'bad' | 'neutral';
const TONE_TEXT: Record<Tone, string> = { good: 'text-edge-good', bad: 'text-edge-bad', neutral: 'text-ink' };
const TONE_BAR: Record<Tone, string> = { good: 'bg-edge-good', bad: 'bg-edge-bad', neutral: 'bg-ink-3/70' };
/** Allowing more is good for the RB (green), less is bad (orange): the same colours as the edge. */
const allowTone = (v: number | null, league: number | null | undefined, band: number): Tone =>
  v == null || league == null ? 'neutral' : v > league + band ? 'good' : v < league - band ? 'bad' : 'neutral';

/** One run defense: what it allows overall and by direction, gap and box, and the backs who'd face it. */
export function DefenseView({ report, season, hash, update }: { report: WeekReport; season: string; hash: HashState; update: Update }) {
  const pool = report.pool[season]!;
  const teams = Object.keys(pool.defenses);
  const team = hash.team && pool.defenses[hash.team] ? hash.team : (report.rows[0]?.defense ?? teams[0]);
  const d = pool.defenses[team];
  const row = report.rows.find((r) => r.defense === team) ?? null;

  // This week's opponent's backs, and every team's starting RB scored against this defense.
  const facing = useMemo(() => {
    if (!row) return [];
    const ids = (row.seasons[season]?.rushers ?? []).filter((r) => (r.kind === 'rb' || r.kind === 'other') && r.att > 0).map((r) => r.id);
    if (row.starter && !ids.includes(row.starter.id)) ids.unshift(row.starter.id);
    return ids
      .map((id) => ({ id, name: report.players.find((p) => p.id === id)?.name ?? row.seasons[season]?.rushers.find((r) => r.id === id)?.name ?? id, team: row.offense, ps: pool.players[id] }))
      .map((x) => ({ ...x, m: matchup(x.ps, d, report) }));
  }, [report, season, team]);
  const league = useMemo(() => {
    const list = report.rows
      .filter((r) => r.starter && r.offense !== team && pool.players[r.starter.id])
      .map((r) => ({ id: r.starter!.id, name: r.starter!.name, team: r.offense, m: matchup(pool.players[r.starter!.id], d, report) }))
      .filter((x) => x.m.run_edge != null && !x.m.small)
      .sort((a, b) => b.m.run_edge! - a.m.run_edge!);
    return { best: list.slice(0, 5), worst: list.slice(-5).reverse() };
  }, [report, season, team]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Defense" value={team} onChange={(v) => update({ team: v })} options={teams.map((t) => [t, `${t} · ${teamName(t)}${report.rows.some((r) => r.defense === t) ? '' : ' (bye)'}`])} />
        <p className="pb-1.5 text-[12px] text-ink-3">
          {d.overall.games} games · {d.overall.att} designed runs faced
          {row ? ` · Week ${report.week}: ${row.home ? '@' : 'vs'} ${row.offense}` : ` · on bye in week ${report.week}`}
        </p>
      </div>

      <div className="flex items-center gap-3">
        <TeamLogo team={team} size={36} />
        <div>
          <h2 className="text-[18px] font-semibold">{teamName(team)} run defense</h2>
          <p className="text-[12px] text-ink-2">
            Allows <span className="num font-semibold text-ink">{formatCell(d.overall.sr, 'pct')}</span> success ({rankPhrase(d.overall.ranks.sr)}, league {formatCell(pool.league.overall.sr, 'pct')}) and{' '}
            <span className="num font-semibold text-ink">{formatCell(d.overall.ypc, 'dec1')}</span> YPC ({rankPhrase(d.overall.ranks.ypc)}, league {formatCell(pool.league.overall.ypc, 'dec1')}). Rank 1 = stingiest.
          </p>
        </div>
      </div>

      <StatStrip title={`${team} defense allowed`} m={d.overall} kind="defense" note={pfrNote(report, season)} team={team} />

      <h2 className="text-[11px] font-semibold uppercase tracking-wider text-ink-2">Where offenses run on {team}, and what it allows there (offense's left / right)</h2>
      <div className="grid gap-3 lg:grid-cols-3">
        {(['direction', 'gap', 'box'] as const).map((g) => d.splits[g] && <GroupCard key={g} d={d} group={g} report={report} league={pool.league[g]} />)}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title={row ? `This week: ${row.offense} backs vs ${team}` : `This week`} note="Run Edge from his own carries">
          {!row ? (
            <p className="text-[12px] text-ink-3">{team} is on bye this week.</p>
          ) : (
            <BackList rows={facing} update={update} opp={team} empty={`No ${row.offense} backs with designed runs in this season.`} />
          )}
        </Panel>
        <Panel title={`If this week's starters faced ${team}`} note="Best and toughest, other teams' starting RBs">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-1.5 text-[10.5px] font-medium uppercase tracking-wider text-edge-good">Best</p>
              <BackList rows={league.best} update={update} opp={team} empty="No ranked starters yet." compact />
            </div>
            <div>
              <p className="mb-1.5 text-[10.5px] font-medium uppercase tracking-wider text-edge-bad">Toughest</p>
              <BackList rows={league.worst} update={update} opp={team} empty="No ranked starters yet." compact />
            </div>
          </div>
        </Panel>
      </div>
      {report.scheme && (
        <p className="text-[11px] text-ink-3">Zone vs man/gap allowed by each defense isn't shown yet: {report.scheme.def_status ?? 'it needs a Data Suite run-defense export.'}</p>
      )}
    </div>
  );
}

/** One split group: the share of runs faced in each bucket vs the league's, and success / YPC allowed there. */
function GroupCard({ d, group, report, league }: { d: PoolDefense; group: SplitGroup; report: WeekReport; league?: Record<string, { share: number | null; sr: number | null; ypc: number | null }> }) {
  const rows = (report.buckets[group] ?? []).map((b) => ({ ...b, m: d.splits[group]?.[b.key] as Metrics | undefined, lg: league?.[b.key] }));
  const maxShare = Math.max(...rows.map((r) => Math.max(r.m?.share ?? 0, r.lg?.share ?? 0)), 0.01);
  const lean = rows
    .filter((r) => r.m?.share != null && r.lg?.share != null)
    .map((r) => ({ ...r, diff: r.m!.share! - r.lg!.share! }))
    .sort((a, b) => b.diff - a.diff)[0];
  return (
    <section className="rounded-md border border-line bg-panel">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-2">{GROUP_LABEL[group]}</h3>
        {lean && Math.abs(lean.diff) >= 0.02 && (
          <span className="whitespace-nowrap rounded border border-accent/40 bg-accent/10 px-2 py-0.5 text-[11.5px] font-semibold text-accent">
            faces {lean.label.toLowerCase()} +{Math.round(lean.diff * 100)} pts
          </span>
        )}
      </header>
      <div className="p-3">
        <div className="grid grid-cols-[5.5rem_minmax(0,1fr)_4.6rem_3.2rem] gap-x-2 text-[10px] uppercase tracking-wider text-ink-3">
          <span />
          <span>Share faced · lg tick</span>
          <span className="text-right">Succ. al.</span>
          <span className="text-right">YPC al.</span>
        </div>
        <div className="mt-1 space-y-1.5">
          {rows.map((r) => {
            const srTone = allowTone(r.m?.sr ?? null, r.lg?.sr, 0.03);
            const ypcTone = allowTone(r.m?.ypc ?? null, r.lg?.ypc, 0.4);
            return (
              <div key={r.key} className="grid grid-cols-[5.5rem_minmax(0,1fr)_4.6rem_3.2rem] items-center gap-x-2">
                <span className="truncate text-[12px]" title={r.label}>
                  {r.label}
                </span>
                <span
                  className="relative block h-3.5 rounded bg-panel-2"
                  role="img"
                  aria-label={`${r.label}: ${formatCell(r.m?.share ?? null, 'pct')} of runs faced, league ${formatCell(r.lg?.share ?? null, 'pct')}`}
                  title={`${formatCell(r.m?.share ?? null, 'pct')} of runs faced (n=${r.m?.att ?? 0}), league ${formatCell(r.lg?.share ?? null, 'pct')}`}
                >
                  <span className={`absolute inset-y-0 left-0 rounded ${TONE_BAR[srTone]}`} style={{ width: `${((r.m?.share ?? 0) / maxShare) * 100}%` }} />
                  {r.lg?.share != null && <span aria-hidden className="absolute -inset-y-0.5 w-0.5 bg-ink" style={{ left: `${(r.lg.share / maxShare) * 100}%` }} />}
                </span>
                <span className="num text-right text-[12px]">
                  <span className={`font-semibold ${TONE_TEXT[srTone]}`}>{formatCell(r.m?.sr ?? null, 'pct')}</span>
                  <span className="block whitespace-nowrap text-[10px] leading-3 text-ink-3">{r.m?.ranks.sr ? `${r.m.ranks.sr[0]}/${r.m.ranks.sr[1]}` : '—'} · n={r.m?.att ?? 0}</span>
                </span>
                <span className="num text-right text-[12px]">
                  <span className={`font-semibold ${TONE_TEXT[ypcTone]}`}>{formatCell(r.m?.ypc ?? null, 'dec1')}</span>
                  <span className="block text-[10px] leading-3 text-ink-3">{r.m?.ranks.ypc ? `${r.m.ranks.ypc[0]}/${r.m.ranks.ypc[1]}` : '—'}</span>
                </span>
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-[10.5px] text-ink-3">
          Bar = share of the designed runs it faced; tick = league share. Green: allows more than the league (good for the RB); orange: less. League success{' '}
          {rows.map((r) => `${r.label} ${formatCell(r.lg?.sr ?? null, 'pct')}`).join(' · ')}.
        </p>
      </div>
    </section>
  );
}

function BackList({ rows, update, opp, empty, compact }: { rows: { id: string; name: string; team: string; m: ReturnType<typeof matchup> }[]; update: Update; opp: string; empty: string; compact?: boolean }) {
  if (!rows.length) return <p className="text-[12px] text-ink-3">{empty}</p>;
  return (
    <ul className="space-y-2">
      {rows.map((r) => {
        const top = r.m.splits.filter((s) => s.group === 'direction').sort((a, b) => (b.off.share ?? 0) - (a.off.share ?? 0))[0];
        return (
          <li key={r.id} className="flex items-start gap-2.5">
            <EdgeBadge edge={r.m.run_edge} band={r.m.band} small={r.m.small} />
            <button type="button" onClick={() => update({ tab: 'player', player: r.id, opp })} className="min-w-0 text-left hover:text-accent">
              <span className="flex items-center gap-1.5 font-semibold">
                <TeamLogo team={r.team} size={16} /> {r.name} <span className="font-normal text-ink-3">{r.team}</span>
              </span>
              {!compact && top?.off.att ? (
                <span className="block text-[11.5px] text-ink-2">
                  Runs {top.label.toLowerCase()} {formatCell(top.off.share ?? null, 'pct')} of the time · {formatCell(top.off.sr, 'pct')} success there; {opp} allows {formatCell(top.def.sr, 'pct')}
                  {r.m.small ? ' · small sample' : ''}
                </span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
