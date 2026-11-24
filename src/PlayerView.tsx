import { useMemo } from 'react';
import { changeText, matchup, type Matchup } from './edge';
import { formatCell, formatDate, formatKickoff } from './format';
import type { HashState, Update } from './MatchupApp';
import { Backs, DefenseContext, PlayerPicker, pfrNote, SchemeTable, SplitTable, StatStrip } from './parts';
import { TeamLogo, teamName } from './TeamLogo';
import type { PoolDefense, PoolPlayer, SchemeRow, Vegas, WeekReport } from './types';
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
  // Vegas only applies to the scheduled game; any other pairing is scored as a neutral game environment.
  const vegas = scheduled ? (row?.seasons[season]?.model.vegas ?? null) : null;
  const m = matchup(ps, d, report, pool.league.overall, vegas);
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
        <HeaderCards team={player.team} ps={ps} d={d} m={m} vegas={vegas} scheduled={scheduled} league={pool.league.overall} report={report} />
      )}

      <div className="grid gap-2 md:grid-cols-2">
        {ps && <StatStrip title={player.name} m={ps.overall} kind="offense" note={pfrNote(report, season)} team={player.team} />}
        <StatStrip title={`${opp} defense allowed`} m={d.overall} kind="defense" note={pfrNote(report, season)} team={opp} />
      </div>

      <Panel title="Where he runs, and what this defense allows there" note="Context: not part of the Run Edge · his carries only · ranks are rank/peer group · left / right = offense's view">
        <SplitTable splits={m.splits} rb={player.name} dfn={opp} />
      </Panel>

      <DefenseContext d={d} report={report} season={season} />

      {meta.current && report.scheme && <SchemePanel report={report} ps={ps} name={player.name} opp={opp} />}

      <Panel title={meta.current ? `${player.team} backfield` : `${player.team}'s current backs, ${season} line`} note={row ? 'Click a back to switch to him' : undefined}>
        {row ? <Backs rows={backs} current={meta.current} selected={player.id} onPick={(id) => update({ player: id })} /> : <p className="text-[12px] text-ink-3">{player.team} is on bye this week, so its backfield table isn't in this report.</p>}
      </Panel>
    </div>
  );
}

function HeaderCards({ team, ps, d, m, vegas, scheduled, league, report }: {
  team: string; ps: PoolPlayer; d: PoolDefense; m: Matchup; vegas: Vegas | null; scheduled: boolean;
  league: { sr: number | null; ypc: number | null }; report: WeekReport;
}) {
  const o = ps.overall;
  const a = d.overall;
  const c = report.edge.model;
  const vegasLine =
    vegas && vegas.avg && vegas.n >= c.vegas_min_games
      ? `Vegas: ${team} implied ${vegas.implied?.toFixed(1)} vs usual ${vegas.avg.toFixed(1)} → ${changeText(m.vegas_part)}`
      : scheduled
        ? `Vegas: ${team} has fewer than ${c.vegas_min_games} lined games, so neutral`
        : 'Vegas: no line (not this week’s game), so neutral';
  const tone = (x: number) => (x > 1.01 ? 'text-edge-good' : x < 0.99 ? 'text-edge-bad' : 'text-ink-2');
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      <Card label="Run Edge" sub={`${changeText(m.mult)} rushing vs his normal game. 50 = an average matchup.`}>
        <EdgeBadge edge={m.run_edge} band={m.band} lg />
      </Card>
      <Card label="Matchup-adjusted rush yds" sub={m.base_ypg != null ? `His normal game: ${m.base_ypg.toFixed(1)} yds on designed runs (${o.games} games)${m.small ? ` · small sample (${o.att} carries)` : ''}` : undefined}>
        <span className="num text-[22px] font-semibold">{m.proj_yds != null ? m.proj_yds.toFixed(1) : '—'}</span>
      </Card>
      <Card label="Why">
        <ul className="space-y-1 text-[12px] leading-snug">
          <li className={tone(m.def_part)}>
            {d.team} allows {formatCell(a.sr, 'pct')} success (lg {formatCell(league.sr, 'pct')}) and {formatCell(a.ypc, 'dec1')} YPC (lg {formatCell(league.ypc, 'dec1')}) → {changeText(m.def_part)}
          </li>
          <li className={tone(m.vegas_part)}>{vegasLine}</li>
        </ul>
      </Card>
      <Card label="His efficiency (context)" sub={`Not in the Run Edge: it measures the matchup, and his own level is already in his normal game.`}>
        <p className="num text-[13px]">
          {formatCell(o.sr, 'pct')} success <span className="text-ink-3">({rankPhrase(o.ranks.sr, 'RBs')})</span>
        </p>
        <p className="num text-[13px]">
          {formatCell(o.ypc, 'dec1')} YPC <span className="text-ink-3">({rankPhrase(o.ranks.ypc, 'RBs')})</span>
        </p>
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
      {status || !rows ? <p className="text-[12px] text-ink-2">{status}</p> : <SchemeTable rows={rows} rb={name} dfn={opp} />}
      <p className="mt-2 text-[10.5px] text-ink-3">
        Zone vs man/gap is how the line blocked the run. Data Suite counts all of his carries, so totals can differ slightly from the nflverse designed-run numbers above. {sc.qualifier}
        {rows && sc.def_status ? ` ${sc.def_status}` : ''}
        {sc.note ? ` ${sc.note}` : ''}
      </p>
    </Panel>
  );
}
