"""
Builds the per-game report JSON from two LeagueWindows (current season to date, prior season).

The page renders every table generically from {columns, rows}, so a later section (e.g. pass coverage)
is just another list of tables under sides[i].sections.
"""

from datetime import datetime, timezone

import polars as pl

from . import fmt
from .config import BOX_BUCKETS, DIRECTIONS, GAPS, OVERLAP, QUALIFIERS, SCHEMA_VERSION
from .metrics import agg_exprs, nan_to_none, pct_from_rank
from .plays import FILTERS
from .window import LeagueWindow

DIR_LABEL = dict(DIRECTIONS)
GAP_LABEL = dict(GAPS)
BOX_LABEL = {k: label for k, label, _lo, _hi in BOX_BUCKETS}
SPLITS = {"direction": (DIRECTIONS, "direction"), "gap": (GAPS, "gap"), "box": ([(k, l) for k, l, *_ in BOX_BUCKETS], "box count")}

EFF = [("ypc", "YPC", "dec1"), ("epa", "EPA/run", "epa"), ("sr", "Success", "pct"), ("expl", "Expl.", "pct"), ("stuff", "Stuff", "pct")]
EFF_TITLES = {
    "offense": {
        "ypc": "Yards per designed run",
        "epa": "EPA per designed run",
        "sr": "Success rate (EPA > 0)",
        "expl": "Explosive rate: runs of 10+ yards",
        "stuff": "Stuff rate: runs of 0 or fewer yards (lower is better)",
    },
    "defense": {
        "ypc": "Yards per designed run allowed",
        "epa": "EPA per designed run allowed",
        "sr": "Success rate allowed",
        "expl": "Explosive runs (10+ yards) allowed",
        "stuff": "Stuff rate forced: runs held to 0 or fewer yards (higher is better)",
    },
}


# ------------------------------------------------------------------------------------------------
# Generic table pieces
# ------------------------------------------------------------------------------------------------

def col(key, label, fmt_, rank=False, title=None):
    c = {"key": key, "label": label, "fmt": fmt_}
    if rank:
        c["rank"] = True
    if title:
        c["title"] = title
    return c


def eff_cols(unit: str) -> list[dict]:
    return [col(k, lbl, f, rank=True, title=EFF_TITLES[unit][k]) for k, lbl, f in EFF]


def _round(v):
    return round(v, 4) if isinstance(v, float) else v


def mk_row(rec: dict | None, keys: list[str], label: str, kind="row", key=None, sub=None, group=None, ranked=True) -> dict:
    rec = rec or {}
    cells = {k: _round(nan_to_none(rec.get(k))) for k in keys}
    ranks = {}
    if ranked:
        for k in keys:
            r, n = rec.get(f"{k}_rank"), rec.get(f"{k}_n")
            if r is not None and n:
                ranks[k] = [int(r), int(n)]
    row = {"key": key or label, "label": label, "kind": kind, "cells": cells, "ranks": ranks}
    if sub:
        row["sub"] = sub
    if group:
        row["group"] = group
    return row


def table(id_, title, w: LeagueWindow, columns, rows, peer, takeaways, notes=None, checks=None, unit=None):
    t = {
        "id": id_,
        "title": title,
        "season": w.season,
        "season_label": f"{w.season} {'(current season)' if w.is_current else '(prior season)'}",
        "caption": f"{w.season} regular season, {fmt.weeks_label(w.weeks)} · designed runs only",
        "columns": columns,
        "rows": rows,
        "peer": peer,
        "notes": notes or [],
        "takeaways": takeaways,
    }
    if unit:
        t["unit"] = unit
    if checks:
        t["checks"] = checks
    return t


def unit_word(unit: str, plural=True) -> str:
    return ("offenses" if plural else "offense") if unit == "offense" else ("defenses" if plural else "defense")


# ------------------------------------------------------------------------------------------------
# Overall efficiency (one team + league average)
# ------------------------------------------------------------------------------------------------

