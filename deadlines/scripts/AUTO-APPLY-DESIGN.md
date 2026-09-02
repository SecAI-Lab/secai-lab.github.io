# Autonomous deadline audit: implementation and design record

Status: **The autonomous sharded publisher is live. Sections explicitly marked
historical or exploratory are rationale only, not descriptions of the deployed
workflow. The current operational flow is summarized in §§6, 7 and 11.**

The design below records the threat model and trade-offs that led to the live
implementation. The publisher now verifies official citations independently,
persists bounded retry/corroboration state, and writes the default branch without
a human data-review step.

Goal: the weekly verification audit publishes verified corrections straight to
master with no human in the loop, without ever publishing a wrong deadline.

Those two halves pull against each other at exactly one point — a change nothing
can mechanically verify. Everything below is about shrinking that set to near
zero rather than pretending it is empty.

---

## 1. Historical baseline — why the old design stopped at a PR

Before the autonomous pipeline, the auditor edited YAML directly and
`audit_lint.py` was the only automated check. It checked the write allowlist and
required a `Verified` comment with a URL, but did not fetch that URL or prove it
said the proposed value.

At that time the PR was the only claim-checking step. That baseline is retired:
the model now writes untrusted JSON, the deterministic verifier re-fetches and
grounds each citation, and the publisher either applies, defers, or refuses the
result without creating a conference-fact review PR.

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
        {"for_value": "2025-12-10 23:59",
         "quote": "Submission deadline (cycle 1): 10 December 2025 (extended!)"},
        {"for_value": "2026-02-18 23:59",
         "quote": "Submission deadline (cycle 2): 18 February 2026 (extended!)"}
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
- acceptance becomes per independently safe field group instead of per-diff;
  multi-cycle deadline evidence is explicitly bound to one concrete value.

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
and translate hosts. The proposed URL and the current record's link never create
authority by themselves. Strong trust comes only from immutable repository
evidence: configured `official_hosts`, older same-title committed hosts,
directional descendants of those hosts, exact hosts independently nominated by
two upstream datasets, or an organizer parent evidenced by at least two distinct
conference titles. An annual hostname rewrite is strong only when the year label
is below an unchanged, positively established parent; registrable-domain rewrites
and hosted-tenant siblings such as `github.io` and `hotcrp.com` are refused.

An exact host nominated by one immutable upstream is classified `provisional`,
not trusted. It is scoped to that title/year and its redirects cannot leave the
nominated host. A mutation needs the identical normalized fact and the same
provenance-bound SHA-256 basis on two scheduled audit dates at least six days
apart. Page conference/year identity is checked after every fetch for every
trust class.

Redirects are followed but the **final** URL is re-classified, so an official
host redirecting onto a tracker fails.

**UNREACHABLE is never VERIFIED.** TLS errors are not bypassed; bot-blocked sites
(`usenix.org`, `dfrws.org`) are reported, not worked around.

---

## 4. Exploratory Gate 2 — not deployed

This section records an evaluated refuter design. Production does **not** run
`REFUTER.md`, a blind extractor, or a second model as publication authority. Its
second Claude invocation is one bounded repair retry guided by deterministic
preflight diagnostics; the write-capable job then re-fetches and verifies all
citations independently.

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

The citation gate answers *"is this value on an admissible official page"*.
The risk policy separately asks *"what does being wrong cost"*. Define the
**effective instant** = date + clock time + timezone offset. Then:

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

Clock time is treated conservatively. `23:59` may be the repo's end-of-day
normalization when the page states no clock, but an explicit clock on the page
must agree with the proposed minute. A mutating deadline, abstract-deadline, or
timezone claim must also carry the complete effective-instant field group, so a
partial quote cannot move the rendered instant by omission.

### Extensions

The live one-run bound accepts a fully grounded later shift of at most 30 days
and an earlier correction of at most 120 days. A larger shift is not sent to a
person: the existing value stays published while a hash of the normalized claim
is retained. The identical VERIFIED claim may promote after a second scheduled
observation at least six days later. The extension-token/refuter/blind-extractor
scheme described in earlier revisions was never deployed.

---

## 6. Live policy

There is no refuter matrix, residual review PR, or human fact queue. The
deterministic verifier and applier produce these outcomes:

