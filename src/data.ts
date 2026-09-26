import type { SeasonIndex, WeekReport } from './types';

/*
 * Reports are precomputed by pipeline/run_matchups.py and committed under data/. They are bundled at
 * build time: the small season index eagerly, each week file as its own chunk loaded on demand.
 * Nothing is fetched from anywhere else at runtime.
 */

const indexes = import.meta.glob('/data/*/index.json', { eager: true, import: 'default' }) as Record<string, SeasonIndex>;
const weeks = import.meta.glob('/data/*/week-*.json', { import: 'default' }) as Record<string, () => Promise<WeekReport>>;

/** Seasons with reports, newest first. */
export function listSeasons(): SeasonIndex[] {
  return Object.values(indexes).sort((a, b) => b.season - a.season);
}

export async function loadWeek(path: string): Promise<WeekReport> {
  const load = weeks[`/${path}`];
  if (!load) throw new Error(`No report file for ${path}. Re-run the pipeline for this week.`);
  return load();
}

/** The week to open by default: the week in progress (first game within the last 6 days), else the next one, else the last. */
export function defaultWeek(index: SeasonIndex, today = new Date()): number | null {
  const iso = today.toISOString().slice(0, 10);
  const cutoff = new Date(today.getTime() - 6 * 864e5).toISOString().slice(0, 10);
  const current = index.weeks.find((w) => w.first_gameday >= cutoff && w.first_gameday <= iso) ?? index.weeks.find((w) => w.first_gameday >= iso);
  return (current ?? index.weeks[index.weeks.length - 1])?.week ?? null;
}