def overall_table(w: LeagueWindow, team: str, unit: str, id_: str, title: str) -> dict:
    rec = w.row("off" if unit == "offense" else "def", team=team)
    lg = w.league["overall"]
    ybc_title = "Yards before contact per carry, non-QB rushers (PFR)" + (" allowed" if unit == "defense" else "")
    cols = [col("games", "G", "int"), col("att", "Att", "int")] + eff_cols(unit) + [
        col("ybc_att", "YBC/att", "dec1", rank=True, title=ybc_title),
    ]
    if unit == "offense":
        cols.append(col("yac_att", "YAC/att", "dec1", rank=True, title="Yards after contact per carry, non-QB rushers (PFR)"))
    cols.append(col("pfr_att", "PFR carries", "int", title="Non-QB carries behind the YBC / YAC figures (PFR counts every carry, so this can differ from Att)"))
    keys = [c["key"] for c in cols]
    lg_row = mk_row({**lg, "games": nan_to_none(lg.get("games"))}, keys, "League average", kind="ref", ranked=False)
    lg_row["cells"]["att"] = round(lg["att"] / max(1, w.games.height))
    lg_row["cells"]["pfr_att"] = round(lg["pfr_att"] / max(1, w.games.height)) if lg.get("pfr_att") else None
    lg_row["sub"] = "per team"
    rows = [mk_row(rec, keys, team, kind="team", key=team), lg_row]
    n = rec.get("epa_n") if rec else None
    peer = f"peer group: {n or w.games.height} {unit_word(unit)} (every team with a game in the window). Rank 1 = best {unit_word(unit, False)}."
    return table(id_, title, w, cols, rows, peer, overall_takeaways(team, rec, lg, unit), unit=unit,
                 notes=["YBC / YAC come from Pro Football Reference via nflverse. PFR publishes them per player per game only, so they include every carry, not just designed runs; QB carries are left out to keep scrambles and kneels out."])


def overall_takeaways(team: str, r: dict | None, lg: dict, unit: str) -> list[str]:
    if not r or not r.get("att"):
        return [f"{team} has no designed runs in this window."]
    rk = lambda k: fmt.rank(r.get(f"{k}_rank"), r.get(f"{k}_n"))  # noqa: E731
    out = []
    if unit == "defense":
        out.append(f"{team} has faced {fmt.att(r['att'])} in {r['games']} game{'s' if r['games'] != 1 else ''}: {fmt.dec(r['ypc'])} yards and {fmt.epa(r['epa'])} EPA per run allowed ({rk('epa')}; league {fmt.epa(lg['epa'])}).")
        out.append(f"Success rate allowed {fmt.pct(r['sr'])} ({rk('sr')}); stuff rate forced {fmt.pct(r['stuff'])} ({rk('stuff')}); explosive runs allowed {fmt.pct(r['expl'])} ({rk('expl')}).")
        if r.get("ybc_att") is not None:
            out.append(f"Non-QB rushers average {fmt.dec(r['ybc_att'])} yards before contact against {team} ({rk('ybc_att')}, {int(r['pfr_att'])} carries; league {fmt.dec(lg.get('ybc_att'))}).")
    else:
        out.append(f"{team} has {fmt.att(r['att'])} in {r['games']} game{'s' if r['games'] != 1 else ''}: {fmt.dec(r['ypc'])} yards and {fmt.epa(r['epa'])} EPA per run ({rk('epa')}; league {fmt.epa(lg['epa'])}).")
        out.append(f"Success rate {fmt.pct(r['sr'])} ({rk('sr')}); explosive rate {fmt.pct(r['expl'])} ({rk('expl')}); stuff rate {fmt.pct(r['stuff'])} ({rk('stuff')}).")
        if r.get("ybc_att") is not None:
            out.append(f"Non-QB rushers gain {fmt.dec(r['ybc_att'])} yards before contact ({rk('ybc_att')}) and {fmt.dec(r['yac_att'])} after contact ({rk('yac_att')}) per carry, over {int(r['pfr_att'])} carries.")
        if r.get("qb_att"):
            out.append(f"{r['qb_att']} of the {r['att']} designed runs ({fmt.pct(r['qb_att'] / r['att'])}) {'was a QB run' if r['qb_att'] == 1 else 'were QB runs'}.")
    return out[:4]


# ------------------------------------------------------------------------------------------------
# Direction / gap / box splits
# ------------------------------------------------------------------------------------------------

