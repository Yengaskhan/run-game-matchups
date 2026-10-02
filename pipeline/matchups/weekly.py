"""
Builds one JSON file per week: a row for every offense playing that week, each with a compact summary
(for the main table) and a detail block (for the expanded view), once per season. The current season
(games before this week) and the prior season (full regular season) are separate blocks, never combined.
"""

from datetime import datetime, timezone

import polars as pl

from . import fmt
from .config import BOX_BUCKETS, DIRECTIONS, EDGE, EXPLOSIVE_YARDS, GAPS, QUALIFIERS, SCHEMA_VERSION
from .metrics import agg_exprs, nan_to_none, pct_from_rank
from .plays import FILTERS
from .window import LeagueWindow

GROUPS = [
    ("direction", DIRECTIONS),
    ("gap", GAPS),
    ("box", [(k, label) for k, label, *_ in BOX_BUCKETS]),
]
RANKED = ["ypc", "epa", "sr", "expl", "stuff", "ybc_att", "yac_att"]


def _round(v):
    v = nan_to_none(v)
    return round(v, 4) if isinstance(v, float) else v


def metrics(rec: dict | None, keys=("att", "share", "ypc", "epa", "sr", "expl", "stuff")) -> dict:
    """Numbers plus [rank, peer group size] for every ranked metric that qualified."""
    rec = rec or {}
    m = {k: _round(rec.get(k)) for k in keys}
    m["att"] = int(rec.get("att") or 0)
    m["ranks"] = {k: [int(rec[f"{k}_rank"]), int(rec[f"{k}_n"])] for k in RANKED if rec.get(f"{k}_rank") is not None and rec.get(f"{k}_n")}
    return m


def edge_from(off: dict, dfn: dict) -> int | None:
    """50 + 50 x (offense EPA percentile - defense EPA-allowed percentile); None unless both are ranked."""
    po = pct_from_rank(*off["ranks"]["epa"]) if "epa" in off["ranks"] else None
    pd_ = pct_from_rank(*dfn["ranks"]["epa"]) if "epa" in dfn["ranks"] else None
    if po is None or pd_ is None:
        return None
    return round(50 + 50 * (po - pd_))


def band(edge: int | None, small_sample: bool = False) -> str:
    if edge is None or small_sample:
        return "neutral"
    return next(key for key, _label, lo in EDGE["bands"] if edge >= lo)


# ------------------------------------------------------------------------------------------------

def _player_rows(w: LeagueWindow, table: str, pid: str, team: str) -> list[dict]:
    """A rusher's rows in a league table: by (player, team) for the current season, by player for the prior one."""
    df = w.tables.get(table)
    if df is None or not df.height:
        return []
    match = {"rusher_player_id": pid, "posteam": team} if w.is_current else {"rusher_player_id": pid}
    return w.rows(table, **match)


