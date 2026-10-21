"""
Data Suite exports: run-scheme (blocking concept) splits, which nflverse doesn't chart.

Files live in imports/datasuite/<kind>/<export date>.csv (added with pipeline/import_datasuite.py).
  rushing/      player rushing export: each RB's Zone Concept vs Man/Gap Concept carries, YPC, success %.
  run_defense/  (not yet supplied) the same splits allowed by each defense.

Each export is a snapshot of every game played before it was exported. A week's report only uses an
export that covers every game in that report's window (otherwise the numbers would be stale); among
those it takes the earliest, so it includes as few later games as possible, and it says which.
"""

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from .config import APP_ROOT, QUALIFIERS

IMPORT_DIR = APP_ROOT / "imports" / "datasuite"
EXPORT_RE = re.compile(r"Exported from Data Suite.*? on (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC")
SCHEMES = [("zone", "Zone runs", "Zone Concept", "ZONE"), ("gap", "Man/gap runs", "Man/Gap Concept", "MAN")]
# A game counts as covered by an export once it kicked off at least this long before the export.
GAME_LENGTH = timedelta(hours=4)
DEF_STATUS = "Defense side needs a Data Suite run-defense export (zone vs man/gap concept splits allowed by each defense)."
ET = ZoneInfo("America/New_York")


class DataSuiteError(Exception):
    pass


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError as e:
        raise DataSuiteError(f"not a number: {s!r}") from e