def split_table(w: LeagueWindow, team: str, unit: str, key: str, id_: str, title: str) -> dict | None:
    tname = f"{'off' if unit == 'offense' else 'def'}_{key}"
    if tname not in w.tables:
        return None
    buckets, word = SPLITS[key]
    lg = w.league.get(key, {})
    share_title = "Share of the team's designed runs" if unit == "offense" else "Share of opponents' designed runs faced"
    cols = [col("share", "Share", "pct", title=share_title), col("lg_share", "Lg share", "pct", title="League-wide share"), col("att", "Att", "int")] + eff_cols(unit)
    keys = [c["key"] for c in cols]
    recs = {r["bucket"]: r for r in w.rows(tname, team=team)}
    rows = []
    for b, label in buckets:
        r = dict(recs.get(b) or {})
        r["lg_share"] = (lg.get(b) or {}).get("share")
        rows.append(mk_row(r, keys, label, key=b))
    notes = []
    unc = w.uncharted.get(tname, {}).get(team, 0)
    if unc:
        what = {"direction": "no run direction charted", "gap": "no gap charted (side runs without end/tackle/guard)", "box": "no FTN box count"}[key]
        notes.append(f"{unc} designed run{'s' if unc != 1 else ''} with {what} {'are' if unc != 1 else 'is'} left out of this table; shares are of the rest.")
    if key == "box":
        notes.append("Box counts are FTN charting (n_defense_box, via nflverse). nflverse participation data (defenders_in_box) is not published for this season.")
    min_att = next(iter(recs.values()), {}).get("min_att")
    peer = f"peer group per {word}: {unit_word(unit)} with {w.bucket_rule}" + (f" (≥ {min_att} here)" if w.is_current and min_att else "") + ". n shown with each rank."
    return table(id_, title, w, cols, rows, peer, split_takeaways(team, unit, key, rows, w), notes=notes,
                 checks={"shares_sum_to_one": "share"}, unit=unit)


def split_takeaways(team: str, unit: str, key: str, rows: list[dict], w: LeagueWindow) -> list[str]:
    used = [r for r in rows if r["cells"]["att"]]
    if not used:
        return [f"No charted designed runs for {team} in this window."]
    out = []
    word = SPLITS[key][1]
    if key == "box":
        heavy = next((r for r in rows if r["key"] == "heavy"), None)
        if heavy:
            c = heavy["cells"]
            who = f"{team} faced 8+ defenders in the box on" if unit == "offense" else f"{team} put 8+ defenders in the box on"
            line = f"{who} {fmt.pct(c['share'])} of designed runs (n={c['att']}; league {fmt.pct(c['lg_share'])})."
            if c["att"]:
                line = line[:-1] + f", {fmt.epa(c['epa'])} EPA/run {'there' if unit == 'offense' else 'allowed there'}."
            out.append(line)
    else:
        top = max(used, key=lambda r: r["cells"]["share"] or 0)
        c = top["cells"]
        if unit == "offense":
            out.append(f"{team}'s most-used {word}: {top['label']}, {fmt.pct(c['share'])} of designed runs (n={c['att']}; league {fmt.pct(c['lg_share'])}).")
        else:
            out.append(f"Opponents' most-used {word} against {team}: {top['label']}, {fmt.pct(c['share'])} of runs faced (n={c['att']}; league {fmt.pct(c['lg_share'])}).")
    ranked = [r for r in rows if "epa" in r["ranks"]]
    if ranked:
        # Highest / lowest EPA among the team's ranked buckets (by value; the rank shows how it compares to the league).
        hi = max(ranked, key=lambda r: r["cells"]["epa"])
        lo = min(ranked, key=lambda r: r["cells"]["epa"])
        rk = lambda r: fmt.rank(*r["ranks"]["epa"])  # noqa: E731
        verb = "EPA/run" if unit == "offense" else "EPA/run allowed"
        out.append(f"Highest {verb} among ranked {word} buckets: {hi['label']}, {fmt.epa(hi['cells']['epa'])} ({rk(hi)}, n={hi['cells']['att']}).")
        if lo is not hi:
            out.append(f"Lowest: {lo['label']}, {fmt.epa(lo['cells']['epa'])} ({rk(lo)}, n={lo['cells']['att']}).")
    unranked = [r for r in used if "epa" not in r["ranks"]]
    if unranked:
        out.append(f"{len(unranked)} {word} bucket{'s' if len(unranked) != 1 else ''} with runs {'are' if len(unranked) != 1 else 'is'} below the rank qualifier ({w.bucket_rule}), so no rank is shown.")
    return out[:4]


# ------------------------------------------------------------------------------------------------
# Overlap: offense's most-used gaps vs the defense's results in the same gaps
# ------------------------------------------------------------------------------------------------

