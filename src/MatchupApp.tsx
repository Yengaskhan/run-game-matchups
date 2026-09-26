import { useEffect, useMemo, useState } from 'react';
import { defaultWeek, listSeasons, loadGame } from './data';
import { formatDate, formatKickoff, weeksLabel } from './format';
import { ReportTable } from './ReportTable';
import type { GameReport, Section } from './types';

function ErrorIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className="inline h-3.5 w-3.5 shrink-0" fill="currentColor">
      <path d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm2.47 3.47L8 6.94 5.53 4.47 4.47 5.53 6.94 8l-2.47 2.47 1.06 1.06L8 9.06l2.47 2.47 1.06-1.06L9.06 8l2.47-2.47-1.06-1.06Z" />
    </svg>
  );
}

/** True when the page runs inside an iframe (e.g. embedded on a website-builder page). */
const embedded = (() => {
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
})();

/** Selection lives in the URL hash (#game=2026_03_BAL_DAL&side=1) so a matchup can be linked directly. */
function readHash(): { game: string | null; side: number } {
  const p = new URLSearchParams(window.location.hash.slice(1));
  return { game: p.get('game'), side: p.get('side') === '1' ? 1 : 0 };
}

export default function MatchupApp() {
  const seasons = useMemo(() => listSeasons(), []);
  const index = seasons[0] ?? null;
  const initial = useMemo(readHash, []);
  const initialWeek = useMemo(() => {
    if (!index) return null;
    const fromHash = index.weeks.find((w) => w.games.some((g) => g.game_id === initial.game));
    return fromHash?.week ?? defaultWeek(index);
  }, [index, initial.game]);

  const [week, setWeek] = useState<number | null>(initialWeek);
  const games = index?.weeks.find((w) => w.week === week)?.games ?? [];
  const [gameId, setGameId] = useState<string | null>(initial.game && games.some((g) => g.game_id === initial.game) ? initial.game : (games[0]?.game_id ?? null));
  const [side, setSide] = useState(initial.side);
  const [report, setReport] = useState<GameReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pickWeek = (w: number) => {
    setWeek(w);
    setGameId(index?.weeks.find((x) => x.week === w)?.games[0]?.game_id ?? null);
    setSide(0);
  };

  useEffect(() => {
    const g = games.find((x) => x.game_id === gameId);
    if (!g) return setReport(null);
    let live = true;
    loadGame(g.path)
      .then((r) => live && (setReport(r), setError(null)))
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [gameId]);

  useEffect(() => {
    if (gameId) history.replaceState(null, '', `#game=${gameId}&side=${side}`);
  }, [gameId, side]);

  const s = report?.sides[side];

  return (
    <div className="flex min-h-full flex-col">
      <header className="z-20 border-b border-line bg-bg/95 backdrop-blur sm:sticky sm:top-0">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm bg-accent" aria-hidden />
            <span className="text-[13px] font-semibold tracking-tight">
              ClevAnalytics <span className="font-normal text-ink-2">Run Game Matchups</span>
            </span>
          </div>
          {index && (
            <>
              <label className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-ink-3">
                Week
                <select
                  value={week ?? ''}
                  onChange={(e) => pickWeek(Number(e.target.value))}
                  className="h-7 rounded border border-line-2 px-1.5 text-[13px] normal-case tracking-normal text-ink"
                >
                  {index.weeks.map((w) => (
                    <option key={w.week} value={w.week}>
                      {index.season} Week {w.week} · {formatDate(w.games[0]?.gameday ?? null, { month: 'short', day: 'numeric' })}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-ink-3">
                Matchup
                <select
                  value={gameId ?? ''}
                  onChange={(e) => {
                    setGameId(e.target.value);
                    setSide(0);
                  }}
                  className="h-7 max-w-[15rem] rounded border border-accent/60 px-1.5 text-[13px] normal-case tracking-normal text-ink"
                >
                  {games.map((g) => (
                    <option key={g.game_id} value={g.game_id}>
                      {g.away} @ {g.home} · {formatDate(g.gameday, { weekday: 'short' })} {formatKickoff(g.gametime)}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          <nav className="ml-auto flex items-center gap-4 text-[12px]">
            {embedded && (
              <a href={window.location.href} target="_blank" rel="noopener" className="text-accent hover:underline">
                Open full screen ↗
              </a>
            )}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 py-4">
        {!index && <p className="text-ink-2">No matchup reports yet. Run the pipeline (see README) and commit data/.</p>}
        {error && (
          <p className="flex items-center gap-2 text-bad">
            <ErrorIcon /> {error}
          </p>
        )}
        {report && s && (
          <>
            <ReportHeader r={report} />
            <div role="tablist" aria-label="Side of the ball" className="mt-4 flex flex-wrap gap-1 border-b border-line">
              {report.sides.map((x, i) => (
                <button
                  key={x.offense}
                  role="tab"
                  type="button"
                  aria-selected={side === i}
                  onClick={() => setSide(i)}
                  className={`-mb-px border-b-2 px-3 pb-2 pt-1 text-[13px] ${side === i ? 'border-accent text-ink' : 'border-transparent text-ink-2 hover:text-ink'}`}
                >
                  <span className="font-semibold">{x.offense}</span> run game <span className="text-ink-3">vs</span> <span className="font-semibold">{x.defense}</span> run D
                </button>
              ))}
            </div>
            <nav aria-label="Sections" className="flex flex-wrap gap-x-4 gap-y-1 py-2 text-[12px]">
              {s.sections.map((sec) => (
                <a key={sec.id} href={`#${sec.id}`} onClick={(e) => (e.preventDefault(), document.getElementById(`sec-${sec.id}`)?.scrollIntoView({ behavior: 'smooth' }))} className="text-ink-2 hover:text-accent">
                  {sec.title}
                </a>
              ))}
            </nav>
            {s.sections.map((sec) => (
              <SectionBlock key={`${s.offense}-${sec.id}`} sec={sec} />
            ))}
            <ReportFooter r={report} />
          </>
        )}
      </main>
    </div>
  );
}

function ReportHeader({ r }: { r: GameReport }) {
  const cur = r.window.current;
  return (
    <section className="rounded-md border border-line bg-panel px-4 py-3">
      <h1 className="text-[22px] font-semibold tracking-tight">
        {r.away} <span className="text-ink-3">@</span> {r.home}
      </h1>
      <dl className="num mt-1 flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
        {[
          ['Week', `${r.season} Week ${r.week}`],
          ['Date', formatDate(r.gameday)],
          ['Kickoff', formatKickoff(r.gametime)],
          ['Stadium', r.stadium ?? '—'],
          ['Data as of', r.data_as_of ? `${formatDate(r.data_as_of, { month: 'short', day: 'numeric', year: 'numeric' })} (${cur.season} ${weeksLabel(cur.weeks)})` : `no ${cur.season} games yet`],
        ].map(([k, v]) => (
          <div key={k} className="flex gap-1.5">
            <dt className="text-ink-3">{k}</dt>
            <dd className="text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[11.5px] text-ink-2">
        Left / middle / right and end / tackle / guard are always from the <strong className="text-ink">offense's</strong> point of view, in the defense tables too.
        Every figure shows its attempts (n); early-season samples are small and noisy.
      </p>
    </section>
  );
}

function SectionBlock({ sec }: { sec: Section }) {
  return (
    <section id={`sec-${sec.id}`} className="mt-6 scroll-mt-16">
      <h2 className="text-[15px] font-semibold tracking-tight">{sec.title}</h2>
      {sec.subtitle && <p className="text-[12px] text-ink-3">{sec.subtitle}</p>}
      {sec.empty ? (
        <p className="mt-2 rounded-md border border-line bg-panel px-3 py-3 text-[12px] text-ink-2">{sec.empty}</p>
      ) : (
        <div className="mt-2 grid gap-3">
          {sec.tables?.map((t) => (
            <ReportTable key={t.id} t={t} />
          ))}
        </div>
      )}
    </section>
  );
}

function ReportFooter({ r }: { r: GameReport }) {
  const block = (title: string, items: string[]) => (
    <div>
      <h3 className="mb-1 text-[11px] uppercase tracking-wider text-ink-3">{title}</h3>
      <ul className="list-disc space-y-0.5 pl-4 text-[11.5px] leading-relaxed text-ink-2 marker:text-ink-3">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
  return (
    <footer className="mt-8 grid gap-4 border-t border-line pt-4 md:grid-cols-2">
      {block('Notes', r.notes)}
      {block('Data source: nflverse', r.sources)}
      {block('Filters', r.filters)}
      {block('Rank qualifiers (rank 1 = best for that unit)', Object.values(r.qualifiers))}
      <details className="md:col-span-2">
        <summary className="cursor-pointer text-[11px] uppercase tracking-wider text-ink-3">Validation checks run for this report</summary>
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11.5px] text-ink-2 marker:text-ink-3">
          {r.checks.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      </details>
      <p className="text-[11px] text-ink-3 md:col-span-2">Generated {r.generated_at.replace('T', ' ').replace('Z', ' UTC')}. Small samples are noisy; read every rate next to its attempt count.</p>
    </footer>
  );
}
