"""
Reconciliation and consistency checks. Any failure stops the run before files are written.

0. Every final game in the window is in play-by-play.
1. PBP rush totals per team-game match nflverse team_stats (carries and rushing yards) within TOLERANCE.
2. Designed runs + every removed category add back up to all rush attempts.
3. PFR carries per team-game match team_stats carries (so YBC/YAC cover every carry).
4. In every written table, shares sum to 100% (±0.1 point: values are rounded to 4 decimals) and rusher rows sum to the team total.
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
    """Shares sum to 1 and rusher rows sum to the total, in every table that declares the check."""
    for s in report["sides"]:
        for sec in s["sections"]:
            for t in sec.get("tables", []):
                where = f"{report['game_id']} {s['offense']} / {t['id']}"
                checks = t.get("checks", {})
                rows = [r for r in t["rows"] if r["kind"] not in ("ref", "total")]
                if "shares_sum_to_one" in checks:
                    k = checks["shares_sum_to_one"]
                    vals = [r["cells"][k] for r in rows if r["cells"].get(k) is not None]
                    if vals and abs(sum(vals) - 1) > 1e-3:
                        raise ValidationError(f"{where}: shares sum to {sum(vals):.6f}")
                if "shares_sum_to_one_by_group" in checks:
                    k = checks["shares_sum_to_one_by_group"]
                    for g in {r.get("group") for r in rows}:
                        vals = [r["cells"][k] for r in rows if r.get("group") == g and r["cells"].get(k) is not None]
                        if vals and abs(sum(vals) - 1) > 1e-3:
                            raise ValidationError(f"{where} [{g}]: shares sum to {sum(vals):.6f}")
                if "rows_sum_to_total" in checks:
                    k = checks["rows_sum_to_total"]
                    total = next((r for r in t["rows"] if r["kind"] == "total"), None)
                    if total and sum(r["cells"][k] or 0 for r in rows) != total["cells"][k]:
                        raise ValidationError(f"{where}: rusher rows sum to {sum(r['cells'][k] or 0 for r in rows)}, team total {total['cells'][k]}")
