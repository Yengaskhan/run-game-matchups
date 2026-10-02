/** Shape of data/<season>/week-XX.json, written by pipeline/run_matchups.py. */

export type Rank = [number, number]; // [rank, peer group size]; rank 1 = best for that unit

export interface Metrics {
  att: number;
  share?: number | null;
  ypc: number | null;
  epa: number | null;
  sr: number | null;
  expl: number | null;
  stuff: number | null;
  ranks: Partial<Record<'ypc' | 'epa' | 'sr' | 'expl' | 'stuff' | 'ybc_att' | 'yac_att', Rank>>;
}

export interface Overall extends Metrics {
  games: number | null;
  ybc_att: number | null;
  yac_att: number | null;
  pfr_att: number | null;
  qb_att: number | null;
}

export type SplitGroup = 'direction' | 'gap' | 'box';

export interface Split {
  group: SplitGroup;
  key: string;
  label: string;
  off: Metrics;
  def: Metrics;
  /** 0-100, 50 = neutral; null when either side is below the rank qualifier. */
  edge: number | null;
}

export interface Rusher {
  id: string;
  name: string;
  /** Depth slot (RB1…), position, or the prior-season team(s). */
  role: string;
  kind: 'rb' | 'other' | 'qb' | 'total';
  note?: string;
  att: number;
  carry_share?: number | null;
  snap_share?: number | null;
  ypc: number | null;
  epa: number | null;
  sr: number | null;
  ybc_att: number | null;
  yac_att: number | null;
  pfr_att: number | null;
  ranks: Metrics['ranks'];
}

export type BandKey = 'big_edge' | 'small_edge' | 'neutral' | 'small_disadvantage' | 'big_disadvantage';

export interface SeasonBlock {
  season: number;
  weeks: number[];
  overall: { off: Overall; def: Overall };
  run_edge: number | null;
  edge_coverage: number;
  small_sample: boolean;
  band: BandKey;
  top_direction: { key: string; label: string; share: number; att: number } | null;
  splits: Split[];
  rushers: Rusher[];
  takeaways: string[];
}

export interface MatchupRow {
  game_id: string;
  offense: string;
  defense: string;
  home: boolean;
  /** Starting RB: RB1 on the depth chart. Null when the team has no RB listed. */
  starter: { id: string; name: string } | null;
  seasons: Record<string, SeasonBlock | null>;
}

export interface WeekReport {
  schema: number;
  season: number;
  week: number;
  generated_at: string;
  data_as_of: string | null;
  /** pfr_weeks: weeks behind YBC / YAC; fewer than `weeks` when PFR hasn't caught up yet. */
  seasons: { season: number; label: string; weeks: number[]; pfr_weeks: number[]; current: boolean; empty: string | null }[];
  games: { game_id: string; away: string; home: string; gameday: string; gametime: string | null; stadium: string | null }[];
  rows: MatchupRow[];
  edge: { bands: { key: BandKey; label: string; min: number }[]; min_coverage: number; definition: string };
  notes: string[];
  filters: string[];
  qualifiers: string[];
  sources: string[];
  checks: string[];
}

export interface SeasonIndex {
  schema: number;
  season: number;
  weeks: { week: number; games: number; first_gameday: string; last_gameday: string; path: string; data_as_of: string | null }[];
}
