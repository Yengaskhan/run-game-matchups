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
        if d.get("Player Details|Name", "").strip() == "League Avg" or not d.get("Player Details|Rank", "").strip():
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


def scheme_block(pick: dict, starter: dict | None) -> dict:
    """The starting RB's zone vs man/gap splits for one row (current season only)."""
    if "df" not in pick:
        return {"status": pick["status"], "rows": []}
    rec = None
    if starter:
        hit = pick["df"].filter(pl.col("player_id") == starter["id"])
        rec = hit.to_dicts()[0] if hit.height else None
    rows = []
    for key, label, *_ in SCHEMES:
        r4 = lambda v: None if v is None else round(v, 4)  # noqa: E731  (same rounding as the rest of the JSON)
        off = {"att": int((rec or {}).get(f"{key}_att") or 0), "share": r4((rec or {}).get(f"{key}_share")),
               "ypc": r4((rec or {}).get(f"{key}_ypc")), "sr": r4((rec or {}).get(f"{key}_sr")), "ranks": {}}
        for m in ("sr", "ypc"):
            if rec and rec.get(f"{key}_{m}_rank") is not None:
                off["ranks"][m] = [int(rec[f"{key}_{m}_rank"]), int(rec[f"{key}_{m}_n"])]
        rows.append({"key": key, "label": label, "off": off, "def": None, "edge": None,
                     "league": {k: r4(v) for k, v in (pick["league"].get(key) or {}).items()}})
    return {
        "status": None if rec else f"{starter['name'] if starter else 'This RB'} isn't in the Data Suite rushing export.",
        "source": "Data Suite",
        "exported_at": pick["exported"].strftime("%Y-%m-%dT%H:%MZ"),
        "extra_games": pick["extra"],
        "def_status": "Defense side needs a Data Suite run-defense export (zone vs man/gap concept splits allowed by each defense).",
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
