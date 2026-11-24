"""
Walk-forward backtest of the Run Edge.

    python pipeline/backtest.py            # writes data/backtest/run-edge.json

For every regular-season week from 4 on (2023 through the current season), each team's lead back (the
non-QB with the most designed runs for that team in earlier weeks, 25+ carries) is scored from EARLIER
games only: the defense's success rate and YPC allowed, and this week's Vegas line. The result is compared
with what he actually did: his rushing yards on designed runs that week vs his normal game (his yards per
game in earlier weeks). Backs with no carry that week (injured, inactive) are left out.

It also scores the same games with the previous Run Edge (rank percentiles by direction) so the two can
be compared, and refits the model's weights on 2023-2025 so you can see where MODEL in config.py came from.
2026 is never used to fit: it is the out-of-sample check.
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))

from matchups import load, model  # noqa: E402
from matchups.config import EDGE, MODEL, OUTPUT_DIR  # noqa: E402
from matchups.plays import designed_runs  # noqa: E402

FIRST_SEASON = 2023
FIRST_WEEK = 4
TRAIN_LAST = 2025
DIRS = ["left", "middle", "right"]


def _agg(df: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    return df.group_by(keys).agg(pl.len().alias("att"), pl.col("success").mean().alias("sr"), pl.col("yards").mean().alias("ypc"), pl.col("yards").sum().alias("yds"))


def _pct(col: str, ok: pl.Expr, higher_better: bool) -> pl.Expr:
    v = pl.when(ok).then(pl.col(col) * (-1.0 if higher_better else 1.0))
    r, n = v.rank("min").over("direction"), ok.sum().over("direction")
    return pl.when(ok & (n > 1)).then(1 - (r - 1) / (n - 1)).when(ok).then(1.0).otherwise(None)


def old_edges(win: pl.DataFrame, games: pl.DataFrame) -> tuple[dict, dict]:
    """The previous Run Edge's inputs: direction percentiles for RBs (2 carries per team game) and defenses (3)."""
    known = win.filter(pl.col("direction").is_not_null())
    dd = _agg(known, ["defteam", "direction"]).join(games.rename({"team": "defteam"}), on="defteam")
    ok = pl.col("att") >= (pl.col("games") * 3 - 1e-9).ceil()
    dd = dd.with_columns(_pct("sr", ok, False).alias("p_sr"), _pct("ypc", ok, False).alias("p_ypc"))
    rd = _agg(known.filter(~pl.col("is_qb_run")), ["rusher_player_id", "posteam", "direction"]).join(games.rename({"team": "posteam"}), on="posteam")
    rd = rd.join(rd.group_by(["rusher_player_id", "posteam"]).agg(pl.col("att").sum().alias("tot")), on=["rusher_player_id", "posteam"])
    ok = pl.col("att") >= (pl.col("games") * 2 - 1e-9).ceil()
    rd = rd.with_columns((pl.col("att") / pl.col("tot")).alias("share"), _pct("sr", ok, True).alias("p_sr"), _pct("ypc", ok, True).alias("p_ypc"))
    return ({(r["defteam"], r["direction"]): r for r in dd.iter_rows(named=True)},
            {(r["rusher_player_id"], r["posteam"], r["direction"]): r for r in rd.iter_rows(named=True)})


def old_run_edge(pid: str, team: str, dfn: str, dd: dict, rd: dict) -> int | None:
    num = cov = 0.0
    for d in DIRS:
        o, de = rd.get((pid, team, d)), dd.get((dfn, d))
        if not o or not de or None in (o["p_sr"], o["p_ypc"], de["p_sr"], de["p_ypc"]):
            continue
        e = round(50 + 50 * ((o["p_sr"] + o["p_ypc"]) / 2 - (de["p_sr"] + de["p_ypc"]) / 2))
        num, cov = num + e * o["share"], cov + o["share"]
    return round(num / cov) if cov else None


