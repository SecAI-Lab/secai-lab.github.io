# Deadline auditor instructions

You verify this lab's conference deadline records against OFFICIAL sources and
report findings as JSON. You do not edit repository data — a deterministic
program (`apply_proposals.py`) applies your findings after machine-checking
every one of them.

**Write exactly one file: `audit-proposals.json` at the repository root.**
Do not edit anything under `deadlines/`. Do not commit, push, create branches,
or invoke repository-hosting operations. A separate step checks that you
touched nothing else and fails the run if you did.

**Write that file on every run, without exception — including when you find
nothing wrong.** Finding nothing is a normal, good outcome, but it is reported
by writing the file with an empty `proposals` array (plus `no_change` entries
for what you checked), never by writing nothing. A run that produces no file is
failed: it cannot be told apart from a run that did no work, so it is treated as
the latter. If you are about to finish without writing the file, stop and write
it.

**Attempt every watchlist record.** Verify each one with real fetched quotes or
record the concrete reason its official evidence could not be obtained. During
the run you may use `not_checked` as a temporary checkpoint for work that is
still pending, but replace every such entry before finishing. An output that
still contains `not_checked` is incomplete, is retried once, and is rejected if
the retry does not finish it.

**Account for every watchlist record.** Each one appears exactly once, either in
`proposals` (with any action, `no_change` included) or in `unverifiable`. A
record you skipped silently is reported as an error. An unavailable page is a
valid result, but use the specific cause that describes the attempted check.

On a completion retry, `audit-preflight.json` may exist beside the proposal
file. It is read-only diagnostic output from the deterministic citation gate.
Inspect each verdict's top-level `detail.status` first.
`REJECTED_SOURCE` and `UNREACHABLE` are source/reachability failures and may
have no field results at all. Repair those first: fetch the correct admissible
official page for this conference edition. If no permitted official page is
reachable, remove that proposal and account for the identity in `unverifiable`
with the specific cause. Do not keep rewriting quotes against a rejected or
unreachable source. Only after the source is admitted and fetched should you
repair each entry in `detail.fields` whose status is not `VERIFIED`, using the
exact reason it gives. Preserve already verified fields when the source remains
appropriate.
Never edit the preflight file: the publisher discards it and independently
fetches every citation again.

## Input

`watchlist.json` at the repo root: the records worth checking this week. Each
item has `title` (the canonical key — reuse it verbatim), `year`, `reasons`,
`file`, and the current `record` values.

## The contract that decides whether your work is used

Every value you propose must be backed by a `quote` **copied
character-for-character from a page you fetched this run**. Copy and paste it;
do not retype it from memory, and do not tidy it up.

- A paraphrase fails. "The deadline is Feb 10" when the page says
  "Paper Submission Deadline: February 10, 2026 (AoE)" is a paraphrase.
- **Quote the whole row — label and value together.** Many CFPs are tables, and
  once the markup is stripped the label and the date land on separate lines. A
  quote of just the date is refused ("almost entirely the date itself") and so
  is a quote of just the label. Quote across the cells: `Paper Submission
  21 August 2026 (AoE)`.
- The quote needs at least two words that are not part of the date, so that
  what the date *is* can be identified from the quote alone.
- For `place` and conference `date`, copy the surrounding venue/header row
  (`Venue: Rabat, Morocco`, `Conference dates: April 19-23, 2027`), not a bare
  city or bare date. Short values without their meaning are deliberately
  refused.
- If a value exists only in an image, a scanned PDF, or JavaScript you cannot
  read, you have no quote. Record it under `unverifiable`.

## Ground rules

1. **Official sources only.** The venue's own site, its official CFP page, or
   the publisher/TC's own CFP calendar (e.g.
   `ieee-security.org/Calendar/cfps/`). `ccfddl`, `sec-deadlines`, WikiCFP and
   conferencelists are context, never evidence.
2. **Never invent.** If you cannot confirm a field, omit it. Omitting is always
   safe; guessing never is.
3. **Fetched this run.** Not memory, not training data. Today's date is given
   to you in the prompt — use it.
4. **Unreachable means UNVERIFIABLE.** Make no proposal; add an `unverifiable`
   entry instead.
5. **Propose only fields you can quote.** Fields are gated independently, while
   a correction to `deadline`, `abstract_deadline`, or `timezone` needs the
   complete effective-instant group: quote `timezone` plus every paper/abstract
   deadline field already present or being proposed. Omitting a member does not
   make the remainder independently applicable; the deterministic applier keeps
   the whole correction for a later retry.
   In particular, do not copy every field from `record` into a `no_change`
   result. A `no_change` proposal may contain a strict subset: include only the
   fields this official page actually states and that your quotes prove.

## Actions

- `upsert_manual` — a field is wrong or missing on an existing record. The
  normal case, and the right choice when unsure.
- `create_record` — no record exists for this edition at all
  (`coverage-gap`). Requires at least a `deadline`.
- `delete_manual` — an existing override is obsolete because upstream now
  agrees. Set `"obsolete_because": "upstream_agrees"`; no web evidence needed,
  the program checks this against the immutable static-updater marker and
  requires the same result on two distinct weekly runs. If the override is
  *wrong* rather than obsolete, use `upsert_manual` with corrected values.
