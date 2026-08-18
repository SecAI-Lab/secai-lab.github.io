# Tier 2 auto-apply: design

Status: **§8 fixed and tested (2026-08-18). The rest is a proposal, revised the same day against a probe of all 36 tracked venues.**

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

### Check 4 — label association

Checks 1–3 catch *dishonest* quoting. They do not catch honest quoting of the
wrong thing: an auditor that faithfully quotes
`"Notification of acceptance: February 10, 2026"` and proposes it as `deadline`
grounds perfectly and would be VERIFIED. Since the matrix auto-applies
VERIFIED + UNSURE for R0/R1, and R0 (`tba-upcoming-cycle`) is the highest-volume
path in the system, that gap sits under the busiest auto-apply route.

The value must therefore be **paired** with a field-appropriate label, not merely
near one. Windowing cannot do this, because real CFPs put the label on either
side of the date — `<li>Wed, 23 April 2025: Paper submission deadline</li>`
(NDSS, date first) and `<li><strong>Paper Submission Deadline</strong>: Feb
10</li>` (EuroSec, label first) are both real, in the same element type, with the
same separator. Pairing is resolved by the first rule that applies, and a refusal
by that rule is final:

**A. Declarative table.** A `<table>` whose header row names a date column and a
label column yields pairs directly; ordering is never inferred. Extra columns
become named scopes (tracks), and a proposal not naming its track is refused.

**B. Separator-split container.** Within one `<li>`/`<tr>`/`<dd>`, a single `:`
(or em/en dash) that splits the text so all live dates fall on one side and the
label on the other yields the pair. Order-agnostic by construction, so NDSS and
EuroSec take the same code path.

**C. Block-inferred ordering.** For containers with no separator, infer
date-first vs label-first from the enclosing block and require **unanimity**
across at least two items carrying both. Any dissent refuses the whole block.

**D. Flat text.** Associate a date with the nearest label only when it is within
8 tokens, decisively closer than the other side (difference ≥ 3), separated from
it by no other date, and not competing with another date for the same label.
Otherwise UNCONFIRMED. This is the explicit ambiguity-refusal condition.

Dates inside `<s>`/`<del>`/`line-through` are marked superseded: excluded as
candidates, and a proposal matching one is **REFUTED** rather than merely
unconfirmed — positive evidence the value is stale. Two unconnected live dates
under one label refuse; two joined by `to`/`–` form a range, valid for `date` and
refused for `deadline`.

Per-field label vocabulary:

| field | label must match | must not match |
|---|---|---|
| `deadline` | submission deadline, paper deadline, papers due, full paper, submission due, **submission of regular papers** | notification, acceptance, camera-ready, rebuttal, workshop, poster, demo, tutorial, doctoral, SRC |
| `abstract_deadline` | abstract (registration/submission/due) | — |
| `date` | — | submission, deadline, due |

**The vocabulary must not require the word "deadline".** SAC 2027 publishes
`IMPORTANT DATES … October 2, 2026 (EST) Submission of regular papers` and never
writes "deadline" anywhere on the page; DSN publishes under "Call for
Contributions". Both are fully explicit, and both were false-negatived by a
first-pass classifier that keyed on that one word — which is how SAC was briefly
misdiagnosed as unverifiable.

**Rationale for the ordering rules:** DSN 2027's CFP is a real `<table>` with
`<th>Date</th><th>Milestone</th>` and rows reading
`December 2, 2026 | Paper Submission Deadline`. A label-then-date reading verifies
`January 26, 2027` — the Early Reject Notification, 55 days **late**, the
direction that costs a researcher their paper. Ordering must come from structure,
never from assumption.

### Numeric dates

The surface-form generator must emit **two-digit-year** variants, and resolve a
numeric date deterministically when any component exceeds 12 (`11/20/26` can only
be Nov 20 2026). Where no component disambiguates, the form stays `ambiguous` and
cannot verify alone. Without this the strongest available evidence for EuroS&P
2027 — the IEEE TC calendar's `Submission deadline: 11/20/26` — fails to parse at
all.

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
  latest possible reading. Permanent, no exceptions — see below.
