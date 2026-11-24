import { loadBacktest } from './data';
import type { BacktestPart } from './types';
import { BAND_STYLE, Panel } from './ui';

const pct = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(Math.round(v * 100))}%`);

/** How well the Run Edge has predicted real results: the walk-forward backtest, by band and by fifth. */
export function TrackRecordView() {
  const bt = loadBacktest();
  if (!bt) return <p className="text-ink-3">No backtest yet. Run python pipeline/backtest.py and commit data/backtest/.</p>;
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-[18px] font-semibold">Track record</h2>
        <p className="max-w-[900px] text-[12.5px] text-ink-2">
          Every week scored the way the page scores it, from earlier games only, then compared with what each team&apos;s lead back actually ran for: his rushing yards that week vs his normal game.
          The weights were fitted on {bt.train.label?.replace(' (fitted)', '')}; {bt.test.label?.replace(' (not used to fit)', '')} was never used to fit, so it is the honest test.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Part title={bt.train.label ?? 'Fitted seasons'} p={bt.train} />
        <Part title={bt.test.label ?? 'Out of sample'} p={bt.test} highlight />
      </div>
      <Panel title="By season" note="ρ = rank correlation with actual results (0 = chance)">
        <table className="num w-full max-w-[640px] text-[12px]">
          <thead className="text-[10.5px] uppercase tracking-wider text-ink-3">
            <tr className="text-left">
              <th className="py-1 font-medium">Season</th>
              <th className="py-1 text-right font-medium">Games</th>
              <th className="py-1 text-right font-medium">Run Edge ρ</th>
              <th className="py-1 text-right font-medium">Old Run Edge ρ</th>
              <th className="py-1 text-right font-medium">Worst fifth</th>
              <th className="py-1 text-right font-medium">Best fifth</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(bt.seasons).map(([s, p]) => (
              <tr key={s} className="border-t border-line/60">
                <td className="py-1.5">{s}</td>
                <td className="py-1.5 text-right text-ink-2">{p.n}</td>
                <td className="py-1.5 text-right font-semibold">{p.rho?.toFixed(3) ?? '—'}</td>
                <td className="py-1.5 text-right text-ink-3">{p.rho_old?.toFixed(3) ?? '—'}</td>
                <td className="py-1.5 text-right text-edge-bad">{pct(p.fifths[0]?.actual ?? null)}</td>
                <td className="py-1.5 text-right text-edge-good">{pct(p.fifths[4]?.actual ?? null)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="How the test works">
        <ul className="list-disc space-y-1 pl-5 text-[12px] text-ink-2">
          {bt.method.map((m) => (
            <li key={m}>{m}</li>
          ))}
          <li>
            Weights in use: success rate allowed^{bt.model.w_sr} × YPC allowed^{bt.model.w_ypc} × Vegas^{bt.model.w_vegas}, defenses shrunk by G / (G + {bt.model.k_games}). Refit on the
            fitted seasons today: {bt.refit_train.w_sr} / {bt.refit_train.w_ypc} / {bt.refit_train.w_vegas}.
          </li>
          <li>Tested and left out because they added nothing: the RB&apos;s own direction and gap splits matched to the defense&apos;s, explosive and stuff rates allowed, heavy-box rate, point spread on its own.</li>
        </ul>
        <p className="mt-2 text-[11px] text-ink-3">Backtest run {bt.generated_at.replace('T', ' ').replace('Z', ' UTC')}.</p>
      </Panel>
    </div>
  );
}

function Part({ title, p, highlight }: { title: string; p: BacktestPart; highlight?: boolean }) {
  const max = Math.max(0.05, ...p.fifths.map((f) => Math.abs(f.actual ?? 0)));
  return (
    <Panel title={title} note={`${p.n} lead-back games`} className={highlight ? 'border-accent/40' : ''}>
      <p className="text-[12.5px]">
        Rank correlation with actual yards: <span className="num font-semibold">{p.rho?.toFixed(3) ?? '—'}</span>{' '}
        <span className="text-ink-3">(the old Run Edge: {p.rho_old?.toFixed(3) ?? '—'} on {p.n_old} games)</span>
      </p>
      <table className="num mt-3 w-full text-[12px]">
        <thead className="text-[10.5px] uppercase tracking-wider text-ink-3">
          <tr className="text-left">
            <th className="py-1 font-medium">Band</th>
            <th className="py-1 text-right font-medium">Games</th>
            <th className="py-1 text-right font-medium">Predicted</th>
            <th className="py-1 text-right font-medium">Actual vs normal</th>
          </tr>
        </thead>
        <tbody>
          {p.bands.map((b) => (
            <tr key={b.key} className="border-t border-line/60">
              <td className="py-1.5">
                <span className={`rounded border px-1.5 py-px text-[11px] ${BAND_STYLE[b.key]}`}>{b.label}</span>
              </td>
              <td className="py-1.5 text-right text-ink-2">{b.n}</td>
              <td className="py-1.5 text-right text-ink-3">{pct(b.pred)}</td>
              <td className={`py-1.5 text-right font-semibold ${(b.actual ?? 0) > 0.02 ? 'text-edge-good' : (b.actual ?? 0) < -0.02 ? 'text-edge-bad' : ''}`}>{pct(b.actual)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-[10.5px] uppercase tracking-wider text-ink-3">Matchups split into fifths, worst to best: actual yards vs normal</p>
      <div className="mt-1 grid grid-cols-5 gap-2" style={{ height: 84 }}>
        {p.fifths.map((f, i) => {
          const v = f.actual ?? 0;
          const h = (Math.abs(v) / max) * 40;
          return (
            <div key={i} className="relative h-full" role="img" aria-label={`Fifth ${i + 1}: actual ${pct(f.actual)}`} title={`Fifth ${i + 1}: predicted ${pct(f.pred)}, actual ${pct(f.actual)} (${f.n} games)`}>
              <span aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-line-2" />
              <span aria-hidden className={`absolute inset-x-1 rounded ${v >= 0 ? 'bg-edge-good' : 'bg-edge-bad'}`} style={v >= 0 ? { bottom: '50%', height: h } : { top: '50%', height: h }} />
            </div>
          );
        })}
      </div>
      <div className="mt-1 grid grid-cols-5 gap-2 text-center">
        {p.fifths.map((f, i) => (
          <span key={i} className="num text-[11px] text-ink-2">
            {pct(f.actual)}
            <span className="block text-[10px] text-ink-3">{i === 0 ? 'worst' : i === 4 ? 'best' : `fifth ${i + 1}`}</span>
          </span>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-ink-3">One game is noisy: judge the bands over many games, not one back&apos;s week.</p>
    </Panel>
  );
}
