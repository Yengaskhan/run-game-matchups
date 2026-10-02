"""
Reconciliation and consistency checks. Any failure stops the run before files are written.

0. Every final game in the window is in play-by-play.
1. PBP rush totals per team-game match nflverse team_stats (carries and rushing yards) within TOLERANCE.
2. Designed runs + every removed category add back up to all rush attempts.
3. PFR carries per team-game match team_stats carries (so YBC/YAC cover every carry).
4. In every season block, split shares sum to 100% (±0.1 point: values are rounded to 4 decimals) and rusher rows sum to the team total.
"""

import polars as pl

from .config import TOLERANCE
from .plays import all_rushes


class ValidationError(Exception):
    pass


def check_pbp_complete(pbp: pl.DataFrame, schedule: pl.DataFrame, weeks: list[int]) -> str:
    """Every final game in the window must be in play-by-play (nflverse can lag a day behind the scores)."""
    final = schedule.filter(pl.col("game_type") == "REG", pl.col("week").is_in(weeks), pl.col("result").is_not_null())
    have = set(pbp.filter(pl.col("week").is_in(weeks))["game_id"].unique().to_list())
    missing = sorted(set(final["game_id"].to_list()) - have)
    if missing:
        raise ValidationError(f"Play-by-play is missing {len(missing)} final games: {missing}. nflverse PBP usually lands within a day; re-run later.")
    return f"Play-by-play: all {final.height} final games in the window are present."


def reconcile_team_totals(pbp: pl.DataFrame, team_stats: pl.DataFrame, weeks: list[int]) -> str:
    rush = all_rushes(pbp.filter(pl.col("week").is_in(weeks)))
    ours = rush.group_by(["game_id", "posteam"]).agg(pl.len().alias("att"), pl.col("rushing_yards").fill_null(0).sum().alias("yds"))
    ts = team_stats.filter(pl.col("season_type") == "REG", pl.col("week").is_in(weeks))
    j = ts.join(ours, left_on=["game_id", "team"], right_on=["game_id", "posteam"], how="left").with_columns(
        (pl.col("carries") - pl.col("att").fill_null(0)).abs().alias("d_att"),
        (pl.col("rushing_yards") - pl.col("yds").fill_null(0)).abs().alias("d_yds"),
    )
    bad = j.filter((pl.col("d_att") > TOLERANCE["carries"]) | (pl.col("d_yds") > TOLERANCE["yards"]))
    if bad.height:
        raise ValidationError(f"PBP rush totals don't reconcile with nflverse team_stats:\n{bad.select(['game_id', 'team', 'carries', 'att', 'rushing_yards', 'yds'])}")
    exact = j.filter((pl.col("d_att") == 0) & (pl.col("d_yds") == 0)).height
    return (f"Team rushing totals: {j.height} team-games checked against nflverse team_stats; {exact} exact, "
            f"max difference {int(j['d_att'].max() or 0)} carries / {int(j['d_yds'].max() or 0)} yards (tolerance {TOLERANCE['carries']} / {TOLERANCE['yards']}).")


def reconcile_removed(pbp: pl.DataFrame, runs: pl.DataFrame, removed: dict, weeks: list[int]) -> str:
    total = all_rushes(pbp.filter(pl.col("week").is_in(weeks))).height
    if runs.height + sum(removed.values()) != total:
        raise ValidationError(f"Designed runs ({runs.height}) + removed ({removed}) != all rush attempts ({total})")
    return f"Filter accounting: {total} rush attempts = {runs.height} designed runs + " + ", ".join(f"{v} {k.replace('_', '-')}" for k, v in removed.items() if v) + "."


def pfr_complete_weeks(pfr: pl.DataFrame, team_stats: pl.DataFrame, weeks: list[int]) -> tuple[list[int], list[str]]:
    """The leading run of weeks in which PFR has every team-game, plus the games it is still missing.
    PFR lags play-by-play by a day or two (Monday night games especially), so the weekly run uses
    YBC / YAC through the last complete week instead of stopping, and says so on the page."""
    ts = team_stats.filter(pl.col("season_type") == "REG", pl.col("week").is_in(weeks))
    have = set(zip(pfr["game_id"].to_list(), pfr["team"].to_list()))
    missing = ts.filter(~pl.struct(["game_id", "team"]).map_elements(lambda r: (r["game_id"], r["team"]) in have, return_dtype=pl.Boolean))
    bad_weeks = set(missing["week"].to_list())
    complete = []
    for w in sorted(weeks):
        if w in bad_weeks:
            break
        complete.append(w)
    return complete, sorted(missing["game_id"].unique().to_list())


def reconcile_pfr(pfr: pl.DataFrame, team_stats: pl.DataFrame, weeks: list[int]) -> str:
    ts = team_stats.filter(pl.col("season_type") == "REG", pl.col("week").is_in(weeks))
    p = pfr.group_by(["game_id", "team"]).agg(pl.col("carries").sum().alias("pfr"))
    j = ts.join(p, on=["game_id", "team"], how="left")
    missing = j.filter(pl.col("pfr").is_null())
    if missing.height:
        raise ValidationError(
            f"PFR advanced rushing is missing {missing.height} team-games in the window: {missing['game_id'].unique().to_list()}. "
            "nflverse usually publishes PFR a day or two after the games; re-run later, or run an earlier --week."
        )
    bad = j.filter((pl.col("carries") - pl.col("pfr")).abs() > TOLERANCE["carries"])
    if bad.height:
        raise ValidationError(f"PFR carries don't match team_stats:\n{bad.select(['game_id', 'team', 'carries', 'pfr'])}")
    return f"PFR carries: all {j.height} team-games present and matching team_stats carries (tolerance {TOLERANCE['carries']})."


def check_report(report: dict) -> None:
    """In every season block: each split group's shares sum to 1 (offense and defense), and the
    current-season rusher rows sum to the team total."""
    for row in report["rows"]:
        for season, blk in row["seasons"].items():
            if not blk:
                continue
            where = f"week {report['week']} {row['offense']} vs {row['defense']} ({season})"
            for group in {s["group"] for s in blk["splits"]}:
                for unit in ("off", "def"):
                    vals = [s[unit]["share"] for s in blk["splits"] if s["group"] == group and s[unit]["share"] is not None]
                    if vals and abs(sum(vals) - 1) > 1e-3:
                        raise ValidationError(f"{where}: {unit} {group} shares sum to {sum(vals):.6f}")
            total = next((r for r in blk["rushers"] if r["kind"] == "total"), None)
            if total:
                got = sum(r["att"] for r in blk["rushers"] if r["kind"] != "total")
                if got != total["att"]:
                    raise ValidationError(f"{where}: rusher rows sum to {got}, team total {total['att']}")
