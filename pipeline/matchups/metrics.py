"""
League-wide metric tables for one season window. Ranks are computed here, once, within each table:
same table, same qualifier, same season. Rank 1 = best for that unit (best offense / stingiest defense).
"""

import math

import polars as pl

from .config import EXPLOSIVE_YARDS, QUALIFIERS

# metric -> higher is better, from the OFFENSE's point of view. Defense ranks flip every direction.
OFF_BETTER = {"ypc": True, "epa": True, "sr": True, "expl": True, "stuff": False, "ybc_att": True, "yac_att": True}
RANKED = ["ypc", "epa", "sr", "expl", "stuff"]


def agg_exprs() -> list[pl.Expr]:
    y = pl.col("yards")
    return [
        pl.len().alias("att"),
        y.sum().alias("yds"),
        (y.sum() / pl.len()).alias("ypc"),
        pl.col("epa").mean().alias("epa"),
        pl.col("success").mean().alias("sr"),
        (y >= EXPLOSIVE_YARDS).cast(pl.Float64).mean().alias("expl"),
        (y <= 0).cast(pl.Float64).mean().alias("stuff"),
    ]


EMPTY_METRICS = {"att": 0, "yds": 0.0, "ypc": None, "epa": None, "sr": None, "expl": None, "stuff": None}


def add_ranks(df: pl.DataFrame, metrics: list[str], unit: str, qualified: pl.Expr, over: list[str] | None = None) -> pl.DataFrame:
    """Adds <metric>_rank and <metric>_n (peer-group size) for rows where `qualified` holds."""
    df = df.with_columns(qualified.fill_null(False).alias("_q"))
    for m in metrics:
        better_high = OFF_BETTER[m] if unit == "offense" else not OFF_BETTER[m]
        ok = pl.col("_q") & pl.col(m).is_not_null()
        val = pl.when(ok).then(pl.col(m) * (-1.0 if better_high else 1.0))
        rank = val.rank("min")
        n = ok.sum()
        if over:
            rank, n = rank.over(over), n.over(over)
        df = df.with_columns(rank.cast(pl.Int32).alias(f"{m}_rank"), pl.when(ok).then(n).otherwise(None).cast(pl.Int32).alias(f"{m}_n"))
    return df.drop("_q")


def team_games(schedule: pl.DataFrame, weeks: list[int]) -> pl.DataFrame:
    """Games each team played in the window (completed regular-season games in `weeks`)."""
    g = schedule.filter(pl.col("game_type") == "REG", pl.col("week").is_in(weeks), pl.col("result").is_not_null())
    both = pl.concat([g.select(pl.col("away_team").alias("team"), "game_id"), g.select(pl.col("home_team").alias("team"), "game_id")])
    return both.group_by("team").agg(pl.col("game_id").n_unique().alias("games"))


def ceil_min(per_game: float, games: pl.Expr) -> pl.Expr:
    # 6.25 x 2 games = 12.5 -> 13. A tiny epsilon keeps whole products (3 x 2 = 6) from rounding up.
    return (games * per_game - 1e-9).ceil().cast(pl.Int32)


def overall(runs: pl.DataFrame, side: str, games: pl.DataFrame, pfr: pl.DataFrame | None) -> pl.DataFrame:
    """One row per team: designed-run efficiency for (side='posteam') or allowed by (side='defteam')."""
    unit = "offense" if side == "posteam" else "defense"
    g = runs.group_by(side).agg(*agg_exprs(), pl.col("is_qb_run").sum().alias("qb_att")).rename({side: "team"})
    df = games.join(g, on="team", how="left").with_columns(pl.col("att").fill_null(0), pl.col("qb_att").fill_null(0))
    if pfr is not None and pfr.height:
        # PFR publishes yards before / after contact per player per game only, so it cannot be cut to
        # designed runs. Summing NON-QB rushers keeps scrambles and kneels (QB carries) out of it.
        key = "team" if unit == "offense" else "opponent"
        p = pfr.filter(~pl.col("is_qb")).group_by(key).agg(
            pl.col("carries").sum().alias("pfr_att"),
            (pl.col("rushing_yards_before_contact").sum() / pl.col("carries").sum()).alias("ybc_att"),
            (pl.col("rushing_yards_after_contact").sum() / pl.col("carries").sum()).alias("yac_att"),
        ).rename({key: "team"})
        df = df.join(p, on="team", how="left")
    else:
        df = df.with_columns(pl.lit(None, pl.Float64).alias(c) for c in ["pfr_att", "ybc_att", "yac_att"])
    return add_ranks(df, RANKED + ["ybc_att", "yac_att"], unit, pl.col("games") >= QUALIFIERS["team_min_games"])


