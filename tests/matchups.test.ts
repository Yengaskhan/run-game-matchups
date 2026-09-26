import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { formatCell, formatKickoff } from '../src/format';
import type { GameReport, SeasonIndex } from '../src/types';

/*
 * Checks every committed matchup report (data/). `npm run build` runs this, so a bad pipeline
 * output fails the deploy instead of reaching the site.
 */

const ROOT = join(__dirname, '..');
const DATA = join(ROOT, 'data');
const seasons = existsSync(DATA) ? readdirSync(DATA).filter((d) => /^\d{4}$/.test(d)) : [];
const TOL = 1e-3; // values are rounded to 4 decimals in the JSON

describe.each(seasons)('matchup reports %s', (season) => {
  const index = JSON.parse(readFileSync(join(DATA, season, 'index.json'), 'utf8')) as SeasonIndex;
  const games = index.weeks.flatMap((w) => w.games.map((g) => ({ ...g, week: w.week })));

  it('index lists every file and every file is in the index', () => {
    const onDisk = readdirSync(join(DATA, season))
      .filter((d) => d.startsWith('week-'))
      .flatMap((d) => readdirSync(join(DATA, season, d)).map((f) => `data/${season}/${d}/${f}`));
    expect(games.map((g) => g.path).sort()).toEqual(onDisk.sort());
  });

  it.each(games.map((g) => [g.game_id, g] as const))('%s', (_id, g) => {
    const r = JSON.parse(readFileSync(join(ROOT, g.path), 'utf8')) as GameReport;
    expect(r.schema).toBe(index.schema);
    expect([r.game_id, r.week, r.away, r.home]).toEqual([g.game_id, g.week, g.away, g.home]);
    // Current and prior seasons are separate windows, never blended.
    expect(r.window.prior.season).toBe(r.season - 1);
    expect(r.window.current.weeks.every((w) => w < r.week)).toBe(true);
    expect(r.sides.map((s) => [s.offense, s.defense])).toEqual([
      [r.away, r.home],
      [r.home, r.away],
    ]);

    for (const side of r.sides) {
      expect(side.sections.map((s) => s.id)).toEqual(['defense', 'offense', 'overlap', 'rushers', 'prior']);
      for (const sec of side.sections) {
        expect(!!sec.empty !== !!sec.tables?.length).toBe(true);
        for (const t of sec.tables ?? []) {
          const where = `${r.game_id} ${side.offense} ${t.id}`;
          // Every table is labeled with exactly one season, matching its window.
          expect(t.season, where).toBe(sec.id === 'prior' ? r.window.prior.season : r.season);
          expect(t.peer.length, where).toBeGreaterThan(0);
          expect(t.takeaways.length, where).toBeGreaterThanOrEqual(1);
          expect(t.takeaways.length, where).toBeLessThanOrEqual(4);
          const body = t.rows.filter((x) => x.kind !== 'ref' && x.kind !== 'total');
          const shareKey = t.checks?.shares_sum_to_one;
          if (shareKey) {
            const vals = body.map((x) => x.cells[shareKey]).filter((v): v is number => typeof v === 'number');
            if (vals.length) expect(Math.abs(vals.reduce((a, b) => a + b, 0) - 1), `${where} shares`).toBeLessThan(TOL);
          }
          const groupKey = t.checks?.shares_sum_to_one_by_group;
          if (groupKey) {
            for (const grp of new Set(body.map((x) => x.group))) {
              const vals = body.filter((x) => x.group === grp).map((x) => x.cells[groupKey]).filter((v): v is number => typeof v === 'number');
              if (vals.length) expect(Math.abs(vals.reduce((a, b) => a + b, 0) - 1), `${where} ${grp}`).toBeLessThan(TOL);
            }
          }
          const sumKey = t.checks?.rows_sum_to_total;
          const total = t.rows.find((x) => x.kind === 'total');
          if (sumKey && total) expect(body.reduce((a, x) => a + ((x.cells[sumKey] as number) ?? 0), 0), `${where} rows vs total`).toBe(total.cells[sumKey]);
          for (const x of t.rows) {
            for (const [k, [rank, n]] of Object.entries(x.ranks)) {
              expect(rank, `${where} ${x.label} ${k}`).toBeGreaterThanOrEqual(1);
              expect(rank, `${where} ${x.label} ${k}`).toBeLessThanOrEqual(n);
            }
          }
        }
      }
    }
  });
});

describe('matchup formatting', () => {
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