def season_rows(season: int, players: pl.DataFrame) -> list[dict]:
    sched = load.schedule(season).filter(pl.col("game_type") == "REG")
    try:
        ftn = load.ftn(season)
    except Exception:  # noqa: BLE001
        ftn = None
    runs, _ = designed_runs(load.pbp(season), players, ftn)
    runs = runs.filter(pl.col("success").is_not_null())
    done = sched.group_by("week").agg(pl.col("result").is_not_null().all().alias("done")).filter(pl.col("done"))
    out = []
    for w in range(FIRST_WEEK, (done["week"].max() or 0) + 1):
        win, game = runs.filter(pl.col("week") < w), runs.filter(pl.col("week") == w)
        if not game.height or not win.height:
            continue
        games = pl.concat([win.select("game_id", pl.col("posteam").alias("team")), win.select("game_id", pl.col("defteam").alias("team"))]).unique().group_by("team").len().rename({"len": "games"})
        lg = {k: round(v, 4) for k, v in win.select(pl.col("success").mean().alias("sr"), pl.col("yards").mean().alias("ypc")).row(0, named=True).items()}
        dfo = {r["defteam"]: r for r in _agg(win, ["defteam"]).join(games.rename({"team": "defteam"}), on="defteam").iter_rows(named=True)}
        nonqb = win.filter(~pl.col("is_qb_run"))
        pw = _agg(nonqb, ["rusher_player_id", "posteam"]).join(nonqb.group_by(["rusher_player_id", "posteam"]).agg(pl.col("game_id").n_unique().alias("g")), on=["rusher_player_id", "posteam"])
        lead = pw.sort(["att", "rusher_player_id"], descending=[True, False]).group_by("posteam", maintain_order=True).first()
        actual = {(r["rusher_player_id"], r["posteam"]): r for r in _agg(game.filter(~pl.col("is_qb_run")), ["rusher_player_id", "posteam", "defteam"]).iter_rows(named=True)}
        vg = model.vegas_table(sched, w)
        dd, rd = old_edges(win, games)
        for p in lead.iter_rows(named=True):
            a = actual.get((p["rusher_player_id"], p["posteam"]))
            if p["att"] < MODEL["min_att"] or not a or a["defteam"] not in dfo:
                continue
            d = dfo[a["defteam"]]
            d_over = {"sr": round(d["sr"], 4), "ypc": round(d["ypc"], 4), "games": d["games"]}
            m = model.matchup(d_over, lg, vg.get(p["posteam"]))
            base = p["yds"] / p["g"]
            if base <= 10:  # no meaningful normal game to compare with
                continue
            out.append({
                "season": season, "week": w, "player_id": p["rusher_player_id"], "team": p["posteam"], "opp": a["defteam"],
                "run_edge": m["run_edge"], "pred": m["mult"] - 1, "old_edge": old_run_edge(p["rusher_player_id"], p["posteam"], a["defteam"], dd, rd),
                "sr_idx": m["sr_idx"], "ypc_idx": m["ypc_idx"], "vegas_idx": m["vegas_idx"],
                "base_ypg": base, "yds": a["yds"], "att": a["att"], "actual": min(a["yds"] / base, 4.0) - 1,
            })
    return out


def spearman(a, b) -> float | None:
    if len(a) < 30:
        return None
    ra, rb = pl.Series(a).rank().to_numpy(), pl.Series(b).rank().to_numpy()
    return round(float(np.corrcoef(ra, rb)[0, 1]), 3)


