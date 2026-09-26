export type CellFormat = 'int' | 'dec1' | 'epa' | 'pct' | 'text';

export function formatCell(v: number | string | null | undefined, fmt: CellFormat): string {
  if (v == null || v === '') return '—';
  if (typeof v === 'string') return v;
  switch (fmt) {
    case 'int':
      return Math.round(v).toLocaleString();
    case 'dec1':
      return v.toFixed(1);
    case 'epa':
      return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(2)}`;
    case 'pct':
      return `${(v * 100).toFixed(0)}%`;
    default:
      return String(v);
  }
}

/** "2026-09-27" -> "Sun, Sep 27, 2026" (the date is the game's local calendar date, so no time zone shift). */
export function formatDate(iso: string | null, opts: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }): string {
  if (!iso) return '—';
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-US', { timeZone: 'UTC', ...opts });
}

/** nflverse schedule times are US Eastern, "16:25" -> "4:25 PM ET". */
export function formatKickoff(t: string | null): string {
  if (!t) return 'TBD';
  const [h, m] = t.split(':').map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'} ET`;
}
