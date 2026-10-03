"""
Play filtering: nflverse play-by-play -> one row per DESIGNED run.

Every filter is listed in FILTERS (shown on the report footer) and commented where it is applied.
"""

import polars as pl

from .config import BOX_BUCKETS, EXPLOSIVE_YARDS, SEASON_TYPE

FILTERS = [
    "Regular-season games only.",
    "Rushing plays only (nflverse rush_attempt = 1).",
    "QB scrambles removed (qb_scramble = 1): dropbacks that turned into runs, not designed runs.",
    "QB kneels removed (qb_kneel = 1).",
    "Aborted snaps removed (aborted_play = 1): no designed run happened.",
    "Two-point tries removed (two_point_attempt = 1).",
    "Plays wiped out by penalty removed (play_type = no_play), plus plays nflverse marks deleted.",
    "Designed QB runs are kept and labeled (rusher's roster position = QB); QB sneaks come from FTN (is_qb_sneak).",
    f"Explosive run = {EXPLOSIVE_YARDS}+ rushing yards. Stuff = 0 or fewer rushing yards. Success = nflverse success flag (the run improved the offense's expected scoring, given down, distance and field position).",
    "Left / middle / right and end / tackle / guard are nflverse run_location / run_gap, from the OFFENSE's point of view.",
]


def _flag(col: str) -> pl.Expr:
    """nflverse 0/1 flags are floats and can be null; treat null as 0."""
    return pl.col(col).fill_null(0) == 1


def all_rushes(pbp: pl.DataFrame) -> pl.DataFrame:
    """Every nflverse rush attempt (the population nflverse team_stats counts). Used for reconciliation."""
    return pbp.filter(
        # Regular season only.
        (pl.col("season_type") == SEASON_TYPE)
        # nflverse's rush_attempt flag: every charted rushing play, scrambles and kneels included.
        & _flag("rush_attempt")
    )


def designed_runs(pbp: pl.DataFrame, players: pl.DataFrame, ftn: pl.DataFrame | None) -> tuple[pl.DataFrame, dict]:
    """Returns (designed runs, counts of what each filter removed)."""
    base = all_rushes(pbp)
    removed = {
        "scrambles": base.filter(_flag("qb_scramble")).height,
        "kneels": base.filter(_flag("qb_kneel")).height,
        "aborted": base.filter(_flag("aborted_play") & ~_flag("qb_scramble") & ~_flag("qb_kneel")).height,
        "two_point": base.filter(_flag("two_point_attempt")).height,
    }
    runs = base.filter(
        # QB scrambles: the QB dropped back to pass, so the run was not designed.
        ~_flag("qb_scramble")
        # Kneel-downs: clock plays, not attempts to gain yards.
        & ~_flag("qb_kneel")
        # Aborted snaps (fumbled exchange): no designed run took place, and no direction is charted.
        & ~_flag("aborted_play")
        # Two-point tries: not scrimmage plays, and not part of rushing totals.
        & ~_flag("two_point_attempt")
        # Plays nullified by a penalty. rush_attempt is already 0 on these; the filter makes it explicit.
        & (pl.col("play_type") != "no_play")
        # Plays nflverse marks as deleted from the gamebook.
        & ~_flag("play_deleted")
    )
    removed["other"] = base.height - runs.height - sum(removed.values())

    runs = runs.join(
        players.select(pl.col("gsis_id").alias("rusher_player_id"), pl.col("position").alias("rusher_pos"), pl.col("name").alias("rusher_full_name")),
        on="rusher_player_id",
        how="left",
    )
    if ftn is not None:
        runs = runs.join(ftn, on=["game_id", "play_id"], how="left")
    else:
        runs = runs.with_columns(pl.lit(None, pl.Int32).alias("n_defense_box"), pl.lit(None, pl.Boolean).alias("is_qb_sneak"))

    box = pl.col("n_defense_box")
    box_bucket = pl.lit(None, pl.Utf8)
    for key, _label, lo, hi in reversed(BOX_BUCKETS):
        cond = pl.lit(True)
        if lo is not None:
            cond = cond & (box >= lo)
        if hi is not None:
            cond = cond & (box <= hi)
        box_bucket = pl.when(cond).then(pl.lit(key)).otherwise(box_bucket)

    loc = pl.col("run_location")
    gap = pl.col("run_gap")
    runs = runs.with_columns(
        # rushing_yards is null only on a handful of odd plays; nflverse totals treat those as 0.
        pl.col("rushing_yards").fill_null(0).alias("yards"),
        (pl.col("rusher_pos") == "QB").fill_null(False).alias("is_qb_run"),
        pl.col("is_qb_sneak").fill_null(False),
        loc.alias("direction"),
        # Gap bucket: "middle" has no gap; a side run with no charted gap stays null (left out of the gap table).
        pl.when(loc == "middle").then(pl.lit("middle")).when(loc.is_not_null() & gap.is_not_null()).then(loc + "_" + gap).otherwise(None).alias("gap"),
        pl.when(box.is_null() | (box <= 0)).then(None).otherwise(box_bucket).alias("box"),
    ).select(
        "season", "week", "game_id", "play_id", "posteam", "defteam", "rusher_player_id",
        pl.coalesce("rusher_full_name", "rusher_player_name").alias("rusher_name"),
        "rusher_pos", "is_qb_run", "is_qb_sneak", "direction", "gap", "box", "n_defense_box",
        "yards", "epa", "success",
    )
    return runs, removed