def overlap_section(w: LeagueWindow, off: str, dfn: str) -> dict:
    return {
        "id": "overlap",
        "title": "3 · Overlap",
        "subtitle": f"Where {off} runs, and how {dfn} has fared in those same spots",
        "tables": [overlap_table(w, off, dfn, "direction"), overlap_table(w, off, dfn, "gap")],
    }


def overlap_table(w: LeagueWindow, off: str, dfn: str, key: str) -> dict:
    buckets, word = SPLITS[key]
    o = {r["bucket"]: r for r in w.rows(f"off_{key}", team=off)}
    d = {r["bucket"]: r for r in w.rows(f"def_{key}", team=dfn)}
    cols = [
        col("o_share", f"{off} share", "pct", title=f"Share of {off}'s designed runs"),
        col("o_att", f"{off} att", "int"),
        col("o_epa", f"{off} EPA", "epa", rank=True, title=f"{off} EPA per designed run here (rank among offenses)"),
        col("o_sr", f"{off} Succ.", "pct", rank=True),
        col("d_att", f"{dfn} faced", "int", title=f"Designed runs {dfn} has faced here"),
        col("d_epa", f"{dfn} EPA al.", "epa", rank=True, title=f"EPA per run {dfn} allows here (rank among defenses; 1 = stingiest)"),
        col("d_sr", f"{dfn} Succ. al.", "pct", rank=True),
        col("edge", "Edge", "edge", title="Offense EPA percentile minus defense EPA-allowed percentile (both 0 = worst, 1 = best). Positive favours the offense. Blank when either side is unranked."),
    ]
    rows = []
    for b, label in buckets:
        orr, drr = o.get(b) or {}, d.get(b) or {}
        rec = {
            "o_share": orr.get("share"), "o_att": orr.get("att", 0), "o_epa": orr.get("epa"), "o_sr": orr.get("sr"),
            "d_att": drr.get("att", 0), "d_epa": drr.get("epa"), "d_sr": drr.get("sr"),
            "o_epa_rank": orr.get("epa_rank"), "o_epa_n": orr.get("epa_n"), "o_sr_rank": orr.get("sr_rank"), "o_sr_n": orr.get("sr_n"),
            "d_epa_rank": drr.get("epa_rank"), "d_epa_n": drr.get("epa_n"), "d_sr_rank": drr.get("sr_rank"), "d_sr_n": drr.get("sr_n"),
        }
        # Edge: offense EPA percentile minus defense EPA-allowed percentile, each within its own ranked table.
        po, pd_ = pct_from_rank(rec["o_epa_rank"], rec["o_epa_n"]), pct_from_rank(rec["d_epa_rank"], rec["d_epa_n"])
        rec["edge"] = None if po is None or pd_ is None else round(po - pd_, 2)
        rows.append(mk_row(rec, [c["key"] for c in cols], label, key=b))
    rows.sort(key=lambda r: -(r["cells"]["o_share"] or 0))

    most = [r for r in rows if (r["cells"]["o_share"] or 0) >= OVERLAP["min_share"]]
    bullets = []
    if not any(r["cells"]["o_att"] for r in rows):
        bullets.append(f"{off} has no charted designed runs in this window.")
    else:
        bullets.append(f"{off}'s most-used {word} buckets (≥ {fmt.pct(OVERLAP['min_share'])} of designed runs): " + ", ".join(f"{r['label']} {fmt.pct(r['cells']['o_share'])} (n={r['cells']['o_att']})" for r in most) + ".")
        with_edge = [r for r in most if r["cells"]["edge"] is not None]
        fav = max(with_edge, key=lambda r: r["cells"]["edge"], default=None)
        unf = min(with_edge, key=lambda r: r["cells"]["edge"], default=None)

        def detail(r):
            c, rk = r["cells"], r["ranks"]
            return (f"{off} runs there on {fmt.pct(c['o_share'])} of designed runs for {fmt.epa(c['o_epa'])} EPA/run ({fmt.rank(*rk['o_epa'])}, n={c['o_att']}); "
                    f"{dfn} allows {fmt.epa(c['d_epa'])} EPA/run there ({fmt.rank(*rk['d_epa'])}, n={c['d_att']}).")

        if fav and fav["cells"]["edge"] >= OVERLAP["min_edge"]:
            fav["flag"] = "offense"
            bullets.append(f"Largest {off} edge, {fav['label']}: " + detail(fav))
        if unf and unf["cells"]["edge"] <= -OVERLAP["min_edge"]:
            unf["flag"] = "defense"
            bullets.append(f"Largest {dfn} edge, {unf['label']}: " + detail(unf))
        if not any(r.get("flag") for r in rows):
            bullets.append(f"No {word} bucket among {off}'s most-used has an edge of {OVERLAP['min_edge']:.2f} or more either way with both sides ranked.")
        unr = [r["label"] for r in most if r["cells"]["edge"] is None]
        if unr:
            bullets.append(f"Not compared (one side below the rank qualifier): {', '.join(unr)}.")
    return table(f"overlap_{key}", f"{off} {word} usage vs {dfn} {word} results", w, cols, rows,
                 f"ranks carried over from the {word} tables above: offenses / defenses with {w.bucket_rule}. Edge compares EPA percentiles.",
                 bullets[:4], notes=["Rows sorted by how often the offense runs there. Flagged rows: largest mismatch each way."], unit="matchup")


