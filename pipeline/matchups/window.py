"""
A LeagueWindow is every league-wide table for one season over a set of weeks. The current-season
window for a Week N report holds only games BEFORE week N; the prior-season window is the full
regular season. The two are never combined.
"""

from dataclasses import dataclass, field

import polars as pl

from . import load
from .config import BOX_BUCKETS, DIRECTIONS, GAPS, QUALIFIERS
from .metrics import agg_exprs, ceil_min, league_split_avgs, overall, pfr_window, rushers, snap_shares, split, team_games, uncharted
from .plays import designed_runs


@dataclass
class LeagueWindow:
    season: int
    weeks: list[int]
    is_current: bool
    runs: pl.DataFrame
    removed: dict
    games: pl.DataFrame
    bucket_rule: str
    rusher_rule: str
    data_as_of: str | None
    tables: dict[str, pl.DataFrame] = field(default_factory=dict)
    uncharted: dict[str, dict[str, int]] = field(default_factory=dict)
    league: dict[str, dict] = field(default_factory=dict)
    pfr: pl.DataFrame | None = None

    def row(self, table: str, **match) -> dict | None:
        df = self.tables[table]
        for k, v in match.items():
            df = df.filter(pl.col(k) == v)
        return df.to_dicts()[0] if df.height else None

    def rows(self, table: str, **match) -> list[dict]:
        df = self.tables[table]
        for k, v in match.items():
            df = df.filter(pl.col(k) == v)
        return df.to_dicts()


def completed_weeks_before(schedule: pl.DataFrame, week: int) -> list[int]:
    """Weeks before `week` in which EVERY game is final. A half-played week (e.g. only Thursday night
    done) is left out until it finishes, so every team's sample covers the same weeks."""
    s = schedule.filter(pl.col("game_type") == "REG", pl.col("week") < week)
    done = s.group_by("week").agg(pl.col("result").is_not_null().all().alias("done")).filter(pl.col("done"))
    return sorted(done["week"].to_list())


def build_window(season: int, weeks: list[int], is_current: bool, players: pl.DataFrame) -> LeagueWindow:
    sched = load.schedule(season)
    pbp = load.pbp(season)
    pbp = pbp.filter(pl.col("week").is_in(weeks))
    try:
        ftn = load.ftn(season)
    except Exception:  # noqa: BLE001 - FTN missing for a season: box tables are skipped, not faked
        ftn = None
    runs, removed = designed_runs(pbp, players, ftn)
    games = team_games(sched, weeks)
    played = sched.filter(pl.col("game_type") == "REG", pl.col("week").is_in(weeks), pl.col("result").is_not_null())
    data_as_of = played["gameday"].max() if played.height else None

    if is_current:
        per = QUALIFIERS["bucket_att_per_team_game"]
        min_att = ceil_min(per, pl.col("games"))
        bucket_rule = f"at least {per:g} designed runs per team game in that bucket"
    else:
        min_att = pl.lit(QUALIFIERS["bucket_min_att_prior"], pl.Int32)
        bucket_rule = f"at least {QUALIFIERS['bucket_min_att_prior']} designed runs in that bucket"
    rper = QUALIFIERS["rusher_att_per_team_game"]
    rusher_rule = f"non-QB rushers with at least {rper:g} designed runs per team game"

    pfr = pfr_window(load.pfr_rush_weekly(season), weeks, players) if weeks else None
    snaps = snap_shares(load.snap_counts(season), weeks, players) if (weeks and is_current) else None

    w = LeagueWindow(season, weeks, is_current, runs, removed, games, bucket_rule, rusher_rule, data_as_of, pfr=pfr)
    if not weeks:
        return w
    box_ok = runs["box"].is_not_null().any()
    w.tables["off"] = overall(runs, "posteam", games, pfr)
    w.tables["def"] = overall(runs, "defteam", games, pfr)
    for key, buckets in [("direction", [d for d, _ in DIRECTIONS]), ("gap", [g for g, _ in GAPS]), ("box", [b[0] for b in BOX_BUCKETS])]:
        if key == "box" and not box_ok:
            continue
        w.tables[f"off_{key}"] = split(runs, "posteam", key, buckets, games, min_att)
        w.tables[f"def_{key}"] = split(runs, "defteam", key, buckets, games, min_att)
        w.uncharted[f"off_{key}"] = uncharted(runs, "posteam", key)
        w.uncharted[f"def_{key}"] = uncharted(runs, "defteam", key)
        w.league[key] = league_split_avgs(runs, key)
    w.tables["rushers"] = rushers(runs, games, pfr, snaps, rper, by_team=is_current)
    # Rusher x direction, for the per-rusher splits table (not ranked: samples are too small).
    w.tables["rusher_dir"] = (
        runs.filter(pl.col("direction").is_not_null())
        .group_by(["rusher_player_id", "posteam", "direction"])
        .agg(agg_exprs())
    )
    league = runs.select(agg_exprs()).to_dicts()[0]
    if pfr is not None and pfr.height:
        np_ = pfr.filter(~pl.col("is_qb"))
        c = np_["carries"].sum()
        league["ybc_att"] = np_["rushing_yards_before_contact"].sum() / c if c else None
        league["yac_att"] = np_["rushing_yards_after_contact"].sum() / c if c else None
        league["pfr_att"] = c
    league["games"] = games["games"].mean() if games.height else None
    w.league["overall"] = league
    return w
