"""
Independent spot-check of one matchup report against nflverse.

    python pipeline/verify_matchup.py 2026_03_BAL_DAL

Re-derives the headline numbers straight from nflverse with pandas (none of the pipeline's own code),
then compares them with the committed JSON. Exits non-zero on any mismatch.
"""

import json
import math
import sys
from pathlib import Path

import nflreadpy as nfl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOL = 0.0006  # JSON values are rounded to 4 decimals


def main(game_id: str) -> int:
    path = next((p for p in (ROOT / "data").glob("*/week-*.json") if game_id in p.read_text()[:20000]), None)
    rep = json.loads(path.read_text()) if path else None
    if not rep or not any(g["game_id"] == game_id for g in rep["games"]):
        print(f"No report file for {game_id}")
        return 1
    season, prior = rep["season"], rep["season"] - 1
    weeks = next(x["weeks"] for x in rep["seasons"] if x["current"])
    # YBC / YAC cover only the weeks PFR has published (they can trail play-by-play by a day or two).
    pfr_weeks = next(x.get("pfr_weeks", x["weeks"]) for x in rep["seasons"] if x["current"])

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
    pfr = pfr[(pfr.game_type == "REG") & pfr.week.isin(pfr_weeks)]
    pfr_pos = ro.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id", keep="last").set_index("pfr_id")
    pfr["gsis_id"] = pfr.pfr_player_id.map(pfr_pos["gsis_id"])
    pfr["is_qb"] = pfr.pfr_player_id.map(pfr_pos["position"]).eq("QB")

    # Ranks recomputed independently: RBs (non-QB rushers, per team) and defenses, by direction.
    games_played = pd.concat([pbp[["game_id", "posteam"]].rename(columns={"posteam": "team"}), pbp[["game_id", "defteam"]].rename(columns={"defteam": "team"})]).dropna().drop_duplicates().groupby("team").size()
    nonqb = runs[~runs.qb]

    def pct(values, me, higher_better):
        r = (values > values[me]).sum() + 1 if higher_better else (values < values[me]).sum() + 1
        n = len(values)
        return r, n, (1.0 if n == 1 else 1 - (r - 1) / (n - 1))

    def rb_rank(pid, team, loc=None, per_game=6.25):
        df = nonqb if loc is None else nonqb[nonqb.run_location == loc]
        gg = df.groupby(["rusher_player_id", "posteam"]).epa.agg(["mean", "size"]).reset_index()
        gg = gg[gg["size"] >= gg.posteam.map(lambda t: math.ceil(per_game * games_played[t] - 1e-9))]
        gg = gg.set_index(["rusher_player_id", "posteam"])["mean"]
        return pct(gg, (pid, team), True) if (pid, team) in gg.index else None

    def def_rank(team, loc):
        dd = runs[runs.run_location == loc].groupby("defteam").epa.agg(["mean", "size"])
        dd = dd[[dd.loc[t, "size"] >= math.ceil(3.0 * games_played[t] - 1e-9) for t in dd.index]]["mean"]
        return pct(dd, team, False) if team in dd.index else None

    ppbp = nfl.load_pbp([prior]).to_pandas()
    ppbp = ppbp[ppbp.season_type == "REG"]
    g = lambda c: ppbp[c].fillna(0) == 1  # noqa: E731
    pruns = ppbp[g("rush_attempt") & ~g("qb_scramble") & ~g("qb_kneel") & ~g("aborted_play") & ~g("two_point_attempt") & (ppbp.play_type != "no_play") & ~g("play_deleted")]

    for row in [x for x in rep["rows"] if x["game_id"] == game_id]:
        off, dfn = row["offense"], row["defense"]
        b = row["seasons"][str(season)]
        splits = {(s["group"], s["key"]): s for s in b["splits"]}
        pid, name = row["starter"]["id"], row["starter"]["name"]
        check(f"{off} starter = depth-chart RB1 ({name})", 1, int(b["subject"]["id"] == pid), 0)

        # Starting RB overall: HIS designed runs for this team only, ranked among qualifying non-QB rushers.
        mine = runs[(runs.posteam == off) & (runs.rusher_player_id == pid)]
        for k, v in summarize(mine).items():
            check(f"{name} {k}", v, b["overall"]["off"][k])
        check(f"{name} carry share", len(mine) / len(runs[runs.posteam == off]), b["overall"]["off"]["carry_share"])
        rk = rb_rank(pid, off)
        check(f"{name} EPA rank among RBs", rk[0] if rk else None, b["overall"]["off"]["ranks"].get("epa", [None])[0], 0)
        check(f"{name} RB peer group", rk[1] if rk else None, b["overall"]["off"]["ranks"].get("epa", [None, None])[1], 0)
        pp = pfr[(pfr.gsis_id == pid) & (pfr.team == off)]
        check(f"{name} YBC/att (PFR)", pp.rushing_yards_before_contact.sum() / pp.carries.sum() if len(pp) else None, b["overall"]["off"]["ybc_att"])
        check(f"{name} YAC/att (PFR)", pp.rushing_yards_after_contact.sum() / pp.carries.sum() if len(pp) else None, b["overall"]["off"]["yac_att"])

        # Team totals still reconcile with nflverse team_stats (all rushes, before filtering).
        allr = pbp[f("rush_attempt") & (pbp.posteam == off)]
        t = ts[ts.team == off]
        check(f"{off} all rush attempts vs team_stats carries", len(allr), t.carries.sum(), 2)
        check(f"{off} all rushing yards vs team_stats", allr.rushing_yards.fillna(0).sum(), t.rushing_yards.sum(), 3)

        # Defense overall (against every rusher).
        d = summarize(runs[runs.defteam == dfn])
        for k, v in d.items():
            check(f"{dfn} defense {k} allowed", v, b["overall"]["def"][k])
        def_epa = runs.groupby("defteam").epa.mean().sort_values()
        check(f"{dfn} defense EPA rank", list(def_epa.index).index(dfn) + 1, b["overall"]["def"]["ranks"]["epa"][0], 0)
        p = pfr[(pfr.opponent == dfn) & ~pfr.is_qb]
        check(f"{dfn} YBC/att allowed (PFR, non-QB)", p.rushing_yards_before_contact.sum() / p.carries.sum(), b["overall"]["def"]["ybc_att"])

        # Direction shares / EPA (offense perspective), then the Run Edge from independent ranks.
        mine_dir = mine[mine.run_location.notna()]
        rb_shares = mine_dir.run_location.value_counts(normalize=True)
        dd = runs[(runs.defteam == dfn) & runs.run_location.notna()]
        def_shares = dd.run_location.value_counts(normalize=True)
        edges = {}
        for loc in ["left", "middle", "right"]:
            sp = splits[("direction", loc)]
            sub = mine_dir[mine_dir.run_location == loc]
            check(f"{name} {loc} share", rb_shares.get(loc, 0.0), sp["off"]["share"])
            check(f"{name} {loc} EPA", sub.epa.mean() if len(sub) else None, sp["off"]["epa"])
            check(f"{dfn} defense {loc} share", def_shares.get(loc, 0.0), sp["def"]["share"])
            o_r, d_r = rb_rank(pid, off, loc, per_game=2.0), def_rank(dfn, loc)
            edges[loc] = None if o_r is None or d_r is None else round(50 + 50 * (o_r[2] - d_r[2]))
            check(f"{name} vs {dfn} {loc} edge", edges[loc], sp["edge"], 0)
        cov = sum(rb_shares.get(x, 0.0) for x in edges if edges[x] is not None)
        run_edge = round(sum(edges[x] * rb_shares.get(x, 0.0) for x in edges if edges[x] is not None) / cov) if cov else None
        check(f"{name} vs {dfn} Run Edge", run_edge, b["run_edge"], 0)

        # Backs table still adds up to the team's designed runs.
        total = next(r for r in b["rushers"] if r["kind"] == "total")
        check(f"{off} backs table sums to team designed runs", sum(r["att"] for r in b["rushers"] if r["kind"] != "total"), total["att"], 0)

        # Prior season is a separate block: the same RB's full prior-season line (any team).
        pb = row["seasons"][str(prior)]
        pr = pruns[pruns.rusher_player_id == pid]
        check(f"{name} {prior} designed runs", len(pr), pb["overall"]["off"]["att"], 0)
        check(f"{name} {prior} EPA/run", pr.epa.mean() if len(pr) else None, pb["overall"]["off"]["epa"])
        check(f"{name} {prior} block labeled {prior}", prior, pb["season"], 0)

    width = max(len(r[1]) for r in results)
    for ok, label, ours, theirs in results:
        fmt = lambda v: "None" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))  # noqa: E731
        print(f"{'✓' if ok else '✗'} {label:<{width}}  nflverse {fmt(ours):>9}   report {fmt(theirs):>9}")
    bad = sum(not r[0] for r in results)
    print(f"\n{len(results) - bad}/{len(results)} checks match.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "2026_03_BAL_DAL"))
