"""Unit tests for the matchup metric code on small hand-built frames (no network)."""

import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matchups.metrics import add_ranks, ceil_min, overall, pct_from_rank, split  # noqa: E402
from matchups.plays import designed_runs  # noqa: E402
from matchups.validate import ValidationError, check_report  # noqa: E402


def pbp_rows(rows):
    base = {
        "season": 2026, "week": 1, "game_id": "g1", "season_type": "REG", "posteam": "AAA", "defteam": "BBB",
        "rush_attempt": 1.0, "qb_scramble": 0.0, "qb_kneel": 0.0, "aborted_play": 0.0, "two_point_attempt": 0.0,
        "play_deleted": 0.0, "play_type": "run", "run_location": "left", "run_gap": "end", "rushing_yards": 4.0,
        "epa": 0.1, "success": 1.0, "rusher_player_id": "r1", "rusher_player_name": "R.One",
    }
    return pl.DataFrame([{**base, "play_id": float(i), **r} for i, r in enumerate(rows)])


PLAYERS = pl.DataFrame({"gsis_id": ["r1", "q1"], "position": ["RB", "QB"], "name": ["Rusher One", "Quarter Back"], "pfr_id": [None, None]})


def test_filters_remove_scrambles_kneels_aborted_2pt_noplay_and_label_qb_runs():
    pbp = pbp_rows([
        {},
        {"qb_scramble": 1.0, "rusher_player_id": "q1"},
        {"qb_kneel": 1.0, "rusher_player_id": "q1", "play_type": "qb_kneel"},
        {"aborted_play": 1.0, "run_location": None},
        {"two_point_attempt": 1.0},
        {"play_type": "no_play"},
        {"rush_attempt": 0.0},
        {"season_type": "POST"},
        {"rusher_player_id": "q1", "run_location": "middle", "run_gap": None},
        {"qb_scramble": None},  # null flags count as 0
    ])
    runs, removed = designed_runs(pbp, PLAYERS, None)
    assert runs.height == 3
    assert runs["is_qb_run"].to_list() == [False, True, False]
    assert removed == {"scrambles": 1, "kneels": 1, "aborted": 1, "two_point": 1, "other": 1}  # "other" = the no_play row
    assert runs["gap"].to_list() == ["left_end", "middle", "left_end"]


def test_gap_null_on_side_run_stays_out_of_gap_table():
    runs, _ = designed_runs(pbp_rows([{"run_gap": None}]), PLAYERS, None)
    assert runs["direction"].to_list() == ["left"] and runs["gap"].to_list() == [None]


def runs_frame(rows):
    base = {"game_id": "g1", "posteam": "AAA", "defteam": "BBB", "direction": "left", "gap": "left_end", "box": "base",
            "yards": 4.0, "epa": 0.0, "success": 0.0, "is_qb_run": False}
    return pl.DataFrame([{**base, **r} for r in rows])


def test_overall_metrics_explosive_stuff_and_defense_view():
    runs = runs_frame([{"yards": 10.0, "epa": 1.0, "success": 1.0}, {"yards": 0.0, "epa": -0.5}, {"yards": -2.0, "epa": -0.5}, {"yards": 4.0}])
    games = pl.DataFrame({"team": ["AAA", "BBB"], "games": [1, 1]})
    off = overall(runs, "posteam", games, None).filter(pl.col("team") == "AAA").to_dicts()[0]
    assert off["att"] == 4 and off["yds"] == 12 and off["ypc"] == 3.0
    assert off["expl"] == 0.25 and off["stuff"] == 0.5 and off["sr"] == 0.25 and off["epa"] == 0.0
    d = overall(runs, "defteam", games, None).filter(pl.col("team") == "BBB").to_dicts()[0]
    assert d["att"] == 4 and d["ypc"] == 3.0
    assert overall(runs, "defteam", games, None).filter(pl.col("team") == "AAA")["att"].to_list() == [0]


def test_ranks_direction_and_peer_group():
    df = pl.DataFrame({"team": ["A", "B", "C", "D"], "epa": [0.3, -0.1, 0.1, 0.5], "stuff": [0.1, 0.2, 0.3, 0.4], "ok": [True, True, True, False]})
    off = add_ranks(df, ["epa", "stuff"], "offense", pl.col("ok")).sort("team")
    assert off["epa_rank"].to_list() == [1, 3, 2, None]  # D is unqualified: no rank, not counted
    assert off["epa_n"].to_list() == [3, 3, 3, None]
    assert off["stuff_rank"].to_list() == [1, 2, 3, None]  # lower stuff rate is better for an offense
    dfn = add_ranks(df, ["epa", "stuff"], "defense", pl.col("ok")).sort("team")
    assert dfn["epa_rank"].to_list() == [3, 1, 2, None]  # lower EPA allowed is better for a defense
    assert dfn["stuff_rank"].to_list() == [3, 2, 1, None]  # more stuffs forced is better


def test_split_shares_sum_to_one_zero_fill_and_bucket_qualifier():
    runs = runs_frame([{"direction": "left"}] * 3 + [{"direction": "right"}] + [{"direction": None}])
    games = pl.DataFrame({"team": ["AAA", "BBB"], "games": [1, 1]})
    s = split(runs, "posteam", "direction", ["left", "middle", "right"], games, pl.lit(2)).filter(pl.col("team") == "AAA").sort("bucket")
    assert s["att"].to_list() == [3, 0, 1]
    assert s["share"].to_list() == [0.75, 0.0, 0.25]  # the uncharted run is left out of the denominator
    assert s["epa_rank"].to_list() == [1, None, None]  # middle (0) and right (1) are below the 2-attempt qualifier


def test_qualifier_rounding():
    df = pl.DataFrame({"g": [2, 17, 2]}).with_columns(ceil_min(6.25, pl.col("g")).alias("a"), ceil_min(3.0, pl.col("g")).alias("b"))
    assert df["a"].to_list() == [13, 107, 13]
    assert df["b"].to_list() == [6, 51, 6]


def test_pct_from_rank():
    assert pct_from_rank(1, 32) == 1.0 and pct_from_rank(32, 32) == 0.0 and pct_from_rank(None, 32) is None
    assert pct_from_rank(1, 1) == 1.0


def test_check_report_catches_bad_shares_and_totals():
    def rep(shares, att_rows, total):
        rows = [{"kind": "row", "cells": {"share": s}} for s in shares]
        rrows = [{"kind": "row", "cells": {"att": a}} for a in att_rows] + [{"kind": "total", "cells": {"att": total}}]
        tables = [{"id": "d", "checks": {"shares_sum_to_one": "share"}, "rows": rows}, {"id": "r", "checks": {"rows_sum_to_total": "att"}, "rows": rrows}]
        return {"game_id": "g", "sides": [{"offense": "AAA", "sections": [{"tables": tables}]}]}

    check_report(rep([0.5, 0.5], [3, 2], 5))
    with pytest.raises(ValidationError):
        check_report(rep([0.5, 0.4], [3, 2], 5))
    with pytest.raises(ValidationError):
        check_report(rep([0.5, 0.5], [3, 2], 6))