# ------------------------------------------------------------------------------------------------
# Rushers
# ------------------------------------------------------------------------------------------------

RUSHER_KEYS = ["att", "carry_share", "snap_share", "ypc", "epa", "sr", "expl", "stuff", "ybc_att", "yac_att", "pfr_att"]


def rusher_cols(current: bool) -> list[dict]:
    c = [col("depth", "Depth", "text", title="Current RB depth chart slot")] if current else [col("teams", "Team", "text")]
    c += [col("games_played" if current else "games_with_carry", "G", "int", title="Games with an offensive snap" if current else "Games with a designed run"), col("att", "Att", "int")]
    if current:
        c += [col("carry_share", "Carry %", "pct", title="Share of the team's designed runs"), col("snap_share", "Snap %", "pct", title="Share of the team's offensive snaps (nflverse snap counts)")]
    c += eff_cols("offense") + [
        col("ybc_att", "YBC/att", "dec1", rank=True, title="Yards before contact per carry (PFR, all carries)"),
        col("yac_att", "YAC/att", "dec1", rank=True, title="Yards after contact per carry (PFR, all carries)"),
        col("pfr_att", "PFR car.", "int", title="Carries behind YBC / YAC"),
    ]
    return c


def rusher_section(cur: LeagueWindow, prior: LeagueWindow, team: str, depth: list[dict]) -> tuple[dict, list[dict]]:
    """Section 4 (current) and the prior-season rusher table. Returns (section, prior_rusher_table_players)."""
    cols = rusher_cols(True)
    keys = [c["key"] for c in cols]
    recs = {r["rusher_player_id"]: r for r in cur.rows("rushers", posteam=team)} if "rushers" in cur.tables else {}
    rows, players = [], []
    for d in depth:
        r = dict(recs.get(d["gsis_id"]) or {"att": 0, "carry_share": 0.0})
        r["depth"] = f"RB{d['pos_rank']}"
        rows.append(mk_row(r, keys, d["name"], key=d["gsis_id"]))
        players.append({"id": d["gsis_id"], "name": d["name"]})
    listed = {d["gsis_id"] for d in depth}
    others = sorted([r for r in recs.values() if r["rusher_player_id"] not in listed and not r["is_qb"] and r["att"]], key=lambda r: -r["att"])
    for r in others:
        r = dict(r)
        r["depth"] = r.get("pos") or "—"
        rows.append(mk_row(r, keys, r["name"], key=r["rusher_player_id"], sub="not on the current RB depth chart"))
        players.append({"id": r["rusher_player_id"], "name": r["name"]})

    qb = cur.runs.filter(pl.col("posteam") == team, pl.col("is_qb_run"))
    team_rec = cur.row("off", team=team) if "off" in cur.tables else None
    team_att = (team_rec or {}).get("att") or 0
    if qb.height:
        q = qb.select(agg_exprs()).to_dicts()[0]
        q["carry_share"] = q["att"] / team_att if team_att else None
        q["depth"] = "QB"
        sneaks = int(qb["is_qb_sneak"].sum())
        names = ", ".join(qb["rusher_name"].unique().sort().to_list())
        rows.append(mk_row(q, keys, "Designed QB runs", key="qb", kind="qb", ranked=False,
                           sub=f"{names}; {sneaks} QB sneak{'s' if sneaks != 1 else ''} (FTN). Not ranked; PFR YBC/YAC not shown for QBs (includes scrambles)."))
    if team_rec:
        t = dict(team_rec)
        t["carry_share"] = 1.0
        t["depth"] = ""
        for k in ["ybc_att", "yac_att", "pfr_att"]:
            t[k] = team_rec.get(k)
        rows.append(mk_row(t, keys, f"{team} total", key="total", kind="total", ranked=False, sub="all designed runs; YBC/YAC non-QB"))

    qual = recs and next(iter(recs.values())).get("min_att")
    n_peer = next((r["epa_n"] for r in cur.rows("rushers") if r.get("epa_n")), 0) if "rushers" in cur.tables else 0
    peer = f"peer group: {n_peer} {cur.rusher_rule}" + (f" (≥ {qual} here)" if qual else "") + ". Rank 1 = best."
    t1 = table("rushers", f"{team} rushers: volume and efficiency", cur, cols, rows, peer, rusher_takeaways(team, rows, qual),
               notes=["RBs listed in current depth-chart order (nflverse depth charts). Other players with designed runs for this team follow."],
               checks={"rows_sum_to_total": "att"}, unit="offense")

    # Direction splits per rusher (not ranked).
    dcols = [col("att", "Att", "int"), col("share", "Share", "pct", title="Share of this rusher's designed runs with a charted direction")] + [
        col(k, lbl, f, title=EFF_TITLES["offense"][k]) for k, lbl, f in EFF[:3]
    ]
    drows = []
    rd = cur.tables.get("rusher_dir")
    for r in rows:
        if r["kind"] != "row" or not r["cells"]["att"] or rd is None:
            continue
        sub = rd.filter(pl.col("rusher_player_id") == r["key"], pl.col("posteam") == team)
        tot = sub["att"].sum()
        by = {x["direction"]: x for x in sub.to_dicts()}
        for dkey, dlabel in DIRECTIONS:
            x = dict(by.get(dkey) or {"att": 0})
            x["share"] = x["att"] / tot if tot else None
            drows.append(mk_row(x, [c["key"] for c in dcols], dlabel, key=f"{r['key']}:{dkey}", group=r["label"], ranked=False))
    t2 = table("rusher_directions", f"{team} rushers by direction", cur, dcols, drows,
               "not ranked: per-rusher direction samples are too small to rank.", rusher_dir_takeaways(drows),
               notes=["Direction is from the offense's point of view."], checks={"shares_sum_to_one_by_group": "share"}, unit="offense")
    return {"id": "rushers", "title": "4 · Rusher splits", "subtitle": f"{team} backs: volume, efficiency, blocking vs running (YBC vs YAC), direction", "tables": [t1, t2]}, players


