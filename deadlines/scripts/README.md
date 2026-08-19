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
re-trigger workflows, but GitHub Pages still rebuilds the site. Each run's
full change/warning report is mirrored to the job summary on the Actions tab.

Updater exit codes and what the workflow does with them:

- **0 (healthy)** — normal run, changes (if any) are committed.
- **2 (degraded)** — something needs human attention: an upstream source was
  unreachable or changed shape, validation rejected a record, the safety rail
  fired, or `manual.yml` has a bad entry. Whatever could still be safely
  written IS written and committed, then the job fails so the run shows red,
  and an alert issue (label `deadline-pipeline`) is filed or bumped.
- **1 (fatal)** — nothing was written (config unreadable, every source down).
  The job fails and the alert issue is filed.

Operational notes:

- GitHub disables cron schedules in repos with no activity for 60 days. The
  workflow re-enables itself via the API on every run (the last step), which
  resets that timer, so this should never happen in practice.
- Venues mapped `manual-only` in `conferences.yml` (DFRWS US, BAR, CCS-LAMPS)
  have no reliable machine-readable upstream. Their editions must be added to
  the data files or `deadlines/data/manual.yml` by hand or they will not
  appear on the page at all — the run summary prints a `coverage gap` warning
  whenever any target has no entry for the upcoming cycle year. The
  sustainable fix is contributing the venue to
  [ccfddl/ccf-deadlines](https://github.com/ccfddl/ccf-deadlines) upstream,
  then switching the mapping from `manual-only` to the new file path.

## Weekly verification audit (Tier 2)

`.github/workflows/audit-deadlines.yml` runs weekly (Sunday 23:00 UTC =
Monday 08:00 KST, plus manual dispatch). The hour is deliberate: Tier 1 runs
daily at 21:00 UTC, so an audit at 21:00 Sunday started from a tree Tier 1 was
rewriting at that moment. Both workflows also share one `deadline-pipeline`
concurrency group, so they can never overlap whatever the schedules say.
It builds a **watchlist** — the
small subset of records worth verifying against official conference pages
(`update_deadlines.py --watchlist`): upcoming-cycle TBAs, deadlines within
45 days, active manual overrides, cross-source disagreements, stale
placeholder notes, coverage gaps, and records whose deadline is known but
whose `place`/`date`/`timezone` is still TBA. That last reason exists because
such a record matches none of the others — it is not a TBA cycle, usually not
within 45 days, and its note need not look stale — so its city and dates would
otherwise stay TBA forever. Then, depending on configuration:

- **Claude mode** (the `CLAUDE_CODE_OAUTH_TOKEN` secret exists): Claude Code
  verifies each watchlist record against the venue's official page
  (instructions pinned in `deadlines/scripts/AUDITOR.md`) and writes findings
  to `audit-proposals.json`. **It never edits repository data.**
  `apply_proposals.py` validates the proposals and writes the YAML;
  deterministic steps then converge, lint, and open/update a pull request on
  the `deadline-audit` branch. Claude never pushes anything itself; merging the
  PR is the human decision. The guardrails, in order:
  1. a check that the auditor touched nothing under `deadlines/` or `.github/`,
     run *before* the gates — `audit_lint.py` executes from the working tree and
     so cannot police itself, and the auditor holds `Bash(python3:*)`;
  2. schema and repo-contract validation of every proposal (canonical title,
     year in window, overridable fields only, well-formed deadlines, a quote
     behind every value);
  3. the applier's own guards — manual.yml must round-trip byte-for-byte before
     it is touched, records are validated before being written, and the result
     must not degrade the updater;
  4. the updater must converge (a second run reports `no file changes`);
  5. every manual.yml entry needs a `Verified <date> against <URL>` citation,
     and no file outside the allowlist may be touched (`audit_lint.py`).

  Why proposals rather than a diff: a JSON claim carrying a verbatim quote is
  machine-checkable, a diff is not. Today a human still checks the citations —
  the applier says so in the PR body — but this is the shape the verification
  gates in `AUTO-APPLY-DESIGN.md` plug into.

  A **degraded** updater run (exit 2 — typically one upstream source
  unreachable) no longer discards the audit. The PR still opens, carrying a
  warning banner, because losing a week of verified corrections to an
  unrelated fetch failure is the worse outcome.
- **Human mode** (no secret): the watchlist is filed/updated as a GitHub
  issue (label `deadline-audit`) with a checkbox per record — a lab member
  verifies by hand, ~5-10 minutes weekly.

### Setting up Claude mode (Max subscription, no API billing)

1. Any lab member with the Claude Max account runs `claude setup-token` in a
   terminal (requires Claude Code installed; it opens a browser to
   authorize) and copies the generated token. The token is valid for about a
   year and consumes the **subscription quota** — no API billing account is
   needed.
2. In the GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret** (the *Actions* tab specifically — not Codespaces,
   not Dependabot, and not the "Agents" section). Name it exactly
   `CLAUDE_CODE_OAUTH_TOKEN`, paste the token as the value.
3. That's it — the next scheduled run (or Actions tab → "Audit conference
   deadlines" → Run workflow) uses Claude mode automatically.
4. Renewal: the token expires after ~1 year with no warning in CI — put a
   calendar reminder to re-run `claude setup-token` and update the secret.

Whoever generates the token pays with their personal Max quota (a weekly
watchlist-sized audit is a small fraction of a Max 20x budget); commits and
PRs are still authored by `github-actions[bot]`, not that person.

## Running locally

```sh
pip install pyyaml                                   # only dependency
python3 deadlines/scripts/update_deadlines.py --dry-run   # preview changes
python3 deadlines/scripts/update_deadlines.py             # write files in place
```

Works from any CWD; exit 0 = healthy, 2 = degraded (see above), 1 = fatal.

## Tests

```sh
python3 deadlines/scripts/tests/test_update_deadlines.py
python3 deadlines/scripts/tests/test_audit_lint.py
python3 deadlines/scripts/tests/test_apply_proposals.py
python3 deadlines/scripts/tests/test_verify_citations.py
python3 deadlines/scripts/tests/simulate_workflow.py   # needs a clean tree
```

No network; the audit-lint tests build throwaway git repos in a temp dir and
the citation tests use inline HTML fixtures. `simulate_workflow.py` extracts the
workflow's real `run:` blocks from the YAML and executes them with the Claude
step stubbed, so shell logic can be checked before it reaches CI. The audit
workflow runs the four unit suites before it does anything else
— if the gates are broken, the audit does not run. Each test pins a specific
way the pipeline could have published a wrong deadline, so a failure here is
worth reading rather than deleting:

- an obsolete-looking override being auto-declared removable when it is not
  (a `null` override suppressing an upstream fabrication is the live case);
- an IANA-shaped timezone no tz database knows, which the frontend silently
  renders as AoE — i.e. *later* than the truth;
- a manual override moving a deadline by more than the 90-day safety rail,
  which the rail itself does not cover;
- the audit writing outside `deadlines/data`, including via an **untracked**
  file, which `git diff` cannot see but `git add` would stage anyway.

## Adding a new target conference

1. Add an entry to `deadlines/scripts/conferences.yml` (canonical key,
   category, upstream aliases, tier — tiers are curated by the lab, never
   taken from upstream).
2. Add the same canonical key to the `TARGETS` list in
   `deadlines/assets/deadline-tracker.js` so the frontend displays it.
3. Run the script (or wait for the cron) to populate the data files.

## What self-corrects automatically

- `title`, `id`, `full_name`, `type`, and `tier` are enforced from
  `conferences.yml` onto current and future editions every run (past editions
  keep their historical values), so fixing the mapping fixes the data.
- A record filed in the wrong year/category file is re-filed into the bucket
  `conferences.yml` assigns.
- Placeholder notes ("CFP not announced yet", ...) are dropped the moment the
  record gains its first concrete deadline.
- New editions of tracked venues (and new year directories, e.g. `2028/`) are
  created automatically as upstream publishes them.

## Golden rule

Never hand-edit files under `deadlines/data/conferences/` — the next cron run
overwrites them. Human corrections (wrong deadline, date, place, ...) go in
`deadlines/data/manual.yml`. The updater propagates those overrides into the
generated files on every run, so a manual entry beats upstream on every field
it sets — in either direction — and stays in effect until you delete it. A
field explicitly set to `null` deletes it from the generated record (for
values fabricated upstream, e.g. an abstract deadline the CFP never had). The
run summary tells you when upstream has caught up and an entry can be removed
— it will not say that about a `null` override, since upstream omitting the
fabricated value on one run is exactly what the override is there for.

One asymmetry worth knowing: a `manual.yml` entry for a venue/year that has
neither an existing record nor an upstream candidate never reaches a generated
file, but the frontend loads `manual.yml` **directly** at priority 0, so it
still renders on the page. The updater validates those rows explicitly and
degrades on a bad one — nothing else would catch them.
Manual titles must be the canonical key, or the run goes red.