def summarize(rows: list[dict]) -> dict:
    bands = [(k, label, lo) for k, label, lo in EDGE["bands"]]
    by_band = []
    for i, (k, label, lo) in enumerate(bands):
        hi = bands[i - 1][2] if i else 101
        sel = [r for r in rows if lo <= r["run_edge"] < hi]
        by_band.append({"key": k, "label": label, "n": len(sel),
                        "actual": round(float(np.mean([r["actual"] for r in sel])), 4) if sel else None,
                        "pred": round(float(np.mean([r["pred"] for r in sel])), 4) if sel else None})
    preds = np.array([r["pred"] for r in rows])
    q = np.quantile(preds, [0.2, 0.4, 0.6, 0.8]) if rows else []
    fifths = []
    for i in range(5):
        sel = [r for r in rows if np.digitize(r["pred"], q) == i]
        fifths.append({"n": len(sel), "actual": round(float(np.mean([r["actual"] for r in sel])), 4) if sel else None,
                       "pred": round(float(np.mean([r["pred"] for r in sel])), 4) if sel else None})
    old = [r for r in rows if r["old_edge"] is not None]
    return {
        "n": len(rows),
        "rho": spearman([r["pred"] for r in rows], [r["actual"] for r in rows]),
        "rho_old": spearman([r["old_edge"] for r in old], [r["actual"] for r in old]),
        "n_old": len(old),
        "bands": by_band,
        "fifths": fifths,
    }


def refit(rows: list[dict]) -> dict:
    """Least squares of (actual change) on ln(sr_idx), ln(ypc_idx), ln(vegas_idx) — where MODEL's weights come from."""
    X = np.array([[math.log(r["sr_idx"]), math.log(r["ypc_idx"]), math.log(r["vegas_idx"]), 1.0] for r in rows])
    y = np.array([r["actual"] for r in rows])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    return {"w_sr": round(float(b[0]), 2), "w_ypc": round(float(b[1]), 2), "w_vegas": round(float(b[2]), 2), "n": len(rows)}


def main() -> int:
    current = load.current_season()
    seasons = list(range(FIRST_SEASON, current + 1))
    players = load.players(tuple(seasons))
    rows = []
    for s in seasons:
        r = season_rows(s, players)
        print(f"{s}: {len(r)} lead-back games")
        rows += r
    train = [r for r in rows if r["season"] <= TRAIN_LAST]
    test = [r for r in rows if r["season"] > TRAIN_LAST]
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "model": {k: MODEL[k] for k in ("k_games", "w_sr", "w_ypc", "w_vegas", "vegas_min_games", "scale", "min_att")},
        "refit_train": refit(train),
        "method": [
            f"Every regular-season week from {FIRST_WEEK} on, {FIRST_SEASON}–{current}, scored from earlier games only (nflverse play-by-play and schedule lines).",
            f"Each team's lead back: the non-QB with the most designed runs for that team in earlier weeks ({MODEL['min_att']}+). Games he missed are left out.",
            "Result: his rushing yards on designed runs that week ÷ his yards per game in earlier weeks, minus 1 (capped at +300%).",
            f"Weights fitted on {FIRST_SEASON}–{TRAIN_LAST}; {TRAIN_LAST + 1}+ is the out-of-sample check.",
            "Rank correlation (ρ): 0 = no better than chance, 1 = perfect order. One game is noisy; even good inputs reach about 0.15–0.20.",
        ],
        "train": {"label": f"{FIRST_SEASON}–{TRAIN_LAST} (fitted)", **summarize(train)},
        "test": {"label": f"{TRAIN_LAST + 1}{'–' + str(current) if current > TRAIN_LAST + 1 else ''} (not used to fit)", **summarize(test)},
        "seasons": {str(s): summarize([r for r in rows if r["season"] == s]) for s in seasons},
    }
    path = OUTPUT_DIR / "backtest" / "run-edge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, allow_nan=False) + "\n")
    print(json.dumps({k: out[k] for k in ("refit_train",)}, indent=1))
    for k in ("train", "test"):
        t = out[k]
        print(f"{t['label']}: n={t['n']} rho new {t['rho']} vs old {t['rho_old']}; fifths actual {[f['actual'] for f in t['fifths']]}")
    print(f"-> {path.relative_to(OUTPUT_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
