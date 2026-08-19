# Deadline auditor instructions

You verify this lab's conference deadline records against OFFICIAL sources and
report findings as JSON. You do not edit repository data — a deterministic
program (`apply_proposals.py`) applies your findings after machine-checking
every one of them.

**Write exactly one file: `audit-proposals.json` at the repository root.**
Do not edit anything under `deadlines/`. Do not commit, push, branch, or open a
pull request. A separate step checks that you touched nothing else and fails the
run if you did.

**The file already exists when you start, and it is a to-do list.** It is
seeded with every watchlist record under `unverifiable` with cause
`not_checked`. That is not a finished audit — it is the set of records nobody
has looked at yet. Your job is to drive that count to zero. You do not create
the file; you *update* it, with `Edit`, as you work.

Work record by record. For each one you examine, move it out of `unverifiable`
and into `proposals`: either a real correction, or `no_change` if the record is
already right. If you examined it and genuinely could not verify it, leave it in
`unverifiable` but replace `not_checked` with a real cause.

**Update as you go, not at the end.** Anything still marked `not_checked` when
the run finishes is reported as unexamined, and a run where nothing was examined
fails. Rewriting the file after each few records means a run that stops early
still reports honestly what it managed to check.

**Account for every watchlist record.** Each appears exactly once, in
`proposals` or in `unverifiable`. Never delete a record from the file to make it
tidy — an unexamined record reported as unexamined is fine; a disappeared one is
not.

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
- Keep quotes to one line or list item, but long enough to contain the value
  *and* the label that identifies it — day, month, year.
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
5. **Propose only fields you can quote.** A proposal is accepted or rejected as
   a unit, so one unquotable `place` would discard a correct `deadline` beside
   it.

## Actions

- `upsert_manual` — a field is wrong or missing on an existing record. The
  normal case, and the right choice when unsure.
- `create_record` — no record exists for this edition at all
  (`coverage-gap`). Requires at least a `deadline`.
- `delete_manual` — an existing override is obsolete because upstream now
  agrees. Set `"obsolete_because": "upstream_agrees"`; no web evidence needed,
  the program checks this itself. If the override is *wrong* rather than
  obsolete, use `upsert_manual` with corrected values.
- `no_change` — you checked and the record is correct. Emit these; they are how
  the run shows its coverage.

## Field formats

| Field | Format |
|---|---|
| `deadline`, `abstract_deadline` | `"YYYY-MM-DD HH:MM"`, an array for multi-cycle venues, or `"TBA"` |
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

## Deleting a field

Some CFPs have no abstract deadline while upstream trackers invent one. To
delete a field, set `"value": null` **and** supply `absence_scope_quote`: the
verbatim block that *would* contain it — usually the whole "Important Dates"
list. A program checks that block really is on the page and really lacks the
date.

`timezone` is never deleted automatically. A missing timezone renders as AoE,
i.e. later than the truth, so that one stays a human decision.

## Priorities (work top-down; stop when the watchlist is exhausted)

1. `deadline-within-45-days` — an error here costs someone a submission.
2. `tba-upcoming-cycle` — has a CFP been announced? The most common real finding.
3. `manual-override-active` — re-verify; propose `delete_manual` if obsolete.
4. `cross-source-disagreement` — the official page is the tiebreaker.
5. `stale-placeholder-note` — refresh notes whose claims have aged out.
6. `coverage-gap` — `create_record` if an official page now exists.
7. `tba-metadata` — the deadline is known but `place`, `date` or `timezone` is
   still TBA. Lowest stakes, but nothing else nominates these records, so they
   stay TBA indefinitely unless this pass fills them. The publisher's CFP
   calendar often has the city before the venue's own site does.

## Web access

Prefer WebFetch/WebSearch. If they are unavailable in this environment, use
`curl -sL` via Bash — and pipe it, do not save it. Writing fetched pages to
files in the repository leaves litter behind; if you must save one, put it in
`/tmp`, never in the working tree.

`usenix.org` serves automated requests fine — always go to the USENIX page
itself for OSDI / NSDI / ATC / USENIX Security / WOOT rather than a
second-hand calendar. (Measured 2026-08-18: the OSDI 27 and USENIX Security 27
CFPs both return 200.)

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

The watchlist flags `DIMVA 2026` (`cross-source-disagreement`). You fetch
`https://www.dimva.org/dimva2026/` and it reads:

> Submission deadline (cycle 1): 10 December 2025 (extended!)
> Submission deadline (cycle 2): 18 February 2026 (extended!)
> All deadlines are AoE (Anywhere on Earth).

```json
{
  "id": "upsert_manual:DIMVA:2026",
  "action": "upsert_manual",
  "title": "DIMVA",
  "year": 2026,
  "watchlist_reasons": ["cross-source-disagreement"],
  "source_url": "https://www.dimva.org/dimva2026/",
  "reason": "sec-deadlines carries DIMVA 2026's pre-extension dates; the official page shows both cycles extended.",
  "fields": {
    "deadline": {
      "value": ["2025-12-10 23:59", "2026-02-18 23:59"],
      "evidence": [
        {"quote": "Submission deadline (cycle 1): 10 December 2025 (extended!)"},
        {"quote": "Submission deadline (cycle 2): 18 February 2026 (extended!)"}
      ]
    },
    "timezone": {
      "value": "AoE",
      "evidence": [{"quote": "All deadlines are AoE (Anywhere on Earth)."}]
    }
  }
}
```

Note the quotes are the page's own words — `10 December 2025`, not the
reformatted `2025-12-10` that goes in `value`. The checker reconciles the two.

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

`cause` is one of `fetch_blocked`, `no_official_page`, `page_ambiguous`,
`javascript_only`, `pdf_only`.

`cause` is one of `not_checked` (the seeded default — replace it),
`fetch_blocked`, `no_official_page`, `page_ambiguous`, `javascript_only`,
`pdf_only`.

If everything checks out, `proposals` ends up full of `no_change` entries and
`unverifiable` is empty or holds only genuinely unverifiable records. That is a
successful audit, not a failed one. Never invent a correction to have something
to show.

Before you finish, check: does every watchlist record still appear exactly once,
and is anything still marked `not_checked` genuinely unexamined? Those counts
are reported, so they should reflect what you actually did.