def side_block(w: LeagueWindow, off: str, dfn: str, depth: list[dict], starter: dict | None,
               players_prior: list[dict] | None = None) -> dict | None:
    """Everything the page shows for one starting RB vs one defense in one season window.

    The offense side is the starting RB's OWN designed runs (current season: for this team; prior season:
    his full line, any team), ranked among non-QB rushers. The defense side is the defense against every
    rusher. QB runs, backups and the rest of the team are left out of the RB's numbers."""
    if not w.weeks or "off" not in w.tables:
        return None
    d_all = w.row("def", team=dfn)
    pid = starter["id"] if starter else None
    rec = (_player_rows(w, "rushers", pid, off) or [None])[0] if pid else None
    if rec:
        rec = {**rec, "games": rec.get("games_played") or rec.get("games_with_carry")}
    o_over = metrics(rec, ("games", "att", "ypc", "epa", "sr", "expl", "stuff", "ybc_att", "yac_att", "pfr_att", "carry_share", "snap_share"))
    d_over = metrics(d_all, ("games", "att", "ypc", "epa", "sr", "expl", "stuff", "ybc_att", "yac_att", "pfr_att", "qb_att"))

    splits = []
    for group, buckets in GROUPS:
        if f"def_{group}" not in w.tables:
            continue
        orecs = {r["bucket"]: r for r in _player_rows(w, f"rb_{group}", pid, off)} if pid else {}
        drecs = {r["bucket"]: r for r in w.rows(f"def_{group}", team=dfn)}
        for key, label in buckets:
            o, d = metrics(orecs.get(key)), metrics(drecs.get(key))
            splits.append({"group": group, "key": key, "label": label, "off": o, "def": d, "edge": edge_from(o, d)})

    # Headline Run Edge: direction edges weighted by where the RB runs.
    dirs = [s for s in splits if s["group"] == "direction"]
    ranked = [s for s in dirs if s["edge"] is not None and s["off"]["share"]]
    coverage = sum(s["off"]["share"] for s in ranked)
    run_edge = round(sum(s["edge"] * s["off"]["share"] for s in ranked) / coverage) if coverage else None
    small = coverage < EDGE["min_coverage"]

    top = max(dirs, key=lambda s: s["off"]["share"] or 0) if dirs else None
    name = starter["name"] if starter else off
    return {
        "season": w.season,
        "weeks": w.weeks,
        "subject": {"kind": "rb", "id": pid, "name": name, "team": off, "teams": (rec or {}).get("teams")},
        "overall": {"off": o_over, "def": d_over},
        "run_edge": run_edge,
        "edge_coverage": _round(coverage),
        "small_sample": small,
        "band": band(run_edge, small),
        "top_direction": {"key": top["key"], "label": top["label"], "share": top["off"]["share"], "att": top["off"]["att"]} if top and top["off"]["att"] else None,
        "splits": splits,
        "rushers": rushers_block(w, off, depth) if w.is_current else prior_rushers_block(w, players_prior or []),
        "takeaways": takeaways(name, dfn, splits, o_over["att"], w),
    }


def rushers_block(w: LeagueWindow, team: str, depth: list[dict]) -> list[dict]:
    """Depth-chart RBs in order, other non-QB rushers, designed QB runs, team total (rows sum to the total)."""
    recs = {r["rusher_player_id"]: r for r in w.rows("rushers", posteam=team)}
    keys = ("att", "carry_share", "snap_share", "ypc", "epa", "sr", "ybc_att", "yac_att", "pfr_att")
    out = []
    for d in depth:
        m = metrics(recs.get(d["gsis_id"]), keys)
        out.append({"id": d["gsis_id"], "name": d["name"], "role": f"RB{d['pos_rank']}", "kind": "rb", **m})
    listed = {d["gsis_id"] for d in depth}
    for r in sorted((r for r in recs.values() if r["rusher_player_id"] not in listed and not r["is_qb"] and r["att"]), key=lambda r: (-r["att"], r["name"] or "", r["rusher_player_id"])):  # stable order for ties
        out.append({"id": r["rusher_player_id"], "name": r["name"], "role": r.get("pos") or "—", "kind": "other", **metrics(r, keys)})
    team_rec = w.row("off", team=team)
    team_att = (team_rec or {}).get("att") or 0
    qb = w.runs.filter(pl.col("posteam") == team, pl.col("is_qb_run"))
    if qb.height:
        q = qb.select(agg_exprs()).to_dicts()[0]
        q["carry_share"] = q["att"] / team_att if team_att else None
        m = metrics(q, keys)
        m["ranks"] = {}  # QBs are outside the rusher peer group
        m["ybc_att"] = m["yac_att"] = m["pfr_att"] = None  # PFR includes scrambles for QBs
        sneaks = int(qb["is_qb_sneak"].sum())
        out.append({"id": "qb", "name": "Designed QB runs", "role": "QB", "kind": "qb",
                    "note": f"{', '.join(qb['rusher_name'].unique().sort().to_list())}; {sneaks} sneak{'s' if sneaks != 1 else ''}", **m})
    if team_rec:
        t = metrics(team_rec, keys)
        t["carry_share"] = 1.0
        t["ranks"] = {}
        out.append({"id": "total", "name": f"{team} total", "role": "", "kind": "total", **t})
    return out


