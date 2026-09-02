#!/usr/bin/env python3
"""Apply audit proposals to deadlines/data/manual.yml, deterministically.

The auditor emits `audit-proposals.json` and never writes YAML. This program
validates those proposals and writes the accepted fields. Splitting it that way
means the model's output is machine-checkable, field-group outcomes are
deterministic, and a whole class of YAML and merge errors cannot happen at all.

manual.yml is the pipeline's persistent override layer and may contain legacy
curated entries. The guiding rule throughout is: never destroy existing work.
Before any modification the file must round-trip through parse/render
byte-for-byte; on mismatch this program refuses rather than rewriting under a
misparse.

Usage:
  apply_proposals.py --proposals audit-proposals.json --ungated
  apply_proposals.py --proposals audit-proposals.json --verdicts audit-verdicts.json

Exactly one of --verdicts / --ungated is required.

With --verdicts, only fields VERIFIED by the gate can be applied, and coupled
deadline fields stay together. Verified field groups must also stay inside the
deterministic one-run safety bounds in risk_policy. Identical verified claims
outside those bounds promote after two distinct weekly audit dates. Deferred
fields stay unchanged and remain on later watchlists; they never require a
person to edit conference data.

--ungated skips the gate entirely. It exists for local diagnostics and is
spelled out so it cannot be enabled accidentally by the publishing workflow.

Exit codes: 0 = applied cleanly (possibly nothing to do); 1 = refused, nothing
written; 3 = applied, but some proposals were malformed (see the report).
"""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_batches as B  # noqa: E402
import audit_state as AS  # noqa: E402
import reconcile_audit_outcomes as RA  # noqa: E402
import risk_policy  # noqa: E402
import update_deadlines as U  # noqa: E402

MANUAL_PATH = U.MANUAL_PATH
AUDIT_STATE_PATH = AS.STATE_PATH
MAX_RETAINED_CITATIONS = 3
DEFAULT_MAX_CHANGES = 8
ACTIONS = ("upsert_manual", "create_record", "delete_manual", "no_change")
WATCHLIST_REASONS = ("deadline-within-45-days", "tba-upcoming-cycle",
                     "manual-override-active", "cross-source-disagreement",
                     "stale-placeholder-note", "coverage-gap", "tba-metadata",
                     "audit-deferred", "scheduled-full-audit")
UNVERIFIABLE_CAUSES = ("not_checked", "no_official_page", "fetch_blocked",
                       "page_ambiguous", "javascript_only", "pdf_only")

DEFAULT_PREAMBLE = [
    "# Manual overrides have the highest priority (priority 0 in deadline-tracker.js).",
    "# The autonomous audit stores confirmed CFP data here when trackers differ;",
    "# every entry MUST cite the official source it was verified against.",
]


# --------------------------------------------------------------- manual.yml I/O

class Chunk:
    """One manual.yml entry plus the comment block bound to it."""

    def __init__(self, comments, body):
        self.comments = list(comments)
        self.body = list(body)

    @property
    def key(self):
        try:
            rec = U.yaml.safe_load("\n".join(self.body))
        except Exception:  # noqa: BLE001 - a malformed chunk simply has no key
            return None
        if not isinstance(rec, list) or not rec or not isinstance(rec[0], dict):
            return None
        title, year = rec[0].get("title"), rec[0].get("year")
        return (title, year) if isinstance(year, int) else None

    def record(self):
        rec = U.yaml.safe_load("\n".join(self.body))
        return rec[0] if isinstance(rec, list) and rec else {}

    def citation_lines(self):
        return [c for c in self.comments if "Verified" in c]


class ManualFile:
    def __init__(self, preamble, chunks, epilogue=()):
        self.preamble = list(preamble)
        self.chunks = list(chunks)
        # Trailing comments after the last entry belong to the FILE, not to
        # that entry. Left in the chunk body they round-trip fine but vanish
        # the moment that entry is upserted, since the body is regenerated from
        # the record - silently deleting a human's note.
        self.epilogue = list(epilogue)

    def find(self, key):
        for i, c in enumerate(self.chunks):
            if c.key == key:
                return i
        return None


def parse_manual(text):
    """Split into a preamble and (comment block, entry) chunks.

    The backwards walk over '#' lines stops at a blank line, which reproduces
    exactly the adjacency rule audit_lint.py enforces - so a chunk that parses
    here is a chunk that lints there.
    """
    lines = text.split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith("- ")]
    if not starts:
        return ManualFile([l for l in lines if l.strip()], [])
    chunk_starts = []
    for i in starts:
        j = i
        while j - 1 >= 0 and lines[j - 1].startswith("#"):
            j -= 1
        chunk_starts.append(j)
    preamble = lines[:chunk_starts[0]]
    while preamble and not preamble[-1].strip():
        preamble.pop()
    chunks = []
    for n, start in enumerate(chunk_starts):
        end = chunk_starts[n + 1] if n + 1 < len(chunk_starts) else len(lines)
        block = lines[start:end]
        while block and not block[-1].strip():
            block.pop()
        split = starts[n] - start
        body = block[split:]
        # For the LAST chunk only, peel a trailing comment run off the body: it
        # is file epilogue, not part of that entry.
        epilogue = []
        if n == len(chunk_starts) - 1:
            k = len(body)
            while k > 0 and (body[k - 1].startswith("#") or not body[k - 1].strip()):
                k -= 1
            if k < len(body):
                epilogue = [l for l in body[k:] if l.strip()]
                body = body[:k]
        chunks.append(Chunk(block[:split], body))
    return ManualFile(preamble, chunks, epilogue)


def render_manual(mf):
    parts = ["\n".join(mf.preamble).rstrip("\n")] if mf.preamble else []
    parts += ["\n".join(c.comments + c.body) for c in mf.chunks]
    if mf.epilogue:
        parts.append("\n".join(mf.epilogue))
    return "\n\n".join(parts) + "\n"


def write_manual_atomic(text):
    """Replace manual.yml atomically so an interrupted write cannot truncate it."""
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANUAL_PATH.with_name(MANUAL_PATH.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, MANUAL_PATH)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def restore_manual(text, existed):
    """Restore the exact pre-run state, including absence of the file."""
    if existed:
        write_manual_atomic(text)
    else:
        MANUAL_PATH.unlink(missing_ok=True)


def assert_round_trip(text):
    """Refuse to touch a file we cannot reproduce.

    A human may introduce a shape the parser does not model. Rewriting under a
    misparse could silently drop a hand-written override, which is the worst
    failure available to this program - strictly worse than doing nothing.
    """
    out = render_manual(parse_manual(text))
    if out != text:
        for n, (a, b) in enumerate(zip(text.split("\n"), out.split("\n"))):
            if a != b:
                return (f"manual.yml does not round-trip; first difference at "
                        f"line {n + 1}:\n  on disk: {a!r}\n  rendered: {b!r}")
        return "manual.yml does not round-trip (length differs)"
    return None


def render_manual_entry(rec):
    """Like update_deadlines.render_record, but emits explicit nulls.

    render_record drops None values, so it cannot express the deletion form
    (`abstract_deadline: null`) that apply_manual_override keys on. Everything
    else delegates to render_scalar so quoting stays byte-identical.
    """
    order = [k for k in U.FIELD_ORDER if k in ("title", "year") or k in U.MANUAL_FIELDS]
    keys = [k for k in order if k in rec]
    lines = []
    for key in keys:
        value = rec[key]
        prefix = "- " if not lines else "  "
        if key in ("deadline", "abstract_deadline") and isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            lines += ["    - " + ("null" if v is None else U.yaml_quote(v)) for v in value]
        else:
            lines.append(f"{prefix}{key}: {U.render_scalar(key, value)}")
    return lines


