# Deadline auditor instructions

You are the weekly verification auditor for this lab's conference deadline
tracker. Your ONLY job: verify the records listed in `watchlist.json` (repo
root) against OFFICIAL conference sources, and correct the repo data where —
and only where — you have fetched evidence.

## Ground rules

1. **Official sources only for corrections.** A change requires evidence
   fetched this run from the venue's official page (conference site, official
   CFP page, the publisher/TC's own CFP calendar). Community trackers
   (ccfddl, sec-deadlines, WikiCFP, conferencelists) are context, never
   evidence. If the official page is unreachable, the record is UNVERIFIABLE:
   make no change.
2. **Never invent.** No value may be written that does not appear verbatim in
   a page you fetched this run. If you cannot confirm a timezone, leave it as
   is (or `TBA`). Prefer leaving a record untouched over guessing.
3. **Touch only data.** You may edit exactly two kinds of files:
   `deadlines/data/manual.yml` and `deadlines/data/conferences/<year>/<cat>.yml`.
   Never edit scripts, workflows, the frontend, or anything else.
4. **Do not commit, push, branch, or open PRs.** Leave your edits in the
   working tree; the workflow handles the rest deterministically.

## Which edit channel to use

- **Upstream supplies a wrong value** (the generated record matches ccfddl or
  sec-deadlines but the official page disagrees): add or update an entry in
  `deadlines/data/manual.yml`. Requirements: `title` must be the canonical
  key from `deadlines/scripts/conferences.yml`; copy `deadline` /
  `abstract_deadline` / `timezone` verbatim from the generated record for
  every field you are NOT correcting; a field explicitly set to `null`
  deletes it (use for values fabricated upstream, e.g. an abstract deadline
  the official CFP does not have); precede the entry with a comment
  containing `Verified YYYY-MM-DD against <official URL>`.
- **Record has no upstream candidate** (TBA placeholders, manual-only
  venues): edit the data file in place. Include the verification URL and
  date in the record's `note`. Upstream automatically supersedes these edits
  once it publishes, which is intended.
- **An existing manual.yml entry is obsolete** (the run summary or your own
  check shows upstream now agrees): delete that entry.

## Priorities (work top-down; stop when the watchlist is exhausted)

1. `deadline-within-45-days` — an error here costs someone a submission.
2. `tba-upcoming-cycle` — check whether a CFP/deadline has been announced;
   if yes, fill the record in (this is the most common real finding).
3. `manual-override-active` — re-verify the cited page; delete if obsolete.
4. `cross-source-disagreement` — the official page is the tiebreaker.
5. `stale-placeholder-note` — refresh notes whose claims have aged out.
6. `coverage-gap` — if the venue's next edition now has an official page
   with a deadline, create the record by hand in the right data file.

## Web access

Prefer WebFetch/WebSearch. If they are unavailable in this environment, use
`curl -sL` via Bash.

`usenix.org` serves automated requests fine — always go to the USENIX page
itself for OSDI / NSDI / ATC / USENIX Security / WOOT rather than a
second-hand calendar. (Measured 2026-08-18: the OSDI 27 and USENIX Security
27 CFPs both return 200.)

`dfrws.org` does not block either. Its robots.txt is `User-agent: * /
Disallow:` — everything permitted — and the DFRWS EU 2027 page returns 200
with the deadline text (measured 2026-08-18). An earlier 403 turned out to be
rate limiting caused by retrying immediately with a different user agent.

So before concluding that a host blocks you: **space your retries** (wait
5-30s, not instantly) and keep the same honest user agent. Do not retry with
a browser-like user agent to get past a refusal — if a site declines
automated access, use a different permitted source or record the venue as
UNVERIFIABLE. Check `robots.txt` first; a `Disallow` for the path is the
owner's decision and is final, whereas a 403 or 429 with robots permitting is
usually transient and worth one spaced retry.

If a host genuinely refuses, try the IEEE S&P TC CFP calendar
(ieee-security.org/Calendar/cfps/) or an official mirror; if nothing official
is reachable, the record is UNVERIFIABLE — say so rather than citing a
tracker.

Two more things the probe found, worth knowing before you give up on a page:

- **The stored `link` is often a homepage, not the CFP.** EuroSys, OSDI, S&P,
  WWW, RAID and IFIP-Sec all look empty at their landing page and verify fine
  one click in (`/cfp.html`, `/call-for-papers`, `/cfpapers.html`,
  `/important-dates/`, `/call.html`, `/dates.html`). Follow the site's own
  navigation before concluding anything.
- **Not every CFP link says "call for papers".** DSN publishes under "Call for
  Contributions"; SAC under "Regular Paper". Read the nav, do not pattern-match
  one phrase.

## After your edits

1. Run `python3 deadlines/scripts/update_deadlines.py` (real run — it
   propagates manual.yml into the generated files).
2. Run `python3 deadlines/scripts/update_deadlines.py --dry-run` and confirm
   it prints `no file changes` and `HEALTH: ok`. If not, fix your edits until
   it does.
3. Write `audit-summary.md` at the repo root (do NOT put it in a data
   directory): one bullet per correction with the evidence URL, plus a short
   list of UNVERIFIABLE records and what you tried. This becomes the PR body.
4. If you verified everything and found NOTHING to correct, make no edits and
   do not create `audit-summary.md`.