def prior_rushers_block(w: LeagueWindow, players: list[dict]) -> list[dict]:
    """This season's backs, with their full prior-season line (whichever team they played for)."""
    recs = {r["rusher_player_id"]: r for r in w.rows("rushers")}
    keys = ("att", "ypc", "epa", "sr", "ybc_att", "yac_att", "pfr_att")
    out = []
    for p in players:
        r = recs.get(p["id"])
        out.append({"id": p["id"], "name": p["name"], "role": (r or {}).get("teams") or "—", "kind": "rb", **metrics(r, keys)})
    return out


def takeaways(name: str, dfn: str, splits: list[dict], att: int, w: LeagueWindow) -> list[str]:
    """At most two lines: the RB's biggest edge each way among the gaps he uses most."""
    if not att:
        return [f"{name} has no designed runs in {w.season} {fmt.weeks_label(w.weeks)}, so there's nothing to compare yet."]
    used = [s for s in splits if s["group"] == "gap" and (s["off"]["share"] or 0) >= EDGE["min_share"] and s["edge"] is not None]
    if not used:
        return [f"No gap {name} uses on {fmt.pct(EDGE['min_share'])}+ of his runs has both sides ranked yet (samples too small)."]

    def line(s, who):
        o, d = s["off"], s["def"]
        return (f"{who}: {s['label']} (edge {s['edge']}). {name} runs there {fmt.pct(o['share'])} of the time, "
                f"{fmt.epa(o['epa'])} EPA/run ({fmt.rank(*o['ranks']['epa'])} RBs, n={o['att']}); "
                f"{dfn} allows {fmt.epa(d['epa'])} ({fmt.rank(*d['ranks']['epa'])}, n={d['att']}).")

    hi, lo = max(used, key=lambda s: s["edge"]), min(used, key=lambda s: s["edge"])
    out = [line(hi, f"Best spot for {name}")]
    if lo is not hi:
        out.append(line(lo, f"Toughest spot for {name}"))
    return out


# ------------------------------------------------------------------------------------------------