- `no_change` — you checked and the record is correct. Emit these; they are how
  the run shows its coverage. **They carry the same evidence as a correction**:
  `source_url`, and a `fields` map holding the values you verified — the ones
  already in the record — each with its quote. It is normal to verify only a
  subset of the record. "This is already right" is a claim about a page like
  any other, and an unevidenced one cannot be told apart from not having looked.

## Field formats

| Field | Format |
|---|---|
| `deadline`, `abstract_deadline` | `"YYYY-MM-DD HH:MM"`, an array for multi-cycle venues, or `"TBA"`. **Each cycle in an array needs its own quote** — one quote cannot evidence two cycles |
| `timezone` | `AoE`, `UTC+9`, `UTC-5`, `PST`, or an IANA name like `America/Los_Angeles` |
| `place` | `"City, Country"` |
| `date` | `"April 27-30, 2026"` or `"June 29 - July 3, 2026"` |
| `link` | `https://…` |
| `note` | one line, no newlines |

Deadline times are local to `timezone`. A CFP saying "February 10, 2026 (AoE)"
is `deadline: "2026-02-10 23:59"` with `timezone: "AoE"`. Prefer
`America/Los_Angeles` over `PST` for Pacific venues — the page pins `PST` to
-08:00 year-round and gets DST wrong. Do not propose `start`/`end`; they are
derived from `date`.

For a multi-cycle deadline, make the binding explicit on every evidence item:

```json
"evidence": [
  {"for_value": "2026-05-14 23:59", "quote": "Full paper submissions due: Thursday, May 14, 2026"},
  {"for_value": "2026-09-24 23:59", "quote": "Full paper submissions due: Thursday, September 24, 2026"}
]
```

Copy each row separately. Do not use one large quote containing both dates and
do not reuse the first-cycle quote for the second cycle.

## Deleting a field

Some CFPs have no abstract deadline while upstream trackers invent one. To
delete a field, set `"value": null` **and** supply `absence_scope_quote`: the
verbatim block that *would* contain it — usually the whole "Important Dates"
list. verify_citations.py grounds that block on the page and then checks, inside
that block only, that no date sits near the field's label. A fragment will not
do - quote the whole block.

`timezone` is never deleted automatically. A missing timezone renders as AoE,
i.e. later than the truth. Leave the stored value unchanged and do not propose
a deletion; retain the official source in the record's audit result.

## Priorities (work top-down; stop when the watchlist is exhausted)

1. `deadline-within-45-days` — an error here costs someone a submission.
2. `audit-deferred` — retry a correction retained by a prior evidence, safety,
   or per-run budget gate; this persists across edition-year boundaries.
3. `tba-upcoming-cycle` — has a CFP been announced? The most common real finding.
4. `manual-override-active` — re-verify; propose `delete_manual` if obsolete.
5. `cross-source-disagreement` — the official page is the tiebreaker.
6. `stale-placeholder-note` — refresh notes whose claims have aged out.
7. `coverage-gap` — `create_record` if an official page now exists.
8. `tba-metadata` — the deadline is known but `place`, `date` or `timezone` is
   still TBA. Lowest stakes, but nothing else nominates these records, so they
   stay TBA indefinitely unless this pass fills them. The publisher's CFP
   calendar often has the city before the venue's own site does.
9. `scheduled-full-audit` — routine coverage for every current or future
   edition. Check these too; persisted `audit-deferred` state carries unresolved
   older editions independently of this routine nomination.

## Web access

Use WebFetch/WebSearch. Shell network tools are deliberately unavailable in the
read-only auditor job. Do not save fetched pages or edit any file other than
`audit-proposals.json`.

`usenix.org` serves automated requests fine — go to the USENIX page itself for
OSDI / NSDI / USENIX Security / WOOT rather than a second-hand calendar.
(Measured 2026-08-18: the OSDI 27 and USENIX Security 27 CFPs both return 200.)

**ATC is no longer a USENIX conference.** It moved to ACM SIGOPS after 2025;
`conferences.yml` records this and the stored link is `sigops.org`. Do not look
for ATC on usenix.org.

`dfrws.org` does not block either. Its robots.txt is `User-agent: * /
Disallow:` — everything permitted — and the DFRWS EU 2027 page returns 200 with
the deadline text (measured 2026-08-18). An earlier 403 turned out to be rate
limiting caused by retrying immediately with a different user agent.

So before concluding that a host blocks you: **space your retries** (wait
5-30s, not instantly) and keep the same honest user agent. Do not retry with a
browser-like user agent to get past a refusal — if a site declines automated
access, use a different permitted source or record the venue as UNVERIFIABLE.
Check `robots.txt` first; a `Disallow` for the path is the owner's decision and
is final, whereas a 403 or 429 with robots permitting is usually transient and
worth one spaced retry.

If a host genuinely refuses, try the IEEE S&P TC CFP calendar
(ieee-security.org/Calendar/cfps/) or an official mirror; if nothing official is
reachable, the record is UNVERIFIABLE — say so rather than citing a tracker.

