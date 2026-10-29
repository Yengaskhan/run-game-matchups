"""
Undo changes to data files whose only difference is the generated_at timestamp.

The refresh re-runs the pipeline on Wednesday; when nothing new has been published, every file is the
same apart from generated_at. Committing that would redeploy the site (Netlify charges per deploy) for
no change, so such files are restored to their committed version before the commit step.

    python pipeline/drop_timestamp_only_changes.py     # run from the repo root, after the pipeline
"""

import json
import subprocess
import sys


def strip(obj):
    if isinstance(obj, dict):
        return {k: strip(v) for k, v in obj.items() if k != "generated_at"}
    if isinstance(obj, list):
        return [strip(v) for v in obj]
    return obj


def main() -> int:
    changed = subprocess.run(["git", "diff", "--name-only", "--", "data"], capture_output=True, text=True, check=True).stdout.split()
    restored = 0
    for path in changed:
        if not path.endswith(".json"):
            continue
        old = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, text=True)
        if old.returncode != 0:
            continue  # a new file: keep it
        try:
            same = strip(json.loads(old.stdout)) == strip(json.loads(open(path).read()))
        except ValueError:
            continue
        if same:
            subprocess.run(["git", "checkout", "--", path], check=True)
            restored += 1
    print(f"{restored} file(s) differed only in generated_at and were left as committed; {len(changed) - restored} real change(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