- **Risk-direction changes that miss the §5 extension bar.**

### Deletions

Earlier drafts refused all deletions, on the argument that a deletion's
justification is a universal negative and quote-grounding proves presence, never
absence. That argument is beatable, and beating it removes the last structural
reason to keep a human in the loop.

The claim a deletion actually needs is not *"this page has no abstract
deadline"*. CFPs do not scatter milestones through prose — they publish an
**enumeration**. The real claim is:

> The milestone enumeration containing the paper deadline we independently
> verified contains no abstract entry.

That is bounded and decidable. The verified paper deadline proves *which* list is
authoritative, and that step is what converts the universal negative into a finite
one.

**Structural support (S).** Extract enumerations from the DOM (`<table>`, `<dl>`,
`<ul>`, `<ol>`), qualifying a block only when ≥3 items each carry exactly one date
span and ≥2 distinct dates appear. A block is *authoritative* iff one item carries
a date equal to our independently verified `deadline` with a matching label (the
anchor), the block holds ≥3 recognised CFP milestones, and all its dates fall
inside `[deadline − 18 months, conference end + 6 months]`. Deletion of field `F`
is structurally supported iff an authoritative block exists, **no** item in **any**
qualifying block on the page carries an `F` label, and no `F`-vocabulary
occurrence outside the enumerations sits within 200 characters of a date.

**Cross-edition prior (P).** Computed from *upstream candidates*, not merged data
— the merged record already has the override applied, which would be circular —
and restricted to the same source. With `E` = other editions where that source
gave a concrete deadline and `A ⊆ E` those where it also gave an abstract:
`SUPPORTS` if `|E| ≥ 3` and `|A| = 0`; `OPPOSES` if `|A|/|E| ≥ 0.5`; else
`NEUTRAL`. The `|A| = 0` threshold is deliberate: "never, across ≥3 editions" is
categorically different from "usually not".

**Corroborators.** Cross-source absence (only one tracker supplies the value), and
a synthetic-offset fingerprint (every cycle's `deadline − abstract` identical and
in {7, 14} days, consistent with mechanical derivation rather than transcription).
Corroborating only, never decisive.

```
auto-apply a field-null deletion iff
    S and P                          (both mandatory, no substitute)
    and (cross-source or fingerprint)
    and field != "timezone"
    and the affected deadline is > 45 days away
    and evidence is T0/T1 (6.1 - a publisher stub cannot bound an absence)
    and no breaker / quarantine / cooldown applies
```

S and P are independent in kind — one reads the world, one reads history.
Requiring both means a deletion needs a page that structurally lacks the field
*and* a venue that has never had it.

Worked on the live case: NDSS 2026's CFP has **0 tables, 15 date-bearing `<li>`
items across two cycle blocks, each anchored by a verified paper deadline**, and
the word "abstract" appears **exactly once on the page** — in prose, advising
authors how to write one. ccfddl reports no abstract for NDSS 2024, 2025 and
2027, fabricating only for 2026 at exactly deadline − 7 for both cycles. So
S ∧ P ∧ (cross-source ∧ fingerprint) → auto-applies. The same machinery
**refuses** DSN 2027, whose table row reads `November 25, 2026 | Abstract
Submission Deadline`.

**`timezone` deletion stays permanently manual.** Not caution: the frontend
renders a missing timezone as AoE, so a correct-but-unverifiable deletion and a
wrong one fail identically, both in the direction that costs a paper. The
structural test barely applies anyway — timezones live in footers and
parentheses, not enumerated milestones, so the anchor has nothing to bind to.

**`delete_manual`** — retiring an override upstream has caught up on — is a
repo-state computation, not a page claim. Now that `manual_matches_upstream`
returns False for vacuous and `null`-valued matches (§8.1, §8.2), its True is
finally meaningful. Auto-retire needs no model gate at all, but does require the
same verdict on two consecutive runs, since one run's agreement can reflect a
transient upstream state and waiting a week costs nothing.