def wrap_comment(text, width=76):
    out, line = [], "#"
    for word in str(text).split():
        if len(line) + 1 + len(word) > width and line != "#":
            out.append(line)
            line = "#"
        line += " " + word
    if line != "#":
        out.append(line)
    return out


def comment_block(reason, url, date, quote, retained):
    lines = wrap_comment(reason)
    lines += wrap_comment(f"Verified {date} against {url}")
    if quote:
        lines += wrap_comment(f'"{quote}"')
    for old in retained[:MAX_RETAINED_CITATIONS]:
        lines.append("# Earlier: " + old.lstrip("# ").strip())
    return lines


# ------------------------------------------------------------------ validation

def seed_from_watchlist(watchlist_path, out_path, audit_date):
    """Write a skeleton audit-proposals.json before the auditor runs.

    Asking a model to create a file at the end of a long run is a soft
    instruction, and compliance proved nondeterministic: one run produced a
    complete 30/30 file, the next produced nothing at all. Seeding removes the
    question - the file always exists, so the run is always legible.

    Every record starts as `not_checked`, which is the PESSIMISTIC claim. An
    auditor that does nothing therefore reports that it verified nothing, which
    is both true and visible. Seeding with `no_change` would have the opposite
    property: doing nothing would look like a clean audit.
    """
    items = json.loads(Path(watchlist_path).read_text(encoding="utf-8"))
    doc = {
        "audit_date": audit_date,
        "watchlist_size": len(items),
        "proposals": [],
        "unverifiable": [
            {"title": i.get("title"), "year": i.get("year"),
             "cause": "not_checked", "attempted": [],
             "note": "Seeded before the audit; the auditor did not reach this record."}
            for i in items],
    }
    Path(out_path).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    return len(items)


def audit_effort(doc):
    """(examined, total, causes) - how much of the watchlist was actually read."""
    unver = doc.get("unverifiable") or []
    causes = {}
    for u in unver:
        c = u.get("cause") or "unspecified"
        causes[c] = causes.get(c, 0) + 1
    not_checked = causes.get("not_checked", 0)
    machine_deferred = doc.get("machine_deferred") or []
    if machine_deferred:
        causes["machine_deferred"] = len(machine_deferred)
    total = (len(doc.get("proposals") or []) + len(unver)
             + len(machine_deferred))
    return total - not_checked - len(machine_deferred), total, causes