def rusher_takeaways(team: str, rows: list[dict], qual) -> list[str]:
    backs = [r for r in rows if r["kind"] == "row" and r["cells"]["att"]]
    out = []
    if not backs:
        return [f"No {team} non-QB rusher has a designed run in this window."]
    lead = max(backs, key=lambda r: r["cells"]["att"])
    c = lead["cells"]
    snap = f" and {fmt.pct(c['snap_share'])} of offensive snaps" if c.get("snap_share") is not None else ""
    out.append(f"{lead['label']} has {fmt.pct(c['carry_share'])} of {team}'s designed runs ({c['att']}){snap}.")
    for r in sorted(backs, key=lambda r: -r["cells"]["att"])[:2]:
        c = r["cells"]
        if c.get("ybc_att") is not None and c.get("yac_att") is not None and (c["ybc_att"] + c["yac_att"]) > 0:
            share_after = c["yac_att"] / (c["ybc_att"] + c["yac_att"])
            out.append(f"{r['label']}: {fmt.dec(c['ybc_att'])} yards before contact and {fmt.dec(c['yac_att'])} after contact per carry; {fmt.pct(share_after)} of his yards came after contact ({int(c['pfr_att'])} carries).")
    ranked = [r for r in backs if "epa" in r["ranks"]]
    if ranked:
        b = min(ranked, key=lambda r: r["ranks"]["epa"][0])
        out.append(f"Best EPA/run among {team} rushers who qualify: {b['label']}, {fmt.epa(b['cells']['epa'])} ({fmt.rank(*b['ranks']['epa'])}).")
    else:
        out.append(f"No {team} rusher meets the rank qualifier yet ({qual} designed runs), so rusher ranks are blank.")
    qb = next((r for r in rows if r["kind"] == "qb"), None)
    if qb and len(out) < 4:
        out.append(f"Designed QB runs: {qb['cells']['att']} ({fmt.pct(qb['cells']['carry_share'])} of designed runs), {fmt.epa(qb['cells']['epa'])} EPA/run.")
    return out[:4]