### 6.1 The evidence ladder

A binary "official page or nothing" rule refuses whenever the front door is shut,
even when the venue's own words are available by another permitted route.

| Tier | Source |
|---|---|
| **T0** | the venue's own site, fetched live, robots-permitted |
| **T1** | the venue's own content by another permitted transport: GitHub Pages **source repo**, RSS/Atom, sitemap-discovered CFP subpage, JSON-LD |
| **T2** | the publisher's own CFP record: `ieee-security.org/Calendar/cfps/`, `sigapp.org`, `usenix.org`, `sigsac.org`, `conf.researchr.org` |
| **T3** | an archived snapshot of the venue's **own** T0 URL |
| **T4** | community trackers — context only, never evidence |

T3 answers the red team's archive objection by construction: a snapshot keyed to
the exact T0 URL is a timestamped observation of the official page, not a mirror,
and the classifier verifies that URL identity mechanically. A snapshot of an
aggregator never reaches T3, because its original does not classify as T0.

T1 carries something no other tier does: a source repo has commit history, so it
can distinguish "this value is new" from "this value has been stable for a year"
— the signal the extension rule in §5 needs.

**Independence.** T1 *substitutes* for an unreachable T0; it never corroborates
it, because a repo and the page it renders are one source. Likewise T3 against its
own T0. Two sources also fail independence on a shared registrable domain or ≥0.9
text similarity. Real independence means T0/T1 + T2, or T2 + T3 from a different
original.

**Corroboration required, by risk tier:**

| tier | safe-direction | risk-direction |
|---|---|---|
| R0 / R1 | 1× T0/T1/T2, or 1× T3 in bound | 1× T0/T1, or T2+T3 independent + extension token |
| R2 | 1× T0/T1, or T2 + one independent corroborator | T0/T1 required + refuter CONFIRMED |
| R3 | 1× T0/T1, or T2 + blind-extractor agreement | T0/T1 required + blind extractor + ≤30d shift |
| R4 deletion | **T0/T1 only** | never |

**Staleness bounds** (T1 by last commit touching the file, T2 by listing mtime, T3
by snapshot timestamp), as R0-R1 / R2 / R3: T1 90/30/14 days · T2 120/45/reject ·
T3 180/60/reject.

Archive staleness is *safe-direction-biased*, which is the whole reason T3 is
admissible. A snapshot can only lag the live page, and the change it most often
misses is an extension — which moves a deadline later. So a stale snapshot
systematically errs toward showing an *earlier* deadline than truth, the harmless
direction. That is exactly why T3 is allowed for safe-direction work and refused
for risk-direction: there, the staleness that makes it safe elsewhere becomes the
failure mode.

**Conflict:** lower tier wins, except that a *newer, weaker* source disagreeing in
the risk direction forces HOLD — that is the signature of a just-announced
extension, and we cannot tell whether T0 is stale or T2 is wrong. Any conflict at
all on an R3 record holds. Every conflict is logged with both quotes, because a
recurring T0/T2 disagreement is how you discover a publisher record gone stale.

**Quote-grounding applies at every tier, unconditionally.** Tier answers "is this
page entitled to speak for the venue"; grounding answers "did the model read it,
or invent the value". Hallucination is tier-independent, so dropping grounding at
T2 would give the most authority-laden sources the least verification. Two
tier-specific additions: at T2 the quote must come from the per-venue file, never
the index (the TC calendar index lists 1,761 CFPs), and the URL must match
`^cfp-<venue><year>\.html$` **anchored** — as a substring, `DSN` matches
`cfp-DSN-WACS.html`. At T3, ground against the archived bytes and record the
snapshot timestamp and a digest, which makes T3 the most auditable tier after the
fact.

### 6.2 Corroboration state, for records nothing can verify

