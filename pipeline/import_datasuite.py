"""
Add a Data Suite export to the repo.

    python pipeline/import_datasuite.py ~/Downloads/rushing-stats.csv

Checks the file, reads its export time from the "Exported from Data Suite ... UTC" footer, and copies it
to imports/datasuite/rushing/<export time>.csv. Commit that folder; the next pipeline run uses it for
any week whose games it fully covers.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from matchups.datasuite import IMPORT_DIR, DataSuiteError, parse_rushing  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path, help="the CSV exported from Data Suite")
    args = ap.parse_args()
    try:
        df, league, exported = parse_rushing(args.file)
    except DataSuiteError as e:
        print(f"Not imported: {e}", file=sys.stderr)
        return 1
    dest = IMPORT_DIR / "rushing" / f"{exported:%Y-%m-%dT%H%M}Z.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.file, dest)
    print(f"Imported {df.height} RBs, exported {exported:%Y-%m-%d %H:%M} UTC -> {dest.relative_to(IMPORT_DIR.parents[1])}")
    print(f"League average success: zone {league.get('zone', {}).get('sr')}, man/gap {league.get('gap', {}).get('sr')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