def rusher_dir_takeaways(drows: list[dict]) -> list[str]:
    out = []
    groups = []
    for r in drows:
        if r["group"] not in groups:
            groups.append(r["group"])
    for g in groups[:3]:
        rs = [r for r in drows if r["group"] == g]
        tot = sum(r["cells"]["att"] for r in rs)
        if not tot:
            continue
        parts = ", ".join(f"{fmt.pct(r['cells']['share'])} {r['label'].lower()}" for r in rs)
        out.append(f"{g} (n={tot}): {parts}.")
    return out or ["No rusher has a charted designed run in this window."]


# ------------------------------------------------------------------------------------------------
# Prior season
# ------------------------------------------------------------------------------------------------

def prior_section(prior: LeagueWindow, off: str, dfn: str, players: list[dict]) -> dict:
    tables = [
        overall_table(prior, off, "offense", "prior_off", f"{off} rushing offense, {prior.season}"),
        overall_table(prior, dfn, "defense", "prior_def", f"{dfn} run defense, {prior.season}"),
        split_table(prior, off, "offense", "gap", "prior_off_gap", f"{off} by gap, {prior.season}"),
        split_table(prior, dfn, "defense", "gap", "prior_def_gap", f"{dfn} by gap allowed, {prior.season}"),
    ]
    cols = rusher_cols(False)
    keys = [c["key"] for c in cols]
    recs = {r["rusher_player_id"]: r for r in prior.rows("rushers")}
    rows = []
    for p in players:
        r = recs.get(p["id"])
        rows.append(mk_row(r, keys, p["name"], key=p["id"], sub=None if r else f"no designed runs in {prior.season}"))
    qual = next((r["min_att"] for r in recs.values() if r.get("min_att")), None)
    n_peer = next((r["epa_n"] for r in recs.values() if r.get("epa_n")), 0)
    tk = []
    for r in rows:
        if r["cells"]["att"] and len(tk) < 3:
            rk = fmt.rank(*r["ranks"]["epa"]) if "epa" in r["ranks"] else f"unranked, below {qual}"
            tk.append(f"{r['label']} ({r['cells']['teams']}) in {prior.season}: {r['cells']['att']} designed runs, {fmt.dec(r['cells']['ypc'])} YPC, {fmt.epa(r['cells']['epa'])} EPA/run ({rk}).")
    tk.append(f"{prior.season} is last season; roster, scheme and coaching changes since then are not reflected.")
    tables.append(table("prior_rushers", f"{off} current rushers, {prior.season}", prior, cols, rows,
                        f"peer group: {n_peer} {prior.rusher_rule} (≥ {qual} in {prior.season}).", tk[:4],
                        notes=[f"Each player's full {prior.season} line, whichever team he played for."], unit="offense"))
    for t in tables:
        if t:
            t["takeaways"] = t["takeaways"][:3] + [f"{prior.season} full regular season; not combined with {prior.season + 1} numbers."]
    return {"id": "prior", "title": f"5 · Prior season ({prior.season})", "subtitle": f"Last season's key numbers, shown separately from {prior.season + 1}", "tables": [t for t in tables if t]}


# ------------------------------------------------------------------------------------------------
# Whole game
# ------------------------------------------------------------------------------------------------