def week_report(season: int, week: int, games: list[dict], cur: LeagueWindow, prior: LeagueWindow,
                depth_by_game: dict[str, dict[str, list[dict]]], checks: list[str]) -> dict:
    rows = []
    for g in games:
        depth = depth_by_game[g["game_id"]]
        for off, dfn, home in [(g["away_team"], g["home_team"], False), (g["home_team"], g["away_team"], True)]:
            dep = depth.get(off, [])
            starter = {"id": dep[0]["gsis_id"], "name": dep[0]["name"]} if dep else None
            cur_block = side_block(cur, off, dfn, dep, starter)
            players = [{"id": r["id"], "name": r["name"]} for r in (cur_block or {}).get("rushers", []) if r["kind"] in ("rb", "other")] \
                or [{"id": d["gsis_id"], "name": d["name"]} for d in dep]
            rows.append({
                "game_id": g["game_id"], "offense": off, "defense": dfn, "home": home,
                # Starting RB: RB1 on the nflverse depth chart (latest snapshot; before kickoff day for played games).
                "starter": starter,
                "seasons": {str(cur.season): cur_block, str(prior.season): side_block(prior, off, dfn, dep, starter, players)},
            })
    bands = [{"key": k, "label": label, "min": lo} for k, label, lo in EDGE["bands"]]
    return {
        "schema": SCHEMA_VERSION,
        "season": season,
        "week": week,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "data_as_of": cur.data_as_of,
        "seasons": [
            {"season": cur.season, "label": f"{cur.season} ({fmt.weeks_label(cur.weeks)})" if cur.weeks else f"{cur.season} (no games yet)", "weeks": cur.weeks, "current": True,
             "pfr_weeks": cur.pfr_weeks,
             "empty": None if cur.weeks else f"No {cur.season} regular-season games were played before Week {week}. Switch to {prior.season}."},
            {"season": prior.season, "label": f"{prior.season} (full season)", "weeks": prior.weeks, "current": False, "pfr_weeks": prior.pfr_weeks, "empty": None},
        ],
        "games": [{"game_id": g["game_id"], "away": g["away_team"], "home": g["home_team"], "gameday": g["gameday"],
                   "gametime": g["gametime"], "stadium": g.get("stadium")} for g in games],
        "rows": rows,
        "edge": {
            "bands": bands,
            "min_coverage": EDGE["min_coverage"],
            "definition": ("Run Edge (0–100, 50 = neutral), starting RB vs run defense. In each direction, gap or box count: "
                           "50 + 50 × (the RB's EPA/run percentile among RBs − the defense's EPA-allowed percentile among defenses), each "
                           "within its own ranked table. The headline edge averages the left / middle / right edges, weighted by how often the "
                           f"RB runs each way. It is shaded only when the ranked directions cover at least {fmt.pct(EDGE['min_coverage'])} of his runs; "
                           "otherwise it shows grey as a small sample."),
        },
        "notes": [
            "Each row is the starting RB (RB1 on the nflverse depth chart) against the opposing run defense. The RB side counts only his own designed runs (current season: for this team; prior season: his full line, any team); QB runs and backups are not included. The defense side is against every rusher.",
            "Left / middle / right and end / tackle / guard are from the OFFENSE's point of view, including for the defense.",
            f"Current-season numbers use only games before Week {week} ({fmt.weeks_label(cur.weeks)}). Small samples are noisy: read every rate next to its attempts (n).",
            "The two seasons are never combined. The prior season is last year's full regular season.",
            "Box counts: FTN charting via nflverse (n_defense_box). nflverse participation data is not published for the current season. Box counts of 0 are treated as not charted.",
            "YBC / YAC: Pro Football Reference via nflverse, per player per game, so they include every carry; defense “allowed” figures use non-QB rushers only."
            + (f" PFR hasn't published every {cur.season} game yet, so YBC / YAC cover {fmt.weeks_label(cur.pfr_weeks)} (everything else: {fmt.weeks_label(cur.weeks)})."
               if cur.weeks and cur.pfr_weeks != cur.weeks else ""),
            f"Explosive = {EXPLOSIVE_YARDS}+ yards. Stuff = 0 or fewer. Success = EPA > 0. Rank 1 = best: the most productive RB, or the stingiest defense.",
        ],
        "filters": FILTERS,
        "qualifiers": [
            f"Teams: all teams with at least {QUALIFIERS['team_min_games']} game are ranked (peer group: 32).",
            f"RBs overall: non-QB rushers with at least {QUALIFIERS['rusher_att_per_team_game']:g} designed runs per team game.",
            f"RB direction / gap / box splits: at least {QUALIFIERS['rusher_bucket_att_per_team_game']:g} carries per team game in the bucket (current season), {QUALIFIERS['rusher_bucket_min_att_prior']} (prior season).",
            f"Defense direction / gap / box splits: at least {QUALIFIERS['bucket_att_per_team_game']:g} designed runs faced per game in the bucket (current season), {QUALIFIERS['bucket_min_att_prior']} (prior season).",
        ],
        "sources": [
            "nflverse play-by-play, schedules, weekly rosters, depth charts, snap counts (nflreadpy)",
            "Pro Football Reference advanced rushing via nflverse (load_pfr_advstats, stat_type='rush')",
            "FTN charting via nflverse (load_ftn_charting): box counts and QB sneaks",
        ],
        "checks": checks,
    }