Verification is not the only decision available. We cannot automatically *verify*
an uncorroborated deadline, but we can automatically *observe* that it is
uncorroborated, classify the record, and act on that. The fact stays unverified;
the decision stops being a human's.

Per `(title, year)` each run: `NOT_APPLICABLE` (no concrete deadline) ·
`VERIFIED_OFFICIAL` (T0/T1 grounds it) · `CORROBORATED_SECONDARY` (T2/T3 grounds
it) · `TRACKER_ONLY` · `NO_SOURCE` (not even a tracker) · `CONTRADICTED` (a source
grounds a *different* value, which feeds the normal proposal path).

State lives in a machine-owned sidecar, `deadlines/data/corroboration.json`, read
as a **fourth input** to `update_deadlines.py`. Not in `manual.yml`: that is the
human override channel, and machine bookkeeping there would be indistinguishable
from a verified human decision, would be swept by `manual_matches_upstream`, and
would mark `note` as `owned`, permanently disabling `maybe_clear_stale_note`. As
an input, generated files stay a pure function of their inputs and there is
exactly one writer. The file is committed, so `git log` on it is the metrics
history.

A `TRACKER_ONLY` / `NO_SOURCE` record gets a bracketed suffix appended to whatever
note it already has (57 of 123 records have one):

```
<existing note> [unconfirmed: deadline from community trackers; no official CFP page found]
```

A single strip rule (`\s*\[unconfirmed:[^\]]*\]\s*$`) governs the lifecycle: the
annotator strips, recomputes and re-appends every run, so it is idempotent and can
never mangle the human half. **No date in the text**, or every annotated record
diffs weekly.

Two constraints on the wording, both verified against the code:

- It must not match `STALE_NOTE_RE`. "CFP not yet announced" and "official CFP
  not available" both match, and a matching note re-nominates that record to the
  watchlist *every run, forever*.
- It must not match `deriveAbstractFromComment` (`deadline-tracker.js:131`),
  which **fabricates** an abstract deadline at paper − 7 days when a note matches
  `/abstract.*1 week before|1 week before.*abstract/i`. The annotation avoids the
  word "abstract" entirely.

**Hysteresis:** demotion needs 2 consecutive confirming observations, promotion
takes 1. The asymmetry is the point — promotion carries proof (a grounded quote),
demotion is merely an absence of proof. An UNREACHABLE observation never promotes
and never removes an annotation. Annotations are added at most once per record per
21 days and removed immediately, always. A record whose state changes 3+ times in
56 days is frozen at the more cautious state until stable for 28 days.

**Inside 45 days, escalate effort, not severity.** Never suppress the value:
showing nothing reads as *not announced*, which is more wrong and less actionable
than an unverified date. Instead the note switches to an imperative form, the
probe moves to daily cadence in the Tier-1 run so a newly published CFP clears it
within a day rather than a week, and auto-apply is refused for that record.

### 6.3 Fetch policy

Reach depends entirely on fetching correctly, and three traps here are each
capable of silently disabling large parts of the ladder.

**One honest user agent, always.** `secai-lab-deadline-auditor/1.0
(+https://secai-lab.github.io/deadlines/)`, never a browser string. Retrying a
refusal with a different identity is both a circumvention of the host's stated
wishes and — as DFRWS proved — counterproductive: it reads as abuse to a rate
limiter and turns a transient 403 into a persistent one. A verifier that lies
about who it is cannot be the foundation of a system whose purpose is
establishing truth.

**Spaced retries, and `Disallow` ≠ blocked.** Back off 0 / 5 / 30 s and honor
`Retry-After`. Then distinguish two things that look alike and mean opposite
things:

- a `robots.txt` **Disallow** is the owner's *policy*. Stable, final, maps to
  `REJECTED_SOURCE`. Retrying is a violation.
- a **403/429 while robots permits** is an *operational* condition — rate
  limiting, a WAF heuristic. Transient, maps to `UNREACHABLE`, retried later.

Conflating them is exactly what produced the false "dfrws blocks bots" belief
that was written into `AUDITOR.md` and had to be retracted.