def coverage(doc, watchlist_path):
    """Which watchlist records did the auditor actually account for?

    An empty proposals array is a legitimate outcome, but only when the auditor
    says so explicitly - every watchlist item should turn up as a proposal (of
    any action, including no_change) or as an `unverifiable` entry. Without
    this, "checked all 30 and found nothing" and "looked at 3 and gave up" are
    the same output.
    """
    try:
        items = json.loads(Path(watchlist_path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        # Do NOT return quietly. A missing watchlist used to make the coverage
        # line simply vanish from the output while the exit code stayed 0 - the
        # coverage check disappearing unnoticed is the same "silence reads as
        # success" failure this program exists to prevent, one layer up.
        print(f"  [!] coverage NOT checked: {watchlist_path} unreadable ({exc})")
        return None
    want = {(i.get("title"), i.get("year")) for i in items}
    seen = {(p.get("title"), p.get("year")) for p in doc.get("proposals") or []}
    seen |= {(u.get("title"), u.get("year")) for u in doc.get("unverifiable") or []}
    seen |= {(u.get("title"), u.get("year"))
             for u in doc.get("machine_deferred") or []}
    return len(want), sorted(want - seen)


def exact_coverage(doc, watchlist_path):
    """Return exact-once coverage violations for a completed autonomous audit."""
    try:
        items = json.loads(Path(watchlist_path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"watchlist unreadable ({exc})"]
    expected = Counter((i.get("title"), i.get("year")) for i in items)
    accounted = (list(doc.get("proposals") or [])
                 + list(doc.get("unverifiable") or [])
                 + list(doc.get("machine_deferred") or []))
    observed = Counter((i.get("title"), i.get("year")) for i in accounted
                       if isinstance(i, dict))
    problems = []
    order = lambda item: (str(item[0][0]), str(item[0][1]))
    for key, count in sorted((expected - observed).items(), key=order):
        problems.append(f"missing {key[0]} {key[1]} ({count})")
    for key, count in sorted((observed - expected).items(), key=order):
        problems.append(f"unexpected {key[0]} {key[1]} ({count})")
    for key in sorted(expected.keys() & observed.keys(), key=lambda x: (str(x[0]), str(x[1]))):
        if observed[key] != expected[key]:
            problems.append(f"{key[0]} {key[1]} appears {observed[key]} times; expected once")
    return problems


def watchlist_by_identity(watchlist_path):
    """Load the immutable prepare-stage watchlist as an exact identity map."""
    items = json.loads(Path(watchlist_path).read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("watchlist must be a JSON array")
    out = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"watchlist[{index}] is not an object")
        key = (item.get("title"), item.get("year"))
        if not isinstance(key[0], str) or not isinstance(key[1], int) \
                or isinstance(key[1], bool):
            raise ValueError(f"watchlist[{index}] has an invalid identity")
        if key in out:
            raise ValueError(f"duplicate watchlist identity: {key[0]} {key[1]}")
        out[key] = item
    return out


def _err(errors, pid, msg):
    errors.append(f"{pid}: {msg}")


def validate_multicycle_evidence(name, value, evidence, pid, errors):
    """Require one explicitly bound quote for every concrete deadline cycle.

    A verifier can prove that two dates both occur on a page without proving
    which quote supports which proposed list item. Multi-cycle claims therefore
    use an exact, value-preserving ``for_value`` binding. Single concrete-cycle
    claims retain the historical unbound evidence format.
    """
    if not isinstance(value, list):
        return True
    concrete = [item for item in value
                if item is not None and item.upper() not in ("TBA", "TBD")]
    if len(concrete) <= 1:
        return True

    ok = True
    expected = set(concrete)
    if len(expected) != len(concrete):
        duplicates = sorted(item for item, count in Counter(concrete).items()
                            if count > 1)
        _err(errors, pid, f"field {name!r} repeats concrete cycle value(s): "
                          + ", ".join(repr(item) for item in duplicates))
        ok = False

    bindings = Counter()
    for index, ev in enumerate(evidence):
        if not isinstance(ev, dict):
            # The ordinary evidence-shape check reports this independently.
            continue
        if "for_value" not in ev:
            _err(errors, pid, f"field {name!r} multi-cycle evidence[{index}] "
                              "is missing exact for_value binding")
            ok = False
            continue
        bound = ev["for_value"]
        if not isinstance(bound, str) or bound not in expected:
            choices = ", ".join(repr(item) for item in sorted(expected))
            _err(errors, pid, f"field {name!r} multi-cycle evidence[{index}] has "
                              f"unknown for_value {bound!r}; expected one of {choices}")
            ok = False
            continue
        bindings[bound] += 1

    for item in sorted(expected):
        if bindings[item] == 0:
            _err(errors, pid, f"field {name!r} is missing evidence bound with "
                              f"for_value {item!r}")
            ok = False
        elif bindings[item] > 1:
            _err(errors, pid, f"field {name!r} has duplicate evidence bindings "
                              f"for for_value {item!r}")
            ok = False
    return ok


def validate_proposal(p, targets_by_key, errors):
    """Schema + repo-contract checks. Returns True when the proposal is usable."""
    pid = p.get("id") or "<no id>"
    if not isinstance(p, dict):
        _err(errors, pid, "not an object")
        return False
    action = p.get("action")
    if action not in ACTIONS:
        _err(errors, pid, f"unknown action {action!r}")
        return False
    title, year = p.get("title"), p.get("year")
    if title not in targets_by_key:
        _err(errors, pid, f"title {title!r} is not a canonical key in conferences.yml")
        return False
    if not isinstance(year, int) or isinstance(year, bool):
        _err(errors, pid, f"year {year!r} is not an integer")
        return False
    if not (U.FROM_YEAR <= year <= U.TO_YEAR):
        _err(errors, pid, f"year {year} outside {U.FROM_YEAR}..{U.TO_YEAR}; "
                          "such a record is never consumed and never rendered")
        return False
    if p.get("id") != f"{action}:{title}:{year}":
        _err(errors, pid, f"id must be '{action}:{title}:{year}'")
        return False
    if action == "delete_manual":
        # Not a claim about a page: the updater computes upstream agreement.
        if p.get("obsolete_because") != "upstream_agrees":
            _err(errors, pid, "delete_manual requires obsolete_because: upstream_agrees")
            return False
        return True

    # no_change is validated exactly like a correction. "This record is already
    # right" is a claim about a page, and an unevidenced one is indistinguishable
    # from not having looked - which is how a lazy run scores full coverage.

    url = p.get("source_url", "")
    if not isinstance(url, str) or not re.match(r"^https?://", url):
        _err(errors, pid, "source_url must be an http(s) URL")
        return False
    if U.clean(p.get("reason")) == "":
        _err(errors, pid, "reason is required and becomes the entry's comment")
        return False
    fields = p.get("fields")
    if not isinstance(fields, dict) or not fields:
        _err(errors, pid, "fields must be a non-empty object")
        return False
    if action == "create_record":
        concrete = [v for v in U.as_list((fields.get("deadline") or {}).get("value"))
                    if v and str(v).upper() not in ("TBA", "TBD")]
        if not concrete:
            _err(errors, pid, "create_record needs a concrete deadline: a new record "
                              "without one is a permanent TBA row nothing will fill")
            return False

    ok = True
    for name, claim in fields.items():
        if name not in U.MANUAL_FIELDS:
            _err(errors, pid, f"field {name!r} is not overridable "
                              f"(allowed: {', '.join(U.MANUAL_FIELDS)})")
            ok = False
            continue
        if name in ("start", "end"):
            # AUDITOR.md forbids these and the updater derives them from `date`.
            # Proposing them directly is how start/end come to contradict the
            # span they describe.
            _err(errors, pid, f"{name!r} is derived from `date`; propose `date` instead")
            ok = False
            continue
        if not isinstance(claim, dict) or "value" not in claim:
            _err(errors, pid, f"field {name!r} must be an object with a 'value'")
            ok = False
            continue
        value = claim["value"]
        if value is None:
            if name == "timezone":
                _err(errors, pid, "timezone deletion is never applied automatically: "
                                  "the page renders a missing timezone as AoE, i.e. "
                                  "LATER than the truth. Omit this field and retain "
                                  "the existing timezone")
                ok = False
            if not U.clean(claim.get("absence_scope_quote")):
                _err(errors, pid, f"deleting {name!r} requires absence_scope_quote - "
                                  "the verbatim block that would contain it")
                ok = False
            continue
        if name in ("deadline", "abstract_deadline"):
            if not isinstance(value, (str, list)):
                _err(errors, pid, f"{name} value must be a string or list of strings")
                ok = False
                continue
            if isinstance(value, list) and (not value or len(value) > 8):
                _err(errors, pid, f"{name} must contain 1..8 cycles")
                ok = False
                continue
            allowed_item = lambda item: isinstance(item, str) or (
                name == "abstract_deadline" and item is None
            )
            if any(not allowed_item(item) for item in U.as_list(value)):
                _err(errors, pid, f"{name} cycles must be strings"
                                  + (" or null" if name == "abstract_deadline" else ""))
                ok = False
                continue
        elif not isinstance(value, str):
            _err(errors, pid, f"field {name!r} value must be a string")
            ok = False
            continue
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            _err(errors, pid, f"field {name!r} has no evidence")
            ok = False
            continue
        for ev in evidence:
            if not isinstance(ev, dict) or not isinstance(ev.get("quote"), str) \
                    or len(U.clean(ev.get("quote"))) < 8:
                _err(errors, pid, f"field {name!r} has an empty or trivial quote")
                ok = False
        if name in ("deadline", "abstract_deadline") \
                and not validate_multicycle_evidence(
                    name, value, evidence, pid, errors):
            ok = False
        if name == "note":
            if "\n" in str(value):
                _err(errors, pid, "note must be a single line")
                ok = False
            # deadline-tracker.js:131 FABRICATES an abstract deadline at
            # paper-7d from any note matching this pattern. A note is free text
            # with no checkable surface form, so without this check it is a
            # route from unverifiable prose to a rendered deadline that appears
            # on no page anywhere.
            if re.search(r"abstract.*1 week before|1 week before.*abstract",
                         str(value), re.I):
                _err(errors, pid, "this note would make the frontend fabricate an "
                                  "abstract deadline (deadline-tracker.js:131); reword it")
                ok = False
        if name in ("deadline", "abstract_deadline"):
            for v in U.as_list(value):
                if v is not None and str(v).upper() not in ("TBA", "TBD") \
                        and not U.valid_deadline(v):
                    _err(errors, pid, f"{name} {v!r} must be 'YYYY-MM-DD HH:MM'")
                    ok = False
    return ok


def validate_unverifiable(items, targets_by_key, errors):
    """Validate negative/deferral outcomes just as strictly as proposals."""
    ok = True
    for index, item in enumerate(items or []):
        label = f"unverifiable[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: not an object")
            ok = False
            continue
        title, year, cause = item.get("title"), item.get("year"), item.get("cause")
        if title not in targets_by_key:
            errors.append(f"{label}: title {title!r} is not a canonical key")
            ok = False
        if not isinstance(year, int) or isinstance(year, bool) or not U.FROM_YEAR <= year <= U.TO_YEAR:
            errors.append(f"{label}: year {year!r} is outside the rendered window")
            ok = False
        if cause not in UNVERIFIABLE_CAUSES:
            errors.append(f"{label}: unknown cause {cause!r}")
            ok = False
        attempted = item.get("attempted")
        if cause != "not_checked":
            if not isinstance(attempted, list) or not attempted:
                errors.append(f"{label}: cause {cause!r} requires attempted official URL(s)")
                ok = False
            elif len(attempted) > RA.MAX_ATTEMPTED_URLS:
                errors.append(
                    f"{label}: attempted may contain at most "
                    f"{RA.MAX_ATTEMPTED_URLS} official URLs"
                )
                ok = False
            elif any(not re.match(r"^https?://", str(url)) for url in attempted):
                errors.append(f"{label}: attempted entries must be http(s) URLs")
                ok = False
    return ok


def validate_merged(rec, canonical_keys, pid, errors):
    """Run the updater's own record validation before writing.

    A manual.yml entry matching no existing record and no upstream candidate
    never reaches a generated file, so update_deadlines' merge loops never
    validate it - but the frontend loads manual.yml directly at priority 0 and
    renders it regardless. Validating here is what stops a bad row reaching the
    page.
    """
    probe = dict(rec)
    probe.setdefault("deadline", "TBA")
    problems = U.validate(probe, canonical_keys, require_deadline=False)
    for problem in problems:
        _err(errors, pid, problem)
    return not problems


# ---------------------------------------------------------------------- applier

def normalise_fields(fields):
    out = {}
    for name, claim in fields.items():
        value = claim["value"]
        if isinstance(value, list) and len(value) == 1:
            value = value[0]  # match build_merged: one cycle renders as a scalar
        out[name] = value
    return out


def fields_match_current(fields, current_record):
    """Whether every proposed field already has the rendered value.

    This comparison deliberately uses the updater's canonical form so scalar
    versus one-item-list, AoE versus UTC-12, and seconds versus minute precision
    are treated the same.  A ``None`` proposal is a deletion and only matches
    when the rendered field is already absent.
    """
    current = U.canon_record(current_record or {})
    for name, value in normalise_fields(fields).items():
        if value is None:
            if name in current:
                return False
            continue
        proposed = U.canon_record({name: value})
        if proposed.get(name) != current.get(name):
            return False
    return True


def effective_current_records(existing_files, manual):
    """Frontend-effective records: generated data overlaid by priority-0 manual."""
    current = {}
    for _, entry in existing_files.items():
        for item in entry.get("items") or ():
            rec = item.get("data") or {}
            if isinstance(rec.get("year"), int):
                current[(rec.get("title"), rec["year"])] = dict(rec)
    for (title, year), override in manual.items():
        rec = current.get((title, year), {"title": title, "year": year})
        U.apply_manual_override(rec, override)
        current[(title, year)] = rec
    return current


def verdict_reason(verdict):
    """Compact, actionable diagnostics from verify_citations' full verdict."""
    if not verdict:
        return "citation verdict missing"
    detail = verdict.get("detail") or {}
    gate = verdict.get("gate") or detail.get("status") or verdict.get("status", "unknown")
    reasons = []
    if detail.get("reason"):
        reasons.append(str(detail["reason"]))
    for name, result in (detail.get("fields") or {}).items():
        if result.get("status") == "VERIFIED":
            continue
        why = result.get("reason") or result.get("status") or "not verified"
        reasons.append(f"{name}: {why}")
    suffix = "; ".join(reasons)
    return f"gate {gate}" + (f" ({suffix})" if suffix else "")


DEADLINE_ATOMIC_FIELDS = frozenset(("deadline", "abstract_deadline", "timezone"))


def split_verified_fields(proposal, verdict):
    """Split a proposal into independently verified and pending parts.

    One weak metadata quote must not discard an otherwise grounded correction.
    Deadline fields and timezone stay atomic whenever more than one of them is
    proposed, because applying only half can move the effective instant.  Every
    cycle of a multi-cycle field is already atomic inside verify_citations.

    Per-field results are authoritative even when the verdict's top-level
    ``status`` says accepted.  This is deliberately fail-closed: a historical
    verifier bug marked VERIFIED+UNCHECKED as globally VERIFIED, and trusting
    that shortcut applied the unchecked field too.
    """
    if proposal.get("action") == "delete_manual":
        # This action has no page fields; its global verdict is the only gate.
        if (verdict or {}).get("status") == "accepted":
            return proposal, None
        return None, proposal

    fields = proposal.get("fields") or {}
    detail = (verdict or {}).get("detail") or verdict or {}
    results = detail.get("fields") or {}
    verified = {name for name in fields
                if (results.get(name) or {}).get("status") == "VERIFIED"}

    coupled = set(fields) & DEADLINE_ATOMIC_FIELDS
    if len(coupled) > 1 and not coupled.issubset(verified):
        verified -= coupled

    # A partial create without its paper deadline is not a usable record.
    if proposal.get("action") == "create_record" and "deadline" not in verified:
        verified.clear()

    if not verified:
        return None, proposal
    if verified == set(fields):
        return proposal, None

    accepted = dict(proposal)
    accepted["fields"] = {name: fields[name] for name in fields if name in verified}
    pending = dict(proposal)
    pending["fields"] = {name: fields[name] for name in fields if name not in verified}
    return accepted, pending


def proposal_state_scope(proposal):
    """Value-free persistent-state scope for a validated proposal."""
    if proposal.get("action") == "delete_manual":
        return {AS.DELETE_SCOPE}
    return set((proposal.get("fields") or {}).keys())


def scope_text(proposal):
    """Human-readable scope for one independently handled proposal fragment."""
    if proposal.get("action") == "delete_manual":
        return "scope: whole override"
    fields = sorted((proposal.get("fields") or {}).keys())
    return "fields: " + (", ".join(fields) if fields else "none")


def atomic_context_requirement(proposal, current_record):
    """Return (required, missing) for a real deadline-related mutation.

    Looking only at fields the model chose to mention is not atomic: a
    deadline-only proposal could otherwise inherit an unverified timezone or
    abstract cycle. Exact-current fragments are not mutations and deliberately
    return an empty requirement so narrow confirmations remain useful.
    """
    if proposal.get("action") not in ("upsert_manual", "create_record"):
        return set(), set()
    claims = proposal.get("fields") or {}
    changed = {
        name for name in DEADLINE_ATOMIC_FIELDS & set(claims)
        if not fields_match_current({name: claims[name]}, current_record)
    }
    if not changed:
        return set(), set()

    proposed = normalise_fields(claims)
    required = set(changed)
    required.add("timezone")
    for name in ("deadline", "abstract_deadline"):
        effective = proposed[name] if name in proposed else current_record.get(name)
        if effective is not None:
            required.add(name)
    return required, required - set(claims)


def outcome_accounting(proposal_doc, applied, skipped, held, scope_rows=None):
    """Count original proposals separately from their field-group outcomes.

    A mixed citation verdict deliberately splits one proposal into an accepted
    fragment and a pending fragment with the same id.  Consequently the outcome
    row count is not a proposal count and must be reported independently. In
    production, ``scope_rows`` additionally proves that those fragments form an
    exact, disjoint partition of every original field scope.
    """
    originals = [p for p in (proposal_doc.get("proposals") or [])
                 if isinstance(p, dict)]
    original = [p.get("id") for p in originals]
    rows = ([pid for pid, _ in applied]
            + [pid for pid, _ in skipped]
            + [p.get("id") for p, _ in held])
    frequencies = Counter(rows)
    original_ids = set(original)
    outcome_ids = set(rows)
    result = {
        "proposals": len(original),
        "field_groups": len(rows),
        "split_proposals": sum(frequencies[pid] > 1 for pid in original_ids),
        "unaccounted": sorted(original_ids - outcome_ids),
        "unexpected": sorted(outcome_ids - original_ids),
        "scope_errors": [],
    }
    if scope_rows is None:
        return result

    expected_outcomes = Counter(
        [("applied", pid) for pid, _ in applied]
        + [("confirmed/no-op", pid) for pid, _ in skipped]
        + [("deferred", p.get("id")) for p, _ in held]
    )
    scoped_outcomes = Counter((status, pid) for status, pid, _ in scope_rows)
    if scoped_outcomes != expected_outcomes:
        result["scope_errors"].append(
            "scope ledger does not match the reported outcome rows")

    original_counts = Counter(original)
    for pid, count in sorted(original_counts.items()):
        if count > 1:
            result["scope_errors"].append(
                f"duplicate input proposal id {pid!r}")
    original_scopes = {
        p.get("id"): proposal_state_scope(p)
        for p in originals if original_counts[p.get("id")] == 1
    }
    fragments = {}
    for status, pid, scope in scope_rows:
        if not isinstance(scope, (set, frozenset)) or not scope \
                or any(not isinstance(field, str) or not field for field in scope):
            result["scope_errors"].append(
                f"{status} outcome {pid!r} has an invalid empty/non-string scope")
            continue
        fragments.setdefault(pid, []).append(frozenset(scope))

    for pid, original_scope in original_scopes.items():
        parts = fragments.get(pid, [])
        duplicate_parts = [scope for scope, count in Counter(parts).items()
                           if count > 1]
        for scope in duplicate_parts:
            result["scope_errors"].append(
                f"proposal {pid!r} has duplicate field fragment "
                f"{sorted(scope)!r}")
        combined = set()
        overlap = set()
        for scope in parts:
            overlap.update(combined & set(scope))
            combined.update(scope)
        if overlap:
            result["scope_errors"].append(
                f"proposal {pid!r} has overlapping outcome field(s): "
                + ", ".join(sorted(overlap)))
        missing = original_scope - combined
        extra = combined - original_scope
        if missing:
            result["scope_errors"].append(
                f"proposal {pid!r} has unaccounted field(s): "
                + ", ".join(sorted(missing)))
        if extra:
            result["scope_errors"].append(
                f"proposal {pid!r} has unexpected outcome field(s): "
                + ", ".join(sorted(extra)))
    return result


def bound_autonomous_changes(proposals, limit):
    """Take a stable per-run mutation budget and return deferred overflow.

    Refusing the whole run when a yearly rollover produced many legitimate
    corrections made the safety rail non-convergent: the same oversized set
    failed every week.  Watchlist order already puts urgent records first, so a
    stable prefix makes bounded progress without weakening any evidence gate.
    """
    if limit < 0:
        raise ValueError("max changes must be non-negative")
    accepted = list(proposals[:limit])
    reason = (f"per-run autonomous change budget ({limit}) exhausted; "
              "scheduled for a later audit")
    deferred = [(proposal, reason) for proposal in proposals[limit:]]
    return accepted, deferred


def primary_quote(fields):
    for claim in fields.values():
        for ev in claim.get("evidence") or []:
            q = U.clean(ev.get("quote"))
            if q:
                return q
    for claim in fields.values():
        q = U.clean(claim.get("absence_scope_quote"))
        if q:
            return q
    return ""


def apply_proposals(proposals, mf, audit_date, canonical_keys, targets_by_key, errors,
                    approved_delete_ids=()):
    applied, skipped = [], []
    approved_delete_ids = set(approved_delete_ids)
    for p in proposals:
        pid = p["id"]
        action, title, year = p["action"], p["title"], p["year"]
        key = (title, year)
        scope = scope_text(p)
        if action == "no_change":
            skipped.append((pid, f"[{scope}] no_change performs no mutation"))
            continue
        if action == "delete_manual":
            idx = mf.find(key)
            if idx is None:
                skipped.append((pid, f"[{scope}] no manual.yml entry to delete"))
                continue
            if pid not in approved_delete_ids:
                skipped.append((
                    pid, f"[{scope}] delete_manual is not applied automatically "
                         "without two-run deterministic upstream agreement"))
                continue
            del mf.chunks[idx]
            applied.append((pid, f"[{scope}] retired obsolete override for "
                                 f"{title} {year}"))
            continue

        new_fields = normalise_fields(p["fields"])
        idx = mf.find(key)
        existing = mf.chunks[idx].record() if idx is not None else {}
        merged = {k: v for k, v in existing.items() if k not in ("title", "year")}
        merged.update(new_fields)          # unmentioned human fields survive
        record = {"title": title, "year": year, **merged}
        U.default_timezone(record)

        if not validate_merged(record, canonical_keys, pid, errors):
            skipped.append((pid, f"[{scope}] failed record validation"))
            continue

        if idx is not None:
            old = {k: v for k, v in existing.items() if k not in ("title", "year")}
            if U.canon_record(dict(old, title=title, year=year)) == U.canon_record(record):
                skipped.append((pid, f"[{scope}] already matches manual.yml (no-op)"))
                continue

        retained = mf.chunks[idx].citation_lines() if idx is not None else []
        chunk = Chunk(comment_block(p["reason"], p["source_url"], audit_date,
                                    primary_quote(p["fields"]), retained),
                      render_manual_entry(record))
        changed = ", ".join(sorted(new_fields))
        if idx is None:
            mf.chunks.append(chunk)
            applied.append((pid, f"[{scope}] added an override for {title} "
                                 f"{year} ({changed})"))
        else:
            mf.chunks[idx] = chunk
            applied.append((pid, f"[{scope}] updated {title} {year} ({changed})"))
    return applied, skipped


def write_report(path, applied, skipped, errors, proposals, gated, held=(),
                 accounting=None):
    accounting = accounting or outcome_accounting(
        proposals, applied, skipped, held)
    lines = [
        "Automated deadline audit corrections.", "",
        f"**Proposal accounting:** {accounting['proposals']} proposal record(s); "
        f"{accounting['split_proposals']} split by field; "
        f"{accounting['field_groups']} field-group outcomes.",
        f"**Field-group outcomes:** {len(applied)} applied, {len(held)} deferred, "
        f"{len(skipped)} confirmed/no-op.",
        f"**Apply/schema errors:** {len(errors)}.", "",
    ]
    if not gated:
        lines += ["> [!NOTE]",
                  "> No automated verification gate ran on these proposals - every"
                  " proposal is ineligible for autonomous publication.", ""]
    if applied:
        lines += [f"**Applied field groups ({len(applied)})**", ""]
        lines += [f"- {desc}" for _, desc in applied] + [""]
    if held:
        lines += [f"**Deferred field groups ({len(held)})** — the evidence gate or",
                  "a safety bound did not confirm these. Values for the deferred fields",
                  "were kept unchanged;",
                  "the scheduler will retry them on a later autonomous audit.",
                  ""]
        for p, why in held:
            fields = ", ".join(f"`{k}` → `{(v or {}).get('value')}`"
                               for k, v in (p.get("fields") or {}).items())
            action = p.get("action") or "unknown"
            lines.append(f"- **{p.get('title')} {p.get('year')}** "
                         f"(`{action}`; {scope_text(p)}; {why}): {fields}")
            if p.get("source_url"):
                lines.append(f"  - source: {p['source_url']}")
            for k, v in (p.get("fields") or {}).items():
                for ev in (v or {}).get("evidence") or []:
                    binding = (f" for {ev.get('for_value')}"
                               if ev.get("for_value") is not None else "")
                    lines.append(
                        f"  - quote ({k}{binding}): \"{ev.get('quote', '')}\"")
        lines.append("")
    if skipped:
        lines += [f"**Confirmed/no-op field groups ({len(skipped)})**", ""]
        lines += [f"- `{pid}` — {why}" for pid, why in skipped] + [""]
    if errors:
        lines += [f"**Apply/schema error details ({len(errors)})**", ""]
        lines += [f"- {e}" for e in errors] + [""]
    unverifiable = [u for u in (proposals.get("unverifiable") or [])]
    if unverifiable:
        lines += [f"**Unverifiable ({len(unverifiable)})**", ""]
        lines += [f"- {u.get('title')} {u.get('year')} — {u.get('cause')}"
                  for u in unverifiable] + [""]
    machine_deferred = [u for u in (proposals.get("machine_deferred") or [])]
    if machine_deferred:
        lines += [
            f"**Machine-deferred ({len(machine_deferred)})** — these records",
            "were not counted as examined and remain on the autonomous retry queue.",
            "",
        ]
        lines += [f"- {u.get('title')} {u.get('year')} — {u.get('reason')}"
                  for u in machine_deferred] + [""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    # The CLI is also invoked repeatedly in unit/integration processes. Do not
    # let updater diagnostics from an earlier invocation poison this one.
    U.health.clear()
    U.warnings.clear()
    U.actions.clear()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--proposals", default="audit-proposals.json")
    ap.add_argument("--verdicts")
    ap.add_argument("--ungated", action="store_true",
                    help="apply without a verification gate (local diagnostics only)")
    ap.add_argument("--report", default="audit-summary.md")
    ap.add_argument("--max-changes", type=int, default=DEFAULT_MAX_CHANGES)
    ap.add_argument("--watchlist",
                    help="report which watchlist records went unaddressed")
    ap.add_argument("--require-complete", action="store_true",
                    help="fail validation if any watchlist record is missing or not_checked")
    ap.add_argument(
        "--allow-unfinished", action="store_true",
        help="accept raw not_checked checkpoints during the pre-finalization stage",
    )
    ap.add_argument(
        "--allow-machine-deferred", action="store_true",
        help="accept the trusted finalizer's retry-only coverage group",
    )
    ap.add_argument("--require-some-proposal", action="store_true",
                    help="for a non-empty watchlist, fail validation when every "
                         "outcome is unverifiable (used to trigger one bounded retry)")
    ap.add_argument("--seed-from-watchlist", metavar="WATCHLIST",
                    help="write a skeleton proposals file marking every "
                         "watchlist record not_checked, then exit")
    ap.add_argument("--audit-date", default=dt.date.today().isoformat())
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.seed_from_watchlist:
        n = seed_from_watchlist(args.seed_from_watchlist, args.proposals,
                                args.audit_date)
        print(f"seeded {args.proposals} with {n} record(s) marked not_checked")
        return 0

    if args.allow_unfinished and args.allow_machine_deferred:
        print("APPLY REFUSED: --allow-unfinished and --allow-machine-deferred "
              "are mutually exclusive")
        return 1
    if args.allow_unfinished and not args.validate_only:
        print("APPLY REFUSED: --allow-unfinished is validation-only")
        return 1
    if args.require_complete and not args.watchlist:
        print("APPLY REFUSED: --require-complete requires --watchlist")
        return 1

    if args.max_changes < 0:
        print("APPLY REFUSED: --max-changes must be non-negative")
        return 1

    if not args.validate_only and bool(args.verdicts) == bool(args.ungated):
        print("APPLY REFUSED: pass exactly one of --verdicts or --ungated")
        return 1

    path = Path(args.proposals)
    if not path.exists():
        if args.require_complete or args.allow_unfinished \
                or args.allow_machine_deferred:
            print(f"APPLY REFUSED: required proposal checkpoint does not exist: {path}")
            return 1
        print(f"no {path} - the auditor proposed nothing")
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"APPLY REFUSED: {path} is not valid JSON ({exc})")
        return 1
    if not isinstance(doc, dict) or not isinstance(doc.get("proposals"), list):
        print("APPLY REFUSED: expected an object with a 'proposals' array")
        return 1

    if args.allow_machine_deferred:
        if "machine_deferred" not in doc:
            print("APPLY REFUSED: --allow-machine-deferred requires trusted "
                  "finalizer output")
            return 1
        if not args.watchlist:
            print("APPLY REFUSED: --allow-machine-deferred requires --watchlist")
            return 1
        try:
            final_watchlist = B.validate_watchlist(json.loads(
                Path(args.watchlist).read_text(encoding="utf-8")
            ))
            B.validate_audit_document(
                final_watchlist, doc, str(path),
                allow_machine_deferred=True,
            )
        except (B.BatchError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"APPLY REFUSED: invalid trusted-finalizer document ({exc})")
            return 1
    elif "machine_deferred" in doc:
        print("APPLY REFUSED: machine_deferred is reserved for trusted finalization")
        return 1

    targets = U.load_config()
    if not targets:
        print("APPLY REFUSED: conferences.yml unreadable")
        return 1
    targets_by_key = {t["key"]: t for t in targets}
    canonical_keys = set(targets_by_key)

    errors: list[str] = []
    held: list = []
    pre_skipped: list = []
    pre_skipped_scopes: dict[str, set[str]] = {}
    approved_delete_ids: set[str] = set()
    state = None
    state_observed: set[AS.ClaimRef] = set()
    state_audited: dict[str, set[str] | None] = {}
    immutable_watchlist = {}
    audit_date = doc.get("audit_date") or dt.date.today().isoformat()
    proposals = [p for p in doc["proposals"]
                 if isinstance(p, dict) and validate_proposal(p, targets_by_key, errors)]
    validate_unverifiable(doc.get("unverifiable") or [], targets_by_key, errors)
    if args.watchlist:
        try:
            source_trust_policy = RA.source_trust_policy_for_watchlist(
                args.watchlist, targets)
            errors.extend(RA.unverifiable_source_trust_errors(
                doc, source_trust_policy))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(
                f"unverifiable source trust could not be established: {exc}")

    # Completion is a publication invariant, not merely a workflow preflight.
    # Enforce it before any persistent state or manual YAML can be mutated.
    if args.require_complete:
        _, _, completion_causes = audit_effort(doc)
        if completion_causes.get("not_checked", 0):
            errors.append(
                f"incomplete audit: {completion_causes['not_checked']} "
                "record(s) remain not_checked"
            )
        for problem in exact_coverage(doc, args.watchlist):
            errors.append(f"incomplete audit: {problem}")

    # Never perform a partial transaction from a mixed valid/malformed model
    # document. The workflow already treats any schema error as fatal; refusing
    # before manual/state mutation also keeps local invocations byte-identical.
    if errors and not args.validate_only:
        for error in errors:
            print(f"  [!] apply/schema error {error}")
        print("APPLY REFUSED: proposal document contains validation errors")
        return 1

    # Persistence is enabled only for the production-shaped gated invocation,
    # which always supplies the immutable prepare-stage watchlist. Local
    # diagnostics without a watchlist retain the one-run safety policy and do
    # not write repository state.
    if args.verdicts and args.watchlist:
        try:
            immutable_watchlist = watchlist_by_identity(args.watchlist)
            state = AS.load(AUDIT_STATE_PATH)
            AS.prune_years(state, U.FROM_YEAR, U.TO_YEAR)
            for item in doc.get("unverifiable") or []:
                if isinstance(item, dict) and item.get("cause") != "not_checked":
                    AS.mark_retry(state, item.get("title"), item.get("year"),
                                  audit_date, "unverifiable")
                    state_audited[AS.identity_key(item.get("title"),
                                                  item.get("year"))] = None
            # Trusted machine deferrals are scheduling state, not audit
            # outcomes. Queue them without marking the identity as audited;
            # doing so would reset unrelated corroboration claims.
            for item in doc.get("machine_deferred") or []:
                AS.mark_retry(state, item.get("title"), item.get("year"),
                              audit_date, "unverifiable")
        except (AS.StateError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"APPLY REFUSED: persistent audit state/watchlist unusable ({exc})")
            return 1

    if args.verdicts:
        try:
            verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
            verdict_by_id = {v["id"]: v for v in verdicts.get("verdicts", [])}
        except Exception as exc:  # noqa: BLE001 - fail closed, never open
            print(f"APPLY REFUSED: verdict file unusable ({exc})")
            return 1
        # A rejected citation is a DEFER, not an error and never a request for a
        # person to edit YAML. Per-field results partition mixed proposals; only
        # verified fragments can be confirmed or changed, while pending fields
        # retain their old values and are retried later.
        current_manual = U.load_manual(targets)
        if U.health:
            print("APPLY REFUSED: manual.yml is invalid; current effective values "
                  "cannot be established")
            return 1
        current = effective_current_records(U.load_existing(), current_manual)
        kept = []
        try:
            for p in proposals:
                identity = (p.get("title"), p.get("year"))
                state_key = AS.identity_key(*identity) if state is not None else None
                if state is not None:
                    if state_key not in state_audited:
                        state_audited[state_key] = set(proposal_state_scope(p))
                    elif state_audited[state_key] is not None:
                        state_audited[state_key].update(proposal_state_scope(p))
                current_record = current.get(identity) or {}
                verdict = verdict_by_id.get(p["id"])
                # Always consult field verdicts. A top-level accepted flag is
                # not evidence for every field and must never bypass this
                # partition.
                candidate, pending = split_verified_fields(p, verdict)
                if pending is not None:
                    held.append((pending, verdict_reason(verdict)))
                    if state is not None:
                        AS.mark_retry_fields(
                            state, *identity, audit_date, "citation",
                            proposal_state_scope(pending))
                if candidate is None:
                    continue

                if candidate.get("action") == "delete_manual":
                    marker = (immutable_watchlist.get(identity) or {}).get(
                        "upstream_agreement")
                    marker_ok = (
                        isinstance(marker, dict)
                        and marker.get("agrees") is True
                        and marker.get("all_fetches_healthy") is True
                        and isinstance(marker.get("sources"), list)
                        and bool(marker["sources"])
                        and all(isinstance(src, str) and src for src in marker["sources"])
                        and isinstance(marker.get("basis_digest"), str)
                        and re.fullmatch(r"sha256:[0-9a-f]{64}",
                                         marker["basis_digest"]) is not None
                    )
                    if state is None or not marker_ok:
                        why = ("delete_manual requires complete deterministic agreement "
                               "from every healthy configured upstream source")
                        held.append((candidate, why))
                        if state is not None:
                            AS.mark_retry_fields(
                                state, *identity, audit_date, "citation",
                                proposal_state_scope(candidate))
                        continue
                    # The immutable upstream agreement is a substantive
                    # record-level result. Only now may it discharge a prior
                    # whole-record completion retry.
                    AS.resolve_record_retry(state, *identity)
                    promoted, observed_ref = AS.observe_verified_claim(
                        state, candidate,
                        {"upstream_agreement": marker["basis_digest"]},
                        audit_date)
                    state_observed.add(observed_ref)
                    if promoted:
                        kept.append(candidate)
                        approved_delete_ids.add(candidate["id"])
                    else:
                        held.append((candidate,
                                     "awaiting the second distinct weekly upstream-agreement run"))
                    continue

                verdict_detail = (verdict or {}).get("detail") or {}
                source_trust = verdict_detail.get("source_trust")
                if source_trust not in ("trusted", "provisional"):
                    held.append((
                        candidate,
                        "citation verifier supplied no valid source-trust class",
                    ))
                    if state is not None:
                        AS.mark_retry_fields(
                            state, *identity, audit_date, "citation",
                            proposal_state_scope(candidate))
                    continue

                source_basis = None
                if source_trust == "provisional":
                    source_basis = verdict_detail.get("source_trust_basis")
                    if not isinstance(source_basis, str) or re.fullmatch(
                            r"sha256:[0-9a-f]{64}", source_basis) is None:
                        held.append((
                            candidate,
                            "provisional official host has no valid lowercase "
                            "sha256 source-trust basis",
                        ))
                        if state is not None:
                            AS.mark_retry_fields(
                                state, *identity, audit_date, "citation",
                                proposal_state_scope(candidate))
                        continue

                if state is not None:
                    # At least one field has verified against a trusted (or
                    # provenance-bound provisional) source. Only such a
                    # substantive result may discharge a prior whole-record
                    # machine deferral; a missing/rejected verdict above keeps
                    # the full completion obligation intact.
                    AS.resolve_record_retry(state, *identity)

                matches = fields_match_current(candidate.get("fields") or {}, current_record)
                if source_trust == "provisional" and matches \
                        and candidate.get("action") in ("no_change", "upsert_manual"):
                    # A grounded provisional page can truthfully confirm that
                    # no YAML mutation is needed, but it is not strong enough
                    # to erase a pending correction/corroboration claim.  Do
                    # not observe it in the same field-scope slot: that would
                    # overwrite the stronger claim before this source matured.
                    # Keep the identity scheduled until a strongly trusted
                    # confirmation or an independently matured correction
                    # resolves it.
                    scope = set(proposal_state_scope(candidate))
                    pre_skipped.append((
                        candidate["id"],
                        f"[{scope_text(candidate)}] provisional source confirms "
                        "the rendered fields; retry state retained",
                    ))
                    pre_skipped_scopes[candidate["id"]] = scope
                    if state is not None:
                        audited = state_audited.get(state_key)
                        if isinstance(audited, set):
                            audited.difference_update(scope)
                            if not audited:
                                state_audited.pop(state_key, None)
                        AS.mark_retry_fields(
                            state, *identity, audit_date, "citation", scope)
                    continue
                if candidate.get("action") == "no_change":
                    if matches:
                        pre_skipped.append((
                            candidate["id"],
                            f"[{scope_text(candidate)}] verified fields match "
                            "rendered data"))
                        pre_skipped_scopes[candidate["id"]] = set(
                            proposal_state_scope(candidate))
                        if state is not None:
                            AS.resolve_fields(
                                state, *identity, proposal_state_scope(candidate))
                    else:
                        held.append((candidate,
                                     "non-mutating confirmation disagrees with the current record"))
                        if state is not None:
                            AS.mark_retry_fields(
                                state, *identity, audit_date, "citation",
                                proposal_state_scope(candidate))
                    continue
                if candidate.get("action") == "upsert_manual" and matches:
                    pre_skipped.append((
                        candidate["id"],
                        f"[{scope_text(candidate)}] verified fields already match "
                        "rendered data (no-op)"))
                    pre_skipped_scopes[candidate["id"]] = set(
                        proposal_state_scope(candidate))
                    if state is not None:
                        AS.resolve_fields(
                            state, *identity, proposal_state_scope(candidate))
                    continue

                required_atomic, missing_atomic = atomic_context_requirement(
                    candidate, current_record)
                if missing_atomic:
                    held.append((
                        candidate,
                        "deadline mutation is missing verified atomic context "
                        f"field(s): {', '.join(sorted(missing_atomic))}; required "
                        f"group: {', '.join(sorted(required_atomic))}",
                    ))
                    if state is not None:
                        AS.mark_retry_fields(
                            state, *identity, audit_date, "citation",
                            proposal_state_scope(candidate) | missing_atomic)
                    continue

                # A page on a brand-new host nominated by exactly one immutable
                # upstream is grounded but not yet a strong authority.  It can
                # confirm an existing value without mutation above; every
                # correction is quarantined until the identical normalized fact
                # and provenance digest verify again on a scheduled date at
                # least six days later.  Only the digest enters repository
                # state--never the model URL, quote, or prose.
                if source_trust == "provisional":
                    if state is None:
                        held.append((
                            candidate,
                            "provisional official host requires persistent two-run "
                            "corroboration",
                        ))
                        continue
                    promoted, observed_ref = AS.observe_verified_claim(
                        state, candidate, normalise_fields(candidate["fields"]),
                        audit_date, basis_digest=source_basis)
                    state_observed.add(observed_ref)
                    if promoted:
                        kept.append(candidate)
                    else:
                        held.append((
                            candidate,
                            "provisional official host is quarantined; awaiting the "
                            "same provenance-bound fact on a second scheduled run",
                        ))
                    continue
                what, why = risk_policy.decide(
                    "VERIFIED", candidate, current_record)
                if what == "apply":
                    kept.append(candidate)
                elif state is not None:
                    promoted, observed_ref = AS.observe_verified_claim(
                        state, candidate, normalise_fields(candidate["fields"]),
                        audit_date)
                    state_observed.add(observed_ref)
                    if promoted:
                        kept.append(candidate)
                    else:
                        held.append((candidate, why + "; awaiting a second distinct verified run"))
                else:
                    held.append((candidate, why))

            if state is not None:
                AS.finish_corroboration_claims(
                    state, state_audited, state_observed)
        except AS.StateError as exc:
            print(f"APPLY REFUSED: cannot update persistent audit state ({exc})")
            return 1
        proposals = kept

    if args.validate_only:
        for e in errors:
            print(f"  [!] {e}")
        actions = {}
        for p in doc["proposals"]:
            if isinstance(p, dict):
                actions[p.get("action")] = actions.get(p.get("action"), 0) + 1
        print(f"{len(proposals)} proposal(s) valid, "
              f"{len(errors)} apply/schema error(s)"
              + (f" ({', '.join(f'{k}={v}' for k, v in sorted(actions.items()))})"
                 if actions else ""))
        examined, total, causes = audit_effort(doc)
        if causes:
            print("unverifiable: " + ", ".join(f"{k}={v}" for k, v in sorted(causes.items())))
        incomplete = False
        retry_needed = False
        watchlist_total = None
        if args.watchlist:
            cov = coverage(doc, args.watchlist)
            if cov:
                wl_total, missing = cov
                watchlist_total = wl_total
                print(f"coverage: {wl_total - len(missing)}/{wl_total} watchlist "
                      "record(s) accounted for")
                for title, year in missing[:20]:
                    print(f"  [!] not addressed: {title} {year}")
                if missing:
                    print("  (a record the auditor neither proposed for nor listed "
                          "as unverifiable was silently skipped)")
                    incomplete = True
        if args.require_some_proposal and watchlist_total \
                and not doc["proposals"]:
            print("  [!] retry requested: a non-empty shard produced no positive "
                  "proposal or no_change finding")
            retry_needed = True
        if args.require_complete and causes.get("not_checked", 0):
            print(f"  [!] incomplete audit: {causes['not_checked']} record(s) remain not_checked")
            incomplete = True
        if args.require_complete and args.watchlist:
            for problem in exact_coverage(doc, args.watchlist):
                print(f"  [!] incomplete audit: {problem}")
                incomplete = True
        if total:
            print(f"examined: {examined}/{total} record(s) actually checked")
            if examined == 0:
                if args.allow_machine_deferred and doc.get("machine_deferred"):
                    print("  [!] audit degraded: every record is machine-deferred; "
                          "none count as examined and all remain scheduled")
                elif args.allow_unfinished:
                    print("  [!] shard checkpoint is entirely unfinished; the clean "
                          "global finalizer will enforce the zero-work circuit breaker")
                else:
                    print("  [!] the auditor examined nothing: every record is still "
                          "marked not_checked from the seed")
                    return 1
        return 1 if errors or retry_needed \
            or (args.require_complete and incomplete) else 0

    if args.verdicts:
        proposals, budget_deferred = bound_autonomous_changes(
            proposals, args.max_changes)
        held.extend(budget_deferred)
        if state is not None:
            try:
                for proposal, _ in budget_deferred:
                    AS.mark_retry_fields(
                        state, proposal.get("title"), proposal.get("year"),
                        audit_date, "change-budget", proposal_state_scope(proposal))
            except AS.StateError as exc:
                print(f"APPLY REFUSED: cannot persist budget deferral ({exc})")
                return 1

    manual_existed = MANUAL_PATH.exists()
    original = MANUAL_PATH.read_text(encoding="utf-8") if manual_existed else ""
    if original:
        problem = assert_round_trip(original)
        if problem:
            print(f"APPLY REFUSED: {problem}")
            return 1
        mf = parse_manual(original)
    else:
        mf = ManualFile(DEFAULT_PREAMBLE, [])

    applied, apply_skipped = apply_proposals(
        proposals, mf, audit_date, canonical_keys, targets_by_key, errors,
        approved_delete_ids)
    skipped = pre_skipped + apply_skipped

    # validate_merged() can discover a cross-field error only after otherwise
    # valid proposal fields are overlaid on the existing manual entry. Refuse
    # the entire in-memory transaction before either manual.yml or audit state
    # is persisted; never publish the other candidates from a partially invalid
    # batch.
    if errors:
        for error in errors:
            print(f"  [!] apply/schema error {error}")
        print("APPLY REFUSED: post-merge record validation failed; nothing written")
        return 1

    final_scopes = {p.get("id"): set(proposal_state_scope(p)) for p in proposals}
    scope_rows = (
        [("applied", pid, final_scopes.get(pid, set())) for pid, _ in applied]
        + [("confirmed/no-op", pid, pre_skipped_scopes.get(pid, set()))
           for pid, _ in pre_skipped]
        + [("confirmed/no-op", pid, final_scopes.get(pid, set()))
           for pid, _ in apply_skipped]
        + [("deferred", p.get("id"), set(proposal_state_scope(p)))
           for p, _ in held]
    )
    accounting = outcome_accounting(
        doc, applied, skipped, held, scope_rows=scope_rows)
    if accounting["unaccounted"] or accounting["unexpected"] \
            or accounting["scope_errors"]:
        details = []
        if accounting["unaccounted"]:
            details.append("unaccounted input proposal(s): "
                           + ", ".join(accounting["unaccounted"]))
        if accounting["unexpected"]:
            details.append("unexpected outcome id(s): "
                           + ", ".join(accounting["unexpected"]))
        details.extend(accounting["scope_errors"])
        print("APPLY REFUSED: outcome accounting invariant failed ("
              + "; ".join(details) + ")")
        return 1

    if state is not None:
        proposal_scopes = {
            p.get("id"): ((p.get("title"), p.get("year")), final_scopes[p.get("id")])
            for p in proposals
        }
        try:
            # pre_skipped candidates were resolved inline using their exact
            # verified fragment. Only outcomes from the kept candidate list
            # belong to this id-to-scope map.
            for pid, _ in applied + apply_skipped:
                scoped = proposal_scopes.get(pid)
                if scoped:
                    identity, fields = scoped
                    AS.resolve_fields(state, *identity, fields)
        except AS.StateError as exc:
            print(f"APPLY REFUSED: cannot resolve persistent audit state ({exc})")
            return 1

    if len(applied) > args.max_changes:
        print(f"APPLY REFUSED: internal change-budget violation: {len(applied)} "
              f"changes exceeds --max-changes {args.max_changes}")
        return 1

    if applied and not args.dry_run:
        try:
            write_manual_atomic(render_manual(mf))
        except OSError as exc:
            print(f"APPLY REFUSED: cannot atomically write manual.yml ({exc})")
            return 1
        U.health.clear()
        U.warnings.clear()
        U.load_manual(U.load_config())
        if U.health:
            try:
                restore_manual(original, manual_existed)
            except OSError as exc:
                print(f"APPLY REFUSED: manual.yml validation failed and rollback "
                      f"also failed ({exc})")
                return 1
            for h in U.health:
                print(f"  [!] {h}")
            print("APPLY REFUSED: the written manual.yml would degrade the updater; "
                  "reverted")
            return 1

    if state is not None and not errors and not args.dry_run:
        try:
            AS.save(state, AUDIT_STATE_PATH)
        except AS.StateError as exc:
            if applied:
                try:
                    restore_manual(original, manual_existed)
                except OSError as rollback_exc:
                    print(f"APPLY REFUSED: state save and manual.yml rollback both "
                          f"failed ({rollback_exc})")
                    return 1
            print(f"APPLY REFUSED: persistent audit state could not be saved ({exc}); "
                  "manual.yml reverted")
            return 1

    write_report(args.report, applied, skipped, errors, doc,
                 gated=bool(args.verdicts), held=held,
                 accounting=accounting)
    for pid, desc in applied:
        print(f"  applied  {pid}: {desc}")
    for pid, why in skipped:
        print(f"  confirmed/no-op  {pid}: {why}")
    for p, why in held:
        print(f"  deferred {p['id']} [{scope_text(p)}]: {why}; deferred fields "
              "kept unchanged and queued for automatic retry")
    for e in errors:
        print(f"  [!] apply/schema error {e}")
    print(f"\nProposal accounting: {accounting['proposals']} proposal record(s); "
          f"{accounting['split_proposals']} split by field; "
          f"{accounting['field_groups']} field-group outcomes")
    print(f"Field-group outcomes: {len(applied)} applied, {len(held)} deferred, "
          f"{len(skipped)} confirmed/no-op"
          + (" (dry run)" if args.dry_run else ""))
    print(f"Apply/schema errors: {len(errors)}")
    return 3 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
