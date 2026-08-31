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
deadlines/data/manual.yml   (verified audit overrides, priority 0 — beats everything)
```

## How the cron works

`.github/workflows/update-deadlines.yml` runs daily at 21:17 UTC (06:17 KST),
plus on manual dispatch from the Actions tab. It runs the updater and, if anything under
`deadlines/data/conferences/` changed, commits only that path as
`github-actions[bot]` and pushes. Bot pushes with `GITHUB_TOKEN` do not
re-trigger workflows, but GitHub Pages still rebuilds the site. Each run's
full change/warning report is mirrored to the job summary on the Actions tab.

Updater exit codes and what the workflow does with them:

- **0 (healthy)** — normal run, changes (if any) are committed.
- **2 (degraded)** — an upstream source was unreachable or changed shape,
  validation rejected a record, the safety rail fired, or `manual.yml` has a
  bad entry. Safe local output may be produced for diagnostics, but publication
  requires a healthy post-rebase rerun. Otherwise the job stays red, retries on
  the next schedule, and files or bumps an infrastructure alert (label
  `deadline-pipeline`).
- **1 (fatal)** — nothing was written (config unreadable, every source down).
  The job fails and the alert issue is filed.

Operational notes:

- GitHub may disable public-repository cron schedules after 60 days without
  repository activity. Every run verifies via the API that the workflow is
  enabled, and the daily publisher makes a fact-neutral empty bot commit after
  45 otherwise quiet days. This supplies actual repository activity before the
  documented inactivity threshold instead of assuming an API enable call resets
  it.
- Venues mapped `manual-only` in `conferences.yml` (DFRWS US, BAR, CCS-LAMPS)
  have no reliable machine-readable upstream. The weekly official-source audit
  handles their coverage gaps when it can bind the new edition to an older
  stored official host or an `official_hosts` trust anchor in
  `conferences.yml`. A genuinely new current host can also bootstrap when two
  independently fetched upstream datasets agree on it. A current link imported
  from one community tracker is never a trust anchor by itself. Without any of
  those grounds, the run keeps retrying and never trusts a domain proposed by
  the model. The sustainable additional fix is contributing the venue to
  [ccfddl/ccf-deadlines](https://github.com/ccfddl/ccf-deadlines) upstream,
  then switching the mapping from `manual-only` to the new file path.

## Weekly verification audit (Tier 2)

`.github/workflows/audit-deadlines.yml` runs weekly (Sunday 23:17 UTC =
Monday 08:17 KST, plus manual dispatch). The hour is deliberate: Tier 1 runs
daily at 21:17 UTC, so an audit at the same hour Sunday would start from a tree Tier 1 was
rewriting at that moment. Both workflows also share one `deadline-pipeline`
concurrency group, so they can never overlap whatever the schedules say.
It builds a **watchlist** of every current/future edition plus upcoming-cycle
coverage gaps (`update_deadlines.py --watchlist`). Urgent reasons — deadlines
within 45 days, TBAs, active overrides, source disagreements and stale notes —
sort first, but none are dropped. This full scheduled nomination is also the
durable retry mechanism: a deferred correction cannot disappear merely because
an old stored deadline passes.

The workflow splits that watchlist into stable shards of at most ten records.
Each read-only Claude job verifies every record in its shard against official
pages (instructions pinned in `deadlines/scripts/AUDITOR.md`) and writes only
JSON. A completion invocation retries missing, malformed or temporary
`not_checked` results; a non-empty first pass that returns only unverifiable
outcomes also receives that one bounded retry. A fully checked second pass may
still conclude that every source is unverifiable. Final merging rejects a
missing, duplicate, invented or unfinished identity. The write-capable job then
starts from a fresh checkout,
re-fetches citations and writes eligible corrections. Deterministic steps
converge and lint the result before `github-actions[bot]` pushes. The guardrails
are:

  1. model jobs have read-only repository permissions, no push credential and
     no arbitrary shell tool; the authoritative watchlist artifact is created
     before any model runs;
  2. the publishing job uses a fresh checkout and exact-once shard merge, so no
     model-modified working tree, git config, hook or environment crosses the
     write boundary;
  3. schema and repo-contract validation of every proposal (canonical title,
     year in window, overridable fields only, well-formed deadlines, a quote
     behind every value);
  4. citations are fetched again outside Claude, and both the submitted and
     redirected hosts must match a curated/historical official anchor or a host
     independently agreed by two configured upstreams for that conference;
  5. only independently verified fields pass; coupled deadline/timezone fields
     remain atomic. Changes outside the one-run safety bounds need the exact
     same normalized fact VERIFIED on two audit dates at least six days apart;
  6. the applier's own guards — manual.yml must round-trip byte-for-byte before
     it is touched, records are validated before being written, and the result
     must not degrade the updater;
  7. the updater must converge (a second run reports `no file changes`);
  8. every manual.yml entry needs a `Verified <date> against <URL>` citation,
     and no file outside the allowlist may be touched (`audit_lint.py`).

The publisher is pinned to the exact repository revision used to build the
watchlist. Before it reports even a no-change run as healthy, it fetches the
current default-branch tip and refuses the result if anything under
`deadlines/` or either pipeline workflow changed during the audit. Unrelated
site changes are allowed; a concurrent branch advance after that check still
causes the normal non-fast-forward push failure and automatic retry.

Why proposals rather than a diff: a JSON claim carrying a verbatim quote is
machine-checkable, a diff is not. Citation verification and the deterministic
risk policy decide which findings may be applied; unresolved findings remain in
the run's telemetry artifact instead of opening a review issue.
The applier also uses a stable eight-change budget per run: excess verified
corrections are deferred, not failed, so large yearly rollovers converge across
successive weekly runs without allowing one audit to rewrite everything at once.
Deferred identities and corroboration hashes live in the bounded,
machine-owned `deadlines/data/audit-state.json`; this keeps them on later
watchlists even across a year boundary. The state stores no model prose or
unverified values. Obsolete manual overrides need two weekly confirmations plus
agreement from every healthy configured deterministic upstream source.

A **degraded** updater run (exit 2 — typically one upstream source unreachable)
retains the audit telemetry, refuses to publish partial uncertainty, and retries
on the next schedule. The normal failure alert is infrastructure telemetry, not
a queue asking someone to decide conference facts.

`CLAUDE_CODE_OAUTH_TOKEN` is required infrastructure. If it is missing or
expired, the audit fails and creates/updates the normal `Deadline audit failed`
alert; it does not switch to a human watchlist workflow.

### Setting up the auditor credential (Max subscription, no API billing)

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
   deadlines" → Run workflow) starts the automated auditor.
4. Renewal: the token expires after ~1 year with no warning in CI — put a
   calendar reminder to re-run `claude setup-token` and update the secret.

Whoever generates the token pays with their personal Max quota. Repository
commits are authored by `github-actions[bot]`, not that person; the audit JSON
and report are retained as a workflow-run telemetry artifact.

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
python3 deadlines/scripts/tests/test_audit_state.py
python3 deadlines/scripts/tests/test_audit_batches.py
python3 deadlines/scripts/tests/test_reconcile_audit_outcomes.py
python3 deadlines/scripts/tests/test_risk_policy.py
python3 deadlines/scripts/tests/test_verify_citations.py
python3 deadlines/scripts/tests/simulate_workflow.py
```

No network; the audit-lint tests build throwaway git repos in a temp dir and
the citation tests use inline HTML fixtures. The audit workflow runs all unit
suites before it does anything else
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
   taken from upstream). For `manual-only` sources with no stored edition link,
   also add the narrowly scoped official domain in `official_hosts`.
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

Files under `deadlines/data/conferences/` are generated and pipeline-owned.
Independently verified corrections persist in `deadlines/data/manual.yml`; the
weekly audit writes that layer and the daily updater propagates it into generated
files. An override beats community trackers on every field it sets and remains
until two weekly observations plus deterministic upstream agreement prove it is
obsolete. A field explicitly set to `null` removes a fabricated upstream value
from the generated record.

One asymmetry worth knowing: a `manual.yml` entry for a venue/year that has
neither an existing record nor an upstream candidate never reaches a generated
file, but the frontend loads `manual.yml` **directly** at priority 0, so it
still renders on the page. The updater validates those rows explicitly and
degrades on a bad one — nothing else would catch them.
Manual titles must be the canonical key, or the run goes red.