def split(runs: pl.DataFrame, side: str, key: str, buckets: list[str], games: pl.DataFrame, min_att: pl.Expr) -> pl.DataFrame:
    """One row per team x bucket (direction, gap or box), zero-filled, with share and per-bucket ranks.

    share = the bucket's share of the team's designed runs that HAVE a value for this key, so each
    team's shares sum to 100%. Runs with no charted value are counted separately (see uncharted()).
    """
    unit = "offense" if side == "posteam" else "defense"
    grid = games.join(pl.DataFrame({"bucket": buckets}), how="cross")
    known = runs.filter(pl.col(key).is_not_null())
    g = known.group_by([side, key]).agg(agg_exprs()).rename({side: "team", key: "bucket"})
    df = grid.join(g, on=["team", "bucket"], how="left").with_columns(pl.col("att").fill_null(0), pl.col("yds").fill_null(0.0))
    tot = df.group_by("team").agg(pl.col("att").sum().alias("team_att"))
    df = df.join(tot, on="team").with_columns(
        pl.when(pl.col("team_att") > 0).then(pl.col("att") / pl.col("team_att")).otherwise(None).alias("share"),
        min_att.alias("min_att"),
    )
    return add_ranks(df, RANKED, unit, pl.col("att") >= pl.col("min_att"), over=["bucket"])


def uncharted(runs: pl.DataFrame, side: str, key: str) -> dict[str, int]:
    u = runs.filter(pl.col(key).is_null()).group_by(side).len()
    return dict(zip(u[side].to_list(), u["len"].to_list()))


def league_split_avgs(runs: pl.DataFrame, key: str) -> dict[str, dict]:
    """League-wide share and efficiency per bucket (for context in takeaways)."""
    known = runs.filter(pl.col(key).is_not_null())
    if not known.height:
        return {}
    g = known.group_by(key).agg(agg_exprs()).with_columns((pl.col("att") / known.height).alias("share"))
    return {r[key]: r for r in g.to_dicts()}


def rushers(runs: pl.DataFrame, games: pl.DataFrame, pfr: pl.DataFrame | None, snaps: pl.DataFrame | None, per_game: float, by_team: bool) -> pl.DataFrame:
    """One row per rusher (per rusher x team when by_team). Ranked among qualifying NON-QB rushers."""
    keys = ["rusher_player_id", "posteam"] if by_team else ["rusher_player_id"]
    g = runs.group_by(keys).agg(
        *agg_exprs(),
        pl.col("rusher_name").last().alias("name"),
        pl.col("rusher_pos").last().alias("pos"),
        pl.col("is_qb_run").any().alias("is_qb"),
        pl.col("posteam").unique().sort().str.join("/").alias("teams"),
        pl.col("game_id").n_unique().alias("games_with_carry"),
    )
    team_att = runs.group_by("posteam").agg(pl.len().alias("team_att"))
    if by_team:
        g = g.join(team_att, on="posteam", how="left").with_columns((pl.col("att") / pl.col("team_att")).alias("carry_share"))
        g = g.join(games.rename({"team": "posteam", "games": "team_games"}), on="posteam", how="left")
    else:
        # Prior season: the qualifier uses the most games any of his teams played.
        primary = runs.group_by(["rusher_player_id", "posteam"]).len().join(games.rename({"team": "posteam"}), on="posteam")
        tg = primary.group_by("rusher_player_id").agg(pl.col("games").max().alias("team_games"))
        g = g.join(tg, on="rusher_player_id", how="left").with_columns(pl.lit(None, pl.Float64).alias("carry_share"))

    if pfr is not None and pfr.height:
        pk = ["gsis_id", "team"] if by_team else ["gsis_id"]
        p = pfr.filter(pl.col("gsis_id").is_not_null()).group_by(pk).agg(
            pl.col("carries").sum().alias("pfr_att"),
            (pl.col("rushing_yards_before_contact").sum() / pl.col("carries").sum()).alias("ybc_att"),
            (pl.col("rushing_yards_after_contact").sum() / pl.col("carries").sum()).alias("yac_att"),
        )
        rename = {"gsis_id": "rusher_player_id", "team": "posteam"} if by_team else {"gsis_id": "rusher_player_id"}
        g = g.join(p.rename(rename), on=keys, how="left")
    else:
        g = g.with_columns(pl.lit(None, pl.Float64).alias(c) for c in ["pfr_att", "ybc_att", "yac_att"])

    if by_team and snaps is not None and snaps.height:
        g = g.join(snaps.rename({"gsis_id": "rusher_player_id", "team": "posteam"}), on=["rusher_player_id", "posteam"], how="left")
    else:
        g = g.with_columns(pl.lit(None, pl.Float64).alias("snap_share"), pl.lit(None, pl.Int64).alias("games_played"))

    g = g.with_columns(ceil_min(per_game, pl.col("team_games")).alias("min_att"))
    return add_ranks(g, RANKED + ["ybc_att", "yac_att"], "offense", (~pl.col("is_qb")) & (pl.col("att") >= pl.col("min_att")))


