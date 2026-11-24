import type { BandKey, Metrics, PoolDefense, PoolPlayer, Split, SplitGroup, Vegas, WeekReport } from './types';

/*
 * The Run Edge for any RB against any defense, computed in the browser from the report's player /
 * defense pool. It mirrors the pipeline exactly (pipeline/matchups/model.py), from the same rounded
 * numbers, and tests/matchups.test.ts checks it reproduces every row the pipeline scored.
 *
 *   multiplier = sr_idx^w_sr × ypc_idx^w_ypc × vegas^w_vegas   (defensive indexes shrunk by games)
 *   Run Edge   = 50 + 50 × tanh(ln(multiplier) / scale)
 */

const GROUPS: SplitGroup[] = ['direction', 'gap', 'box'];
const EMPTY: Metrics = { att: 0, share: null, ypc: null, sr: null, ranks: {} };

/** Python's round(): exact halves go to the even neighbour, as in the pipeline. */
export function pyRound(x: number): number {
  const f = Math.floor(x);
  if (x - f === 0.5) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
}

const round4 = (x: number) => pyRound(x * 1e4) / 1e4;

export function bandFor(edge: number | null, bands: WeekReport['edge']['bands']): BandKey {
  if (edge == null) return 'neutral';
  return bands.find((b) => edge >= b.min)?.key ?? 'neutral';
}

type ModelConsts = WeekReport['edge']['model'];

export function defIndex(rate: number | null | undefined, league: number | null | undefined, games: number | null | undefined, k: number): number {
  if (rate == null || !league || !games) return 1;
  return 1 + (games / (games + k)) * (rate / league - 1);
}

export function vegasIndex(v: Vegas | null | undefined, c: ModelConsts): number {
  if (!v || v.implied == null || !v.avg || v.n < c.vegas_min_games) return 1;
  return v.implied / v.avg;
}

export interface Matchup {
  splits: Split[];
  run_edge: number;
  band: BandKey;
  mult: number;
  sr_idx: number;
  ypc_idx: number;
  vegas_idx: number;
  /** What the defense alone and the game alone are worth (each as a multiplier). */
  def_part: number;
  vegas_part: number;
  base_ypg: number | null;
  proj_yds: number | null;
  /** Too few carries for his "normal game" to mean much. */
  small: boolean;
}

/**
 * One RB vs one defense. `vegas` is the line for the scheduled game, or null (no line: neutral) when the
 * opponent isn't this week's.
 */
export function matchup(p: PoolPlayer | null | undefined, d: PoolDefense, report: Pick<WeekReport, 'buckets' | 'edge'>, league: { sr: number | null; ypc: number | null }, vegas: Vegas | null): Matchup {
  const c = report.edge.model;
  const splits: Split[] = [];
  for (const group of GROUPS) {
    const dg = d.splits[group];
    if (!dg) continue;
    for (const { key, label } of report.buckets[group] ?? []) {
      splits.push({ group, key, label, off: p?.splits[group]?.[key] ?? EMPTY, def: dg[key] ?? EMPTY, edge: null });
    }
  }
  const o = d.overall;
  const sr_idx = defIndex(o.sr, league.sr, o.games, c.k_games);
  const ypc_idx = defIndex(o.ypc, league.ypc, o.games, c.k_games);
  const vegas_idx = vegasIndex(vegas, c);
  const mult = Math.exp(c.w_sr * Math.log(sr_idx) + c.w_ypc * Math.log(ypc_idx) + c.w_vegas * Math.log(vegas_idx));
  const run_edge = pyRound(50 + 50 * Math.tanh(Math.log(mult) / c.scale));
  const po = p?.overall;
  const base = po && po.games && po.yds != null ? po.yds / po.games : null;
  return {
    splits,
    run_edge,
    band: bandFor(run_edge, report.edge.bands),
    mult,
    sr_idx,
    ypc_idx,
    vegas_idx,
    def_part: Math.exp(c.w_sr * Math.log(sr_idx) + c.w_ypc * Math.log(ypc_idx)),
    vegas_part: Math.exp(c.w_vegas * Math.log(vegas_idx)),
    base_ypg: base == null ? null : round4(base),
    proj_yds: base == null ? null : round4(base * round4(mult)), // as the pipeline: base × the rounded multiplier
    small: (po?.att ?? 0) < c.min_att,
  };
}

/** "+8%", "−4%", "±0%" for a multiplier. */
export function changeText(mult: number): string {
  const n = Math.round((mult - 1) * 100);
  return n > 0 ? `+${n}%` : n < 0 ? `−${-n}%` : '±0%';
}
