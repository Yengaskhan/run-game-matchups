"""
The Run Edge model (see MODEL in config.py for the formula and where the weights come from).

Inputs are the rounded numbers written to the week JSON, so the page (src/edge.ts) reproduces every score
exactly from the same file.
"""

import math

from .config import EDGE, MODEL


def def_index(rate: float | None, league: float | None, games: int | None) -> float:
    """A defense's rate allowed vs league (1.00 = average), shrunk toward 1.00 by games played."""
    if rate is None or not league or not games:
        return 1.0
    return 1 + games / (games + MODEL["k_games"]) * (rate / league - 1)


def vegas_index(implied: float | None, avg: float | None, n: int) -> float:
    """This week's implied team total vs the team's average implied total in earlier weeks."""
    if implied is None or not avg or n < MODEL["vegas_min_games"]:
        return 1.0
    return implied / avg


def multiplier(sr_idx: float, ypc_idx: float, vegas: float) -> float:
    return math.exp(MODEL["w_sr"] * math.log(sr_idx) + MODEL["w_ypc"] * math.log(ypc_idx) + MODEL["w_vegas"] * math.log(vegas))


def score(mult: float) -> int:
    return round(50 + 50 * math.tanh(math.log(mult) / MODEL["scale"]))


def band(edge: int | None) -> str:
    if edge is None:
        return "neutral"
    return next(key for key, _label, lo in EDGE["bands"] if edge >= lo)


def matchup(def_overall: dict, league: dict, vegas: dict | None) -> dict:
    """The defense / game side of one matchup. `vegas` = {implied, avg, n} for a scheduled game, else None."""
    sr_idx = def_index(def_overall.get("sr"), league.get("sr"), def_overall.get("games"))
    ypc_idx = def_index(def_overall.get("ypc"), league.get("ypc"), def_overall.get("games"))
    v = vegas_index(*(vegas[k] for k in ("implied", "avg", "n"))) if vegas else 1.0
    m = multiplier(sr_idx, ypc_idx, v)
    edge = score(m)
    return {"sr_idx": round(sr_idx, 4), "ypc_idx": round(ypc_idx, 4), "vegas_idx": round(v, 4), "mult": round(m, 4), "run_edge": edge, "band": band(edge)}


def vegas_table(schedule, week: int) -> dict[str, dict]:
    """{team: {implied, avg, n}} for the teams playing `week`: this game's implied team total and the team's
    average implied total over its earlier regular-season games (nflverse total_line / spread_line, where
    spread_line > 0 means the home team is favored)."""
    import polars as pl

    s = schedule.filter(pl.col("game_type") == "REG", pl.col("week") <= week, pl.col("total_line").is_not_null(), pl.col("spread_line").is_not_null())
    both = pl.concat([
        s.select("week", pl.col("home_team").alias("team"), ((pl.col("total_line") + pl.col("spread_line")) / 2).alias("implied")),
        s.select("week", pl.col("away_team").alias("team"), ((pl.col("total_line") - pl.col("spread_line")) / 2).alias("implied")),
    ])
    out = {}
    for r in both.filter(pl.col("week") == week).iter_rows(named=True):
        prev = both.filter(pl.col("team") == r["team"], pl.col("week") < week)["implied"]
        out[r["team"]] = {"implied": round(r["implied"], 2), "avg": round(prev.mean(), 4) if prev.len() else None, "n": prev.len()}
    return out
