import type { BandKey, Metrics, PoolDefense, PoolPlayer, Rank, Split, SplitGroup, WeekReport } from './types';

/*
 * The Run Edge for any RB against any defense, computed in the browser from the report's player /
 * defense pool. It mirrors the pipeline exactly (pipeline/matchups/weekly.py: edge_from, side_block),
 * and tests/matchups.test.ts checks it reproduces every row the pipeline scored.
 */

const EDGE_METRICS = ['sr', 'ypc'] as const;
const GROUPS: SplitGroup[] = ['direction', 'gap', 'box'];

const EMPTY: Metrics = { att: 0, share: null, ypc: null, sr: null, ranks: {} };

/** Rank -> percentile: 1.0 = best in the peer group, 0.0 = worst. */
export function pctFromRank([rank, n]: Rank): number {
  return n === 1 ? 1 : 1 - (rank - 1) / (n - 1);
}

/** 50 + 50 x (RB percentile - defense percentile), each the average of its success-rate and YPC percentiles. */
export function edgeFrom(off: Metrics, def: Metrics): number | null {
  if (!EDGE_METRICS.every((m) => off.ranks[m] && def.ranks[m])) return null;
  const po = EDGE_METRICS.reduce((a, m) => a + pctFromRank(off.ranks[m]!), 0) / EDGE_METRICS.length;
  const pd = EDGE_METRICS.reduce((a, m) => a + pctFromRank(def.ranks[m]!), 0) / EDGE_METRICS.length;
  return pyRound(50 + 50 * (po - pd));
}

/** Python's round(): exact halves go to the even neighbour, so 62.5 -> 62 as in the pipeline. The
 * arithmetic above runs in the same order as the pipeline's, so the floats match bit for bit. */
export function pyRound(x: number): number {
  const f = Math.floor(x);
  if (x - f === 0.5) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
}

export function bandFor(edge: number | null, bands: WeekReport['edge']['bands'], small = false): BandKey {
  if (edge == null || small) return 'neutral';
  return bands.find((b) => edge >= b.min)?.key ?? 'neutral';
}

export interface Matchup {
  splits: Split[];
  run_edge: number | null;
  coverage: number;
  small: boolean;
  band: BandKey;
}

/** Every split for one RB vs one defense, and the headline Run Edge (direction edges weighted by where he runs). */
export function matchup(p: PoolPlayer | null | undefined, d: PoolDefense, report: Pick<WeekReport, 'buckets' | 'edge'>): Matchup {
  const splits: Split[] = [];
  for (const group of GROUPS) {
    const dg = d.splits[group];
    if (!dg) continue;
    for (const { key, label } of report.buckets[group] ?? []) {
      const off = p?.splits[group]?.[key] ?? EMPTY;
      const def = dg[key] ?? EMPTY;
      splits.push({ group, key, label, off, def, edge: edgeFrom(off, def) });
    }
  }
  const ranked = splits.filter((s) => s.group === 'direction' && s.edge != null && s.off.share);
  const coverage = ranked.reduce((a, s) => a + (s.off.share ?? 0), 0);
  const run_edge = coverage ? pyRound(ranked.reduce((a, s) => a + s.edge! * (s.off.share ?? 0), 0) / coverage) : null;
  const small = coverage < report.edge.min_coverage;
  return { splits, run_edge, coverage, small, band: bandFor(run_edge, report.edge.bands, small) };
}

/** The RB's best and worst ranked gaps among those he uses on 10%+ of his runs (the pipeline's takeaways rule). */
export function spots(m: Matchup, minShare = 0.1): { best: Split | null; worst: Split | null } {
  const used = m.splits.filter((s) => s.group === 'gap' && (s.off.share ?? 0) >= minShare && s.edge != null);
  if (!used.length) return { best: null, worst: null };
  const best = used.reduce((a, s) => (s.edge! > a.edge! ? s : a));
  const worst = used.reduce((a, s) => (s.edge! < a.edge! ? s : a));
  return { best, worst: worst === best ? null : worst };
}
