# ClevAnalytics Run Game Matchup Report

A weekly matchup report as its own website. Pick a week and every offense playing gets one row: its run game (RBs and offensive line) against the opposing run defense, scored as a Run Edge, with a View button for the details. It uses free [nflverse](https://nflverse.nflverse.com/) data only.

It has two parts:
- **Pipeline** (`pipeline/`, Python + [nflreadpy](https://github.com/nflverse/nflreadpy)): pulls nflverse data, computes everything, runs the validation checks, and writes one JSON file per week to `data/<season>/week-XX.json` (every offense playing that week, with both seasons' numbers), plus `data/<season>/index.json`.
- **Page** (`index.html`, `src/`): reads those files. They're bundled at build time and each week loads on demand. There are no runtime network calls.

All commands below run from the repo root.

## Run it locally

```bash
npm install
npm run dev        # local dev server
npm test           # data checks + formatting tests (vitest)
npm run build      # typecheck + tests + static bundle in dist/
```

## Deploy (one time, about 5 minutes)

1. In Netlify, click **Add new site → Import an existing project → GitHub** and pick **Yengaskhan/run-game-matchups**. Netlify asks for access to it because the repo is private.
2. Leave the settings alone. `netlify.toml` already sets the build command `npm run build`, publish directory `dist`, and Node 22.
3. Click **Deploy**. You get its own URL, e.g. `https://something.netlify.app`. Rename it under **Site configuration → Change site name** (e.g. `clevanalytics-matchups`).
4. Optional: under **Domain management → Add a domain**, use e.g. `matchups.yourdomain.com` and add the CNAME record Netlify shows at your DNS provider.

Every push to `main` redeploys, including your weekly data commits.

**On your website:** add a menu link to the site's URL, or embed it with a Custom HTML / Code / Embed block:

```html
<iframe
  src="https://matchups.yourdomain.com/"
  title="ClevAnalytics Run Game Matchups"
  style="width:100%; height:1200px; border:0;"
  loading="lazy"
></iframe>
```

When embedded, the page shows an "Open full screen ↗" link. The selected game and side live in the URL hash (`#game=2026_03_BAL_DAL&side=1`), so links go straight to a matchup. To allow embedding only on your own site, change `frame-ancestors *` in `netlify.toml` to your domain.

## Refreshing the data (weekly)

Netlify only runs Node, so you refresh the data on your own computer and push it.

One-time setup:

```bash
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements.txt
```

Each week, once nflverse has the new games (PBP usually lands within a day; PFR can take a little longer):

```bash
.venv/bin/python pipeline/run_matchups.py            # this week's games (nflverse's current week)
.venv/bin/python pipeline/run_matchups.py --week 4   # one specific week
.venv/bin/python pipeline/run_matchups.py --all      # every week on the current-season schedule (~25 MB)
.venv/bin/python pipeline/verify_matchup.py 2026_03_BAL_DAL   # optional: independent spot-check of one game
npm run check-data                                   # the same data checks the build runs
git add data && git commit -m "Matchups: week 4" && git push
```

A single-week run adds that week and keeps the weeks already on disk; the index is rebuilt from the files present. To drop old weeks, delete their `data/<season>/week-XX.json` files and re-run any week.

**Which games count:** a Week N report uses only current-season weeks before N in which **every** game is final. A half-played week (e.g. only Thursday night done) is left out until it finishes, so every team's sample covers the same weeks. Reports for future weeks use every completed week. The prior season is always the full regular season, picked with the page's Season selector and never combined with the current one.

**The run stops, and writes nothing, if a check fails:**
- a final game is missing from play-by-play
- PBP rush totals don't match nflverse `team_stats` within tolerance (2 carries / 3 yards per team-game)
- designed runs plus removed plays don't add back up to all rush attempts
- PFR carries are missing or don't match
- a table's direction/gap/box shares don't sum to 100%
- rusher rows don't sum to the team total

When PBP or PFR is simply a day behind, the message says so. Re-run later.

## Changing the qualifiers

Every tunable number is in `pipeline/matchups/config.py`. Edit it, then re-run the pipeline:

| Setting | Default | Meaning |
|---|---|---|
| `QUALIFIERS["team_min_games"]` | 1 | Teams ranked (so all 32) |
| `QUALIFIERS["rusher_att_per_team_game"]` | 6.25 | Non-QB rushers are ranked with ≥ 6.25 designed runs per team game (the NFL rushing-title standard: 13 after 2 games, 107 over 17) |
| `QUALIFIERS["bucket_att_per_team_game"]` | 3.0 | A team's direction/gap/box bucket is ranked with ≥ 3 runs per team game in it (current season) |
| `QUALIFIERS["bucket_min_att_prior"]` | 25 | Same, prior season (flat) |
| `EDGE["bands"]` | 70 / 58 / 43 / 31 | Run Edge colour bands: big edge ≥ 70, small edge ≥ 58, neutral 43–57, small disadvantage 31–42, big disadvantage ≤ 30 |
| `EDGE["min_coverage"]` | 0.5 | The headline Run Edge is shaded only when ranked directions cover ≥ 50% of the offense's runs (else grey "small sample") |
| `EDGE["min_share"]` | 0.10 | Detail takeaways only consider gaps the offense uses on ≥ 10% of its runs |
| `EXPLOSIVE_YARDS` | 10 | Explosive run threshold |
| `BOX_BUCKETS` | ≤6 / 7 / 8+ | Box-count buckets |
| `TOLERANCE` | 2 carries / 3 yards | Reconciliation tolerance per team-game |

Every row still shows its numbers; a row that misses the qualifier just shows rank "—". Each table prints its peer group ("peer group: 32 defenses", "peer group: 45 non-QB rushers…"). Ranks are computed only within one table, one qualifier and one season. Rank 1 = best for that unit (the best offense, or the stingiest defense).

## Data rules

- **Designed runs only.** Filters, each commented in `pipeline/matchups/plays.py`:
  - regular season only
  - `rush_attempt = 1`
  - remove QB scrambles, kneels, aborted snaps, two-point tries, `no_play` penalty plays and deleted plays
  - keep designed QB runs, labeled (and QB sneaks from FTN)
- **Left / middle / right and end / tackle / guard** are nflverse `run_location` / `run_gap`, always from the **offense's** point of view, including in the defense tables.
- **The current and prior seasons are never blended.** Each table carries one season label, and the page shows it as a chip. Attempts (and games) sit next to every figure.
- **YBC / YAC** come from PFR (`load_pfr_advstats`, `stat_type="rush"`, weekly rows). PFR only publishes them per player per game, so they can't be filtered to designed runs or split by direction. Team and "allowed" figures use non-QB rushers only, which keeps QB scrambles and kneels out.
- **Box counts** come from FTN charting (`load_ftn_charting`, `n_defense_box`). nflverse participation data (`defenders_in_box`, `offense_formation`) isn't published for the current season, so it isn't used. Box counts of 0 are treated as not charted.
- **Snap share** comes from nflverse snap counts; **depth-chart order** from nflverse depth charts (the snapshot before kickoff day for a played game, else the latest).
- **Takeaways** (at most two per matchup) are fixed templates filled from the numbers. No LLM is involved.

## Run Edge

A 0–100 score, 50 = even, shaded green (offense edge) to orange (defense edge).

- **Per bucket** (a direction, gap or box count): `50 + 50 × (offense EPA/run percentile − defense EPA-allowed percentile)`. Each percentile comes from its own ranked table (1 = best offense / stingiest defense), so a top offense meeting the leakiest defense in that bucket scores 100. It's blank when either side is below the rank qualifier.
- **Headline Run Edge:** the left / middle / right edges, averaged with weights from how often the offense runs each way. When the ranked directions cover less than half of the offense's runs, the badge shows grey with a dashed border ("small sample").
- The **Split** selector (Left / Middle / Right) swaps the table to that one direction's numbers and edge.

## Report layout

- **Header:** week, **Season** selector (current season to date, or the full prior season; never combined), **Split** selector, **Find team** box, and the colour legend.
- **Main table:** one row per offense playing that week, with opponent, offense EPA/run and defense EPA allowed (each with rank/peer group and attempts), main run direction, and Run Edge. Every column sorts.
- **View** opens the detail under the row:
  - one-line stat strips for the offense and the defense (EPA, success, YPC, explosive, stuffed, YBC, YAC, with ranks)
  - one table of direction / gap / box splits: offense | defense | edge
  - up to two takeaways (best and toughest gap for the offense)
  - the backs: depth-chart order, carry and snap share, efficiency, YBC vs YAC
- **Footer** (collapsed): Run Edge definition, notes, filters, qualifiers, sources and the validation checks.

The selected week, season, split and open row live in the URL hash (`#week=3&season=2026&split=all&open=BAL`), so links go straight to a view.

## Adding another matchup type later (e.g. pass coverage)

Each row's season block is self-contained (`pipeline/matchups/weekly.py`, types in `src/types.ts`). A coverage report would add its own block builder next to `side_block()` and its own columns and detail on the page, reusing the same week files, selectors, edge badge and checks.

## Tests

- `pipeline/tests/` (pytest): filters, metric maths, rank direction and peer groups, zero-filled splits, qualifiers, report checks. Run with `.venv/bin/python -m pytest pipeline/tests`.
- `tests/matchups.test.ts` (vitest, part of `npm test` / `npm run build`) checks every committed report:
  - the index matches the week files on disk
  - one row per offense, both sides of every game
  - seasons are labeled and never mixed
  - shares sum to 100%
  - rusher rows sum to the team total
  - edges are within 0–100
  - every rank is within its peer group
