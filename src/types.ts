/**
 * Shape of the precomputed matchup files written by pipeline/run_matchups.py.
 * The page renders every table generically, so new sections (e.g. pass coverage) need no new types.
 */

export type CellFormat = 'int' | 'dec1' | 'epa' | 'pct' | 'edge' | 'text';

export interface Column {
  key: string;
  label: string;
  fmt: CellFormat;
  /** Cells in this column may carry a [rank, peerGroupSize] pair. */
  rank?: boolean;
  title?: string;
}

export interface Row {
  key: string;
  label: string;
  sub?: string;
  /** team = the team being described; ref = league average; total = team total; qb = designed QB runs. */
  kind: 'row' | 'team' | 'ref' | 'total' | 'qb';
  group?: string;
  /** Overlap tables: the largest mismatch each way. */
  flag?: 'offense' | 'defense';
  cells: Record<string, number | string | null>;
  ranks: Record<string, [number, number]>;
}

export interface ReportTableData {
  id: string;
  title: string;
  season: number;
  season_label: string;
  caption: string;
  unit?: 'offense' | 'defense' | 'matchup';
  columns: Column[];
  rows: Row[];
  peer: string;
  notes: string[];
  takeaways: string[];
  checks?: Record<string, string>;
}

export interface Section {
  id: string;
  /** Which report the section belongs to ("run"; later e.g. "coverage"). */
  group: string;
  title: string;
  subtitle?: string;
  tables?: ReportTableData[];
  /** Set instead of tables when there is no data (e.g. Week 1). */
  empty?: string;
}

export interface Side {
  offense: string;
  defense: string;
  title: string;
  sections: Section[];
}

export interface GameReport {
  schema: number;
  game_id: string;
  season: number;
  week: number;
  away: string;
  home: string;
  gameday: string;
  gametime: string | null;
  stadium: string | null;
  roof: string | null;
  data_as_of: string | null;
  generated_at: string;
  window: { current: { season: number; weeks: number[] }; prior: { season: number; weeks: number[] } };
  sides: Side[];
  notes: string[];
  filters: string[];
  qualifiers: Record<string, string>;
  sources: string[];
  checks: string[];
}

export interface IndexGame {
  game_id: string;
  away: string;
  home: string;
  gameday: string;
  gametime: string | null;
  path: string;
  data_as_of: string | null;
}

export interface SeasonIndex {
  schema: number;
  season: number;
  weeks: { week: number; games: IndexGame[] }[];
}
