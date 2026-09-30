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

    # Direction EPA ranks, recomputed independently for the Run Edge check.
    games_played = pd.concat([pbp[["game_id", "posteam"]].rename(columns={"posteam": "team"}), pbp[["game_id", "defteam"]].rename(columns={"defteam": "team"})]).dropna().drop_duplicates().groupby("team").size()
    min_att = {t: math.ceil(3.0 * n - 1e-9) for t, n in games_played.items()}

    def pct_rank(col, team, loc, higher_better):
        dd = runs[runs.run_location == loc].groupby(col).epa.agg(["mean", "size"])
        dd = dd[[dd.loc[t, "size"] >= min_att[t] for t in dd.index]]
        if team not in dd.index:
            return None
        r = (dd["mean"] > dd.loc[team, "mean"]).sum() + 1 if higher_better else (dd["mean"] < dd.loc[team, "mean"]).sum() + 1
        n = len(dd)
        return 1.0 if n == 1 else 1 - (r - 1) / (n - 1)

    ppbp = nfl.load_pbp([prior]).to_pandas()
    ppbp = ppbp[ppbp.season_type == "REG"]
    g = lambda c: ppbp[c].fillna(0) == 1  # noqa: E731
    pruns = ppbp[g("rush_attempt") & ~g("qb_scramble") & ~g("qb_kneel") & ~g("aborted_play") & ~g("two_point_attempt") & (ppbp.play_type != "no_play") & ~g("play_deleted")]

    for row in [x for x in rep["rows"] if x["game_id"] == game_id]:
        off, dfn = row["offense"], row["defense"]
        b = row["seasons"][str(season)]
        splits = {(s["group"], s["key"]): s for s in b["splits"]}

        # Offense overall + league EPA rank (all 32 teams).
        o = summarize(runs[runs.posteam == off])
        for k, v in o.items():
            check(f"{off} offense {k}", v, b["overall"]["off"][k])
        team_epa = runs.groupby("posteam").epa.mean().sort_values(ascending=False)
        check(f"{off} offense EPA rank", list(team_epa.index).index(off) + 1, b["overall"]["off"]["ranks"]["epa"][0], 0)
        check(f"{off} offense EPA peer group", len(team_epa), b["overall"]["off"]["ranks"]["epa"][1], 0)

        # Offense totals reconcile with nflverse team_stats (all rushes, before filtering).
        allr = pbp[f("rush_attempt") & (pbp.posteam == off)]
        t = ts[ts.team == off]
        check(f"{off} all rush attempts vs team_stats carries", len(allr), t.carries.sum(), 2)
        check(f"{off} all rushing yards vs team_stats", allr.rushing_yards.fillna(0).sum(), t.rushing_yards.sum(), 3)

        # Defense overall.
        d = summarize(runs[runs.defteam == dfn])
        for k, v in d.items():
            check(f"{dfn} defense {k} allowed", v, b["overall"]["def"][k])
        def_epa = runs.groupby("defteam").epa.mean().sort_values()
        check(f"{dfn} defense EPA rank", list(def_epa.index).index(dfn) + 1, b["overall"]["def"]["ranks"]["epa"][0], 0)

        # YBC allowed (PFR, non-QB).
        p = pfr[(pfr.opponent == dfn) & ~pfr.is_qb]
        check(f"{dfn} YBC/att allowed (PFR, non-QB)", p.rushing_yards_before_contact.sum() / p.carries.sum(), b["overall"]["def"]["ybc_att"])

        # Direction shares and EPA (offense perspective) for both units, then the Run Edge.
        edges, shares_off = {}, {}
        for unit, team, col in [("off", off, "posteam"), ("def", dfn, "defteam")]:
            dd = runs[(runs[col] == team) & runs.run_location.notna()]
            shares = dd.run_location.value_counts(normalize=True)
            for loc in ["left", "middle", "right"]:
                sp = splits[("direction", loc)][unit]
                check(f"{team} {unit} {loc} share", shares.get(loc, 0.0), sp["share"])
                sub = dd[dd.run_location == loc]
                check(f"{team} {unit} {loc} EPA", sub.epa.mean() if len(sub) else None, sp["epa"])
                if unit == "off":
                    shares_off[loc] = shares.get(loc, 0.0)
        for loc in ["left", "middle", "right"]:
            po, pd_ = pct_rank("posteam", off, loc, True), pct_rank("defteam", dfn, loc, False)
            edges[loc] = None if po is None or pd_ is None else round(50 + 50 * (po - pd_))
            check(f"{off} vs {dfn} {loc} edge", edges[loc], splits[("direction", loc)]["edge"], 0)
        cov = sum(shares_off[x] for x in edges if edges[x] is not None)
        run_edge = round(sum(edges[x] * shares_off[x] for x in edges if edges[x] is not None) / cov) if cov else None
        check(f"{off} vs {dfn} Run Edge", run_edge, b["run_edge"], 0)

        # Lead rusher: attempts, YPC, carry share, YBC/YAC.
        backs = [r for r in b["rushers"] if r["kind"] in ("rb", "other")]
        lead = max(backs, key=lambda r: r["att"])
        mine = runs[(runs.posteam == off) & (runs.rusher_player_id == lead["id"])]
        check(f"{lead['name']} designed runs", len(mine), lead["att"], 0)
        check(f"{lead['name']} YPC", mine.yards.mean(), lead["ypc"])
        check(f"{lead['name']} carry share", len(mine) / len(runs[runs.posteam == off]), lead["carry_share"])
        pp = pfr[(pfr.gsis_id == lead["id"]) & (pfr.team == off)]
        check(f"{lead['name']} YBC/att (PFR)", pp.rushing_yards_before_contact.sum() / pp.carries.sum(), lead["ybc_att"])
        check(f"{lead['name']} YAC/att (PFR)", pp.rushing_yards_after_contact.sum() / pp.carries.sum(), lead["yac_att"])
        total = next(r for r in b["rushers"] if r["kind"] == "total")
        check(f"{off} rusher rows sum to team designed runs", sum(r["att"] for r in b["rushers"] if r["kind"] != "total"), total["att"], 0)
        qb = runs[(runs.posteam == off) & runs.qb]
        check(f"{off} designed QB runs", len(qb), next((r["att"] for r in b["rushers"] if r["kind"] == "qb"), 0), 0)

        # Prior season is a separate block: offense over the full prior regular season.
        pb = row["seasons"][str(prior)]
        pr = pruns[pruns.posteam == off]
        check(f"{off} {prior} designed runs", len(pr), pb["overall"]["off"]["att"], 0)
        check(f"{off} {prior} EPA/run", pr.epa.mean(), pb["overall"]["off"]["epa"])
        check(f"{off} {prior} block labeled {prior}", prior, pb["season"], 0)

    width = max(len(r[1]) for r in results)
    for ok, label, ours, theirs in results:
        fmt = lambda v: "None" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))  # noqa: E731
        print(f"{'✓' if ok else '✗'} {label:<{width}}  nflverse {fmt(ours):>9}   report {fmt(theirs):>9}")
    bad = sum(not r[0] for r in results)
    print(f"\n{len(results) - bad}/{len(results)} checks match.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "2026_03_BAL_DAL"))