def snap_shares(snaps: pl.DataFrame, weeks: list[int], players: pl.DataFrame) -> pl.DataFrame:
    """Offensive snap share per player x team over the window: his snaps / his team's offensive snaps."""
    s = snaps.filter(pl.col("game_type") == "REG", pl.col("week").is_in(weeks))
    if not s.height:
        return pl.DataFrame(schema={"gsis_id": pl.Utf8, "team": pl.Utf8, "snap_share": pl.Float64, "games_played": pl.Int64})
    # Team snaps per game, recovered from any player's snaps / pct (they all agree up to rounding).
    team = (
        s.filter(pl.col("offense_pct") > 0)
        .with_columns((pl.col("offense_snaps") / pl.col("offense_pct")).alias("t"))
        .group_by(["game_id", "team"])
        .agg(pl.col("t").median().round(0).alias("team_snaps"))
    )
    team_tot = team.group_by("team").agg(pl.col("team_snaps").sum())
    pid = players.filter(pl.col("pfr_id").is_not_null()).select("gsis_id", pl.col("pfr_id").alias("pfr_player_id")).unique("pfr_player_id")
    p = (
        s.group_by(["pfr_player_id", "team"])
        .agg(pl.col("offense_snaps").sum(), (pl.col("offense_snaps") > 0).sum().alias("games_played"))
        .join(team_tot, on="team")
        .with_columns((pl.col("offense_snaps") / pl.col("team_snaps")).alias("snap_share"))
        .join(pid, on="pfr_player_id", how="inner")
    )
    return p.select("gsis_id", "team", "snap_share", pl.col("games_played").cast(pl.Int64))


def pfr_window(pfr: pl.DataFrame, weeks: list[int], players: pl.DataFrame) -> pl.DataFrame:
    """PFR weekly rows for the window, tagged with gsis_id and whether the player is a QB."""
    p = pfr.filter(pl.col("game_type") == "REG", pl.col("week").is_in(weeks))
    pid = players.filter(pl.col("pfr_id").is_not_null()).select("gsis_id", pl.col("pfr_id").alias("pfr_player_id"), "position").unique("pfr_player_id")
    return p.join(pid, on="pfr_player_id", how="left").with_columns((pl.col("position") == "QB").fill_null(False).alias("is_qb"))


def pct_from_rank(rank: int | None, n: int | None) -> float | None:
    """Rank -> percentile where 1.0 = best in the peer group and 0.0 = worst."""
    if rank is None or not n:
        return None
    return 1.0 if n == 1 else 1 - (rank - 1) / (n - 1)


def nan_to_none(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def rusher_split(runs: pl.DataFrame, key: str, buckets: list[str], games: pl.DataFrame, by_team: bool,
                 per_game: float | None, flat_min: int | None) -> pl.DataFrame:
    """One row per non-QB rusher x bucket (direction, gap or box), zero-filled, with the bucket's share of
    HIS charted runs and ranks within the bucket among rushers with enough carries there.

    by_team: current season keys rushers by (player, team); the prior season by player across teams.
    The minimum is per_game x his team's games (current) or flat_min (prior)."""
    keys = ["rusher_player_id", "posteam"] if by_team else ["rusher_player_id"]
    known = runs.filter(pl.col(key).is_not_null() & ~pl.col("is_qb_run"))
    if not known.height:
        return pl.DataFrame()
    grid = known.select(keys).unique().join(pl.DataFrame({"bucket": buckets}), how="cross")
    g = known.group_by(keys + [key]).agg(agg_exprs()).rename({key: "bucket"})
    df = grid.join(g, on=keys + ["bucket"], how="left").with_columns(pl.col("att").fill_null(0), pl.col("yds").fill_null(0.0))
    tot = df.group_by(keys).agg(pl.col("att").sum().alias("player_att"))
    df = df.join(tot, on=keys).with_columns(
        pl.when(pl.col("player_att") > 0).then(pl.col("att") / pl.col("player_att")).otherwise(None).alias("share"))
    if by_team:
        df = df.join(games.rename({"team": "posteam"}), on="posteam", how="left").with_columns(ceil_min(per_game, pl.col("games")).alias("min_att"))
    else:
        df = df.with_columns(pl.lit(flat_min, pl.Int32).alias("min_att"))
    return add_ranks(df, RANKED, "offense", pl.col("att") >= pl.col("min_att"), over=["bucket"])
