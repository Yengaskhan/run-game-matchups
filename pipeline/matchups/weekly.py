"""
Builds one JSON file per week: a row for every offense playing that week, each with a compact summary
(for the main table) and a detail block (for the expanded view), once per season. The current season
(games before this week) and the prior season (full regular season) are separate blocks, never combined.
"""

from datetime import datetime, timezone

import polars as pl

from . import fmt
from .datasuite import DEF_STATUS, qualifier_note, scheme_block, scheme_player, team_defense_block, team_defense_meta
from .config import BOX_BUCKETS, DIRECTIONS, EDGE, EXPLOSIVE_YARDS, GAPS, MODEL, QUALIFIERS, SCHEMA_VERSION
from . import model
from .metrics import agg_exprs, nan_to_none, pct_from_rank
from .plays import FILTERS
from .window import LeagueWindow

GROUPS = [
    ("direction", DIRECTIONS),
    ("gap", GAPS),
    ("box", [(k, label) for k, label, *_ in BOX_BUCKETS]),
]
RANKED = ["ypc", "sr", "expl", "stuff", "ybc_att", "yac_att"]
SPLIT_KEYS = ("att", "share", "ypc", "sr")
OFF_KEYS = ("games", "att", "yds", "ypc", "sr", "expl", "stuff", "ybc_att", "yac_att", "pfr_att", "carry_share", "snap_share")
DEF_KEYS = ("games", "att", "ypc", "sr", "expl", "stuff", "ybc_att", "yac_att", "pfr_att", "qb_att")


def _round(v):
    v = nan_to_none(v)
    return round(v, 4) if isinstance(v, float) else v


def metrics(rec: dict | None, keys=SPLIT_KEYS) -> dict:
    """Numbers plus [rank, peer group size] for every ranked metric in `keys` that qualified."""
    rec = rec or {}
    m = {k: _round(rec.get(k)) for k in keys}
    m["att"] = int(rec.get("att") or 0)
    m["ranks"] = {k: [int(rec[f"{k}_rank"]), int(rec[f"{k}_n"])] for k in RANKED if k in keys and rec.get(f"{k}_rank") is not None and rec.get(f"{k}_n")}
    return m


# ------------------------------------------------------------------------------------------------

def _player_rows(w: LeagueWindow, table: str, pid: str, team: str) -> list[dict]:
    """A rusher's rows in a league table: by (player, team) for the current season, by player for the prior one."""
    df = w.tables.get(table)
    if df is None or not df.height:
        return []
    match = {"rusher_player_id": pid, "posteam": team} if w.is_current else {"rusher_player_id": pid}
    return w.rows(table, **match)


def player_stats(w: LeagueWindow, pid: str, team: str | None) -> dict | None:
    """One rusher's own designed runs in a window: overall and direction / gap / box splits, ranked among
    non-QB rushers. Current season: for `team` only; prior season: his full line, any team. None if no runs."""
    rec = (_player_rows(w, "rushers", pid, team) or [None])[0] if w.weeks and "rushers" in w.tables else None
    if not rec:
        return None
    rec = {**rec, "games": rec.get("games_played") or rec.get("games_with_carry")}
    splits = {}
    for group, _buckets in GROUPS:
        if f"rb_{group}" in w.tables:
            splits[group] = {r["bucket"]: metrics(r) for r in _player_rows(w, f"rb_{group}", pid, team)}
    return {"team": team if w.is_current else rec.get("teams"), "overall": metrics(rec, OFF_KEYS), "splits": splits}


def defense_stats(w: LeagueWindow, team: str) -> dict | None:
    """A run defense in a window: overall allowed and direction / gap / box splits, ranked among defenses."""
    if not w.weeks or "def" not in w.tables:
        return None
    splits = {}
    for group, _buckets in GROUPS:
        if f"def_{group}" in w.tables:
            splits[group] = {r["bucket"]: metrics(r) for r in w.rows(f"def_{group}", team=team)}
    return {"team": team, "overall": metrics(w.row("def", team=team), DEF_KEYS), "splits": splits}


def league_overall(w: LeagueWindow) -> dict:
    """League success rate and YPC on designed runs in the window, rounded as written to the JSON."""
    return {k: _round(w.league["overall"].get(k)) for k in ("sr", "ypc")}


