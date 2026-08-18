# Tier 2 auto-apply: design

Status: **§8 fixed and tested (2026-08-18). §2–§7 are still a proposal.**

Step 1 of the build order in §11 is done: every bug in §8 is fixed on the
existing PR-based pipeline, with regression tests under
`deadlines/scripts/tests/`. Nothing auto-applies yet — the human still merges
the audit PR, exactly as before. What changed is that the pipeline no longer
loses a week's audit to an unrelated fetch failure, no longer lets an
unresolvable timezone render a deadline as AoE, and no longer treats a
suppressing override as obsolete.

Goal: the weekly verification audit publishes verified corrections straight to
master with no human in the loop, without ever publishing a wrong deadline.

Those two halves pull against each other at exactly one point — a change nothing
can mechanically verify. Everything below is about shrinking that set to near
zero rather than pretending it is empty.

---

## 1. Why the current design stops at a PR

The auditor edits YAML directly. The only automated check is `audit_lint.py`:
files touched are inside `deadlines/data/`, and every `manual.yml` entry has a
comment containing `Verified` and some URL. Neither check looks at the cited
page. **Nothing verifies that the URL says the date.**

So the PR is not bureaucracy — it is the only step that checks the claim.
Automating it means replacing it with something that checks the same claim
mechanically.

---

## 2. The pivot: make the model's output checkable

The auditor stops writing YAML. It emits `audit-proposals.json`, where every
proposed value carries a `source_url` and an `evidence_quote` copied verbatim
from the page:

```json
{
  "id": "upsert_manual:DIMVA:2026",
  "action": "upsert_manual", "title": "DIMVA", "year": 2026,
  "source_url": "https://www.dimva.org/dimva2026/",
  "reason": "sec-deadlines carries pre-extension dates; official page shows both cycles extended.",
  "fields": {
    "deadline": {
      "value": ["2025-12-10 23:59", "2026-02-18 23:59"],
      "evidence": [
        {"quote": "Submission deadline (cycle 1): 10 December 2025 (extended!)"},
        {"quote": "Submission deadline (cycle 2): 18 February 2026 (extended!)"}
      ]
    },
    "timezone": {"value": "AoE",
                 "evidence": [{"quote": "All deadlines are AoE (Anywhere on Earth)."}]}
  }
}
```

Three things follow at once:

- the claim becomes machine-verifiable — a program can re-fetch and check it;
- the model never writes YAML, so a whole class of syntax and merge errors
  disappears;
- accept/reject becomes per-proposal instead of per-diff.

JSON is the right intermediate format for one specific reason: it natively
distinguishes *key absent* (no override) from *key present with `null`* (delete
the field). That distinction is exactly what `apply_manual_override` keys on.

---

## 3. Gate 1 — deterministic, no model

`deadlines/scripts/verify_citations.py`. Fetches each `source_url` fresh and
returns `VERIFIED | UNCONFIRMED | UNREACHABLE | REJECTED_SOURCE | MALFORMED`.

### The matching rule

A claim is VERIFIED iff there is one contiguous window `W` of normalized page
text where:

1. a *strong* surface form of the claimed value occurs (exact substring), **and**
2. the `evidence_quote` is ≥ 0.85 LCS-covered by `W`, **and**
3. every load-bearing token of the quote (digits, month names, tz words) is in `W`.

Check (1) alone accepts "February 10" when the page means the *notification*
date. Check (2) alone accepts a paraphrase wrapped around a hallucinated number.
Together they bind the **label** to the **value** at one place on the page.

Calibrated against real entries already in `manual.yml`:

| case | coverage | outcome |
|---|---|---|
| EuroSec quote incl. `[struck: February 3 …] February 10` | 0.92 | VERIFIED |
| "Paper Submission Deadline: February 10" vs page's "Notification of acceptance: February 10" | 0.50 | UNCONFIRMED |
| quote absent from page (hallucinated) | fails (1) | UNCONFIRMED |

### Field-label vocabulary (check 4)

Checks 1–3 catch *dishonest* quoting. They do not catch honest quoting of the
wrong thing: an auditor that faithfully quotes
`"Notification of acceptance: February 10, 2026"` and proposes it as `deadline`
grounds perfectly — verbatim quote, date in window, all tokens present — and
would be VERIFIED. Since the matrix auto-applies VERIFIED + UNSURE for R0/R1,
and R0 (`tba-upcoming-cycle`) is the highest-volume path in the system, that gap
sits directly under the busiest auto-apply route.

So the grounded window must also carry a label appropriate to the field:

| field | window must contain | window must not contain |
|---|---|---|
| `deadline` | one of: submission deadline, paper deadline, papers due, full paper, submission due | notification, acceptance, camera-ready, rebuttal, workshop, poster, demo, tutorial, doctoral, SRC |
| `abstract_deadline` | abstract (registration/submission/due) | — |
| `date` | — | submission, deadline, due |

Same normalized-window machinery as checks 1–3; no extra fetch. This is the
positive-claim counterpart of the label vocabulary §6 already uses for absence
tests — the two must stay in one table.

### Normalization order is load-bearing

HTML comments are stripped **before** tags. `manual.yml` documents the exact
trap: WWW 2026's superseded April dates live in commented-out HTML on
`www2026.thewebconf.org`. Strip tags first and those dates return as "evidence".
Also removed: `<script>`, `<style>`, `<svg>`, `<noscript>`, and hidden or
struck-through markup.

### Source authority

Community trackers are denied outright — ccfddl, sec-deadlines, WikiCFP,
conferencelists, aideadlin.es and their GitHub raw paths — as are archive, cache
and translate hosts. Officialness is then decided by a publisher allowlist plus a
host/path token heuristic, with a per-venue `official_hosts` escape hatch in
`conferences.yml`. The heuristic was regression-tested against all ten citation
URLs currently in `manual.yml`: 10/10.

Redirects are followed but the **final** URL is re-classified, so an official
host redirecting onto a tracker fails.

**UNREACHABLE is never VERIFIED.** TLS errors are not bypassed; bot-blocked sites
(`usenix.org`, `dfrws.org`) are reported, not worked around.

---

## 4. Gate 2 — adversarial, and measured rather than trusted

A second Claude run (`REFUTER.md`) with a filesystem-enforced fresh context:
`audit-proposals.json` is moved out of the tree, and the refuter receives only
venue, year, current values, proposed values, `source_url`, and `field_semantics`
(which deadline each field means). It never sees the auditor's quote or
reasoning.

The important part: the refuter must report **`observed_values`** — its own
reading of the page — and the pipeline compares those to the proposal
**mechanically**. Its stated verdict is only an input. For a wrong proposal to
survive, the refuter would now have to independently assert the *same* wrong
reading *and* supply a quote that itself grounds on the page.

Deterministic post-checks rewrite verdicts: `observed_values ≠ proposed` forces
REFUTED; an ungroundable refuter quote forces UNSURE; any failed lens check
forces REFUTED; confidence only ever *caps* a verdict, never promotes one.

Four lenses, asked as a checklist in a single invocation: `right_edition`,
`right_deadline_kind`, `current_not_superseded`, `timezone_stated`.

Missing, malformed or timed-out refuter output → all verdicts UNSURE. Fail-closed
here means "hold", not "discard": a broken refuter is an infrastructure failure,
not evidence against a correction.

**Correlation caveat.** Both passes are the same model reading the same page. On
a page carrying injected or hidden text, gate 2 adds close to nothing — which is
why gate 1 strips hidden markup and why the host allowlist matters more than the
second opinion does.

---

## 5. Direction-awareness: the rule that makes this safe

Both gates answer *"is this value on the page"*. Neither answers *"what does
being wrong cost"*. Define the **effective instant** = date + clock time +
timezone offset. Then:

- **Safe-direction** — moves the effective instant *earlier*, leaves it
  unchanged, or fills a previously-absent value.
- **Risk-direction** — moves it *later*: later date, later clock time, or a
  timezone shifted toward AoE. Deleting `timezone` is risk-direction, because
  `deadline-tracker.js:110` defaults a missing timezone to `UTC-12` (AoE) — the
  latest possible reading.

The harm is asymmetric. Too early costs a researcher some hurried hours. Too late
costs them the paper, silently, with this site as the proximate cause.

Computing the effective instant needs `zoneinfo` for IANA zones, since a DST-aware
offset is the whole point of storing `America/Los_Angeles` rather than `PST`. The
baseline for a record with **no** timezone is UTC-12, matching the frontend
default — which makes *adding* a timezone to a record that lacks one always
safe-direction, and *removing* one always risk-direction.

This also settles a genuine conflict between two design passes. Clock time is
**not** required as evidence — `23:59` is this repo's end-of-day convention, not
a claim about page text, and gating on it would manufacture constant false
negatives. But a **risk-direction** change must have its clock time and timezone
explicitly grounded in the quote. A convention is fine exactly as long as it
cannot hurt you.

### Extensions

