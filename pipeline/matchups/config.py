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
SCHEMA_VERSION = 2

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
    # A rusher's own direction / gap / box splits (the starting RB in each row), current season: ranked
    # among non-QB rushers with >= this x his team's games carries in that bucket (e.g. 6 after 3 games).
    "rusher_bucket_att_per_team_game": 2.0,
    # Same, prior season: a flat minimum over the full season.
    "rusher_bucket_min_att_prior": 20,
}

# Run Edge (0-100, 50 = neutral). In one bucket (a direction, gap or box count):
#   edge = 50 + 50 x (offense EPA/run percentile - defense EPA-allowed percentile)
# where each percentile is within its own ranked table (1 = best offense / stingiest defense).
# The headline Run Edge averages the left / middle / right edges, weighted by how often the offense
# runs each way. It is only shaded when the ranked directions cover at least `min_coverage` of the
# offense's runs; below that it shows grey as "small sample".
EDGE = {
    "min_coverage": 0.5,
    # Colour bands, lower bound inclusive.
    "bands": [
        ("big_edge", "Big edge", 70),
        ("small_edge", "Small edge", 58),
        ("neutral", "Neutral", 43),
        ("small_disadvantage", "Small disadvantage", 31),
        ("big_disadvantage", "Big disadvantage", 0),
    ],
    # Detail takeaways: a gap counts as "used" at this share of the offense's designed runs.
    "min_share": 0.10,
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
