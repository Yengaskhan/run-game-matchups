"""nflverse loaders (nflreadpy). Each table is fetched once per run."""

from functools import cache

import nflreadpy as nfl
import polars as pl


@cache
def pbp(season: int) -> pl.DataFrame:
    return nfl.load_pbp([season])


@cache
def schedule(season: int) -> pl.DataFrame:
    return nfl.load_schedules([season])


@cache
def team_stats(season: int) -> pl.DataFrame:
    return nfl.load_team_stats([season], summary_level="week")


@cache
def pfr_rush_weekly(season: int) -> pl.DataFrame:
    # Weekly rows, not the season table: the 2026 season table is still empty, and weekly rows let a
    # report use only the games before its week.
    return nfl.load_pfr_advstats([season], stat_type="rush", summary_level="week")


@cache
def ftn(season: int) -> pl.DataFrame:
    return nfl.load_ftn_charting([season]).select(
        pl.col("nflverse_game_id").alias("game_id"),
        pl.col("nflverse_play_id").cast(pl.Float64).alias("play_id"),
        "n_defense_box",
        "is_qb_sneak",
    )


@cache
def snap_counts(season: int) -> pl.DataFrame:
    return nfl.load_snap_counts([season])


@cache
def depth_charts(season: int) -> pl.DataFrame:
    return nfl.load_depth_charts([season])


@cache
def players(seasons: tuple[int, ...]) -> pl.DataFrame:
    """One row per gsis_id: latest position, display name, and PFR id (for PFR / snap-count joins)."""
    ro = nfl.load_rosters_weekly(list(seasons))
    return (
        ro.filter(pl.col("gsis_id").is_not_null())
        .sort(["season", "week"])
        .group_by("gsis_id")
        .agg(
            pl.col("position").last(),
            pl.col("full_name").last().alias("name"),
            pl.col("pfr_id").drop_nulls().last(),
        )
    )


def current_season() -> int:
    return nfl.get_current_season()