def side_block(w: LeagueWindow, off: str, dfn: str, depth: list[dict], starter: dict | None,
               players_prior: list[dict] | None = None, vegas: dict | None = None) -> dict | None:
    """Everything the slate shows for one starting RB vs one defense in one season window.

    The offense side is the starting RB's OWN designed runs (current season: for this team; prior season:
    his full line, any team), ranked among non-QB rushers. The defense side is the defense against every
    rusher. The Run Edge (model.py) comes from the defense and this week's Vegas line; the RB's numbers set
    his normal game for the projection. The same numbers are in the report's player / defense pool, which the
    page uses to score any RB against any defense."""
    if not w.weeks or "off" not in w.tables:
        return None
    pid = starter["id"] if starter else None
    ps = player_stats(w, pid, off if w.is_current else None) if pid else None
    ds = defense_stats(w, dfn)
    o_over = ps["overall"] if ps else metrics(None, OFF_KEYS)

    # Direction / gap / box splits: context only. The backtest found no predictive value in matching the RB's
    # own splits to the defense's, so they carry no edge.
    splits = []
    for group, buckets in GROUPS:
        if group not in ds["splits"]:
            continue
        for key, label in buckets:
            o = (ps["splits"].get(group, {}).get(key) if ps else None) or metrics(None)
            d = ds["splits"][group].get(key) or metrics(None)
            splits.append({"group": group, "key": key, "label": label, "off": o, "def": d, "edge": None})

    m = model.matchup(ds["overall"], league_overall(w), vegas)
    base = o_over["yds"] / o_over["games"] if o_over.get("games") and o_over.get("yds") is not None else None
    m["vegas"] = vegas
    m["base_ypg"] = _round(base)
    m["proj_yds"] = _round(base * m["mult"]) if base is not None else None
    small = o_over["att"] < MODEL["min_att"]

    dirs = [s for s in splits if s["group"] == "direction"]
    top = max(dirs, key=lambda s: s["off"]["share"] or 0) if dirs else None
    name = starter["name"] if starter else off
    return {
        "season": w.season,
        "weeks": w.weeks,
        "subject": {"kind": "rb", "id": pid, "name": name, "team": off, "teams": ps["team"] if ps and not w.is_current else None},
        "overall": {"off": o_over, "def": ds["overall"]},
        "run_edge": m["run_edge"],
        "small_sample": small,
        "band": m["band"],
        "model": m,
        "top_direction": {"key": top["key"], "label": top["label"], "share": top["off"]["share"], "att": top["off"]["att"]} if top and top["off"]["att"] else None,
        "splits": splits,
        "rushers": rushers_block(w, off, depth) if w.is_current else prior_rushers_block(w, players_prior or []),
        "takeaways": takeaways(name, off, dfn, m, o_over, ds["overall"], league_overall(w), w),
    }


def roster(w: LeagueWindow, depth_by_game: dict[str, dict[str, list[dict]]]) -> list[dict]:
    """Every RB the player page can show: depth-chart RBs of this week's teams (in depth order), then
    other RBs / FBs with current-season designed runs, on the team they have the most carries for."""
    out, seen = [], set()
    for depth in depth_by_game.values():
        for team in sorted(depth):
            for d in depth[team]:
                if d["gsis_id"] not in seen:
                    seen.add(d["gsis_id"])
                    out.append({"id": d["gsis_id"], "name": d["name"], "team": team, "pos": "RB", "depth": f"RB{d['pos_rank']}"})
    if w.weeks and "rushers" in w.tables:
        rs = w.tables["rushers"].filter(~pl.col("is_qb"), pl.col("pos").is_in(["RB", "FB"]), pl.col("att") > 0)
        for r in rs.sort(["att", "rusher_player_id"], descending=[True, False]).iter_rows(named=True):
            if r["rusher_player_id"] not in seen:
                seen.add(r["rusher_player_id"])
                out.append({"id": r["rusher_player_id"], "name": r["name"], "team": r["posteam"], "pos": r["pos"], "depth": None})
    return out


