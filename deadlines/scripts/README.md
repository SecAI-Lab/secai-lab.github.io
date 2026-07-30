# Conference deadline auto-updater

Keeps `deadlines/data/conferences/<year>/<category>.yml` in sync with
community-maintained upstream deadline datasets.

## Architecture

```
upstream deadline datasets (community-maintained)
        |
        v
deadlines/scripts/update_deadlines.py      <- mapping: deadlines/scripts/conferences.yml
        |
        v
deadlines/data/conferences/<year>/<category>.yml   (AUTO-GENERATED, priority 1)
        |
        v
deadlines/assets/deadline-tracker.js  -->  /deadlines/ page
        ^
        |
deadlines/data/manual.yml   (human overrides, priority 0 — beats everything)
```

## How the cron works

`.github/workflows/update-deadlines.yml` runs daily at 21:00 UTC (06:00 KST),
plus on manual dispatch from the Actions tab. It runs the updater and, if anything under
`deadlines/data/conferences/` changed, commits only that path as
`github-actions[bot]` and pushes. Bot pushes with `GITHUB_TOKEN` do not
re-trigger workflows, but GitHub Pages still rebuilds the site. If the script
exits non-zero (all sources unreachable, validation failure) the job fails
loudly — check the Actions log. Each run's full change/warning report is also
mirrored to the job summary on the Actions tab.

Two operational cautions:

- GitHub disables cron schedules in repos with no activity for 60 days. Any
  human commit resets the clock, and deadline data rarely stays unchanged that
  long, but if the repo goes fully dormant re-enable the workflow from the
  Actions tab.
- DFRWS US appears in no upstream dataset and dfrws.org blocks scripted
  fetches, so its editions must be added to `deadlines/data/manual.yml` by
  hand or they will not appear on the page at all.

## Running locally

```sh
pip install pyyaml                                   # only dependency
python3 deadlines/scripts/update_deadlines.py --dry-run   # preview changes
python3 deadlines/scripts/update_deadlines.py             # write files in place
```

Works from any CWD; exit 0 = success (with or without changes), exit 1 = fatal.

## Adding a new target conference

1. Add an entry to `deadlines/scripts/conferences.yml` (canonical key,
   category, upstream aliases, tier — tiers are curated by the lab, never
   taken from upstream).
2. Add the same canonical key to the `TARGETS` list in
   `deadlines/assets/deadline-tracker.js` so the frontend displays it.
3. Run the script (or wait for the cron) to populate the data files.

## Golden rule

Never hand-edit files under `deadlines/data/conferences/` — the next cron run
overwrites them. Human corrections (wrong date, missing venue, ...) go in
`deadlines/data/manual.yml`, which overrides the generated data.
