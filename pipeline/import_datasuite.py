"""
Add a Data Suite export to the repo.

    python pipeline/import_datasuite.py ~/Downloads/rushing-stats.csv
    python pipeline/import_datasuite.py ~/Downloads/team-defense.csv

Checks the file, reads its export time from the "Exported from Data Suite ... UTC" footer, and copies it
to imports/datasuite/<rushing | team_defense>/<export time>.csv. Commit that folder; the next pipeline run uses it for
any week whose games it fully covers.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from matchups.datasuite import IMPORT_DIR, DataSuiteError, parse_rushing, parse_team_defense, read_export  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path, help="the CSV exported from Data Suite")
    args = ap.parse_args()
    try:
        keys = read_export(args.file)[3]
        if any(k.startswith("Team Details|") for k in keys):
            td = parse_team_defense(args.file)
            exported, kind = td["exported"], "team_defense"
            summary = f"Imported {td['season']} team defense for {len(td['teams'])} teams"
        else:
            df, league, exported = parse_rushing(args.file)
            kind = "rushing"
            summary = (f"Imported {df.height} RBs. League average success: zone {league.get('zone', {}).get('sr')}, "
                       f"man/gap {league.get('gap', {}).get('sr')}")
    except DataSuiteError as e:
        print(f"Not imported: {e}", file=sys.stderr)
        return 1
    dest = IMPORT_DIR / kind / f"{exported:%Y-%m-%dT%H%M}Z.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.file, dest)
    print(f"{summary}, exported {exported:%Y-%m-%d %H:%M} UTC -> {dest.relative_to(IMPORT_DIR.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