def pool_block(w: LeagueWindow, players: list[dict], scheme_pick: dict | None = None, td_pick: dict | None = None) -> dict | None:
    """Every listed RB and every defense in one season window, so the page can pair any RB with any
    defense (the Run Edge is recomputed in the browser exactly as edge_from / side_block do here)."""
    if not w.weeks or "off" not in w.tables:
        return None
    ps = {}
    for p in players:
        st = player_stats(w, p["id"], p["team"] if w.is_current else None)
        if st:
            if w.is_current and scheme_pick is not None:
                st["scheme"] = scheme_player(scheme_pick, p["id"])
            ps[p["id"]] = st
    league = {"overall": {k: _round(w.league["overall"].get(k)) for k in ("sr", "ypc")}}
    for group, _buckets in GROUPS:
        if group in w.league:
            league[group] = {b: {k: _round(v.get(k)) for k in ("share", "sr", "ypc")} for b, v in w.league[group].items()}
    defenses = {t: defense_stats(w, t) for t in sorted(w.tables["def"]["team"].to_list())}
    # Data Suite team-defense context (display only, not in the Run Edge): None when no export matches.
    for t, d in defenses.items():
        d["ds"] = team_defense_block(td_pick or {}, t)
    return {"players": ps, "defenses": defenses, "league": league}


def rushers_block(w: LeagueWindow, team: str, depth: list[dict]) -> list[dict]:
    """Depth-chart RBs in order, other non-QB rushers, designed QB runs, team total (rows sum to the total)."""
    recs = {r["rusher_player_id"]: r for r in w.rows("rushers", posteam=team)}
    keys = ("att", "carry_share", "snap_share", "ypc", "sr", "ybc_att", "yac_att", "pfr_att")
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
    keys = ("att", "ypc", "sr", "ybc_att", "yac_att", "pfr_att")
    out = []
    for p in players:
        r = recs.get(p["id"])
        out.append({"id": p["id"], "name": p["name"], "role": (r or {}).get("teams") or "—", "kind": "rb", **metrics(r, keys)})
    return out


def takeaways(name: str, off: str, dfn: str, m: dict, o: dict, d: dict, lg: dict, w: LeagueWindow) -> list[str]:
    """Why the Run Edge is what it is: the defense, then the game environment, then his projection."""
    out = [f"{dfn} allows {fmt.pct(d['sr'])} success (league {fmt.pct(lg['sr'])}) and {fmt.dec(d['ypc'])} YPC (league {fmt.dec(lg['ypc'])}) "
           f"on designed runs over {d['games']} games: {fmt.signed_pct(m['sr_idx'] ** MODEL['w_sr'] * m['ypc_idx'] ** MODEL['w_ypc'] - 1)} for the run game."]
    v = m.get("vegas")
    if v and v.get("avg") and v["n"] >= MODEL["vegas_min_games"]:
        out.append(f"Vegas: {off} implied total {v['implied']:.1f} vs its usual {v['avg']:.1f}: {fmt.signed_pct(m['vegas_idx'] ** MODEL['w_vegas'] - 1)}.")
    if not o["att"]:
        out.append(f"{name} has no designed runs in {w.season} {fmt.weeks_label(w.weeks)}, so there's no normal game to project from.")
    elif m.get("proj_yds") is not None:
        out.append(f"{name}'s normal game: {fmt.dec(m['base_ypg'])} rushing yards (designed runs, {o['games']} games). "
                   f"Matchup-adjusted: {fmt.dec(m['proj_yds'])} ({fmt.signed_pct(m['mult'] - 1)})."
                   + (f" Small sample ({o['att']} carries): treat as rough." if o["att"] < MODEL["min_att"] else ""))
    return out


# ------------------------------------------------------------------------------------------------

