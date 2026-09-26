import teams from './assets/teams.json';

/*
 * Team logos (nflverse squared logos, saved by the pipeline into src/assets/logos) and full names.
 * Bundled with the site; a team without a saved logo falls back to its code in the team colour.
 */

const logos = import.meta.glob('./assets/logos/*.png', { eager: true, query: '?url', import: 'default' }) as Record<string, string>;
const byTeam = Object.fromEntries(Object.entries(logos).map(([path, url]) => [path.replace(/^.*\/|\.png$/g, ''), url]));
const meta = teams as Record<string, { name: string; color: string }>;

export function teamName(code: string): string {
  return meta[code]?.name ?? code;
}

export function TeamLogo({ team, size = 22 }: { team: string; size?: number }) {
  const url = byTeam[team];
  const style = { width: size, height: size };
  if (!url) {
    return (
      <span aria-hidden style={{ ...style, background: meta[team]?.color ?? 'var(--color-raise)' }} className="inline-flex shrink-0 items-center justify-center rounded text-[8px] font-bold text-white">
        {team}
      </span>
    );
  }
  return <img src={url} alt="" aria-hidden width={size} height={size} style={style} className="shrink-0 rounded-[4px]" loading="lazy" />;
}