Deadline extensions are the most common risk-direction change, and blanket-holding
them would push the majority of real deadline corrections back to a human. They
are also unusually quotable — the real DIMVA and EuroSec pages literally contain
"(extended!)". So they auto-apply, at a strictly higher bar: an extension token in
the grounded quote, gate 1 VERIFIED, refuter CONFIRMED with matching
`observed_values`, an independent blind extractor agreeing, and a shift ≤ 30 days.

The blind extractor therefore runs for **every risk-direction proposal, not only
R3** — an extension 90 days out is risk-direction but outside R3, and the bar must
not name a step the wiring never executes. This costs no extra invocation: the
blind extractor handles all flagged proposals in one call, so widening its scope
adds items to that call rather than another run, and the ~38-minute worst-case job
budget is unchanged.

---

## 6. Policy

Risk tiers, computed deterministically:

| tier | definition |
|---|---|
| R0 fill | no concrete deadline today; proposal adds one |
| R1 metadata | only `place`/`date`/`note`/`link`, deadline > 45d out |
| R2 deadline, far | concrete deadline changed, > 45d away |
| R3 deadline, near | any deadline ≤ 45d away |
| R4 deletion | a field set to `null`, or an override removed |

**APPLY** = commit to master · **HOLD** = goes in the residual PR · **DISCARD** =
job summary only.

| gate 1 ↓ / refuter → | CONFIRMED | UNSURE | REFUTED |
|---|---|---|---|
| VERIFIED | APPLY (risk-direction: §5 extension rules; R3 or risk-direction: blind extractor must agree) | APPLY if R0/R1 · HOLD otherwise | HOLD |
| UNCONFIRMED | APPLY if R0/R1 **and** the refuter's own quote grounded · else HOLD | HOLD | DISCARD |
| UNREACHABLE | HOLD | HOLD | DISCARD |
| REJECTED_SOURCE | DISCARD | DISCARD | DISCARD |

The load-bearing cells:

- **VERIFIED + UNSURE → APPLY for R0/R1.** Gate 1 mechanically proved the quote is
  on the official page, contains the value, and carries a label appropriate to the
  field (§3 check 4); the refuter only failed to resolve the remaining semantics.
  For a record showing "TBA", holding leaves the site useless another week. This is
  the system's highest-volume auto-apply path, and it rests on gate 1 alone — which
  is precisely why check 4 is not optional.
- **VERIFIED + REFUTED → HOLD, never DISCARD.** Mechanical evidence against a
  semantic objection is precisely what a human settles in thirty seconds with both
  quotes side by side.
- **UNREACHABLE + CONFIRMED → HOLD.** Our fetcher failed where the model claims
  success. Benign explanations exist; so does "it did not really fetch."

### Never auto-applied

- **`timezone: null`.** Deleting a timezone silently moves the deadline to the
  latest possible reading. No exceptions.
- **Risk-direction changes that miss the §5 extension bar.**
- **Field `null` deletions inside 45 days.** A deletion's justification is a
  universal negative; the bounded absence test below is good, but not good enough
  to spend near a deadline.

### Deletions, by kind

`delete_manual` — retiring an override upstream has caught up on — is not a claim
about a page. It is a computation the updater already performs
(`manual_matches_upstream`). It would be the one free auto-apply in the system,
**except that the function is wrong in two independent ways** (§8.1, §8.2). Until
both are fixed it must not auto-apply at all; afterwards, require the same verdict
across two consecutive runs, and never auto-delete a `null`-valued override.

Field `null` deletions (the real `NDSS 2026 abstract_deadline: null` case) use a
bounded absence test: the proposal supplies an `absence_scope_quote` — the verbatim
block that *would* contain the field, e.g. the whole "Important Dates" list — and
gate 1 checks that block is on the page and that no date-like token sits within 200
characters of the field's label vocabulary. That converts an unfalsifiable claim
into a checkable one, erring conservative.

---

## 7. Circuit breakers

| breaker | value | why |
|---|---|---|
| max auto-applied / run | 6 | steady state is 0–3; caps a runaway without ever binding normally |
| max proposals / run | 12 | watchlist is ~28 today and most are fine; more is a broken upstream, not 20 findings |
| max deadline shift | 120 days | above the ~4-month gap between cycles at EuroSys/NDSS/DIMVA, well below a 365-day year-offset error |
| max risk-direction shift | 30 days | real extensions run days to weeks; today's entries move 1–14 days |
| oscillation | 2 auto-applies to the same `(title, year, field)` within 28 days that revert to a prior value → permanent quarantine until a human clears it |
| cooldown | 14 days per `(title, year)` after an auto-apply |
| kill switch | Actions variable `AUDIT_AUTO_APPLY=false` → degrades to today's PR-only behaviour, no code change |