def week_report(season: int, week: int, games: list[dict], cur: LeagueWindow, prior: LeagueWindow,
                depth_by_game: dict[str, dict[str, list[dict]]], checks: list[str],
                scheme_pick: dict | None = None, scheme_note: str | None = None, td_picks: dict[int, dict] | None = None,
                vegas: dict[str, dict] | None = None) -> dict:
    """scheme_pick: the Data Suite rushing export chosen for this week (see datasuite.pick_rushing_export)."""
    scheme_pick = scheme_pick or {"status": "No Data Suite rushing export has been added yet."}
    rows = []
    for g in games:
        depth = depth_by_game[g["game_id"]]
        for off, dfn, home in [(g["away_team"], g["home_team"], False), (g["home_team"], g["away_team"], True)]:
            dep = depth.get(off, [])
            starter = {"id": dep[0]["gsis_id"], "name": dep[0]["name"]} if dep else None
            vg = (vegas or {}).get(off)
            cur_block = side_block(cur, off, dfn, dep, starter, vegas=vg)
            if cur_block:
                # Run scheme (zone vs man/gap): Data Suite, current season only, kept apart from nflverse numbers.
                cur_block["scheme"] = scheme_block(scheme_pick, starter)
            players = [{"id": r["id"], "name": r["name"]} for r in (cur_block or {}).get("rushers", []) if r["kind"] in ("rb", "other")] \
                or [{"id": d["gsis_id"], "name": d["name"]} for d in dep]
            rows.append({
                "game_id": g["game_id"], "offense": off, "defense": dfn, "home": home,
                # Starting RB: RB1 on the nflverse depth chart (latest snapshot; before kickoff day for played games).
                "starter": starter,
                "seasons": {str(cur.season): cur_block, str(prior.season): side_block(prior, off, dfn, dep, starter, players, vegas=vg)},
            })
    players = roster(cur, depth_by_game)
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
        # Player page / defense page: every RB in `players` and every defense, per season (never combined).
        "players": players,
        "buckets": {group: [{"key": k, "label": label} for k, label in buckets] for group, buckets in GROUPS},
        "pool": {str(cur.season): pool_block(cur, players, scheme_pick, (td_picks or {}).get(cur.season)),
                 str(prior.season): pool_block(prior, players, None, (td_picks or {}).get(prior.season))},
        "team_defense": {str(sn): team_defense_meta((td_picks or {}).get(sn) or {"status": "No Data Suite team defense export has been added yet."}) for sn in (cur.season, prior.season)},
        "edge": {
            "bands": bands,
            "model": {k: MODEL[k] for k in ("k_games", "w_sr", "w_ypc", "w_vegas", "vegas_min_games", "scale", "min_att")},
            "definition": ("Run Edge (0–100, 50 = neutral): how much more or less the starting RB should rush for than in his normal game. "
                           f"It multiplies what this defense allows per designed run (success rate^{MODEL['w_sr']} × YPC^{MODEL['w_ypc']}, each vs league and "
                           f"shrunk toward average by games: G / (G + {MODEL['k_games']})) by his team's Vegas implied total vs its usual (^{MODEL['w_vegas']}). "
                           f"Score = 50 + 50 × tanh(ln(multiplier) / {MODEL['scale']}): +5% → 66, +10% → 79, −5% → 33. "
                           "The weights come from a backtest of every 2023–2025 week scored from earlier games only, checked on 2026 (see the Track record tab). "
                           "The RB's own direction and gap splits are shown for context; they did not predict results."),
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
            f"Explosive = {EXPLOSIVE_YARDS}+ yards. Stuff = 0 or fewer. Success rate = share of runs nflverse marks successful: the run left the offense better placed to score than before it, given down, distance and field position. Rank 1 = best: the most productive RB, or the stingiest defense.",
        ],
        "filters": FILTERS,
        "qualifiers": [
            f"Teams: all teams with at least {QUALIFIERS['team_min_games']} game are ranked (peer group: 32).",
            f"RBs overall: non-QB rushers with at least {QUALIFIERS['rusher_att_per_team_game']:g} designed runs per team game.",
            f"RB direction / gap / box splits: at least {QUALIFIERS['rusher_bucket_att_per_team_game']:g} carries per team game in the bucket (current season), {QUALIFIERS['rusher_bucket_min_att_prior']} (prior season).",
            f"Defense direction / gap / box splits: at least {QUALIFIERS['bucket_att_per_team_game']:g} designed runs faced per game in the bucket (current season), {QUALIFIERS['bucket_min_att_prior']} (prior season).",
        ],
        "scheme": {
            "status": scheme_pick.get("status"),
            "exported_at": scheme_pick["exported"].strftime("%Y-%m-%dT%H:%MZ") if "exported" in scheme_pick else None,
            "note": scheme_note,
            "qualifier": qualifier_note(),
            "def_status": DEF_STATUS,
            "league": {k: {m: _round(x) for m, x in v.items()} for k, v in (scheme_pick.get("league") or {}).items()},
        },
        "sources": [
            "nflverse play-by-play, schedules, weekly rosters, depth charts, snap counts (nflreadpy)",
            "Data Suite rushing export: each RB's zone vs man/gap concept carries, YPC and success % (run-scheme table only)",
            "Data Suite team defense export: RB fantasy points, rush success and explosive rate allowed, average box (run-defense context only; not in the Run Edge)",
            "Pro Football Reference advanced rushing via nflverse (load_pfr_advstats, stat_type='rush')",
            "FTN charting via nflverse (load_ftn_charting): box counts and QB sneaks",
        ],
        "checks": checks,
    }
