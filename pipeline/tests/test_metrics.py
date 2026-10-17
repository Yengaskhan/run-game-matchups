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
        m = lambda sh: {"share": sh}  # noqa: E731
        splits = [{"group": "direction", "off": m(sh), "def": m(sh)} for sh in shares]
        rushers = [{"kind": "rb", "att": a} for a in att_rows] + [{"kind": "total", "att": total}]
        return {"week": 3, "rows": [{"offense": "AAA", "defense": "BBB", "seasons": {"2026": {"splits": splits, "rushers": rushers}, "2025": None}}]}

    check_report(rep([0.5, 0.5], [3, 2], 5))
    with pytest.raises(ValidationError):
        check_report(rep([0.5, 0.4], [3, 2], 5))
    with pytest.raises(ValidationError):
        check_report(rep([0.5, 0.5], [3, 2], 6))


def test_edge_formula_and_bands():
    from matchups.weekly import band, edge_from

    r = lambda sr, ypc: {"ranks": {"sr": sr, "ypc": ypc}}  # noqa: E731
    best, worst, mid = r([1, 32], [1, 32]), r([32, 32], [32, 32]), r([16, 31], [16, 31])
    assert edge_from(best, worst) == 100  # best RB vs the leakiest defense, on both success rate and YPC
    assert edge_from(worst, best) == 0
    assert edge_from(mid, mid) == 50
    # Success-rate and YPC percentiles are averaged: 1st and 32nd of 32 is the middle.
    assert edge_from(r([1, 32], [32, 32]), mid) == 50
    assert edge_from(best, {"ranks": {"sr": [1, 32]}}) is None  # a side missing a metric's rank gives no edge
    assert edge_from({"ranks": {"epa": [1, 32]}}, worst) is None  # EPA plays no part
    assert [band(x) for x in (70, 69, 58, 57, 43, 42, 31, 30)] == [
        "big_edge", "small_edge", "small_edge", "neutral", "neutral", "small_disadvantage", "small_disadvantage", "big_disadvantage"]
    assert band(90, small_sample=True) == "neutral" and band(None) == "neutral"


def test_pfr_complete_weeks_stops_at_first_incomplete_week():
    from matchups.validate import pfr_complete_weeks

    ts = pl.DataFrame({"season_type": ["REG"] * 6, "week": [1, 1, 2, 2, 3, 3],
                       "game_id": ["g1", "g1", "g2", "g2", "g3", "g3"], "team": ["A", "B"] * 3})
    pfr = pl.DataFrame({"game_id": ["g1", "g1", "g2", "g2", "g3"], "team": ["A", "B", "A", "B", "A"]})
    assert pfr_complete_weeks(pfr, ts, [1, 2, 3]) == ([1, 2], ["g3"])  # g3 is missing team B
    assert pfr_complete_weeks(pfr.filter(pl.col("game_id") != "g1"), ts, [1, 2, 3])[0] == []


def test_rusher_split_is_per_player_ignores_qbs_and_ranks_within_bucket():
    from matchups.metrics import rusher_split

    rows = ([{"rusher_player_id": "a", "direction": "left", "epa": 0.5}] * 3 + [{"rusher_player_id": "a", "direction": "right", "epa": 0.1}]
            + [{"rusher_player_id": "b", "direction": "left", "epa": -0.2}] * 3
            + [{"rusher_player_id": "q", "direction": "left", "epa": 2.0, "is_qb_run": True}] * 5)
    runs = runs_frame(rows)
    games = pl.DataFrame({"team": ["AAA"], "games": [1]})
    s = rusher_split(runs, "direction", ["left", "middle", "right"], games, by_team=True, per_game=2.0, flat_min=None)
    a = s.filter(pl.col("rusher_player_id") == "a").sort("bucket")
    assert a["att"].to_list() == [3, 0, 1] and a["share"].to_list() == [0.75, 0.0, 0.25]  # shares of HIS runs
    assert "q" not in s["rusher_player_id"].to_list()  # QB runs are not in the RB peer group
    left = s.filter(pl.col("bucket") == "left").sort("rusher_player_id")
    assert left["epa_rank"].to_list() == [1, 2] and left["epa_n"].to_list() == [2, 2]
    assert a.filter(pl.col("bucket") == "right")["epa_rank"].to_list() == [None]  # 1 carry < 2 per game


# --- Data Suite run-scheme exports -----------------------------------------------------------

DS_HEADER = (
    ",Player Details,Player Details,Player Details,Player Details,Player Details,Rushing,Zone Concept,Zone Concept,Zone Concept,Zone Concept,"
    "Man/Gap Concept,Man/Gap Concept,Man/Gap Concept,Man/Gap Concept,\n"
    "Season,Rank,Name,Team,POS,G,ATT,ZONE ATT,ZONE ATT %,ZONE YPC,ZONE SUCC %,MAN ATT,MAN ATT %,MAN YPC,MAN SUCC %,player_id\n"
    "2026,,League Avg,,,,30,15,55,4.2,48.2,12,43,4.1,48,\n"
)


