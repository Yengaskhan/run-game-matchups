"""
Team logos and names for the page, from nflverse's teams table (load_teams).

Logos are nflverse's squared team logos, downloaded once, shrunk to 64 px, and committed under
src/assets/logos/ so the site serves them itself (no runtime requests to other hosts). Existing files
are kept unless refresh=True.
"""

import io
import json
import urllib.request

import nflreadpy as nfl
from PIL import Image

from .config import APP_ROOT

LOGO_DIR = APP_ROOT / "src" / "assets" / "logos"
TEAMS_JSON = APP_ROOT / "src" / "assets" / "teams.json"
SIZE = 64  # px; shown at 20-28 px, so this is sharp on high-density screens


def _raw_url(url: str) -> str:
    # nflverse lists github.com/.../raw/... links; the raw host serves the same file directly.
    return url.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/raw/", "/", 1)


def ensure_logos(teams: set[str], refresh: bool = False) -> str:
    all_teams = nfl.load_teams()
    t = all_teams.filter(all_teams["team_abbr"].is_in(list(teams))).to_dicts()
    missing_meta = teams - {r["team_abbr"] for r in t}
    if missing_meta:
        raise RuntimeError(f"nflverse teams table has no entry for {sorted(missing_meta)}")
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for r in t:
        path = LOGO_DIR / f"{r['team_abbr']}.png"
        if path.exists() and not refresh:
            continue
        with urllib.request.urlopen(_raw_url(r["team_logo_squared"]), timeout=30) as resp:
            img = Image.open(io.BytesIO(resp.read())).convert("RGBA")
        img.resize((SIZE, SIZE), Image.LANCZOS).save(path, optimize=True)
        fetched += 1
    names = {r["team_abbr"]: {"name": r["team_name"], "color": r["team_color"]} for r in sorted(t, key=lambda r: r["team_abbr"])}
    TEAMS_JSON.write_text(json.dumps(names, indent=1) + "\n")
    return f"Team logos: {len(t)} teams ({fetched} downloaded, {len(t) - fetched} already present)."
