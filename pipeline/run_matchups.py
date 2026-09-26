"""
Run Game Matchup Report pipeline.

    python pipeline/run_matchups.py              # this week's games (nflverse's current week)
    python pipeline/run_matchups.py --week 5     # one week
    python pipeline/run_matchups.py --all        # every week on the current-season schedule

Pulls nflverse data with nflreadpy, computes everything, validates, and writes one JSON per week to
data/<season>/week-XX.json (every offense playing that week) plus data/<season>/index.json.
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))

from matchups import load  # noqa: E402
from matchups.config import OUTPUT_DIR, SCHEMA_VERSION, SEASON_TYPE  # noqa: E402
from matchups.validate import ValidationError, check_pbp_complete, check_report, reconcile_pfr, reconcile_removed, reconcile_team_totals  # noqa: E402
from matchups.weekly import week_report  # noqa: E402
from matchups.window import build_window, completed_weeks_before  # noqa: E402


def rb_depth(season: int, gameday: str, played: bool) -> dict[str, list[dict]]:
    """RBs on each team's depth chart: the last snapshot before kickoff day for a played game, else the latest."""
    dc = load.depth_charts(season).with_columns(pl.col("dt").str.slice(0, 10).alias("day"))
    if played:
        dc = dc.filter(pl.col("day") < gameday)
    latest = dc.group_by("team").agg(pl.col("dt").max())
    rb = dc.join(latest, on=["team", "dt"]).filter(pl.col("pos_abb") == "RB", pl.col("gsis_id").is_not_null()).sort(["team", "pos_rank"]).unique(["team", "gsis_id"], keep="first", maintain_order=True)
    out: dict[str, list[dict]] = {}
    for r in rb.iter_rows(named=True):
        out.setdefault(r["team"], []).append({"gsis_id": r["gsis_id"], "name": r["player_name"], "pos_rank": r["pos_rank"]})
    return out


def write_index(out: Path, season: int) -> Path:
    """Rebuild the season index from the files on disk, so single-week runs add to it."""
    root = out / str(season)
    weeks = []
    for f in sorted(root.glob("week-*.json")):
        r = json.loads(f.read_text())
        weeks.append({
            "week": r["week"], "games": len(r["games"]), "first_gameday": min(g["gameday"] for g in r["games"]),
            # Path as the site sees it (the site always bundles data/).
            "path": f"data/{f.relative_to(out).as_posix()}", "data_as_of": r["data_as_of"],
        })
    idx = {"schema": SCHEMA_VERSION, "season": season, "weeks": sorted(weeks, key=lambda w: w["week"])}
    p = root / "index.json"
    p.write_text(json.dumps(idx, indent=1) + "\n")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, help="season (default: nflverse current season)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--week", type=int, help="one week (default: nflverse current week)")
    g.add_argument("--all", action="store_true", help="every regular-season week on the schedule")
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR, help="output folder (default: data/)")
    args = ap.parse_args()

    import nflreadpy as nfl

    season = args.season or load.current_season()
    prior_season = season - 1
    sched = load.schedule(season).filter(pl.col("game_type") == SEASON_TYPE)
    all_weeks = sorted(sched["week"].unique().to_list())
    target_weeks = all_weeks if args.all else [args.week or nfl.get_current_week()]

    players = load.players((prior_season, season))
    print(f"Season {season} (prior {prior_season}); weeks {target_weeks}")

    prior_weeks = sorted(load.schedule(prior_season).filter(pl.col("game_type") == SEASON_TYPE)["week"].unique().to_list())
    prior = build_window(prior_season, prior_weeks, False, players)
    prior_checks = [
        f"{prior_season}: " + check_pbp_complete(load.pbp(prior_season), load.schedule(prior_season), prior_weeks),
        f"{prior_season}: " + reconcile_team_totals(load.pbp(prior_season), load.team_stats(prior_season), prior_weeks),
        f"{prior_season}: " + reconcile_removed(load.pbp(prior_season), prior.runs, prior.removed, prior_weeks),
        f"{prior_season}: " + reconcile_pfr(load.pfr_rush_weekly(prior_season).filter(pl.col("game_type") == SEASON_TYPE), load.team_stats(prior_season), prior_weeks),
    ]

    windows: dict[tuple, tuple] = {}
    written = 0
    for week in target_weeks:
        weeks = completed_weeks_before(sched, week)
        if tuple(weeks) not in windows:
            cur = build_window(season, weeks, True, players)
            checks = list(prior_checks)
            if weeks:
                checks = [
                    f"{season}: " + check_pbp_complete(load.pbp(season), load.schedule(season), weeks),
                    f"{season}: " + reconcile_team_totals(load.pbp(season), load.team_stats(season), weeks),
                    f"{season}: " + reconcile_removed(load.pbp(season), cur.runs, cur.removed, weeks),
                    f"{season}: " + reconcile_pfr(load.pfr_rush_weekly(season).filter(pl.col("game_type") == SEASON_TYPE), load.team_stats(season), weeks),
                ] + checks
            windows[tuple(weeks)] = (cur, checks)
        cur, checks = windows[tuple(weeks)]
        games = sched.filter(pl.col("week") == week).sort(["gameday", "gametime", "game_id"])
        out_dir = args.out / str(season)
        out_dir.mkdir(parents=True, exist_ok=True)
        game_rows = list(games.iter_rows(named=True))
        depth = {g["game_id"]: rb_depth(season, g["gameday"], g["result"] is not None) for g in game_rows}
        rep = week_report(season, week, game_rows, cur, prior, depth,
                          checks + ["Report: direction / gap / box shares sum to 100% for every offense and defense; rusher rows sum to the team total."])
        check_report(rep)
        (out_dir / f"week-{week:02d}.json").write_text(json.dumps(rep, indent=None, separators=(",", ":"), allow_nan=False) + "\n")
        written += 1
        print(f"  week {week}: {games.height} games, {len(rep['rows'])} run games, current-season window {weeks or 'none'}")

    idx = write_index(args.out, season)
    print(f"Wrote {written} week file{'s' if written != 1 else ''}; index {idx}")
    for c in dict.fromkeys(c for _cur, cs in windows.values() for c in cs):
        print("  ✓", c)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as e:
        print(f"VALIDATION FAILED: {e}", file=sys.stderr)
        sys.exit(1)
