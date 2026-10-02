import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { defaultWeek } from '../src/data';
import { formatCell, formatKickoff } from '../src/format';
import type { SeasonIndex, WeekReport } from '../src/types';

/*
 * Checks every committed week file (data/). `npm run build` runs this, so a bad pipeline output fails
 * the deploy instead of reaching the site.
 */

const ROOT = join(__dirname, '..');
const DATA = join(ROOT, 'data');
const seasons = existsSync(DATA) ? readdirSync(DATA).filter((d) => /^\d{4}$/.test(d)) : [];
const TOL = 1e-3; // values are rounded to 4 decimals in the JSON

describe.each(seasons)('matchup reports %s', (season) => {
  const index = JSON.parse(readFileSync(join(DATA, season, 'index.json'), 'utf8')) as SeasonIndex;

  it('index lists every week file and every file is in the index', () => {
    const onDisk = readdirSync(join(DATA, season)).filter((f) => /^week-\d+\.json$/.test(f)).map((f) => `data/${season}/${f}`);
    expect(index.weeks.map((w) => w.path).sort()).toEqual(onDisk.sort());
  });

  it.each(index.weeks.map((w) => [w.week, w] as const))('week %i', (_w, entry) => {
    const r = JSON.parse(readFileSync(join(ROOT, entry.path), 'utf8')) as WeekReport;
    expect(r.schema).toBe(index.schema);
    expect(r.week).toBe(entry.week);
    expect(r.games.length).toBe(entry.games);

    // Two separate seasons: the current one (games before this week only) and the full prior season.
    const [cur, prior] = r.seasons;
    expect([cur.current, prior.current]).toEqual([true, false]);
    expect(prior.season).toBe(cur.season - 1);
    expect(cur.weeks.every((w) => w < r.week)).toBe(true);

    // One row per offense: both sides of every game.
    expect(r.rows.length).toBe(r.games.length * 2);
    for (const g of r.games) {
      expect(r.rows.filter((x) => x.game_id === g.game_id).map((x) => [x.offense, x.defense]).sort()).toEqual([[g.away, g.home], [g.home, g.away]].sort());
    }

    for (const row of r.rows) {
      // Starting RB (depth-chart RB1) is present on every row, or explicitly null.
      expect(row.starter === null || (typeof row.starter?.id === 'string' && row.starter.name.length > 0), `${row.offense} starter`).toBe(true);
      for (const meta of r.seasons) {
        const b = row.seasons[String(meta.season)];
        const where = `week ${r.week} ${row.offense} vs ${row.defense} (${meta.season})`;
        if (meta.empty) {
          expect(b, where).toBeNull();
          continue;
        }
        expect(b, where).toBeTruthy();
        if (!b) continue;
        expect(b.season).toBe(meta.season);
        for (const grp of new Set(b.splits.map((s) => s.group))) {
          for (const unit of ['off', 'def'] as const) {
            const vals = b.splits.filter((s) => s.group === grp).map((s) => s[unit].share).filter((v): v is number => typeof v === 'number');
            if (vals.length) expect(Math.abs(vals.reduce((a, c) => a + c, 0) - 1), `${where} ${unit} ${grp} shares`).toBeLessThan(TOL);
          }
        }
        for (const s of b.splits) {
          if (s.edge != null) expect(s.edge >= 0 && s.edge <= 100, `${where} ${s.key} edge`).toBe(true);
          for (const m of [s.off, s.def]) for (const [rank, n] of Object.values(m.ranks)) expect(rank >= 1 && rank <= n, `${where} ${s.key} rank`).toBe(true);
        }
        if (b.run_edge != null) expect(b.run_edge >= 0 && b.run_edge <= 100).toBe(true);
        const total = b.rushers.find((x) => x.kind === 'total');
        if (total) expect(b.rushers.filter((x) => x.kind !== 'total').reduce((a, x) => a + x.att, 0), `${where} rushers vs total`).toBe(total.att);
        expect(b.takeaways.length).toBeLessThanOrEqual(2);
      }
    }
  });
});

describe('default week', () => {
  const w = (week: number, first: string, last: string) => ({ week, games: 16, first_gameday: first, last_gameday: last, path: '', data_as_of: null });
  const index = { schema: 2, season: 2026, weeks: [w(3, '2026-09-24', '2026-09-28'), w(4, '2026-10-01', '2026-10-05')] };
  it('opens the week still being played, and moves on once it ends', () => {
    expect(defaultWeek(index, new Date('2026-09-27T15:00:00Z'))).toBe(3); // Sunday of week 3
    expect(defaultWeek(index, new Date('2026-09-28T15:00:00Z'))).toBe(3); // Monday night still to play
    expect(defaultWeek(index, new Date('2026-09-30T15:00:00Z'))).toBe(4); // Wednesday: week 3 is over
    expect(defaultWeek(index, new Date('2026-10-20T15:00:00Z'))).toBe(4); // past the last week on file
  });
});

describe('formatting', () => {
  it('formats cells', () => {
    expect(formatCell(0.1234, 'epa')).toBe('+0.12');
    expect(formatCell(-0.05, 'epa')).toBe('−0.05');
    expect(formatCell(0.456, 'pct')).toBe('46%');
    expect(formatCell(4.8214, 'dec1')).toBe('4.8');
    expect(formatCell(null, 'pct')).toBe('—');
  });
  it('formats Eastern kickoff times', () => {
    expect(formatKickoff('13:00')).toBe('1:00 PM ET');
    expect(formatKickoff('20:15')).toBe('8:15 PM ET');
    expect(formatKickoff('09:30')).toBe('9:30 AM ET');
    expect(formatKickoff('12:05')).toBe('12:05 PM ET');
  });
});