| evidence and mutation | live outcome |
|---|---|
| all fields VERIFIED on a strongly trusted source; values already match | confirm/no-op and resolve the matching retry scope |
| strongly trusted, VERIFIED mutation inside one-run bounds | apply, subject to the stable per-run change budget |
| strongly trusted, VERIFIED mutation outside one-run bounds | keep existing fields and retain a value-free retry plus claim hash; promote only after the identical claim verifies on a second scheduled date at least six days later |
| provisional exact source, VERIFIED mutation | the same two-run rule, additionally bound to the immutable source-provenance digest |
| some fields VERIFIED and others not | apply only independently safe verified field groups; keep the rest unchanged and queued; effective-instant fields stay atomic |
| `UNCONFIRMED`, `UNCHECKED`, `UNREACHABLE`, or `REJECTED_SOURCE` | keep existing fields and persist their retry scope; telemetry records the reason |
| malformed schema, corrupt state, failed exact coverage, or failed convergence | fail the run and publish nothing |

`timezone: null` is rejected by the proposal contract because the frontend
would reinterpret it as AoE. Retiring an entire manual override (`delete_manual`)
requires agreement from every healthy configured deterministic upstream and the
same provenance-bound result on two scheduled audit dates.

### Deletions — historical exploration, not deployed

The structural absence algorithm below was considered but is not part of the
live publisher. Valid field deletions instead use the same citation and bounded
two-run machinery as other out-of-bound mutations; timezone deletion remains a
schema error. Nothing in this historical subsection creates a manual review
queue.

Earlier drafts refused all deletions, on the argument that a deletion's
justification is a universal negative and quote-grounding proves presence, never
absence. The remainder of this subsection records the structural algorithm that
was explored to answer that objection; it is not production behavior.

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

**Current timezone behavior:** `timezone` deletion is rejected by proposal
validation. The frontend renders a missing timezone as AoE, so a
correct-but-unverifiable deletion and a wrong one fail identically, both in the
direction that costs a paper. It is retained, not placed in a manual queue.

**Current `delete_manual` behavior:** retiring an override after upstream has
caught up is a repo-state computation, not a page claim. It requires complete
agreement from every healthy configured deterministic upstream, a
provenance-bound basis digest, and the identical result on two scheduled audit
dates at least six days apart.

### 6.1 Exploratory evidence ladder — not deployed

The tier ladder in this subsection is retained as research context. Production
uses the typed host policy in §3; it does not fetch archives, publisher stubs,
or source repositories as alternative evidence tiers.

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

### 6.2 Live retry and corroboration state

The machine-owned sidecar `deadlines/data/audit-state.json` contains two bounded
maps: value-free retry scopes and SHA-256 fingerprints of already-VERIFIED
claims awaiting a second observation. It stores no model prose, quotes, source
URLs, or unverified values. Provisional claims add the verifier's immutable
source-provenance digest to the fingerprint.

Promotion requires the same normalized identity, action, field scope, values,
and any required provenance basis on two scheduled audit dates at least six days
apart. A changed claim restarts that scope's observation count. Disjoint field
scopes survive independently; a later strong no-change or applied correction
resolves only the matching scope. The file is capped and pruned to the rendered
year window, and invalid or corrupt state fails publication closed.

Citation failures, unverifiable sources, and change-budget overflow add retry
scopes. `update_deadlines.py --watchlist` carries those identities into later
weekly audits, so deferral cannot disappear when a stored deadline passes or a
calendar year rolls over. This is operational state and telemetry, not a review
queue and not a user-visible uncertainty annotation.

### 6.3 Live fetch policy

The verifier always identifies itself as
`secai-lab-deadline-auditor/1.0 (+https://secai-lab.github.io/deadlines/)`. It
fetches `robots.txt` with that same user agent; a failure to fetch the policy is
unknown rather than an invented `disallow_all`. A real path disallow is not
circumvented. Permitted source requests use bounded 0/5/30-second retries for
transient HTTP failures, a per-host pacing floor, a 25-second request timeout,
and a 5 MiB response cap.

Immediately before every robots, page, and redirect request, the verifier
resolves all A/AAAA answers and requires every returned address to be globally
routable. Failed or empty lookups, mixed public/private answers, and common
wildcard-to-IP helper domains fail closed. `urllib` performs its own resolution
again when it connects, so a narrow DNS-rebinding time-of-check/time-of-use gap
remains; eliminating it requires an address-pinned HTTP/TLS transport that still
preserves the original Host header and SNI.

Every redirect is checked before it is followed and again after the fetch.
Strong sources may move only within their directional trusted host boundary;
provisional sources are confined to the exact nominated host. Fetch or robots
failures remain non-VERIFIED and are retried by the scheduled pipeline.

Earlier drafts proposed `Retry-After`/`Crawl-delay` persistence, conditional
`ETag` requests, and archive/source-repository transports. Those refinements are
not deployed and must not be inferred from this document.

---

## 7. Circuit breakers

