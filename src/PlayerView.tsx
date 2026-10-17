import { useMemo } from 'react';
import { matchup, spots, type Matchup } from './edge';
import { formatCell, formatDate, formatKickoff } from './format';
import type { HashState, Update } from './MatchupApp';
import { Backs, PlayerPicker, pfrNote, SchemeTable, SplitTable, StatStrip } from './parts';
import { TeamLogo, teamName } from './TeamLogo';
import type { PoolDefense, PoolPlayer, SchemeRow, Split, WeekReport } from './types';
import { Card, EdgeBadge, Panel, Pill, rankPhrase, Select } from './ui';

/** One RB against one defense: this week's opponent by default, or any other defense. */
export function PlayerView({ report, season, hash, update }: { report: WeekReport; season: string; hash: HashState; update: Update }) {
  const pool = report.pool[season]!;
  const byId = useMemo(() => new Map(report.players.map((p) => [p.id, p])), [report]);
  const player = byId.get(hash.player ?? '') ?? report.players[0];
  const missing = !!hash.player && !byId.has(hash.player);
  const row = report.rows.find((r) => r.offense === player.team) ?? null;
  const game = row ? report.games.find((g) => g.game_id === row.game_id) : undefined;
  const defenses = Object.keys(pool.defenses).filter((t) => t !== player.team);
  const opp = hash.opp && defenses.includes(hash.opp) ? hash.opp : (row?.defense ?? defenses[0]);
  const scheduled = row?.defense === opp;
  const ps = pool.players[player.id] ?? null;
  const d = pool.defenses[opp];
  const m = matchup(ps, d, report);
  const meta = report.seasons.find((s) => String(s.season) === season)!;
  const backs = row?.seasons[season]?.rushers ?? [];

  return (
    <div className="space-y-4">
      <button type="button" onClick={() => update({ tab: 'slate' })} className="text-[12.5px] text-accent hover:underline">
        ← Back to Slate Rankings
      </button>
      <div className="flex flex-wrap items-end gap-3">
        <PlayerPicker players={report.players} value={player} onChange={(p) => update({ player: p.id, opp: undefined })} />
        <Select
          label="Opponent"
          value={opp}
          onChange={(v) => update({ player: player.id, opp: v })}
          options={defenses.map((t) => [t, `${t} · ${teamName(t)}${t === row?.defense ? ' (this week)' : ''}`])}
        />
        <p className="pb-1.5 text-[12px] text-ink-3">
          {row ? (
            <>
              Week {report.week}: {row.home ? 'vs' : '@'} {row.defense}
              {game && ` · ${formatDate(game.gameday, { weekday: 'short', month: 'short', day: 'numeric' })} ${formatKickoff(game.gametime)}`}
              {!scheduled && (
                <button type="button" onClick={() => update({ opp: row.defense })} className="ml-2 text-accent hover:underline">
                  back to this week's opponent
                </button>
              )}
            </>
          ) : (
            `${player.team} is on bye in week ${report.week}`
          )}
        </p>
      </div>
      {missing && (
        <p className="rounded-md border border-warn/40 bg-panel px-3 py-2 text-[12px] text-ink-2">
          That player isn't in the week {report.week} report, so {player.name} is shown instead.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <TeamLogo team={player.team} size={32} />
        <h2 className="text-[18px] font-semibold">{player.name}</h2>
        <span className="text-[13px] text-ink-2">
          {player.team} {player.depth ?? player.pos}
          {ps ? ` · ${ps.overall.att} designed runs in ${ps.overall.games ?? '—'} games` : ''}
          {ps && !meta.current && ps.team ? ` (${ps.team} in ${season})` : ''}
        </span>
        <span className="text-ink-3">vs</span>
        <button type="button" onClick={() => update({ tab: 'defense', team: opp })} className="inline-flex items-center gap-1.5 text-[14px] font-semibold hover:text-accent" title={`${teamName(opp)} defense profile`}>
          <TeamLogo team={opp} size={24} /> {teamName(opp)}
        </button>
        {!scheduled && <Pill tone="warn">not this week's game</Pill>}
        <Pill tone={meta.current ? 'neutral' : 'warn'}>{meta.label}</Pill>
      </div>

      {!ps ? (
        <p className="rounded-md border border-line bg-panel px-3 py-3 text-[12.5px] text-ink-2">
          {player.name} has no designed runs {meta.current ? `for ${player.team} in ${meta.label}` : `in ${meta.label}`}, so there's nothing to score yet. {opp}'s run defense is below.
        </p>
      ) : (
        <HeaderCards name={player.name} ps={ps} d={d} m={m} />
      )}

      <div className="grid gap-2 md:grid-cols-2">
        {ps && <StatStrip title={player.name} m={ps.overall} kind="offense" note={pfrNote(report, season)} team={player.team} />}
        <StatStrip title={`${opp} defense allowed`} m={d.overall} kind="defense" note={pfrNote(report, season)} team={opp} />
      </div>

      <Panel title="Where he runs, and what this defense allows there" note="His carries only · ranks are rank/peer group · n = attempts · left / right = offense's view">
        <SplitTable splits={m.splits} rb={player.name} dfn={opp} report={report} />
      </Panel>

      {meta.current && report.scheme && <SchemePanel report={report} ps={ps} name={player.name} opp={opp} />}

      <Panel title={meta.current ? `${player.team} backfield` : `${player.team}'s current backs, ${season} line`} note={row ? 'Click a back to switch to him' : undefined}>
        {row ? <Backs rows={backs} current={meta.current} selected={player.id} onPick={(id) => update({ player: id })} /> : <p className="text-[12px] text-ink-3">{player.team} is on bye this week, so its backfield table isn't in this report.</p>}
      </Panel>
    </div>
  );
}

function spotText(s: Split) {
  return `${s.label} (edge ${s.edge}): he runs there ${formatCell(s.off.share ?? null, 'pct')} of the time, ${formatCell(s.off.sr, 'pct')} success; allowed ${formatCell(s.def.sr, 'pct')}.`;
}

function HeaderCards({ name, ps, d, m }: { name: string; ps: PoolPlayer; d: PoolDefense; m: Matchup }) {
  const { best, worst } = spots(m);
  const o = ps.overall;
  const a = d.overall;
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      <Card
        label="Run Edge"
        sub={
          m.run_edge == null
            ? 'No direction where both sides are ranked yet.'
            : m.small
              ? `Small sample: ranked directions cover ${formatCell(m.coverage, 'pct')} of his runs.`
              : `Left / middle / right edges, weighted by where he runs (${formatCell(m.coverage, 'pct')} of his runs ranked).`
        }
      >
        <EdgeBadge edge={m.run_edge} band={m.band} small={m.small} lg />
      </Card>
      <Card label="Success rate" sub={`${rankPhrase(o.ranks.sr, 'RBs')} · ${d.team} allows ${formatCell(a.sr, 'pct')} (${rankPhrase(a.ranks.sr)})`}>
        <span className="num text-[22px] font-semibold">{formatCell(o.sr, 'pct')}</span>
      </Card>
      <Card label="Yards per carry" sub={`${rankPhrase(o.ranks.ypc, 'RBs')} · ${d.team} allows ${formatCell(a.ypc, 'dec1')} (${rankPhrase(a.ranks.ypc)})`}>
        <span className="num text-[22px] font-semibold">{formatCell(o.ypc, 'dec1')}</span>
      </Card>
      <Card label="Best and toughest gap">
        {best ? (
          <div className="space-y-1 text-[12px] leading-snug">
            <p className={best.edge! >= 50 ? 'text-edge-good' : best.edge! < 43 ? 'text-edge-bad' : 'text-ink-2'}>
              <b>{worst ? 'Best' : 'Only ranked gap'}:</b> {spotText(best)}
            </p>
            {worst && (
              <p className={worst.edge! < 50 ? 'text-edge-bad' : 'text-ink-2'}>
                <b>Toughest:</b> {spotText(worst)}
              </p>
            )}
          </div>
        ) : (
          <p className="text-[12px] text-ink-3">No gap {name} uses on 10%+ of his runs has both sides ranked yet (samples too small).</p>
        )}
      </Card>
    </div>
  );
}

function SchemePanel({ report, ps, name, opp }: { report: WeekReport; ps: PoolPlayer | null; name: string; opp: string }) {
  const sc = report.scheme!;
  const exported = sc.exported_at ? formatDate(sc.exported_at.slice(0, 10), { month: 'short', day: 'numeric' }) : null;
  const rows: SchemeRow[] | null = ps?.scheme
    ? (['zone', 'gap'] as const).map((k) => ({ key: k, label: k === 'zone' ? 'Zone runs' : 'Man/gap runs', off: ps.scheme![k], def: null, edge: null, league: sc.league?.[k] }))
    : null;
  const status = sc.status ?? (rows ? null : `${name} isn't in the Data Suite rushing export.`);
  return (
    <Panel title="Run scheme: zone vs man/gap" note={`Data Suite${exported ? ` export of ${exported}` : ''} (not nflverse)`}>
      {status || !rows ? <p className="text-[12px] text-ink-2">{status}</p> : <SchemeTable rows={rows} rb={name} dfn={opp} report={report} />}
      <p className="mt-2 text-[10.5px] text-ink-3">
        Zone vs man/gap is how the line blocked the run. Data Suite counts all of his carries, so totals can differ slightly from the nflverse designed-run numbers above. {sc.qualifier}
        {rows && sc.def_status ? ` ${sc.def_status}` : ''}
        {sc.note ? ` ${sc.note}` : ''}
      </p>
    </Panel>
  );
}
