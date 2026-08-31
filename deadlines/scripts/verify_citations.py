#!/usr/bin/env python3
"""Deterministic evidence gate for the deadline audit. No model in the loop.

Re-fetches every source_url an auditor cited and checks, mechanically, that the
quote it gave really appears on that page and really contains the value it is
offered as evidence for. A hallucinated citation cannot survive step 1; an
honestly-quoted *wrong* label cannot survive step 3.

    VERIFIED         quote grounded, value inside it, label appropriate
    UNCONFIRMED      page fetched, evidence did not hold up
    UNREACHABLE      could not fetch (never treated as verified)
    REJECTED_SOURCE  not an admissible source (tracker, robots-disallowed)
    MALFORMED        the proposal itself is unusable

Usage:
  verify_citations.py --proposals audit-proposals.json --watchlist watchlist.json \
      --out audit-verdicts.json
  verify_citations.py ... --offline --fixtures DIR    (tests; never touches the network)

Exit 0 = every proposal decided. 2 = at least one MALFORMED/REJECTED_SOURCE.
1 = fatal (inputs unreadable).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html as htmllib
import ipaddress
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_deadlines as U  # noqa: E402

UA = "secai-lab-deadline-auditor/1.0 (+https://secai-lab.github.io/deadlines/)"
LCS_THRESHOLD = 0.85
QUOTE_MIN_TOKENS = 4
WINDOW_SLACK = 10
FETCH_TIMEOUT = 25
RETRY_DELAYS = (0, 5, 30)
PER_HOST_DELAY = 1.0
MAX_BYTES = 5 * 1024 * 1024
# Keep real HTML heading boundaries in the flattened token stream.  Plain
# words alone cannot distinguish ``<h3>Notification</h3>`` (which scopes the
# rows below it) from an adjacent ``Notification: ...`` milestone row (which
# does not).  These deliberately unlikely alphabetic sentinels survive
# ``flatten``/``tokens`` without ever matching a quoted value.
HEADING_START_TOKEN = "secaiauditheadingstart"
HEADING_END_TOKEN = "secaiauditheadingend"
IDENTITY_BODY_RADIUS = 24  # tokens between the venue name and its edition year

# Community trackers and mirrors: context, never evidence (AUDITOR.md rule 1).
DENY_HOSTS = (
    "ccfddl.github.io", "sec-deadlines.github.io", "wikicfp.com", "www.wikicfp.com",
    "conferencelists.org", "aideadlin.es", "deadlines.cc", "myhuiban.com",
    "dblp.org", "en.wikipedia.org", "web.archive.org", "webcache.googleusercontent.com",
)
DENY_PATH_RE = re.compile(r"raw\.githubusercontent\.com/(ccfddl|sec-deadlines)/", re.I)

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
ABBR = {m: (m[:3] if m != "september" else "sept") for m in MONTHS}
MONTH_TOKENS = set(MONTHS) | {m[:3] for m in MONTHS} | {"sept"}

# A label must be present for the field, and disqualifying labels must not be.
FIELD_LABELS = {
    "deadline": (
        # No bare "submission": it matches "Submission of revised papers" and
        # "Submission site opens", which are not the paper deadline. Demonstrated
        # +99 days against a real-shaped page.
        ("submission deadline", "paper deadline", "papers due", "submission due",
         "full paper", "submission of regular papers", "paper submission",
         "final submission", "submission of papers"),
        ("notification", "acceptance", "camera ready", "rebuttal", "revised",
         "resubmission", "site opens", "workshop", "poster", "demo", "tutorial",
         "doctoral", "src", "registration"),
    ),
    "abstract_deadline": (("abstract",), ("notification", "acceptance", "camera ready")),
    "date": ((), ("submission", "deadline", "due", "notification")),
    "place": ((), ()),
    "timezone": ((), ()),
    "link": ((), ()),
    "note": ((), ()),
}


# ------------------------------------------------------------------ normalizing

def strip_html(raw: str) -> str:
    # Comments FIRST. manual.yml records the real trap: WWW 2026's superseded
    # April dates live in commented-out HTML. Strip tags first and they come
    # back as "evidence".
    s = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    s = re.sub(r"<(script|style|svg|noscript|template)\b.*?</\1>", " ", s,
               flags=re.S | re.I)
    # Struck-through text is superseded, not current: drop it entirely. CSS
    # strikethrough counts too - "extended" CFPs use it, and a superseded date
    # that survives stripping verifies at coverage 1.0.
    s = re.sub(r"<(s|del|strike)\b[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<(\w+)[^>]*(?:line-through|strikethrough)[^>]*>.*?</\1>", " ", s,
               flags=re.S | re.I)
    s = re.sub(r"<h[1-6]\b[^>]*>", f"\n {HEADING_START_TOKEN} ", s, flags=re.I)
    s = re.sub(r"</h[1-6]\s*>", f" {HEADING_END_TOKEN}\n", s, flags=re.I)
    s = re.sub(r"<(br|hr)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|tr|td|th|h[1-6]|section|article|table|dd|dt)\s*>", "\n",
               s, flags=re.I)
    s = re.sub(r"<(b|i|em|strong|span|u|a|sup|sub|small|mark|code|abbr|time|font)\b[^>]*>",
               "", s, flags=re.I)
    s = re.sub(r"</(b|i|em|strong|span|u|a|sup|sub|small|mark|code|abbr|time|font)\s*>",
               "", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return htmllib.unescape(s)


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.translate({0x00a0: " ", 0x202f: " ", 0x2009: " ", 0x2007: " ",
                     0x200b: None, 0x200c: None, 0x200d: None, 0xfeff: None, 0x00ad: None})
    s = re.sub(r"[‐-―−]", "-", s)
    s = re.sub(r"[‘’‛]", "'", s)
    s = re.sub(r"[“”]", '"', s)
    return re.sub(r"\s+", " ", s).strip().casefold()


def flatten(s: str) -> str:
    """Alnum-only view: punctuation and markup differences vanish, digits do not.

    Ordinal suffixes are dropped first. Without this, "July 24th, 2026"
    tokenizes to ['july','24','th','2026'] and the interposed 'th' breaks
    contiguity with every generated form - so AISec's real, correctly-labelled,
    published deadline could not be cited by ANY quote, and the auditor was told
    its perfect quote "was not found on the page".
    """
    n = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", normalize(s))
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", flatten(s))


# -------------------------------------------------------------- surface forms

def date_forms(d: dt.date) -> list[str]:
    m, day, y = MONTHS[d.month - 1], d.day, d.year
    a, yy = ABBR[m], y % 100
    days = {str(day), f"{day:02d}"}
    out = set()
    for dd in days:
        for name in (m, a):
            # No ordinal variants: flatten() strips the suffix, so "24th" and
            # "24" are already the same token by the time forms are compared.
            out |= {f"{name} {dd} {y}", f"{dd} {name} {y}"}
        out.add(f"{y} {d.month:02d} {int(dd):02d}")
        # Numeric forms are admissible only when a component exceeds 12, which
        # makes the ordering unambiguous (11/20/26 can only be Nov 20).
        if day > 12:
            out |= {f"{d.month} {dd} {y}", f"{d.month:02d} {dd} {y}",
                    f"{dd} {d.month} {y}", f"{d.month} {dd} {yy:02d}"}
    return sorted(out)


def tz_forms(tz: str) -> list[str]:
    """Timezone forms are matched against the SIGN-PRESERVING view.

    flatten() turns both 'UTC+12' and 'UTC-12' into 'utc 12', so a page stating
    UTC+12 would confirm an AoE (UTC-12) claim and the countdown would render a
    full day late. Offsets therefore keep their sign and are compared against
    normalize(), which preserves '+' and '-'.
    """
    canon = U.canon_tz(tz)
    table = {
        "UTC-12": ["aoe", "anywhere on earth", "utc-12", "gmt-12"],
        "UTC+0": ["utc", "gmt", "utc+0", "zulu"],
        "UTC-5": ["utc-5", "gmt-5", "est", "eastern standard time"],
        "UTC-8": ["pst", "pdt", "pacific time", "utc-8"],
        "America/Los_Angeles": ["pst", "pdt", "pacific time", "america/los_angeles"],
    }
    return table.get(canon, [normalize(canon)])


def count_dates(text: str) -> int:
    """How many distinct date-like expressions are in this text?

    A quote spanning two table rows contains two dates, which lets an auditor
    present either as the value while the quote still grounds perfectly - it is
    genuine page text. Counting is how that is refused.
    """
    # Strip clock times first: "24 September 2026, 23:59 AoE" is ONE date, but
    # 23:59 flattens to "23 59" and was counted as a second - so the MORE
    # precise quote, the one naming the exact instant, was the one refused.
    flat = re.sub(r"\b\d{1,2}\s*[:.]\s*\d{2}(\s*[:.]\s*\d{2})?\s*(am|pm)?\b", " ",
                  normalize(text))
    flat = re.sub(r"[^a-z0-9]+", " ", flat).strip()
    toks = flat.split()
    seen = set()
    for i, t in enumerate(toks):
        if t in MONTH_TOKENS:
            nums = [x for x in toks[max(0, i - 2):i + 3] if x.isdigit()]
            seen.add((t, tuple(nums)))
    seen |= {m for m in re.findall(r"\b\d{4} \d{1,2} \d{1,2}\b", flat)}
    return len(seen)


def value_forms(field: str, value) -> tuple[list[str], bool]:
    """(surface forms, is_required). Returns ([], False) when a field carries no
    checkable surface form - notes and links are not claims about page text."""
    if field in ("deadline", "abstract_deadline"):
        forms = []
        for v in U.as_list(value):
            d = U.parse_dl_date(v)
            if d:
                forms += date_forms(d)
        return forms, bool(forms)
    if field == "timezone":
        return tz_forms(str(value)), True
    if field == "place":
        components = [flatten(part) for part in str(value).split(",")]
        components = [part for part in components if part]
        if not components:
            return [], False
        forms = {" ".join(components)}
        country_aliases = (
            {"uk", "u k", "united kingdom"},
            {"usa", "u s a", "us", "u s", "united states",
             "united states of america"},
            {"south korea", "republic of korea"},
        )
        for aliases in country_aliases:
            if components[-1] in aliases:
                prefix = components[:-1]
                forms.update(" ".join(prefix + [alias]) for alias in aliases)
        return sorted(forms), True
    if field == "date":
        rng = U.parse_date_range(str(value))
        if not rng:
            return [], False
        a, b = rng
        # Conference spans are written compactly - "April 19-23, 2027" - not as
        # two full dates. Emitting only month-day-year forms made 83 of the
        # repo's 107 date values ungroundable by their own text, including
        # AUDITOR.md's documented example. A compact form still pins BOTH
        # endpoints, so a page saying 19-24 cannot verify a claim of 19-23.
        forms = date_forms(a) + date_forms(b)
        if a.year == b.year:
            ma, mb = MONTHS[a.month - 1], MONTHS[b.month - 1]
            aa, ab = ABBR[ma], ABBR[mb]
            if a.month == b.month:
                for nm in (ma, aa):
                    forms += [f"{nm} {a.day} {b.day} {a.year}",
                              f"{a.day} {b.day} {nm} {a.year}"]
            else:
                for na, nb in ((ma, mb), (aa, ab)):
                    forms += [f"{na} {a.day} {nb} {b.day} {a.year}"]
        return forms, True
    return [], False


def _deadline_clock(value):
    match = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}\s+(\d{2}):(\d{2})(?::\d{2})?", str(value)
    )
    if not match:
        return None
    hour, minute = map(int, match.groups())
    return hour * 60 + minute if hour < 24 and minute < 60 else None


def _clock_evidence(text):
    """Return (clock minutes, ambiguous-time-token-present).

    CFPs commonly spell clocks as ``5 PM`` or ``23.59 AoE`` as well as
    ``17:00``.  Silently overlooking those forms lets a proposed 23:59 pass as
    a date-only default.  Midnight and 24:00 deliberately fail closed because
    the calendar day they belong to is convention-dependent.
    """
    value = normalize(text)
    clocks = set()
    ambiguous = bool(re.search(r"\bmidnight\b|(?<!\d)24\s*[:.]\s*00(?!\d)", value))
    suffix_re = r"(?:a\.?m\.?|p\.?m\.?)"
    pattern = re.compile(
        rf"(?<![\d.])(\d{{1,2}})\s*([:.])\s*(\d{{2}})"
        rf"(?:\s*[:.]\s*\d{{2}})?\s*({suffix_re})?(?=$|[^a-z0-9])",
        re.I,
    )
    for match in pattern.finditer(value):
        hour, minute = int(match.group(1)), int(match.group(3))
        separator = match.group(2)
        suffix = (match.group(4) or "").replace(".", "").casefold()

        # A dotted number is also a common compact date/version.  Treat it as
        # a clock only when nearby language makes that interpretation clear.
        if separator == "." and not suffix:
            before = value[max(0, match.start() - 24):match.start()]
            after = value[match.end():match.end() + 18]
            if re.match(r"\s*\.\s*\d", after):
                continue  # 11.20.2026 is a date, not an 11:20 clock
            clock_signal = (
                re.search(r"(?:\bat|\bby|\bdue|deadline)\s*[:,-]?\s*$", before)
                or re.match(
                    r"\s*(?:aoe|utc(?:[+-]\d{1,2})?|gmt|cet|cest|est|edt|"
                    r"pst|pdt|bst|kst|jst)\b",
                    after,
                )
            )
            if not clock_signal:
                continue

        if minute >= 60 or (suffix and not 1 <= hour <= 12) \
                or (not suffix and hour >= 24):
            ambiguous = True
            continue
        if suffix == "am":
            hour %= 12
        elif suffix == "pm":
            hour = (hour % 12) + 12
        clocks.add(hour * 60 + minute)

    # Bare 12-hour clocks (``5 PM``) are not covered by the minute pattern.
    bare = re.compile(
        rf"(?<![\d:.])(\d{{1,2}})\s*({suffix_re})(?=$|[^a-z])", re.I
    )
    for match in bare.finditer(value):
        hour = int(match.group(1))
        suffix = match.group(2).replace(".", "").casefold()
        if not 1 <= hour <= 12:
            ambiguous = True
            continue
        clocks.add((hour % 12 + (12 if suffix == "pm" else 0)) * 60)

    if re.search(r"\bnoon\b", value):
        clocks.add(12 * 60)
    return clocks, ambiguous


def _explicit_clocks(text):
    """Compatibility wrapper used by tests and diagnostics."""
    return _clock_evidence(text)[0]


def deadline_time_compatible(value, quote, page_text, field):
    """Verify clock precision, retaining the date-only end-of-day convention."""
    expected = _deadline_clock(value)
    date = U.parse_dl_date(value)
    if expected is None or date is None:
        return False, "the proposed deadline has no valid clock time"

    quote_clocks, quote_ambiguous = _clock_evidence(quote)
    if quote_ambiguous:
        return False, "the evidence quote contains an ambiguous or invalid clock time"
    if quote_clocks and quote_clocks != {expected}:
        return False, (f"the evidence quote states clock time(s) "
                       f"{sorted(quote_clocks)}, not proposed minute {expected}")

    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    forms = date_forms(date)
    labels = FIELD_LABELS.get(field, ((), ()))[0]
    relevant_clocks = set()
    relevant_ambiguous = False
    for start in range(len(lines)):
        block = " ".join(lines[start:start + 4])
        flat = flatten(block)
        if any(form in flat for form in forms) and any(
                label_pos(flat, label) >= 0 for label in labels):
            found, ambiguous = _clock_evidence(block)
            relevant_clocks.update(found)
            relevant_ambiguous = relevant_ambiguous or ambiguous
    for line in lines:
        if "all deadlines" in flatten(line):
            found, ambiguous = _clock_evidence(line)
            relevant_clocks.update(found)
            relevant_ambiguous = relevant_ambiguous or ambiguous

    if relevant_ambiguous:
        return False, "the official deadline context contains an ambiguous clock time"

    if relevant_clocks:
        if relevant_clocks != {expected}:
            return False, (f"the official deadline context states clock time(s) "
                           f"{sorted(relevant_clocks)}, not proposed minute {expected}")
        return True, ""
    if expected != 23 * 60 + 59:
        return False, ("the page states no clock time, so only the repository's "
                       "23:59 end-of-day convention is admissible")
    return True, ""


# ------------------------------------------------------------------- matching

def lcs_len(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(cur[j], prev[j + 1]))
        prev = cur
    return prev[-1]


def find_windows(page_toks: list[str], form: str, size: int):
    """Yields (anchor_index, window). The anchor is where the VALUE matched;
    the window is centred on it and extends both ways to tolerate quoting
    slack. Callers needing page context must use the anchor, not the window
    start - the window deliberately reaches back into the previous section."""
    ft = form.split()
    if not ft:
        return
    n = len(page_toks)
    for i in range(n - len(ft) + 1):
        if page_toks[i:i + len(ft)] == ft:
            lo = max(0, i + len(ft) // 2 - size // 2)
            yield i, page_toks[lo:lo + size]


def phrase_present(flat: str, tokset: set, phrase: str) -> bool:
    """Multi-word phrases match as substrings; single words as whole tokens.

    Without the token rule, a short label like 'src' would match inside
    unrelated words and reject valid evidence.
    """
    return phrase in flat if " " in phrase else phrase in tokset


def label_pos(flat: str, phrase: str) -> int:
    """Character offset of a label in the flattened quote, or -1.

    Simple plurals match. CFPs write "Paper titles and abstracts due" far more
    often than the singular, and a strict word-boundary match on "abstract"
    rejected 3 of 4 natural phrasings - the auditor could not cite EuroSys's
    real abstract deadline with any quote on the page. Applies to the forbid
    list too, so "Workshops" no longer slips past a block on "workshop".
    """
    pat = rf"\b{re.escape(phrase)}(?:e?s)?\b"
    m = re.search(pat, flat)
    return m.start() if m else -1


HEADING_LOOKBACK = 30  # tokens; a section heading sits close to its rows
# Milestone words such as "notification" and "acceptance" occur in adjacent
# date rows.  Only use this reduced set for the legacy no-markup fallback;
# structural HTML headings can safely use the complete field forbid list.
TRACK_HEADING_FORBIDS = frozenset(("workshop", "poster", "demo", "tutorial",
                                   "doctoral", "src"))
EXPLICIT_PAPER_LABELS = ("paper submission", "paper deadline", "papers due",
                         "full paper", "submission of regular papers",
                         "research papers", "paper titles")


def heading_scope(page_toks, start, forbid, explicit_paper=False):
    """A disqualifying term in the text just BEFORE the match, if any.

    Some CFPs give every track an identical row and distinguish them only by a
    heading above. ACNS 2027 is the real case - paper, poster and workshop rows
    all read "Submission deadline: <date> AoE", so the quote alone cannot say
    which track it is and the poster date verified as the paper deadline at
    coverage 1.0. That is a false positive, the direction that publishes a
    wrong deadline.

    Real HTML headings are marked by ``strip_html``.  The latest such heading
    scopes the row even when it is farther than a small token window away.  On
    plain text without structural markers, retain the old bounded category-only
    fallback: treating a preceding notification *row* as a heading caused the
    ACNS cycle-2 and SAC false negatives this distinction exists to avoid.
    """
    preceding = page_toks[:start]
    heading_starts = [i for i, tok in enumerate(preceding)
                      if tok == HEADING_START_TOKEN]
    if heading_starts:
        heading_start = heading_starts[-1] + 1
        try:
            heading_end = preceding.index(HEADING_END_TOKEN, heading_start)
        except ValueError:
            heading_end = len(preceding)
        heading = " ".join(preceding[heading_start:heading_end])
        hits = [(label_pos(heading, bad), bad) for bad in forbid]
        hits = [(pos, bad) for pos, bad in hits if pos >= 0]
        if not hits:
            return None
        return max(hits)[1]

    # A quote that explicitly names the paper track can outrank loose navigation
    # text when no heading structure survived (the FSE shape).  It cannot
    # outrank a real heading: "Workshops / Full paper submission" is still a
    # workshop deadline and was handled above.
    if explicit_paper:
        return None
    lo = max(0, start - HEADING_LOOKBACK)
    before = " ".join(page_toks[lo:start])
    if not before:
        return None
    hits = [(label_pos(before, b), b) for b in forbid if b in TRACK_HEADING_FORBIDS]
    hits = [(p, b) for p, b in hits if p >= 0]
    if not hits:
        return None
    # A heading is cancelled only by a label that NAMES PAPERS, not by any
    # deadline label. "Poster Submissions / Submission deadline: ..." carries a
    # generic label belonging to the poster section, and treating that as
    # cancelling would let every track's row verify as the paper deadline -
    # which is the bug this exists to stop. "Poster Submissions ... Paper
    # submission deadline" does cancel, because it names the track explicitly.
    nearest_bad = max(p for p, _ in hits)
    for good in EXPLICIT_PAPER_LABELS:
        if before.rfind(good) > nearest_bad:
            return None
    return next(b for p, b in hits if p == nearest_bad)


def ground_quote(page_toks, quote, forms, labels, single_date=False):
    """Does this quote bind the value to a field-appropriate label, on the page?

    Label and value are checked inside the QUOTE, not inside the surrounding
    window. The quote is the contiguous span the auditor claims to have copied,
    so it is what establishes label-value association; a window wide enough to
    tolerate quoting slack also spans the neighbouring row, whose label would
    otherwise poison a perfect match. Grounding then proves the quote is real
    page text rather than a construction.
    """
    need, forbid = labels
    qt = tokens(quote)
    if len(qt) < QUOTE_MIN_TOKENS:
        return None, "quote too short to be evidence"
    # A raw token minimum is the wrong instrument: it rejected the IEEE TC
    # calendar's complete "Submission deadline: 11/20/26" (5 tokens) while
    # admitting "February 10, 2026 submission", which is three date tokens and
    # one label word. What matters is that the quote carries real context
    # around the value, so count the tokens that are NOT part of the date.
    context = [t for t in qt if not t.isdigit() and t not in MONTH_TOKENS]
    if len(context) < 2:
        return None, ("quote is almost entirely the date itself; it needs the "
                      "surrounding label text to identify what the date is")
    qflat, qset = flatten(quote), set(qt)
    # Signed view for offsets; flat view for everything else (see tz_forms).
    haystack = qflat + " " + normalize(quote)
    if forms and not any(f in haystack for f in forms):
        return None, "the quote does not contain the proposed value"
    if single_date and count_dates(quote) > 1:
        return None, ("the quote contains more than one date, so it does not "
                      "establish which one this value is")
    # A disqualifying term only disqualifies when it OUTRANKS this field's own
    # label - i.e. leads the row. Rows are routinely combined: SAC's real paper
    # deadline reads "Submission of regular papers and SRC research abstracts",
    # and a blanket forbid on 'src' made that line - the only one stating SAC's
    # deadline - permanently uncitable. "Workshop paper submission deadline"
    # still fails, because there the disqualifying term comes first.
    req = [p for p in (label_pos(qflat, l) for l in need) if p >= 0]
    if need and not req:
        return None, "the quote carries no label identifying this field"
    lead = min(req) if req else -1
    for bad in forbid:
        p = label_pos(qflat, bad)
        if p < 0 or (lead >= 0 and p > lead):
            continue
        return None, (f"the quote leads with '{bad}', so it is labelling that, "
                      "not this field")
    size = max(len(qt) + WINDOW_SLACK, int(len(qt) * 1.6))
    best, ctx_reject = 0.0, None
    for form in (forms or [" ".join(qt[:3])]):
        for start, win in find_windows(page_toks, form, size):
            cov = lcs_len(qt, win) / len(qt)
            best = max(best, cov)
            if cov < LCS_THRESHOLD:
                continue
            # Explicit paper text may outrank unstructured navigation, but never
            # a real HTML heading (e.g. Workshops).  ``heading_scope`` owns that
            # distinction so this call cannot bypass a structural true negative.
            explicit_paper = any(label_pos(qflat, label) >= 0
                                 for label in EXPLICIT_PAPER_LABELS)
            bad = heading_scope(page_toks, start, forbid, explicit_paper)
            if bad:
                ctx_reject = (f"the quote grounds under a '{bad}' heading on the "
                              "page, so it belongs to that track, not this field")
                continue
            return round(cov, 3), None
    if ctx_reject:
        return None, ctx_reject
    return None, (f"quote not found on the page (best coverage {best:.2f} "
                  f"< {LCS_THRESHOLD})")


ABSENCE_VOCAB = {
    "abstract_deadline": ("abstract",),
    "deadline": ("submission deadline", "paper deadline", "papers due"),
    "timezone": ("aoe", "utc", "gmt", "timezone"),
}
ABSENCE_RADIUS = 25  # tokens between a label and a date, inside the cited block


def verify_absence(page_toks, field, scope_quote):
    """Bound a negative claim instead of trying to prove one.

    "This page has no abstract deadline" is unfalsifiable. What IS decidable is
    "the block the auditor cited, which really is on this page, contains no
    abstract entry". So: ground the cited block, then look inside it only.
    """
    vocab = ABSENCE_VOCAB.get(field)
    if not vocab:
        return False, f"no absence vocabulary defined for {field!r}"
    qt = tokens(scope_quote)
    if len(qt) < 8:
        return False, ("absence_scope_quote too short: it must be the whole block "
                       "that would contain the field, not a fragment")
    size = max(len(qt) + WINDOW_SLACK, int(len(qt) * 1.6))
    best, block = 0.0, None
    for i in range(max(1, len(page_toks) - size + 1)):
        win = page_toks[i:i + size]
        cov = lcs_len(qt, win) / len(qt)
        if cov > best:
            best, block = cov, win
        if cov >= LCS_THRESHOLD:
            block = win
            break
    if best < LCS_THRESHOLD:
        return False, (f"the cited block is not on the page (best coverage {best:.2f}); "
                       "an absence cannot be bounded by a block that does not exist")
    text = " ".join(block)
    hits = [v for v in vocab if (v in text if " " in v else v in set(block))]
    if not hits:
        return True, "the cited block is on the page and contains no such entry"
    # The label is present - is a date sitting next to it? Match token phrases,
    # not only single-token vocabulary. Without this, the primary deadline
    # labels (all multiword) were detected in `hits` but never examined here, so
    # a block containing the real deadline could incorrectly prove its absence.
    for label in hits:
        phrase = tokens(label)
        for idx in range(len(block) - len(phrase) + 1):
            if block[idx:idx + len(phrase)] != phrase:
                continue
            near = block[max(0, idx - ABSENCE_RADIUS):
                         idx + len(phrase) + ABSENCE_RADIUS]
            if count_dates(" ".join(near)):
                return False, (f"the cited block mentions {label!r} within "
                               f"{ABSENCE_RADIUS} tokens of a date; "
                               "absence not established")
    return True, "the cited block mentions the label but associates no date with it"


# ------------------------------------------------------------------- fetching

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep redirects on pre-authorized public hosts before making the request."""

    def __init__(self, allowed_hosts):
        super().__init__()
        self.allowed_hosts = {
            normalized_host(host) for host in (allowed_hosts or ())
            if normalized_host(host)
        }

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, why = source_ok(newurl)
        host = normalized_host(newurl)
        if not ok or not any(host_matches_trust(host, trusted)
                             for trusted in self.allowed_hosts):
            detail = why or f"redirect host {host or '<missing>'} is not authorized"
            raise urllib.error.HTTPError(
                newurl, code, f"unsafe redirect refused: {detail}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class Fetcher:
    def __init__(self, offline=False, fixtures=None):
        self.offline, self.fixtures = offline, fixtures
        self.cache, self.robots, self.last_hit = {}, {}, {}
        # Requested URL -> final URL after redirects.  Keeping this beside the
        # historical two-tuple ``get`` result preserves small fake fetchers and
        # existing tests while still letting the verifier bind redirect targets.
        self.final_urls = {}

    def _fixture(self, url):
        key = hashlib.sha1(url.encode()).hexdigest()
        for cand in (Path(self.fixtures) / f"{key}.html",
                     Path(self.fixtures) / f"{urllib.parse.urlparse(url).netloc}.html"):
            if cand.exists():
                return cand.read_text(encoding="utf-8")
        return None

    def _raw(self, url, allowed_hosts=None):
        ok, why = source_ok(url)
        if not ok:
            raise urllib.error.URLError(f"unsafe source refused: {why}")
        host = urllib.parse.urlparse(url).netloc
        gap = time.monotonic() - self.last_hit.get(host, 0)
        if gap < PER_HOST_DELAY:
            time.sleep(PER_HOST_DELAY - gap)
        self.last_hit[host] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        allowed = allowed_hosts or {normalized_host(url)}
        opener = urllib.request.build_opener(SafeRedirectHandler(allowed))
        with opener.open(req, timeout=FETCH_TIMEOUT) as r:
            return r.read(MAX_BYTES).decode("utf-8", errors="replace"), r.geturl()

    def robots_allows(self, url, allowed_hosts=None):
        """403 on robots.txt means UNKNOWN, never 'disallow all'.

        urllib.robotparser.read() fetches with the default python-urllib UA;
        USENIX's WAF 403s that and the parser then sets disallow_all, which
        would silently lock the auditor out of five venues over a policy that
        does not exist.
        """
        p = urllib.parse.urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                txt, _ = self._raw(base + "/robots.txt", allowed_hosts)
                rp.parse(txt.splitlines())
            except Exception:  # noqa: BLE001 - unknown policy, not a refusal
                rp = None
            self.robots[base] = rp
        rp = self.robots[base]
        return True if rp is None else rp.can_fetch(UA, url)

    def get(self, url, allowed_hosts=None):
        if url in self.cache:
            return self.cache[url]
        if self.offline:
            txt = self._fixture(url) if self.fixtures else None
            res = (txt, None) if txt is not None else (None, "offline: no fixture")
            self.final_urls[url] = url
            self.cache[url] = res
            return res
        if not self.robots_allows(url, allowed_hosts):
            res = (None, "robots.txt disallows this path")
        else:
            res, last = (None, "unfetched"), None
            for delay in RETRY_DELAYS:
                if delay:
                    time.sleep(delay)
                try:
                    txt, final_url = self._raw(url, allowed_hosts)
                    res = (txt, None)
                    self.final_urls[url] = final_url
                    break
                except urllib.error.HTTPError as e:
                    last = f"HTTP {e.code}"
                    if e.code not in (403, 429, 500, 502, 503, 504):
                        break          # 404 and friends: do not retry
                except Exception as e:  # noqa: BLE001
                    last = f"{type(e).__name__}"
            if res[0] is None:
                res = (None, last or "unreachable")
        self.cache[url] = res
        return res


def normalized_host(value):
    """A conservative host identity for official-source binding.

    ``www`` is presentation, not authority, so it is the only label collapsed.
    Other subdomains remain distinct and are compared directionally below.
    """
    raw = str(value or "").strip()
    parsed = urllib.parse.urlparse(raw if "://" in raw else "//" + raw)
    host = (parsed.hostname or "").rstrip(".").casefold()
    if host.startswith("www."):
        host = host[4:]
    return host


def host_matches_trust(source_host, trusted_host):
    """Exact host or a source subdomain of a trusted parent; never the reverse."""
    source_host = normalized_host(source_host)
    trusted_host = normalized_host(trusted_host)
    if not source_host or not trusted_host:
        return False
    return source_host == trusted_host or source_host.endswith("." + trusted_host)


def source_bound_to_hosts(url, trusted_hosts, title=""):
    """Whether *url* stays inside hosts already linked to this conference."""
    host = normalized_host(url)
    trusted = {normalized_host(item) for item in (trusted_hosts or ())}
    trusted.discard("")
    if not trusted:
        label = f" for {title}" if title else ""
        return False, f"no trusted official link host is recorded{label}"
    if any(host_matches_trust(host, known) for known in trusted):
        return True, ""
    return False, (f"source host {host or '<missing>'} is unrelated to trusted "
                   f"official host(s): {', '.join(sorted(trusted))}")


def trusted_hosts_by_title(watchlist, historical_records=(), configured_hosts=None):
    """Build title -> hosts without trusting a freshly imported link blindly.

    Curated hosts and links from editions older than the active watchlist are
    anchors. A current/future host may extend them directionally, or bootstrap
    a genuinely new annual domain only when two independently fetched upstream
    datasets agree on the exact host. The model cannot edit this evidence: it
    is part of the immutable prepare-stage watchlist.
    """
    out = {}

    def add(title, link):
        host = normalized_host(link)
        if isinstance(title, str) and title and host:
            out.setdefault(title, set()).add(host)

    items = [item for item in (watchlist if isinstance(watchlist, list) else ())
             if isinstance(item, dict)]
    active_years = {}
    scheduled_years = {}
    active_identities = set()
    for item in items:
        title, year = item.get("title"), item.get("year")
        if isinstance(title, str) and isinstance(year, int) and not isinstance(year, bool):
            active_years.setdefault(title, set()).add(year)
            active_identities.add((title, year))
            reasons = item.get("reasons") or []
            if not (isinstance(reasons, list) and set(reasons) == {"audit-deferred"}):
                scheduled_years.setdefault(title, set()).add(year)

    for record in historical_records:
        if isinstance(record, dict):
            title, year = record.get("title"), record.get("year")
            years = active_years.get(title)
            anchor_before = min(scheduled_years.get(title) or years or [U.TODAY.year])
            if (not years or (isinstance(year, int) and not isinstance(year, bool)
                              and year < anchor_before
                              and (title, year) not in active_identities)):
                add(title, record.get("link"))
    for title, hosts in (configured_hosts or {}).items():
        if isinstance(hosts, str):
            hosts = [hosts]
        for host in hosts if isinstance(hosts, list) else ():
            add(title, host)

    for item in items:
        title = item.get("title")
        if not isinstance(title, str) or not title:
            continue
        evidence = {}
        for candidate in item.get("upstream_link_candidates") or ():
            if not isinstance(candidate, dict):
                continue
            source = candidate.get("source")
            host = normalized_host(candidate.get("link"))
            if isinstance(source, str) and source and host:
                evidence.setdefault(host, set()).add(source)
        for host, sources in evidence.items():
            if len(sources) >= 2:
                out.setdefault(title, set()).add(host)

        record = item.get("record") or {}
        current = normalized_host(
            record.get("link") if isinstance(record, dict) else None
        )
        anchors = out.get(title, set())
        if current and any(host_matches_trust(current, anchor) for anchor in anchors):
            anchors.add(current)
    return out


def configured_official_hosts(targets=None):
    """Return curated title -> host anchors from conferences.yml."""
    out = {}
    source_targets = targets if targets is not None else U.load_config()
    for target in source_targets:
        if not isinstance(target, dict):
            continue
        hosts = target.get("official_hosts") or []
        if isinstance(hosts, str):
            hosts = [hosts]
        if isinstance(hosts, list) and hosts:
            out[target.get("key")] = hosts
    return out


def configured_conference_identities(targets=None):
    """Return canonical title -> names an official page may use for the venue.

    An official host is not an identity boundary: Researchr, USENIX, ACM and
    IEEE each host pages for many conferences.  The configured key, aliases and
    full name are trusted repo-owned vocabulary; a model-supplied title is not.
    """
    out = {}
    source_targets = targets if targets is not None else U.load_config()
    for target in source_targets:
        if not isinstance(target, dict):
            continue
        key = target.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        names = [key, target.get("full_name")]
        aliases = target.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            names.extend(aliases)
        # Deduplicate by the same representation used for matching. Retain the
        # original text so diagnostics remain readable.
        seen, clean = set(), []
        for name in names:
            flat = flatten(str(name or ""))
            if flat and flat not in seen:
                seen.add(flat)
                clean.append(str(name))
        out[key] = clean
    return out


def _identity_regions(raw):
    """Extract title-like page regions before falling back to body text."""
    without_comments = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    without_inert = re.sub(
        r"<(script|style|svg|noscript|template)\b.*?</\1>", " ",
        without_comments, flags=re.S | re.I,
    )
    regions = []
    for match in re.finditer(r"<(title|h[1-3])\b[^>]*>(.*?)</\1\s*>",
                             without_inert, flags=re.S | re.I):
        text = strip_html(match.group(2)).strip()
        if text:
            regions.append((match.group(1).casefold(), text))
    # Some conference templates put the useful identity only in OpenGraph or
    # Twitter metadata rather than a visible heading.
    for tag in re.findall(r"<meta\b[^>]*>", without_inert, flags=re.I):
        attrs = dict((name.casefold(), htmllib.unescape(value))
                     for name, _, value in re.findall(
                         r"([:\w-]+)\s*=\s*(['\"])(.*?)\2", tag, flags=re.S))
        label = (attrs.get("property") or attrs.get("name") or "").casefold()
        if label in ("og:title", "twitter:title") and attrs.get("content"):
            regions.append((label, attrs["content"]))
    return regions


def _edition_years(text):
    """Edition years explicitly written as YYYY or apostrophe-YY."""
    normalized = normalize(text)
    years = {int(value) for value in re.findall(r"\b(20\d{2})\b", normalized)}
    years.update(2000 + int(value) for value in re.findall(
        r"['\u2019](\d{2})\b", normalized
    ))
    return years


def _sequence_positions(haystack, needle):
    if not needle or len(needle) > len(haystack):
        return []
    return [i for i in range(len(haystack) - len(needle) + 1)
            if haystack[i:i + len(needle)] == needle]


def page_bound_to_conference_year(raw, title, year, identity_aliases,
                                  identity_catalog=None):
    """Whether the fetched page identifies this conference edition.

    Title-like HTML regions are authoritative. If one names the conference and
    an explicit *different* edition, dates elsewhere cannot turn that page into
    evidence for the requested year. Pages with separate name/year headings
    still work through a bounded body-text fallback.
    """
    try:
        expected_year = int(year)
    except (TypeError, ValueError):
        return False, f"proposal has no valid conference year: {year!r}"
    if expected_year < 2000 or expected_year > 2099:
        return False, f"proposal conference year is outside 2000-2099: {year!r}"

    aliases = []
    seen = set()
    for alias in identity_aliases or ():
        alias_tokens = tokens(str(alias))
        key = tuple(alias_tokens)
        if key and key not in seen:
            seen.add(key)
            aliases.append((str(alias), alias_tokens))
    if not aliases:
        return False, f"no configured conference identity is recorded for {title!r}"

    regions = _identity_regions(raw)
    structured_name_seen = False
    for _, region in regions:
        region_tokens = tokens(region)
        if not any(_sequence_positions(region_tokens, alias_tokens)
                   for _, alias_tokens in aliases):
            continue
        structured_name_seen = True
        years = _edition_years(region)
        if expected_year in years:
            return True, ""
        if years:
            return False, (f"page title/heading identifies {title!r} edition(s) "
                           f"{', '.join(map(str, sorted(years)))}, not "
                           f"{expected_year}")

    # A shared-host page can link to the requested conference in its navigation.
    # Before using body text, reject a title/heading that positively identifies
    # a *different* configured conference. This keeps an "FSE 2027" sibling
    # link on an "ASE 2027" page from satisfying the fallback below.
    for other_title, other_aliases in (identity_catalog or {}).items():
        if other_title == title:
            continue
        other_sequences = [tokens(str(alias)) for alias in other_aliases or ()]
        other_sequences = [seq for seq in other_sequences if seq]
        for _, region in regions:
            region_tokens = tokens(region)
            if any(_sequence_positions(region_tokens, seq)
                   for seq in other_sequences):
                return False, (f"page title/heading identifies conference "
                               f"{other_title!r}, not {title!r}")

    body_tokens = tokens(strip_html(raw))
    expected = str(expected_year)
    nearby_other_years = set()
    name_seen = structured_name_seen
    for _, alias_tokens in aliases:
        for start in _sequence_positions(body_tokens, alias_tokens):
            name_seen = True
            lo = max(0, start - IDENTITY_BODY_RADIUS)
            hi = min(len(body_tokens), start + len(alias_tokens) + IDENTITY_BODY_RADIUS)
            nearby = body_tokens[lo:hi]
            if expected in nearby:
                return True, ""
            nearby_other_years.update(int(tok) for tok in nearby
                                      if re.fullmatch(r"20\d{2}", tok))

    if not name_seen:
        rendered = ", ".join(repr(alias) for alias, _ in aliases[:4])
        return False, (f"page does not identify conference {title!r}; expected "
                       f"one of {rendered}")
    if nearby_other_years:
        return False, (f"page identifies conference {title!r} near edition(s) "
                       f"{', '.join(map(str, sorted(nearby_other_years)))}, not "
                       f"{expected_year}")
    return False, (f"page identifies conference {title!r} but not edition "
                   f"{expected_year}")


def stored_records():
    """Yield generated records used as same-title historical host evidence."""
    for entry in U.load_existing().values():
        for item in entry.get("items") or ():
            record = item.get("data")
            if isinstance(record, dict):
                yield record


def source_ok(url):
    if not isinstance(url, str) or not url or url != url.strip():
        return False, "URL must be a non-empty trimmed string"
    try:
        p = urllib.parse.urlparse(url)
        host = normalized_host(url)
        port = p.port
    except (TypeError, ValueError):
        return False, "malformed URL"
    if p.scheme not in ("http", "https"):
        return False, "not an http(s) URL"
    if not host:
        return False, "URL has no host"
    if p.username is not None or p.password is not None:
        return False, "URL credentials are not allowed"
    if port not in (None, 80, 443):
        return False, "non-standard network port is not allowed"
    if host == "localhost" or host.endswith(".localhost"):
        return False, "local host is not an official public source"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return False, "non-public network address is not allowed"
    # Reject unusual numeric spellings (integer/octal/hex IPv4) that some URL
    # stacks resolve as loopback even though ipaddress intentionally refuses.
    if address is None and re.fullmatch(r"(?:0x[0-9a-f]+|[0-9.]+)", host, re.I):
        return False, "ambiguous numeric network address is not allowed"
    if any(host == d or host.endswith("." + d) for d in DENY_HOSTS):
        return False, f"{host} is a community tracker or mirror, not an official source"
    if DENY_PATH_RE.search(url):
        return False, "community tracker repository"
    return True, ""


# -------------------------------------------------------------------- verdicts

def verify_proposal(p, fetcher, trusted_hosts=None, identity_aliases=None,
                    identity_catalog=None):
    """Verify page claims, optionally bound to previously trusted official hosts.

    Production ``main`` always supplies host and identity sets, including an
    explicit empty set when no trust anchor is known. ``None`` retains
    direct-function test ergonomics. A host-bound direct call that omits
    identity aliases uses the proposal title as its sole identity.
    """
    pid = p.get("id", "<no id>")
    action = p.get("action")
    if action == "delete_manual":
        return {"id": pid, "status": "VERIFIED",
                "reason": "no page claim; upstream agreement is checked by the updater"}
    fields = p.get("fields") or {}
    url = p.get("source_url")
    if not fields:
        return {"id": pid, "status": "MALFORMED", "reason": "no fields to verify"}
    if not url:
        return {"id": pid, "status": "MALFORMED", "reason": "no source_url"}
    ok, why = source_ok(url)
    if not ok:
        return {"id": pid, "status": "REJECTED_SOURCE", "reason": why}
    if trusted_hosts is not None:
        ok, why = source_bound_to_hosts(url, trusted_hosts, p.get("title") or "")
        if not ok:
            return {"id": pid, "status": "REJECTED_SOURCE", "reason": why,
                    "url": url}
    if isinstance(fetcher, Fetcher):
        page, err = fetcher.get(url, trusted_hosts)
    else:
        page, err = fetcher.get(url)
    if page is None:
        return {"id": pid, "status": "UNREACHABLE", "reason": err, "url": url}
    final_url = (getattr(fetcher, "final_urls", {}) or {}).get(url, url)
    ok, why = source_ok(final_url)
    if not ok:
        return {"id": pid, "status": "REJECTED_SOURCE",
                "reason": f"redirect target rejected: {why}", "url": url,
                "final_url": final_url}
    if trusted_hosts is not None:
        ok, why = source_bound_to_hosts(final_url, trusted_hosts, p.get("title") or "")
        if not ok:
            return {"id": pid, "status": "REJECTED_SOURCE",
                    "reason": f"redirect target rejected: {why}", "url": url,
                    "final_url": final_url}
    identity_required = trusted_hosts is not None or identity_aliases is not None
    if identity_required:
        aliases = ([p.get("title")] if identity_aliases is None
                   else identity_aliases)
        ok, why = page_bound_to_conference_year(
            page, p.get("title") or "", p.get("year"), aliases,
            identity_catalog,
        )
        if not ok:
            return {"id": pid, "status": "REJECTED_SOURCE",
                    "reason": f"page identity rejected: {why}", "url": url,
                    "final_url": final_url}
    page_text = strip_html(page)
    page_toks = tokens(page_text)
    results = {}
    for name, claim in fields.items():
        value = claim.get("value")
        quotes = [e.get("quote", "") for e in (claim.get("evidence") or [])]

        if value is None:                       # a deletion: a negative claim
            ok, why = verify_absence(page_toks, name, claim.get("absence_scope_quote", ""))
            results[name] = {"status": "VERIFIED" if ok else "UNCONFIRMED", "reason": why}
            continue

        # Each cycle of a multi-value deadline needs its OWN grounded quote.
        # Checking the union with any() let one real quote validate a whole
        # list, including a fabricated second cycle - and the venues with lists
        # (NDSS, DIMVA, EuroSys) are exactly the ones at risk.
        if name in ("deadline", "abstract_deadline") and isinstance(value, list)                 and len(value) > 1:
            per, bad = [], None
            for item in value:
                f_i, req_i = value_forms(name, item)
                if not req_i:
                    bad = f"cycle {item!r} has no checkable form"
                    break
                hit = None
                for q in [q for q in quotes if q]:
                    time_ok, time_reason = deadline_time_compatible(
                        item, q, page_text, name
                    )
                    if not time_ok:
                        err_i = time_reason
                        continue
                    cov, err_i = ground_quote(page_toks, q, f_i,
                                              FIELD_LABELS.get(name, ((), ())),
                                              single_date=True)
                    if cov is not None:
                        hit = cov
                        break
                if hit is None:
                    bad = f"cycle {item!r} has no grounded quote of its own"
                    break
                per.append(hit)
            if bad:
                results[name] = {"status": "UNCONFIRMED", "reason": bad}
            else:
                results[name] = {"status": "VERIFIED", "coverage": min(per)}
            continue

        forms, required = value_forms(name, value)
        if not required:
            # NOT verified. A field with no checkable surface form - a note, a
            # link, a bare TBA - is one this gate has no opinion about, and
            # "no opinion" must never read as "checked and fine".
            results[name] = {"status": "UNCHECKED",
                             "reason": "no page-checkable surface form for this value"}
            continue

        best_err, ok = "no evidence supplied", False
        for q in [q for q in quotes if q]:
            if name in ("deadline", "abstract_deadline"):
                time_ok, time_reason = deadline_time_compatible(
                    value, q, page_text, name
                )
                if not time_ok:
                    best_err = time_reason
                    continue
            cov, err2 = ground_quote(
                page_toks, q, forms, FIELD_LABELS.get(name, ((), ())),
                single_date=name in ('deadline', 'abstract_deadline'))
            if cov is not None:
                results[name] = {"status": "VERIFIED", "coverage": cov}
                ok = True
                break
            best_err = err2
        if not ok:
            results[name] = {"status": "UNCONFIRMED", "reason": best_err}

    # A proposal is globally VERIFIED only when *every* field earned VERIFIED.
    # The applier consumes per-field statuses too, but the top-level verdict must
    # never say accepted for VERIFIED+UNCHECKED and smuggle the unchecked field
    # through a whole-proposal fast path.
    field_statuses = [result.get("status") for result in results.values()]
    if field_statuses and all(status == "VERIFIED" for status in field_statuses):
        status = "VERIFIED"
    elif any(status == "UNCONFIRMED" for status in field_statuses):
        status = "UNCONFIRMED"
    else:
        status = "UNCHECKED"
    return {"id": pid, "status": status, "url": url, "final_url": final_url,
            "fields": results,
            "sha256": hashlib.sha256(page.encode("utf-8", "replace")).hexdigest()[:16]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--proposals", default="audit-proposals.json")
    ap.add_argument("--watchlist", default="watchlist.json",
                    help="watchlist supplying current trusted official links")
    ap.add_argument("--out", default="audit-verdicts.json")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--fixtures")
    ap.add_argument("--report-only", action="store_true",
                    help="always exit 0; the verdicts file is still written")
    args = ap.parse_args()

    try:
        doc = json.loads(Path(args.proposals).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: cannot read {args.proposals} ({exc})")
        return 1

    try:
        watchlist = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
        if not isinstance(watchlist, list):
            raise ValueError("expected a JSON array")
        targets = U.load_config()
        trusted_by_title = trusted_hosts_by_title(
            watchlist, stored_records(), configured_official_hosts(targets)
        )
        identities_by_title = configured_conference_identities(targets)
    except Exception as exc:  # noqa: BLE001 - missing trust must fail closed
        print(f"FATAL: cannot build official-host trust from {args.watchlist} ({exc})")
        return 1

    fetcher = Fetcher(offline=args.offline, fixtures=args.fixtures)
    verdicts, counts = [], {}
    for p in doc.get("proposals") or []:
        # ``set()`` is intentional: a conference with no known official link
        # cannot bootstrap trust from the source it is asking us to approve.
        v = verify_proposal(
            p, fetcher,
            trusted_by_title.get(p.get("title"), set()),
            identities_by_title.get(p.get("title"), ()),
            identities_by_title,
        )
        # The applier consumes `status: accepted`; only a full VERIFIED earns it.
        v["accepted"] = v["status"] == "VERIFIED"
        verdicts.append(v)
        counts[v["status"]] = counts.get(v["status"], 0) + 1
        mark = "ok " if v["accepted"] else "!! "
        print(f"  {mark}{v['id']}: {v['status']}"
              + (f" - {v.get('reason')}" if v.get("reason") else ""))
        for f, r in (v.get("fields") or {}).items():
            if r["status"] != "VERIFIED":
                print(f"       {f}: {r['status']} - {r.get('reason', '')}")

    Path(args.out).write_text(json.dumps(
        {"tool": "verify_citations/1.0", "counts": counts,
         "verdicts": [{"id": v["id"],
                       "status": "accepted" if v["accepted"] else "rejected",
                       "gate": v["status"], "detail": v} for v in verdicts]},
        indent=2) + "\n", encoding="utf-8")
    print(f"\n{', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'no proposals'}"
          f" -> {args.out}")
    if args.report_only:
        return 0
    return 2 if counts.get("MALFORMED") or counts.get("REJECTED_SOURCE") else 0


if __name__ == "__main__":
    sys.exit(main())