| live rail | value | effect |
|---|---|---|
| applied field-group changes / run | 8 | a stable prefix applies; overflow is recorded in retry state for later weekly runs |
| one-run earlier deadline shift | 120 days | larger wrong-cycle corrections require an identical second VERIFIED observation |
| one-run later deadline shift | 30 days | larger extensions require an identical second VERIFIED observation |
| corroboration | 2 scheduled dates, at least 6 days apart | risky, destructive, or provisional mutations cannot promote twice in one run |
| source boundary | typed trust plus conference/year page identity | redirects, model-only domains, annual registrable-domain rewrites, and tenant siblings fail closed |
| state bound | 500 identities/claims, rendered-year pruning | corrupted or unbounded retry state refuses publication |

There is no `AUDIT_AUTO_APPLY` PR-mode switch. The operational emergency stop is
to disable the GitHub Actions workflow (or revoke its write credential); that
stops publication rather than routing conference facts to a person. Missing
model credentials and all other infrastructure failures produce the normal
pipeline alert.

Before any push, the updater must converge, its second dry run must report no
file changes, and `audit_lint.py` must pass. The publisher also refuses stale
inputs, rebases onto the current default-branch tip, reruns convergence and
linting after the rebase, and pushes directly as `github-actions[bot]`. Any
failure leaves the default branch unchanged and retains the run telemetry.

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

**8.11 Token expiry fails green.** No `CLAUDE_CODE_OAUTH_TOKEN` routes to the old
review-only issue fallback and the job stays green. In auto-apply mode the tracker would quietly
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
- **Round-trip self-test.** `manual.yml` is pipeline-owned but can contain legacy
  curated entries. Before any modification, assert `render(parse(text)) == text`
  byte-for-byte; on mismatch, refuse and exit. Rewriting under a misparse could
  drop an existing override — the worst failure available to this system.
- **Unmentioned fields are preserved** on upsert, so a previously pinned `place`
  survives a machine correction to `deadline`.
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

What remains automatically deferred:

- **`timezone` deletion** is a schema error. The frontend renders a missing
  timezone as AoE, so the existing value is retained.
- **A field no authoritative source states** is omitted from the proposal or
  kept unchanged with a citation retry scope. The pipeline never guesses a
  missing timezone, city, date, or deadline.
- **A rejected or unreachable source** cannot contribute field evidence. The
  bounded retry repairs source identity/reachability first; if that fails, the
  result remains in telemetry and on a later scheduled watchlist.
- **A VERIFIED mutation outside one-run bounds**, a provisional source
  mutation, and `delete_manual` wait for their respective provenance-bound
  second scheduled observation.
- **Change-budget overflow** keeps its existing fields and advances in stable
  order on later weekly runs.
- **Image-only, JavaScript-only, ambiguous, or not-yet-published evidence** is
  recorded as unverifiable and retried automatically when nominated again.

Deferred facts do not create a branch or PR. The committed `audit-state.json`
keeps only bounded retry scopes and verified claim fingerprints; run artifacts
retain detailed telemetry. GitHub issues are reserved for pipeline/lifecycle
failures, not conference-fact approval.

---

## 11. Deployed execution order and tests

The live weekly workflow runs in this order:

1. A read-only prepare job runs every deterministic unit suite and the workflow
   simulation, builds the complete watchlist, and publishes immutable shards.
2. Read-only Claude shards produce untrusted JSON. A deterministic first-pass
   schema/citation preflight can trigger one bounded repair attempt. Exact-once
   identity coverage is required, but raw `not_checked` checkpoints remain
   explicitly unfinished rather than aborting independently useful shards.
3. A fresh write-capable job downloads only the immutable watchlist and completed
   shard artifacts, validates and merges them, and independently reconciles all
   negative source claims. In the same trusted process it replaces residual
   checkpoints with value-free `machine_deferred` identities, distinguishes
   source claims invalidated by that reconciliation from untouched seed records,
   and rejects a global zero-substantive-work run. Machine deferrals never count
   as examined and remain scheduled, while safe findings continue to publication.
   It then independently re-fetches every proposed citation.
4. The field-group applier enforces typed source trust, atomic effective-instant
   context, one-run bounds, provenance-bound corroboration, and the stable
   eight-change budget while updating `audit-state.json`.
5. The updater converges, lint and branch-drift gates run, the result rebases and
   is checked again, and eligible data is pushed directly to the default branch.
6. Telemetry artifacts are uploaded on every outcome. A lifecycle job opens or
   updates only infrastructure-failure alerts and closes them after a healthy run.

The repository has offline regression suites for update/render behavior, lint,
proposal validation/application, audit state, shard merging, outcome
reconciliation, risk policy, citation/source trust, and both daily and weekly
workflow contracts. The workflow runs all of them before invoking Claude; the
commands are listed in `deadlines/scripts/README.md`.