**Post-apply verification**, before any push: re-run `update_deadlines.py`, then
`--dry-run` must print `no file changes` **and** `HEALTH: ok`; `audit_lint.py` must
pass; record count must not decrease; no record may lose its `deadline` unless a
proposal said so. Any failure → `git reset --hard`, no push, red run, alert issue.

One terminal commit carrying an `Audit-Proposals: <ids>` trailer, so
`git revert <sha>` is a documented one-step undo.

---

## 8. Existing bugs that must be fixed first

**All fixed as of 2026-08-18**, each with a regression test. Kept here in full
because they are the evidence for why the rest of the design is shaped the way
it is — several of them are *why* auto-apply was unsafe, not incidental
cleanups.

All were verified against the code; several were reproduced by running the
updater against sandbox copies.

**8.1 `manual_matches_upstream` returns True vacuously.**
`update_deadlines.py:546-549` only returns False for fields present in its `checks`
dict. `note`, `start` and `end` are in `MANUAL_FIELDS` but not in `checks`, so an
override setting only those reports "upstream agrees" every run.

**8.2 A `null`-override compares equal to "upstream has no value".**
`canon_deadline_field(None)` and `canon_deadline_field([])` both yield `()`. The
moment upstream transiently drops the fabricated value an override exists to
suppress, the updater declares that override obsolete — and the bad value returns
on the next sync. `AUDITOR.md` priority 3 points straight at this trap.

**8.3 A manual-only record never passes `validate()` but still renders.**
The merge loop only iterates years present in upstream candidates; the second loop
only iterates existing records. A `manual.yml` entry for a manual-only new edition
falls through both — a sandbox entry with `deadline: "March 5, 2027"` and
`timezone: "Banana/Republic"` produced `HEALTH: ok` and touched no data file. But
the frontend loads `data/manual.yml` **directly at priority 0**
(`deadline-tracker.js:12`), so that unvalidated garbage renders on the live site.
This is the single largest correctness gap for auto-filling coverage gaps, and it
means **the applier must run `validate()` itself** — it cannot rely on the updater.

**8.4 `TIMEZONE_RE` accepts any IANA-shaped string.** `"Banana/Republic"` passes
validation; the frontend then fails to resolve it and falls through to the `-12:00`
branch, silently rendering it as AoE. For a real UTC-5 venue that displays the
deadline 7 hours late. The applier needs a **closed timezone allowlist**. Relatedly,
writing `PST` for a Pacific venue breaks DST correctness — the frontend pins `PST`
to `-08:00` year-round; prefer `America/Los_Angeles`.

**8.5 A manual override disables the safety rail.** `build_merged:571` —
`railed = "deadline" not in owned and rail_triggered(...)`. Verified end to end: an
override moving a deadline **+212 days** landed with `HEALTH: ok`, exit 0, no rail.
The rail only ever protected against *upstream*. Auto-applied overrides inherit a
human's trust without a human, which is why the proposal-level rails in §7 are
mandatory rather than belt-and-braces.

**8.6 Coverage-gap warnings never clear via `manual.yml`.** `covered` is built from
existing records plus upstream candidates only. Fill a gap in `manual.yml` and both
the warning and the `coverage-gap` watchlist entry persist forever — so the applier
is re-nominated the same gap every week. **It must upsert by `(canonical key, year)`,
never append**, or it accumulates duplicates until the duplicate-entry `degrade()`
turns the pipeline red.

**8.7 Sunday cron collision.** Tier 1 is `0 21 * * *`, Tier 2 is `0 21 * * 0` — the
same instant every Sunday, in different concurrency groups, so they do not
serialize. Move the audit to `0 23 * * 0`, put both workflows in one concurrency
group, and have the audit `git pull --rebase` **then re-run the updater** before
pushing (a textual rebase of generated YAML is meaningless — the files are a pure
function of `manual.yml` + upstream + `conferences.yml`).

**8.8 Gates run from code the auditor can edit.** `--allowedTools` grants
`Bash(python3:*)` and the workflow runs `audit_lint.py` from the working tree. Split
into two jobs: job 1 emits only `audit-proposals.json` as an artifact; job 2 takes a
fresh checkout and never executes anything the model touched.

**8.9 `audit_lint.py` is blind to untracked files.** It uses
`git diff --name-only HEAD`, which does not list them, while the PR step's
`git add -- deadlines/data` stages them anyway. New year directories legitimately
create untracked files. Use `git status --porcelain`.

