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
  verify_citations.py --proposals audit-proposals.json --out audit-verdicts.json
  verify_citations.py ... --offline --fixtures DIR    (tests; never touches the network)

Exit 0 = every proposal decided. 2 = at least one MALFORMED/REJECTED_SOURCE.
1 = fatal (inputs unreadable).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html as htmllib
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
    flat = flatten(text)
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
        first = flatten(str(value).split(",")[0])
        return ([first] if first else []), bool(first)
    if field == "date":
        rng = U.parse_date_range(str(value))
        if not rng:
            return [], False
        return date_forms(rng[0]) + date_forms(rng[1]), True
    return [], False


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
    ft = form.split()
    if not ft:
        return
    n = len(page_toks)
    for i in range(n - len(ft) + 1):
        if page_toks[i:i + len(ft)] == ft:
            lo = max(0, i + len(ft) // 2 - size // 2)
            yield lo, page_toks[lo:lo + size]


def phrase_present(flat: str, tokset: set, phrase: str) -> bool:
    """Multi-word phrases match as substrings; single words as whole tokens.

    Without the token rule, a short label like 'src' would match inside
    unrelated words and reject valid evidence.
    """
    return phrase in flat if " " in phrase else phrase in tokset


def label_pos(flat: str, phrase: str) -> int:
    """Character offset of a label in the flattened quote, or -1."""
    if " " in phrase:
        return flat.find(phrase)
    m = re.search(rf"\b{re.escape(phrase)}\b", flat)
    return m.start() if m else -1


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
    best = 0.0
    for form in (forms or [" ".join(qt[:3])]):
        for _, win in find_windows(page_toks, form, size):
            cov = lcs_len(qt, win) / len(qt)
            best = max(best, cov)
            if cov >= LCS_THRESHOLD:
                return round(cov, 3), None
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
    # The label is present - is a date sitting next to it?
    for idx, tok in enumerate(block):
        if tok not in {v for v in vocab if " " not in v}:
            continue
        near = block[max(0, idx - ABSENCE_RADIUS): idx + ABSENCE_RADIUS]
        if any(t in MONTH_TOKENS for t in near) and any(t.isdigit() for t in near):
            return False, (f"the cited block mentions {tok!r} within "
                           f"{ABSENCE_RADIUS} tokens of a date; absence not established")
    return True, "the cited block mentions the label but associates no date with it"


# ------------------------------------------------------------------- fetching

class Fetcher:
    def __init__(self, offline=False, fixtures=None):
        self.offline, self.fixtures = offline, fixtures
        self.cache, self.robots, self.last_hit = {}, {}, {}

    def _fixture(self, url):
        key = hashlib.sha1(url.encode()).hexdigest()
        for cand in (Path(self.fixtures) / f"{key}.html",
                     Path(self.fixtures) / f"{urllib.parse.urlparse(url).netloc}.html"):
            if cand.exists():
                return cand.read_text(encoding="utf-8")
        return None

    def _raw(self, url):
        host = urllib.parse.urlparse(url).netloc
        gap = time.monotonic() - self.last_hit.get(host, 0)
        if gap < PER_HOST_DELAY:
            time.sleep(PER_HOST_DELAY - gap)
        self.last_hit[host] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            return r.read(MAX_BYTES).decode("utf-8", errors="replace"), r.geturl()

    def robots_allows(self, url):
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
                txt, _ = self._raw(base + "/robots.txt")
                rp.parse(txt.splitlines())
            except Exception:  # noqa: BLE001 - unknown policy, not a refusal
                rp = None
            self.robots[base] = rp
        rp = self.robots[base]
        return True if rp is None else rp.can_fetch(UA, url)

    def get(self, url):
        if url in self.cache:
            return self.cache[url]
        if self.offline:
            txt = self._fixture(url) if self.fixtures else None
            res = (txt, None) if txt is not None else (None, "offline: no fixture")
            self.cache[url] = res
            return res
        if not self.robots_allows(url):
            res = (None, "robots.txt disallows this path")
        else:
            res, last = (None, "unfetched"), None
            for delay in RETRY_DELAYS:
                if delay:
                    time.sleep(delay)
                try:
                    txt, _ = self._raw(url)
                    res = (txt, None)
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


def source_ok(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        return False, "not an http(s) URL"
    host = p.netloc.lower()
    if any(host == d or host.endswith("." + d) for d in DENY_HOSTS):
        return False, f"{host} is a community tracker or mirror, not an official source"
    if DENY_PATH_RE.search(url):
        return False, "community tracker repository"
    return True, ""


# -------------------------------------------------------------------- verdicts

def verify_proposal(p, fetcher):
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
    page, err = fetcher.get(url)
    if page is None:
        return {"id": pid, "status": "UNREACHABLE", "reason": err, "url": url}
    page_text = strip_html(page)
    page_toks = tokens(page_text)
    results, grounded, refuted = {}, 0, 0
    for name, claim in fields.items():
        value = claim.get("value")
        quotes = [e.get("quote", "") for e in (claim.get("evidence") or [])]

        if value is None:                       # a deletion: a negative claim
            ok, why = verify_absence(page_toks, name, claim.get("absence_scope_quote", ""))
            results[name] = {"status": "VERIFIED" if ok else "UNCONFIRMED", "reason": why}
            grounded += 1 if ok else 0
            refuted += 0 if ok else 1
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
                refuted += 1
            else:
                results[name] = {"status": "VERIFIED", "coverage": min(per)}
                grounded += 1
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
            cov, err2 = ground_quote(
                page_toks, q, forms, FIELD_LABELS.get(name, ((), ())),
                single_date=name in ('deadline', 'abstract_deadline'))
            if cov is not None:
                results[name] = {"status": "VERIFIED", "coverage": cov}
                ok = True
                break
            best_err = err2
        if ok:
            grounded += 1
        else:
            results[name] = {"status": "UNCONFIRMED", "reason": best_err}
            refuted += 1

    # Start pessimistic and earn VERIFIED, rather than starting at VERIFIED and
    # only degrading: an optimistic default means every gap counts as a pass.
    if refuted:
        status = "UNCONFIRMED"
    elif grounded == 0:
        status = "UNCHECKED"
    else:
        status = "VERIFIED"
    return {"id": pid, "status": status, "url": url, "fields": results,
            "sha256": hashlib.sha256(page.encode("utf-8", "replace")).hexdigest()[:16]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--proposals", default="audit-proposals.json")
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

    fetcher = Fetcher(offline=args.offline, fixtures=args.fixtures)
    verdicts, counts = [], {}
    for p in doc.get("proposals") or []:
        v = verify_proposal(p, fetcher)
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