**`urllib.robotparser` fails dangerously closed.** `RobotFileParser.read()`
fetches with the default `python-urllib` UA. USENIX's WAF 403s that, and the
parser then sets `disallow_all = True`, so **every** USENIX path reports as
forbidden. Verified: with the default UA,
`can_fetch(".../conference/osdi27/call-for-papers")` returns `False`; fetching
`robots.txt` with our own UA and calling `parse()` returns `True` with
`Crawl-delay: 10`. A naive integration would silently lock the auditor out of
OSDI, ATC, NSDI, USENIX Security and WOOT while reporting a policy that does not
exist. **Fetch `robots.txt` with the same honest UA, and treat a 403 on
`robots.txt` itself as "unknown", never as "disallow all".**

**Honor `Crawl-delay`.** It is not decorative and it is not uniform:
`usenix.org` asks 10 s, `sigapp.org` asks **20 s**. Per-host pacing must read the
declared value rather than assume a floor.

**Conditional requests.** Store `ETag` / `Last-Modified` per URL. A **304** is
evidence, not just saved bandwidth: it proves the page has not changed since the
last verification, so a previously VERIFIED value is still current and the record
can be skipped entirely this run.

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

Every venue that looked unautomatable turned out to be a defect in our own
checking tools rather than a property of the world. All 36 tracked venues were
probed on 2026-08-18; the three that failed were:

| venue | looked like | actually was |
|---|---|---|
| **SAC 2027** | no CFP; own links 404 | its landing page carries `IMPORTANT DATES … October 2, 2026 (EST) Submission of regular papers`, grounding both the stored deadline and the `UTC-5` override. Missed because the classifier's label vocabulary required the word "deadline", which that page never uses |
| **DFRWS EU** | bot-blocked (403) | `robots.txt` is `User-agent: * / Disallow:` — everything permitted. The 403 was rate limiting provoked by retrying immediately with a different user agent. One honest UA and spaced retries returns 200 with the deadline table |
| **EuroS&P 2027** | tracker-only, official site is "Coming soon" | already corroborated at T2: `ieee-security.org/Calendar/cfps/cfp-EuroSnP2027.html` states `Submission deadline: 11/20/26`, matching the stored value — and the record's own `note` already said so |

That is the honest headline for these three: **the residue was our bugs, not the
web.** Each was a false negative of a label vocabulary, a fetch policy, or a
source classifier — worth remembering next time something looks structurally
impossible. Check the tool before concluding it about the world.

But do not over-read it. Those are three venues probed on one day. A further 15
were classified "nothing to verify yet", because their 2027 editions have no CFP
at all — they were never tested against a real page. When CCS, SOSP, ESORICS and
the rest publish, some fraction will land in prose, in an image, or in a
structure rules A–D do not handle, and the residue will grow again. The claim
established here is that three specific blockers dissolved, not that the web is
uniformly machine-readable.

What genuinely stays manual, after all of the above:

- **`timezone` deletion**, permanently. The frontend renders a missing timezone
  as AoE, so a correct-but-unverifiable deletion and a wrong one fail
  identically, in the direction that costs a paper.
- **A field no authoritative source has stated.** EuroS&P 2027's timezone is the
  live example: the T2 stub gives a date and no zone, and the design forbids
  defaulting one. This is not a tooling limit — there is nothing to verify yet.
- **Risk-direction changes that miss the §5 extension bar**, and anything a
  circuit breaker, cooldown or quarantine trips.
- **Deadlines published only in prose or in an image**, where no enumeration
  exists to anchor against; and **venues with fewer than 3 prior editions**,
  where the cross-edition prior cannot form.
- **Genuinely varying venues.** CCS, ESORICS and EuroS&P have added and dropped
  abstract deadlines between editions, so the prior correctly refuses — and
  correctly keeps refusing.

Held items still land as a PR on `deadline-audit`, written out by the applier, so
a human reads a diff and clicks merge rather than hand-editing YAML. The PR body
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