def side(cur: LeagueWindow, prior: LeagueWindow, off: str, dfn: str, depth: list[dict], week: int) -> dict:
    if not cur.weeks:
        empty = f"No {cur.season} regular-season games were played before Week {week}. Only prior-season context is available."
        sections = [{"id": s, "title": t, "empty": empty} for s, t in [("defense", "1 · Defense run map"), ("offense", "2 · Offense run tendency"), ("overlap", "3 · Overlap"), ("rushers", "4 · Rusher splits")]]
        players = [{"id": d["gsis_id"], "name": d["name"]} for d in depth]
    else:
        sections = [
            {"id": "defense", "title": "1 · Defense run map", "subtitle": f"What {dfn} allows on designed runs, overall and by where the run goes",
             "tables": [t for t in [
                 overall_table(cur, dfn, "defense", "def_overall", f"{dfn} run defense"),
                 split_table(cur, dfn, "defense", "direction", "def_direction", f"{dfn} by direction"),
                 split_table(cur, dfn, "defense", "gap", "def_gap", f"{dfn} by gap"),
                 split_table(cur, dfn, "defense", "box", "def_box", f"{dfn} by box count"),
             ] if t]},
            {"id": "offense", "title": "2 · Offense run tendency", "subtitle": f"Where {off} runs and how well",
             "tables": [t for t in [
                 overall_table(cur, off, "offense", "off_overall", f"{off} rushing offense"),
                 split_table(cur, off, "offense", "direction", "off_direction", f"{off} by direction"),
                 split_table(cur, off, "offense", "gap", "off_gap", f"{off} by gap"),
                 split_table(cur, off, "offense", "box", "off_box", f"{off} by box count"),
             ] if t]},
            overlap_section(cur, off, dfn),
        ]
        rs, players = rusher_section(cur, prior, off, depth)
        sections.append(rs)
    sections.append(prior_section(prior, off, dfn, players))
    for s in sections:
        s["group"] = "run"
    return {"offense": off, "defense": dfn, "title": f"{off} run game vs {dfn} run defense", "sections": sections}


def game_report(game: dict, week: int, cur: LeagueWindow, prior: LeagueWindow, depth: dict[str, list[dict]], checks: list[str]) -> dict:
    away, home = game["away_team"], game["home_team"]
    notes = [
        "Left / middle / right and end / tackle / guard are from the OFFENSE's point of view, in every table, including the defense tables.",
        f"Small samples are noisy: after {len(cur.weeks)} week{'s' if len(cur.weeks) != 1 else ''}, a team has only a few dozen designed runs and a single long run moves the averages. Check the attempt counts next to each figure." if cur.weeks else "",
        f"Current-season numbers use only games played before Week {week} ({fmt.weeks_label(cur.weeks)}).",
        "Box counts: FTN charting via nflverse (n_defense_box). nflverse participation data (defenders_in_box, offense_formation) is not published for the current season. Box counts of 0 are treated as not charted.",
        "YBC / YAC: Pro Football Reference via nflverse, per player per game. They include every carry (PFR does not split out designed runs), so team figures use non-QB rushers only.",
        f"Excluded from {cur.season} {fmt.weeks_label(cur.weeks)}: {cur.removed['scrambles']} scrambles, {cur.removed['kneels']} kneels, {cur.removed['aborted']} aborted snaps, {cur.removed['two_point']} two-point tries." if cur.weeks else "",
    ]
    return {
        "schema": SCHEMA_VERSION,
        "game_id": game["game_id"],
        "season": cur.season,
        "week": week,
        "away": away,
        "home": home,
        "gameday": game["gameday"],
        "gametime": game["gametime"],
        "stadium": game.get("stadium"),
        "roof": game.get("roof"),
        "data_as_of": cur.data_as_of,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "window": {"current": {"season": cur.season, "weeks": cur.weeks}, "prior": {"season": prior.season, "weeks": prior.weeks}},
        "sides": [side(cur, prior, away, home, depth.get(away, []), week), side(cur, prior, home, away, depth.get(home, []), week)],
        "notes": [n for n in notes if n],
        "filters": FILTERS,
        "qualifiers": {
            "teams": f"All teams with at least {QUALIFIERS['team_min_games']} game in the window are ranked.",
            "rushers": f"{QUALIFIERS['rusher_att_per_team_game']:g} designed runs per team game, non-QB (the NFL rushing-title standard).",
            "buckets_current": f"{QUALIFIERS['bucket_att_per_team_game']:g} designed runs per team game in the bucket.",
            "buckets_prior": f"{QUALIFIERS['bucket_min_att_prior']} designed runs in the bucket over the full prior season.",
            "overlap": f"Most-used gap = at least {fmt.pct(OVERLAP['min_share'])} of the offense's designed runs; mismatch = EPA percentile gap of at least {OVERLAP['min_edge']:.2f}.",
        },
        "sources": [
            "nflverse play-by-play (nflreadpy load_pbp)",
            "nflverse schedules, weekly rosters, depth charts, snap counts",
            "Pro Football Reference advanced rushing via nflverse (load_pfr_advstats, stat_type='rush')",
            "FTN charting via nflverse (load_ftn_charting): box counts and QB sneaks",
        ],
        "checks": checks,
    }