def write_ds(tmp_path, rows, stamp="2026-10-17 16:49"):
    p = tmp_path / "ds.csv"
    p.write_text(DS_HEADER + "".join(rows) + f"Exported from Data Suite 2.0 by someone on {stamp} UTC,,,\n")
    return p


def test_parse_rushing_reads_splits_ranks_and_export_time(tmp_path):
    from matchups.datasuite import parse_rushing

    p = write_ds(tmp_path, [
        "2026,1,A Back,ATL,RB,5,100,60,60,6.0,62,40,40,3.0,43,00-1\n",
        "2026,2,B Back,BUF,RB,5,50,20,40,4.0,50,30,60,5.0,57,00-2\n",
        "2026,3,C Back,DAL,RB,5,12,6,50,4.0,90,6,50,4.0,90,00-3\n",   # too few carries per type to rank
        "2026,4,Q Back,DAL,QB,5,40,20,50,5.0,60,20,50,5.0,60,00-4\n",  # not an RB: ignored
    ])
    df, league, exported = parse_rushing(p)
    assert exported.isoformat() == "2026-10-17T16:49:00+00:00"
    assert league["zone"]["sr"] == pytest.approx(0.482)
    assert sorted(df["player_id"].to_list()) == ["00-1", "00-2", "00-3"]
    a = df.filter(pl.col("player_id") == "00-1").to_dicts()[0]
    assert a["zone_sr"] == pytest.approx(0.62) and a["zone_share"] == pytest.approx(0.60) and a["gap_att"] == 40
    assert (a["zone_sr_rank"], a["zone_sr_n"]) == (1, 2)  # C Back (6 zone carries < 2 x 5 games) isn't ranked
    c = df.filter(pl.col("player_id") == "00-3").to_dicts()[0]
    assert c["zone_sr_rank"] is None


def test_parse_rushing_rejects_files_without_footer_or_columns(tmp_path):
    from matchups.datasuite import DataSuiteError, parse_rushing

    p = tmp_path / "bad.csv"
    p.write_text(DS_HEADER)  # no footer
    with pytest.raises(DataSuiteError, match="footer"):
        parse_rushing(p)
    p.write_text("a,b\nSeason,Rank\n2026,1\nExported from Data Suite 2.0 by x on 2026-10-17 16:49 UTC\n")
    with pytest.raises(DataSuiteError, match="missing column"):
        parse_rushing(p)


def test_pick_export_needs_full_coverage_and_prefers_the_earliest_that_has_it(tmp_path, monkeypatch):
    from matchups import datasuite

    sched = pl.DataFrame({
        "game_id": ["w1", "w2", "w3"], "game_type": ["REG"] * 3, "result": [3, 7, None],
        "gameday": ["2026-10-04", "2026-10-11", "2026-10-18"], "gametime": ["13:00", "13:00", "13:00"],
    })
    folder = tmp_path / "rushing"
    folder.mkdir()
    row = ["2026,1,A Back,ATL,RB,5,100,60,60,6.0,62,40,40,3.0,43,00-1\n"]
    (folder / "2026-10-08T1200Z.csv").write_text(write_ds(tmp_path, row, "2026-10-08 12:00").read_text())
    (folder / "2026-10-13T1200Z.csv").write_text(write_ds(tmp_path, row, "2026-10-13 12:00").read_text())
    monkeypatch.setattr(datasuite, "IMPORT_DIR", tmp_path)
    assert datasuite.pick_rushing_export(sched, {"w1"})["file"].name == "2026-10-08T1200Z.csv"  # earliest that covers
    assert datasuite.pick_rushing_export(sched, {"w1", "w2"})["file"].name == "2026-10-13T1200Z.csv"
    stale = datasuite.pick_rushing_export(sched, {"w1", "w2", "w3x"})
    assert "file" not in stale and "missing 1 game" in stale["status"]
    # Week numbers: w1 = week 1, w2 = week 2 (both final), w3 = week 2's unplayed game.
    weeks = sched.with_columns(pl.Series("week", [1, 2, 2]))
    # Week 2 is still in progress (w3 unplayed). With only the Oct 13 export, which also has week 2's
    # first game (w2), that's still fine for the week 2 report (window = week 1).
    (folder / "2026-10-08T1200Z.csv").unlink()
    assert datasuite.pick_rushing_export(weeks, {"w1"}, week=2)["extra"] == ["w2"]
    # Week 1 is finished: an export that also has week 2's game doesn't fit it.
    one = weeks.filter(pl.col("game_id") != "w3")
    assert "played after them" in datasuite.pick_rushing_export(one, set(), week=1)["status"]
