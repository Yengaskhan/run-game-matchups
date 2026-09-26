"""
Every tunable number in the matchup pipeline lives here. Edit, then re-run the pipeline.

Qualifiers decide who gets a RANK. Everyone still gets a row; a row that misses the
qualifier shows its numbers with rank "—".
"""

from pathlib import Path

# Repo root and output location. The site bundles every JSON under data/ at build time.
APP_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = APP_ROOT / "data"

# Bump when the JSON layout changes in a way the page must know about.
SCHEMA_VERSION = 1

# Only regular-season games feed either season's numbers. Playoff games are excluded.
SEASON_TYPE = "REG"

QUALIFIERS = {
    # Teams: every team with at least this many games in the window is ranked (so all 32).
    "team_min_games": 1,
    # Rushers: ranked when designed runs >= this x their team's games in the window.
    # 6.25 per team game is the NFL's own rushing-title standard (e.g. 13 after 2 games, 107 over 17).
    "rusher_att_per_team_game": 6.25,
    # Direction / gap / box buckets, current season: ranked when the team has >= this x games attempts
    # in that bucket (e.g. 6 after 2 games).
    "bucket_att_per_team_game": 3.0,
    # Direction / gap / box buckets, prior season: a flat minimum over the full season.
    "bucket_min_att_prior": 25,
}

# Overlap section: which offense buckets count as "most used", and how big a gap between the
# offense's and the defense's percentile (0-1) must be before it is called a mismatch.
OVERLAP = {
    "min_share": 0.10,
    "min_edge": 0.25,
}

# A run of this many yards or more is explosive. A run of 0 or fewer yards is a stuff.
EXPLOSIVE_YARDS = 10

# FTN box-count buckets (n_defense_box): light <= 6, base = 7, heavy >= 8.
BOX_BUCKETS = [
    ("light", "Light box (≤6)", None, 6),
    ("base", "Base box (7)", 7, 7),
    ("heavy", "Heavy box (8+)", 8, None),
]

# Reconciliation tolerance per team-game: PBP rush totals vs nflverse team_stats.
# 2025 had one team-game off by 2 carries and one by 3 yards (stat corrections), so allow that much.
TOLERANCE = {"carries": 2, "yards": 3}

# Direction and gap buckets, always from the OFFENSE's point of view (as nflverse charts them).
DIRECTIONS = [("left", "Left"), ("middle", "Middle"), ("right", "Right")]
GAPS = [
    ("left_end", "L end"),
    ("left_tackle", "L tackle"),
    ("left_guard", "L guard"),
    ("middle", "Middle"),
    ("right_guard", "R guard"),
    ("right_tackle", "R tackle"),
    ("right_end", "R end"),
]