**8.10 The converge step lacks `set +e`.** Any unrelated exit-2 degrade — one
ccfddl fetch failing — silently kills that week's audit with no PR and no alert.

**8.11 Token expiry fails green.** No `CLAUDE_CODE_OAUTH_TOKEN` routes to human-mode
issue filing and the job stays green. In auto-apply mode the tracker would quietly
stop self-correcting. Absent token → red + alert.

**8.12 The audit prompt does not actually pin today's date.** It says "Today's date
is in the run environment", but nothing injects it, while `AUDITOR.md` requires
`Verified YYYY-MM-DD` comments. Pass it explicitly.

*Checked and dismissed:* `audit_lint.py`'s comment-run tracker **does** reset at each
`- title:`, so two adjacent entries do not let the second inherit the first's
citation — the second fails, correctly. No fix needed.

---

## 9. Applier constraints

`apply_proposals.py` writes accepted proposals. The non-obvious constraints:

- **Upsert by `(canonical key, year)`, never append** — see §8.6.
- **Run `validate()` yourself**, plus a closed timezone allowlist — see §8.3, §8.4.
- **Reject `year > TODAY.year + 1`.** Outside `FROM_YEAR..TO_YEAR` a record is
  silently never consumed, and the frontend windows identically.
- **`render_record` drops `None`**, so it cannot emit the explicit-`null` deletion
  form. The applier needs its own renderer that delegates to `render_scalar` for
  everything else, so quoting stays byte-identical.
- **`edit_record` on an upstream-backed venue is silently reverted** by the next
  daily sync. Convert such proposals to `upsert_manual` and log the conversion;
  `conferences.yml` is authoritative about the channel, not the model.
- **Citation comment immediately above `- title:`, no blank line** — the lint's
  comment run resets on any blank line.
- **Re-cite on every edit.** The lint is whole-file and freshness-blind, so a stale
  `Verified` date satisfies an edited entry.
- **Round-trip self-test.** `manual.yml` is jointly owned by humans and the applier.
  Before any modification, assert `render(parse(text)) == text` byte-for-byte; on
  mismatch, refuse and exit. Rewriting under a misparse could drop a hand-written
  override — the worst failure available to this system.
- **Unmentioned fields are preserved** on upsert, so a human-pinned `place` survives
  a machine correction to `deadline`.
- **Idempotence** via `canon_record` comparison, so `AoE` ≡ `UTC-12` and `"x"` ≡
  `["x"]` count as no-ops and a re-run produces a zero-byte diff.

Two facts that work in our favour: bot pushes with `GITHUB_TOKEN` do not retrigger
workflows, so an auto-apply push cannot self-trigger a loop; and a `manual.yml` write
causes exactly one data-file change and then stabilises.

---

## 10. What this does not automate

Roughly one case in ten still reaches a human, and the list is short:

- risk-direction changes that miss the extension bar;
- `timezone` deletions and near-deadline deletions;
- override retirements (until §8.1 and §8.2 are fixed, then two-run confirmation);
- pages that are JS-only, PDF-scanned, or bot-blocked;
- anything a circuit breaker or quarantine trips.

Held items still land as a PR on `deadline-audit`, written out by the applier — so
the human reads a diff and clicks merge rather than hand-editing YAML. The PR body
is regenerated wholesale each week, so stale items disappear on their own and no
dedup state is needed.

---

## 11. Build order

The bug fixes are not preparatory chores; several of them are the reason
auto-apply is currently unsafe. Suggested sequence:

1. **Fixes only** — §8.1–8.2, §8.4, §8.6, §8.7, §8.9–8.12. Ship on the existing
   PR-based pipeline and let it run a couple of weeks. Every one of these is an
   improvement even if auto-apply is never enabled.
2. **Proposal schema + applier + round-trip tests** — still PR-based. The auditor
   emits JSON, the applier writes the branch. Same human gate, new plumbing, so the
   diff quality becomes observable before anything is trusted.
3. **Gate 1** — run it in report-only mode alongside step 2 for a few weeks and
   compare its verdicts against what the human actually merged. This is the
   calibration data that tells you whether 0.85 is the right threshold.
4. **Gate 2 + the policy matrix**, with `AUDIT_AUTO_APPLY=false`.
5. **Flip the switch**, R0/R1 only at first, then widen.

There are no tests in this repo today. Steps 2 and 3 add the first ones, and they
are where the real safety comes from — the round-trip and idempotence tests in
particular, because they guard the property that a human's hand-written override
survives a machine write.