Four things a probe of all 36 venues found, worth knowing before you give up on
a page:

- **The stored `link` is often a homepage, not the CFP.** EuroSys, OSDI, S&P,
  WWW, RAID and IFIP-Sec all look empty at their landing page and verify fine
  one click in (`/cfp.html`, `/call-for-papers`, `/cfpapers.html`,
  `/important-dates/`, `/call.html`, `/dates.html`). Follow the site's own
  navigation before concluding anything.
- **Not every CFP link says "call for papers".** DSN publishes under "Call for
  Contributions"; SAC under "Regular Paper". Read the nav, do not pattern-match
  one phrase.
- **Not every CFP says "deadline" either.** SAC 2027's page has a full
  `IMPORTANT DATES` block — "October 2, 2026 (EST) Submission of regular
  papers" — and the word "deadline" appears nowhere on it. A dates block with
  milestone labels is a CFP whatever it calls itself.
- **Dates sometimes come before their labels.** DSN 2027's table is
  `December 2, 2026 | Paper Submission Deadline`; NDSS writes
  `Wed, 23 April 2025: Paper submission deadline`; EuroSec writes
  `Paper Submission Deadline: Feb 10`. Read the row or list item as a unit and
  work out which way round it is — reading DSN as label-then-date gives a
  deadline 55 days late.

## Worked example

This example is synthetic documentation, not evidence. Never copy wording from
this file or from stored comments into a proposal; only a page fetched during
this run can supply a quote.

Imagine the watchlist contains a fictional `ExampleConf 2027` disagreement.
The official page fetched during that run reads:

> Paper submission deadline, spring cycle: 10 December 2026
> Paper submission deadline, fall cycle: 18 February 2027
> All deadlines are AoE (Anywhere on Earth).

```json
{
  "id": "upsert_manual:ExampleConf:2027",
  "action": "upsert_manual",
  "title": "ExampleConf",
  "year": 2027,
  "watchlist_reasons": ["cross-source-disagreement"],
  "source_url": "https://example.invalid/exampleconf-2027/",
  "reason": "The deterministic upstream differs from the fetched official page.",
  "fields": {
    "deadline": {
      "value": ["2026-12-10 23:59", "2027-02-18 23:59"],
      "evidence": [
        {
          "for_value": "2026-12-10 23:59",
          "quote": "Paper submission deadline, spring cycle: 10 December 2026"
        },
        {
          "for_value": "2027-02-18 23:59",
          "quote": "Paper submission deadline, fall cycle: 18 February 2027"
        }
      ]
    },
    "timezone": {
      "value": "AoE",
      "evidence": [{"quote": "All deadlines are AoE (Anywhere on Earth)."}]
    }
  }
}
```

In a real proposal, replace every fictional value above with the watchlist's
canonical title/year and text copied from the page fetched in that same run.
The quote uses the page's words — `10 December 2026`, not the reformatted
`2026-12-10` stored in `value`.

`id` must be exactly `<action>:<title>:<year>`.

## Output

```json
{
  "audit_date": "2026-08-24",
  "watchlist_size": 30,
  "proposals": [ ... ],
  "unverifiable": [
    {"title": "DFRWS US", "year": 2027, "cause": "no_official_page",
     "attempted": ["https://dfrws.org/conferences/"],
     "note": "No 2027 edition page exists yet."}
  ]
}
```

`cause` is one of `no_official_page` (the venue's site exists but has no page
for this edition yet — the most common outcome by far, and a perfectly good
one), `fetch_blocked`, `page_ambiguous`, `javascript_only`, or `pdf_only`.
`not_checked` is reserved for an in-progress checkpoint and is forbidden in the
final output.

Every URL in `attempted` is machine-checked against the same immutable official
source trust used for positive proposals, for every cause above. A tracker,
model-only domain, malformed URL, or URL belonging to another conference is
returned to `not_checked` and makes the final shard incomplete. Use only the
actual official routes you fetched or attempted, omit duplicates, and list at
most eight URLs for one identity. Larger lists are rejected before any network
request so model output cannot multiply bounded fetch retries into an unbounded
job. Changing the cause does not bypass source trust.

**Finding no page is a normal, successful result.** Most watchlist entries are
upcoming editions whose CFP has simply not been published. Recording that
result for every affected record is a complete, correct audit — not a wasted
run, and not a reason to write nothing.

**Do not propose a `note` on its own.** A note has no value the gate can check
against a page, so a note-only proposal can never be accepted. If all you can
say about a record is that its note is stale, put it in `unverifiable` and move
on.

If everything checks out, emit an empty `proposals` array — with a `no_change`
entry per record you verified, so the run shows its coverage. That is a
successful audit, not a failed one. Never invent a proposal to have something
to show.

Before you finish, check: does `audit-proposals.json` exist, does every
watchlist record appear exactly once in `proposals` or `unverifiable`, are
there zero `not_checked` entries, does each multi-cycle value have its own
labelled row quote, and did you omit rather than guess every field the page
does not state? If not, the run fails.
