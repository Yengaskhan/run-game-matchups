import { useEffect, useMemo, useState } from 'react';
import { defaultWeek, listSeasons, loadWeek } from './data';
import { DefenseView } from './DefenseView';
import { formatDate } from './format';
import { Footer } from './parts';
import { PlayerView } from './PlayerView';
import { SlateView } from './SlateView';
import type { WeekReport } from './types';
import { BAND_STYLE, Select } from './ui';

/** True when the page runs inside an iframe (e.g. embedded on a website-builder page). */
const embedded = (() => {
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
})();

export type Tab = 'slate' | 'player' | 'defense';
const TABS: [Tab, string][] = [
  ['slate', 'Slate Rankings'],
  ['player', 'Player vs Defense'],
  ['defense', 'Defense Profiles'],
];

/** The view lives in the URL hash so a link goes straight to it. */
export type HashState = Partial<Record<'tab' | 'week' | 'season' | 'split' | 'player' | 'opp' | 'team', string>>;
export type Update = (patch: HashState) => void;

function readHash(): HashState {
  return Object.fromEntries(new URLSearchParams(window.location.hash.slice(1))) as HashState;
}

export default function MatchupApp() {
  const index = useMemo(() => listSeasons()[0] ?? null, []);
  const [hash, setHash] = useState<HashState>(readHash);
  const [report, setReport] = useState<WeekReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tab = (TABS.some(([t]) => t === hash.tab) ? hash.tab : 'slate') as Tab;
  const week = index ? (index.weeks.find((w) => w.week === Number(hash.week))?.week ?? defaultWeek(index)) : null;

  const update: Update = (patch) => {
    setHash((h) => ({ ...h, ...patch }));
    // Switching views (e.g. clicking a row far down the slate) starts the new view at the top.
    if (patch.tab) window.scrollTo({ top: 0 });
  };

  useEffect(() => {
    const p = new URLSearchParams(Object.entries(hash).filter(([, v]) => v != null && v !== '') as [string, string][]);
    history.replaceState(null, '', `#${p}`);
  }, [hash]);

  useEffect(() => {
    const w = index?.weeks.find((x) => x.week === week);
    if (!w) return;
    let live = true;
    loadWeek(w.path)
      .then((r) => live && (setReport(r), setError(null)))
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [week]);

  // The chosen season if this week has it; otherwise the current season, or the prior one when it's empty.
  const seasonMeta = report ? (report.seasons.find((s) => String(s.season) === hash.season) ?? report.seasons.find((x) => x.current && !x.empty) ?? report.seasons[1]) : null;
  const season = seasonMeta ? String(seasonMeta.season) : null;
  const ready = report && report.week === week && season;

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-line bg-bg/95 px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-sm bg-accent" aria-hidden />
          <span className="text-[13px] font-semibold tracking-tight">
            ClevAnalytics <span className="font-normal text-ink-2">Run Game Matchups</span>
          </span>
          {embedded && (
            <a href={window.location.href} target="_blank" rel="noopener" className="ml-auto text-[12px] text-accent hover:underline">
              Open full screen ↗
            </a>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1320px] flex-1 px-4 py-5">
        {!index && <p className="text-ink-2">No reports yet. Run the pipeline (see README) and commit data/.</p>}
        {error && <p className="rounded-md border border-bad/40 bg-panel px-3 py-2 text-bad">{error}</p>}

        {index && (
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                {index.season} Week {week} preview
              </p>
              <h1 className="text-[22px] font-semibold tracking-tight">Run Game Matchup Report</h1>
              <p className="text-[12px] text-ink-2">Each team's starting RB, on his own carries, against the opponent's run defense, by where he runs.</p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <Select label="Week" value={String(week ?? '')} onChange={(v) => update({ week: v })}
                options={index.weeks.map((w) => [String(w.week), `Week ${w.week} · ${formatDate(w.first_gameday, { month: 'short', day: 'numeric' })}`])} />
              {report && <Select label="Season data" value={season ?? ''} onChange={(v) => update({ season: v })} options={report.seasons.map((s) => [String(s.season), s.label])} />}
            </div>
          </div>
        )}

        {index && (
          <nav className="mt-4 flex gap-1 overflow-x-auto border-b border-line" aria-label="Views">
            {TABS.map(([t, label]) => (
              <button
                key={t}
                type="button"
                onClick={() => update({ tab: t })}
                aria-current={tab === t ? 'page' : undefined}
                className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-[13px] ${tab === t ? 'border-accent font-semibold text-ink' : 'border-transparent text-ink-2 hover:text-ink'}`}
              >
                {label}
              </button>
            ))}
          </nav>
        )}

        {!ready ? (
          index && !error && <p className="mt-4 text-ink-3">Loading…</p>
        ) : (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-1.5 text-[11px]">
              {report.edge.bands.map((b) => (
                <span key={b.key} className={`rounded border px-2 py-1 ${BAND_STYLE[b.key]}`}>
                  {b.key === 'neutral' ? 'Neutral / small sample' : b.label}
                </span>
              ))}
              <span className="ml-1 text-ink-3">
                Run Edge 0–100, 50 = even. Data as of {formatDate(report.data_as_of, { month: 'short', day: 'numeric', year: 'numeric' })}. Left / right = the offense's left / right.
              </span>
            </div>
            {seasonMeta && !seasonMeta.current && (
              <p className="mt-3 rounded-md border border-line-2 bg-panel-2 px-3 py-2 text-[12px] text-ink-2">
                <span className="font-semibold text-ink">Prior season: {seasonMeta.label}.</span> This week's matchups scored with last season's numbers only, not this season's. Rosters and
                schemes have changed since.
              </p>
            )}
            <div className="mt-4">
              {seasonMeta?.empty ? (
                <p className="rounded-md border border-line bg-panel px-3 py-3 text-[12.5px] text-ink-2">{seasonMeta.empty}</p>
              ) : tab === 'player' ? (
                <PlayerView report={report} season={season} hash={hash} update={update} />
              ) : tab === 'defense' ? (
                <DefenseView report={report} season={season} hash={hash} update={update} />
              ) : (
                <SlateView report={report} season={season} hash={hash} update={update} />
              )}
            </div>
            <Footer report={report} />
          </>
        )}
      </main>
    </div>
  );
}