def read_export(path: Path) -> tuple[list[dict], dict | None, datetime, list[str]]:
    """(player rows, league-average row, export time). Columns are keyed "Group|Header" because
    Data Suite repeats header names across groups."""
    rows = list(csv.reader(path.open(newline="", encoding="utf-8-sig")))
    if len(rows) < 3:
        raise DataSuiteError(f"{path.name}: too few rows to be a Data Suite export")
    footer = next((m for r in rows for m in [EXPORT_RE.search(r[0] if r else "")] if m), None)
    if not footer:
        raise DataSuiteError(f"{path.name}: no 'Exported from Data Suite ... on YYYY-MM-DD HH:MM UTC' footer line")
    exported = datetime.strptime(footer.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    keys = [f"{g.strip()}|{h.strip()}" for g, h in zip(rows[0], rows[1])]
    players, league = [], None
    for r in rows[2:]:
        if not r or not r[0].strip().isdigit():  # blank lines and the footer
            continue
        d = dict(zip(keys, r))
        # "Player Details|Name" in player exports, "Team Details|Name" in team exports.
        name = next((v for k, v in d.items() if k.endswith("|Name")), "").strip()
        rank = next((v for k, v in d.items() if k.endswith("|Rank")), "").strip()
        if name == "League Avg" or not rank:
            league = d
        else:
            players.append(d)
    return players, league, exported, keys


def _need(d: dict, key: str, path: Path):
    if key not in d:
        raise DataSuiteError(f"{path.name}: missing column {key.replace('|', ' › ')}. Is this the Data Suite rushing export?")
    return d[key]


def parse_rushing(path: Path) -> tuple[pl.DataFrame, dict, datetime]:
    """One row per RB with his zone and man/gap splits (shares and success as fractions)."""
    players, league, exported, keys = read_export(path)
    # Check the header first, so a wrong file names the missing column rather than failing row by row.
    required = ["Player Details|Name", "Player Details|Team", "Player Details|POS", "Player Details|G", "Rushing|ATT", "|player_id"] + [
        f"{group}|{prefix} {c}" for _k, _l, group, prefix in SCHEMES for c in ("ATT", "ATT %", "YPC", "SUCC %")]
    missing = [k for k in required if k not in keys]
    if missing:
        raise DataSuiteError(f"{path.name}: missing column {missing[0].replace('|', ' › ').strip(' ›')}"
                             f"{f' (and {len(missing) - 1} more)' if len(missing) > 1 else ''}. Is this the Data Suite rushing export?")
    out = []
    for d in players:
        if _need(d, "Player Details|POS", path).strip() != "RB":
            continue
        pid = _need(d, "|player_id", path).strip()
        if not pid:
            raise DataSuiteError(f"{path.name}: {d.get('Player Details|Name')} has no player_id")
        rec = {"player_id": pid, "name": d["Player Details|Name"].strip(), "team": d["Player Details|Team"].strip(),
               "games": _num(_need(d, "Player Details|G", path)), "att": _num(_need(d, "Rushing|ATT", path))}
        for key, _label, group, prefix in SCHEMES:
            rec[f"{key}_att"] = _num(_need(d, f"{group}|{prefix} ATT", path)) or 0
            rec[f"{key}_share"] = (_num(_need(d, f"{group}|{prefix} ATT %", path)) or 0) / 100
            rec[f"{key}_ypc"] = _num(_need(d, f"{group}|{prefix} YPC", path))
            sr = _num(_need(d, f"{group}|{prefix} SUCC %", path))
            rec[f"{key}_sr"] = None if sr is None else sr / 100
        if rec["zone_att"] + rec["gap_att"] > (rec["att"] or 0) + 0.5:
            raise DataSuiteError(f"{path.name}: {rec['name']} has more zone + man/gap carries than carries")
        out.append(rec)
    if not out:
        raise DataSuiteError(f"{path.name}: no RB rows found")
    lg = {}
    if league:
        for key, _label, group, prefix in SCHEMES:
            sr = _num(league.get(f"{group}|{prefix} SUCC %", ""))
            lg[key] = {"sr": None if sr is None else sr / 100, "ypc": _num(league.get(f"{group}|{prefix} YPC", ""))}
    df = pl.DataFrame(out)
    # Rank within each scheme among RBs with enough carries of that type: the same per-game bar as
    # the RB's own direction splits, applied to his games played.
    per_game = QUALIFIERS["rusher_bucket_att_per_team_game"]
    for key, *_ in SCHEMES:
        ok = pl.col(f"{key}_att") >= (pl.col("games") * per_game - 1e-9).ceil()
        for m in ("sr", "ypc"):
            col = f"{key}_{m}"
            df = df.with_columns(
                pl.when(ok & pl.col(col).is_not_null()).then(-pl.col(col)).rank("min").cast(pl.Int32).alias(f"{col}_rank"),
                pl.when(ok & pl.col(col).is_not_null()).then((ok & pl.col(col).is_not_null()).sum()).cast(pl.Int32).alias(f"{col}_n"),
            )
    return df, lg, exported


def kickoff_utc(gameday: str, gametime: str | None) -> datetime:
    h, m = (int(x) for x in (gametime or "13:00").split(":"))
    y, mo, d = (int(x) for x in gameday.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=ET).astimezone(timezone.utc)


def covered_games(schedule: pl.DataFrame, exported: datetime) -> set[str]:
    g = schedule.filter(pl.col("game_type") == "REG", pl.col("result").is_not_null())
    return {r["game_id"] for r in g.iter_rows(named=True) if kickoff_utc(r["gameday"], r["gametime"]) + GAME_LENGTH <= exported}


def exports(kind: str) -> list[Path]:
    d = IMPORT_DIR / kind
    return sorted(d.glob("*.csv")) if d.exists() else []


def pick_rushing_export(schedule: pl.DataFrame, window_games: set[str], week: int | None = None) -> dict:
    """The earliest rushing export that covers every game in the window, or a status explaining why none fits.
    Games beyond the window are allowed only while the report's week is still being played and only from
    that week (its Thursday game, when the export was taken before Sunday); never for a finished week."""
    files = exports("rushing")
    if not files:
        return {"status": "No Data Suite rushing export has been added yet."}
    newest = None
    for f in files:  # file names are export timestamps, so this is oldest first
        df, lg, exported = parse_rushing(f)
        cov = covered_games(schedule, exported)
        newest = (exported, cov)
        if window_games <= cov:
            extra = sorted(cov - window_games)
            if extra and week is not None:
                # Extra games are tolerated only while this week is still being played (an export taken
                # after its Thursday game, before Sunday). A finished week would include its own games.
                wk = schedule.filter(pl.col("week") == week)
                in_progress = wk.height > 0 and wk["result"].is_null().any()
                later = schedule.filter(pl.col("game_id").is_in(extra), pl.col("week") != week).height
                if not in_progress or later:
                    return {"status": f"The Data Suite exports that cover this report's weeks also include {len(extra)} game{'s' if len(extra) != 1 else ''} "
                                      "played after them, so run-scheme splits aren't shown for this week."}
            return {"file": f, "df": df, "league": lg, "exported": exported, "extra": extra}
    missing = len(window_games - newest[1])
    return {"status": f"The newest Data Suite rushing export ({newest[0]:%b %d %H:%M} UTC) is missing {missing} game{'s' if missing != 1 else ''} "
                      "from this report's weeks. Add a newer export to show run-scheme splits."}


def _r4(v):
    return None if v is None else round(v, 4)  # same rounding as the rest of the JSON


def _scheme_off(rec: dict | None, key: str) -> dict:
    rec = rec or {}
    off = {"att": int(rec.get(f"{key}_att") or 0), "share": _r4(rec.get(f"{key}_share")),
           "ypc": _r4(rec.get(f"{key}_ypc")), "sr": _r4(rec.get(f"{key}_sr")), "ranks": {}}
    for m in ("sr", "ypc"):
        if rec.get(f"{key}_{m}_rank") is not None:
            off["ranks"][m] = [int(rec[f"{key}_{m}_rank"]), int(rec[f"{key}_{m}_n"])]
    return off


def _scheme_rec(pick: dict, pid: str | None) -> dict | None:
    if "df" not in pick or not pid:
        return None
    hit = pick["df"].filter(pl.col("player_id") == pid)
    return hit.to_dicts()[0] if hit.height else None


def scheme_player(pick: dict, pid: str) -> dict | None:
    """One RB's zone / man-gap splits for the player page: {zone: {...}, gap: {...}}, or None if he isn't in the export."""
    rec = _scheme_rec(pick, pid)
    return {key: _scheme_off(rec, key) for key, *_ in SCHEMES} if rec else None


def scheme_block(pick: dict, starter: dict | None) -> dict:
    """The starting RB's zone vs man/gap splits for one row (current season only)."""
    if "df" not in pick:
        return {"status": pick["status"], "rows": []}
    rec = _scheme_rec(pick, starter["id"] if starter else None)
    rows = [{"key": key, "label": label, "off": _scheme_off(rec, key), "def": None, "edge": None,
             "league": {k: _r4(v) for k, v in (pick["league"].get(key) or {}).items()}} for key, label, *_ in SCHEMES]
    return {
        "status": None if rec else f"{starter['name'] if starter else 'This RB'} isn't in the Data Suite rushing export.",
        "source": "Data Suite",
        "exported_at": pick["exported"].strftime("%Y-%m-%dT%H:%MZ"),
        "extra_games": pick["extra"],
        "def_status": DEF_STATUS,
        "rows": rows,
    }


def extra_note(pick: dict, schedule: pl.DataFrame) -> str | None:
    if "df" not in pick or not pick["extra"]:
        return None
    g = schedule.filter(pl.col("game_id").is_in(pick["extra"]))
    games = ", ".join(f"{r['away_team']} @ {r['home_team']}" for r in g.iter_rows(named=True))
    return (f"The Data Suite export ({pick['exported']:%b %d} UTC) also includes {games}, played after this report's weeks; "
            "those teams' backs have one more game in their run-scheme splits.")


def qualifier_note() -> str:
    return f"Run-scheme ranks: RBs with at least {QUALIFIERS['rusher_bucket_att_per_team_game']:g} carries of that type per game played."


# ------------------------------------------------------------------------------------------------
# Team defense export: run-defense context per defense (display only; not part of the Run Edge).

TEAM_MAP = Path(__file__).with_name("team_map.csv")
# key -> (Data Suite column, label, rank direction: True = lower allowed ranks 1st (stingiest), None = unranked)
TEAM_DEF_COLS = [
    ("rb_fpg", "Fantasy|RB FPG", "RB fantasy points allowed per game", True),
    ("rush_sr", "Success|RUSH SUCC %", "Rush success allowed", True),
    ("rush_expl", "Explosive|RUSH EXP %", "Explosive rush rate allowed", True),
    ("box", "Tendencies|BOX", "Average defenders in the box", None),
]


def _team_names() -> dict[str, str]:
    with TEAM_MAP.open(newline="", encoding="utf-8") as f:
        return {r["full_name"]: r["nflverse_code"] for r in csv.DictReader(f)}


def parse_team_defense(path: Path) -> dict:
    """{season, exported, teams: {ABBR: {games, rb_fpg, rush_sr, rush_expl, box}}, league: {...}}.
    Rates are fractions. Ranks are among the 32 defenses, 1 = allows the least."""
    rows, league, exported, keys = read_export(path)
    need = ["|Season", "Team Details|Name", "Team Details|G"] + [c for _k, c, _l, _r in TEAM_DEF_COLS]
    missing = [k for k in need if k not in keys]
    if missing:
        raise DataSuiteError(f"{path.name}: missing column {missing[0].replace('|', ' › ').strip(' ›')}. Is this the Data Suite team defense export?")
    names = _team_names()

    def rec(d: dict) -> dict:
        out = {}
        for k, col, _label, _rank in TEAM_DEF_COLS:
            v = _num(d.get(col, ""))
            out[k] = None if v is None else (v / 100 if col.endswith("%") else v)
        return out

    teams, seasons = {}, set()
    for d in rows:
        name = d["Team Details|Name"].strip()
        if name not in names:
            raise DataSuiteError(f"{path.name}: team {name!r} isn't in {TEAM_MAP.name}")
        seasons.add(d["|Season"].strip())
        teams[names[name]] = {"games": int(_num(d["Team Details|G"]) or 0), **rec(d)}
    if len(teams) != 32 or len(seasons) != 1:
        raise DataSuiteError(f"{path.name}: expected 32 teams from one season, found {len(teams)} teams, seasons {sorted(seasons)}")
    for k, _col, _label, low_best in TEAM_DEF_COLS:
        if low_best is None:
            continue
        vals = sorted(t[k] for t in teams.values() if t[k] is not None)
        for t in teams.values():
            if t[k] is not None:
                t[f"{k}_rank"] = [1 + sum(v < t[k] for v in vals), len(vals)]
    return {"season": int(seasons.pop()), "exported": exported, "teams": teams, "league": rec(league) if league else {}}


def pick_team_defense(season: int, team_games: dict[str, int]) -> dict:
    """The earliest team-defense export for `season` whose games per team equal the report window's for
    all 32 teams (team totals can't be trimmed, so an export with extra games is never used)."""
    seen = []
    for f in exports("team_defense"):
        td = parse_team_defense(f)
        if td["season"] != season:
            continue
        seen.append(td)
        if all(td["teams"].get(t, {}).get("games") == g for t, g in team_games.items()) and len(team_games) == 32:
            return {**td, "file": f}
    if not seen:
        return {"status": f"No Data Suite team defense export for {season} has been added yet."}
    last = seen[-1]
    off = sum(last["teams"].get(t, {}).get("games") != g for t, g in team_games.items())
    return {"status": f"The Data Suite team defense exports for {season} don't match this report's games ({off} teams differ in the newest, {last['exported']:%b %d} UTC), so run-defense context isn't shown."}


def team_defense_block(pick: dict, team: str) -> dict | None:
    t = (pick.get("teams") or {}).get(team)
    if not t:
        return None
    out = {k: _r4(t[k]) for k, *_ in TEAM_DEF_COLS}
    out["ranks"] = {k: t[f"{k}_rank"] for k, *_ in TEAM_DEF_COLS if f"{k}_rank" in t}
    return out


def team_defense_meta(pick: dict) -> dict:
    return {
        "status": pick.get("status"),
        "exported_at": pick["exported"].strftime("%Y-%m-%dT%H:%MZ") if "exported" in pick else None,
        "league": {k: _r4(v) for k, v in (pick.get("league") or {}).items()},
        "columns": [{"key": k, "label": label, "ranked": r is not None} for k, _c, label, r in TEAM_DEF_COLS],
    }
