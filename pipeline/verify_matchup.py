"""
Independent spot-check of one matchup report against nflverse.

    python pipeline/verify_matchup.py 2026_03_BAL_DAL

Re-derives the headline numbers straight from nflverse with pandas (none of the pipeline's own code),
then compares them with the committed JSON. Exits non-zero on any mismatch.
"""

import json
import sys
from pathlib import Path

import nflreadpy as nfl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOL = 0.0006  # JSON values are rounded to 4 decimals


def main(game_id: str) -> int:
    path = next((ROOT / "data").glob(f"*/week-*/{game_id}.json"), None)
    if not path:
        print(f"No report file for {game_id}")
        return 1
    rep = json.loads(path.read_text())
    season, weeks = rep["season"], rep["window"]["current"]["weeks"]

    pbp = nfl.load_pbp([season]).to_pandas()
    pbp = pbp[(pbp.season_type == "REG") & pbp.week.isin(weeks)]
    ro = nfl.load_rosters_weekly([season - 1, season]).to_pandas()
    pos = ro.sort_values(["season", "week"]).groupby("gsis_id")["position"].last()
    f = lambda c: pbp[c].fillna(0) == 1  # noqa: E731
    runs = pbp[f("rush_attempt") & ~f("qb_scramble") & ~f("qb_kneel") & ~f("aborted_play") & ~f("two_point_attempt") & (pbp.play_type != "no_play") & ~f("play_deleted")].copy()
    runs["yards"] = runs.rushing_yards.fillna(0)
    runs["qb"] = runs.rusher_player_id.map(pos).eq("QB")

    def summarize(df):
        return {"att": len(df), "ypc": df.yards.mean(), "epa": df.epa.mean(), "sr": df.success.mean(), "expl": (df.yards >= 10).mean(), "stuff": (df.yards <= 0).mean()}

    results = []

    def check(label, ours, theirs, tol=TOL):
        ok = (ours is None and theirs is None) or (ours is not None and theirs is not None and abs(float(ours) - float(theirs)) <= tol)
        results.append((ok, label, ours, theirs))

    ts = nfl.load_team_stats([season], summary_level="week").to_pandas()
    ts = ts[(ts.season_type == "REG") & ts.week.isin(weeks)]
    pfr = nfl.load_pfr_advstats([season], stat_type="rush", summary_level="week").to_pandas()
    pfr = pfr[(pfr.game_type == "REG") & pfr.week.isin(weeks)]
    pfr_pos = ro.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id", keep="last").set_index("pfr_id")
    pfr["gsis_id"] = pfr.pfr_player_id.map(pfr_pos["gsis_id"])
    pfr["is_qb"] = pfr.pfr_player_id.map(pfr_pos["position"]).eq("QB")

    for side in rep["sides"]:
        off, dfn = side["offense"], side["defense"]
        secs = {s["id"]: s for s in side["sections"]}
        tabs = {t["id"]: t for s in side["sections"] for t in s.get("tables", [])}

        # Offense overall + league EPA rank (all 32 teams).
        o = summarize(runs[runs.posteam == off])
        row = tabs["off_overall"]["rows"][0]
        for k, v in o.items():
            check(f"{off} offense {k}", v, row["cells"][k])
        team_epa = runs.groupby("posteam").epa.mean().sort_values(ascending=False)
        check(f"{off} offense EPA rank", list(team_epa.index).index(off) + 1, row["ranks"]["epa"][0], 0)
        check(f"{off} offense EPA peer group", len(team_epa), row["ranks"]["epa"][1], 0)

        # Offense totals reconcile with nflverse team_stats (all rushes, before filtering).
        allr = pbp[f("rush_attempt") & (pbp.posteam == off)]
        t = ts[ts.team == off]
        check(f"{off} all rush attempts vs team_stats carries", len(allr), t.carries.sum(), 2)
        check(f"{off} all rushing yards vs team_stats", allr.rushing_yards.fillna(0).sum(), t.rushing_yards.sum(), 3)

        # Defense overall.
        d = summarize(runs[runs.defteam == dfn])
        row = tabs["def_overall"]["rows"][0]
        for k, v in d.items():
            check(f"{dfn} defense {k} allowed", v, row["cells"][k])
        def_epa = runs.groupby("defteam").epa.mean().sort_values()
        check(f"{dfn} defense EPA rank", list(def_epa.index).index(dfn) + 1, row["ranks"]["epa"][0], 0)

        # YBC allowed (PFR, non-QB).
        p = pfr[(pfr.opponent == dfn) & ~pfr.is_qb]
        check(f"{dfn} YBC/att allowed (PFR, non-QB)", p.rushing_yards_before_contact.sum() / p.carries.sum(), row["cells"]["ybc_att"])

        # Direction shares (offense perspective) for both units.
        for unit, team, col, tid in [("offense", off, "posteam", "off_direction"), ("defense", dfn, "defteam", "def_direction")]:
            dd = runs[(runs[col] == team) & runs.run_location.notna()]
            shares = dd.run_location.value_counts(normalize=True)
            rows = {r["key"]: r for r in tabs[tid]["rows"]}
            for loc in ["left", "middle", "right"]:
                check(f"{team} {unit} {loc} share", shares.get(loc, 0.0), rows[loc]["cells"]["share"])
                sub = dd[dd.run_location == loc]
                check(f"{team} {unit} {loc} EPA", sub.epa.mean() if len(sub) else None, rows[loc]["cells"]["epa"])
            check(f"{team} {unit} direction shares sum", sum(r["cells"]["share"] for r in rows.values()), 1.0, 0.001)

        # Lead rusher: attempts, YPC, carry share, YBC/YAC.
        rt = tabs["rushers"]
        lead = max((r for r in rt["rows"] if r["kind"] == "row"), key=lambda r: r["cells"]["att"] or 0)
        mine = runs[(runs.posteam == off) & (runs.rusher_player_id == lead["key"])]
        check(f"{lead['label']} designed runs", len(mine), lead["cells"]["att"], 0)
        check(f"{lead['label']} YPC", mine.yards.mean(), lead["cells"]["ypc"])
        check(f"{lead['label']} carry share", len(mine) / len(runs[runs.posteam == off]), lead["cells"]["carry_share"])
        pp = pfr[(pfr.gsis_id == lead["key"]) & (pfr.team == off)]
        check(f"{lead['label']} YBC/att (PFR)", pp.rushing_yards_before_contact.sum() / pp.carries.sum(), lead["cells"]["ybc_att"])
        check(f"{lead['label']} YAC/att (PFR)", pp.rushing_yards_after_contact.sum() / pp.carries.sum(), lead["cells"]["yac_att"])
        total = next(r for r in rt["rows"] if r["kind"] == "total")
        check(f"{off} rusher rows sum to team designed runs", sum(r["cells"]["att"] for r in rt["rows"] if r["kind"] in ("row", "qb")), total["cells"]["att"], 0)
        qb = runs[(runs.posteam == off) & runs.qb]
        check(f"{off} designed QB runs", len(qb), next((r["cells"]["att"] for r in rt["rows"] if r["kind"] == "qb"), 0), 0)

        # Prior season is separate: offense EPA over the full prior regular season.
        prior = rep["window"]["prior"]["season"]
        ppbp = nfl.load_pbp([prior]).to_pandas()
        ppbp = ppbp[ppbp.season_type == "REG"]
        g = lambda c: ppbp[c].fillna(0) == 1  # noqa: E731
        pr = ppbp[g("rush_attempt") & ~g("qb_scramble") & ~g("qb_kneel") & ~g("aborted_play") & ~g("two_point_attempt") & (ppbp.play_type != "no_play") & ~g("play_deleted") & (ppbp.posteam == off)]
        prow = tabs["prior_off"]["rows"][0]
        check(f"{off} {prior} designed runs", len(pr), prow["cells"]["att"], 0)
        check(f"{off} {prior} EPA/run", pr.epa.mean(), prow["cells"]["epa"])
        assert secs["prior"]["tables"][0]["season"] == prior

    width = max(len(r[1]) for r in results)
    for ok, label, ours, theirs in results:
        fmt = lambda v: "None" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))  # noqa: E731
        print(f"{'✓' if ok else '✗'} {label:<{width}}  nflverse {fmt(ours):>9}   report {fmt(theirs):>9}")
    bad = sum(not r[0] for r in results)
    print(f"\n{len(results) - bad}/{len(results)} checks match.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "2026_03_BAL_DAL"))
