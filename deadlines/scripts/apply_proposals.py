#!/usr/bin/env python3
"""Apply audit proposals to deadlines/data/manual.yml, deterministically.

The auditor emits `audit-proposals.json` and never writes YAML. This program
validates those proposals and writes the accepted ones. Splitting it that way
means the model's output is machine-checkable, per-proposal accept/reject is
trivial, and a whole class of YAML and merge errors cannot happen at all.

manual.yml is JOINTLY OWNED - humans write entries here too - so the guiding
rule throughout is: never destroy a human's work. Before any modification the
file must round-trip through parse/render byte-for-byte; on mismatch this
program refuses rather than rewriting under a misparse.

Usage:
  apply_proposals.py --proposals audit-proposals.json --ungated
  apply_proposals.py --proposals audit-proposals.json --verdicts audit-verdicts.json

Exactly one of --verdicts / --ungated is required. --ungated means no
verification gate ran, which is correct only while the result still goes to a
human as a pull request; it is spelled out so nobody enables it by accident.

Exit codes: 0 = applied cleanly (possibly nothing to do); 1 = refused, nothing
written; 3 = applied, but some proposals were rejected (see the report).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_deadlines as U  # noqa: E402

MANUAL_PATH = U.MANUAL_PATH
MAX_RETAINED_CITATIONS = 3
DEFAULT_MAX_CHANGES = 8
ACTIONS = ("upsert_manual", "create_record", "delete_manual", "no_change")
WATCHLIST_REASONS = ("deadline-within-45-days", "tba-upcoming-cycle",
                     "manual-override-active", "cross-source-disagreement",
                     "stale-placeholder-note", "coverage-gap", "tba-metadata")

DEFAULT_PREAMBLE = [
    "# Manual overrides have the highest priority (priority 0 in deadline-tracker.js).",
    "# Add confirmed CFP data here when upstream trackers are wrong or missing;",
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
    total = len(doc.get("proposals") or []) + len(unver)
    return total - not_checked, total, causes


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
    return len(want), sorted(want - seen)


def _err(errors, pid, msg):
    errors.append(f"{pid}: {msg}")


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
    if not re.match(r"^https?://", str(url)):
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
                                  "LATER than the truth. Hand-edit if truly intended")
                ok = False
            if not U.clean(claim.get("absence_scope_quote")):
                _err(errors, pid, f"deleting {name!r} requires absence_scope_quote - "
                                  "the verbatim block that would contain it")
                ok = False
            continue
        if not claim.get("evidence"):
            _err(errors, pid, f"field {name!r} has no evidence")
            ok = False
            continue
        for ev in claim["evidence"]:
            if len(U.clean(ev.get("quote"))) < 8:
                _err(errors, pid, f"field {name!r} has an empty or trivial quote")
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
                        and not U.DEADLINE_RE.match(str(v)):
                    _err(errors, pid, f"{name} {v!r} must be 'YYYY-MM-DD HH:MM'")
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


def apply_proposals(proposals, mf, audit_date, canonical_keys, targets_by_key, errors):
    applied, skipped = [], []
    for p in proposals:
        pid = p["id"]
        action, title, year = p["action"], p["title"], p["year"]
        key = (title, year)
        if action == "no_change":
            continue
        if action == "delete_manual":
            idx = mf.find(key)
            if idx is None:
                skipped.append((pid, "no manual.yml entry to delete"))
                continue
            # Nothing verifies this. The gate returns VERIFIED for
            # delete_manual on the grounds that "the updater checks upstream
            # agreement" - and no code path actually calls
            # manual_matches_upstream before the chunk is removed. Deleting the
            # real NDSS override would let the upstream FABRICATED abstract
            # deadline back onto the live page.
            #
            # AUTO-APPLY-DESIGN.md 6 requires agreement on two consecutive runs
            # from every source covering the venue. Until that exists, removal
            # stays a human decision.
            skipped.append((pid, "delete_manual is not applied automatically: "
                                 "nothing yet verifies that upstream really agrees "
                                 "(see AUTO-APPLY-DESIGN.md 6). Remove the entry by "
                                 "hand if the run summary says it is obsolete"))
            continue

        new_fields = normalise_fields(p["fields"])
        idx = mf.find(key)
        existing = mf.chunks[idx].record() if idx is not None else {}
        merged = {k: v for k, v in existing.items() if k not in ("title", "year")}
        merged.update(new_fields)          # unmentioned human fields survive
        record = {"title": title, "year": year, **merged}

        if not validate_merged(record, canonical_keys, pid, errors):
            skipped.append((pid, "failed record validation"))
            continue

        if idx is not None:
            old = {k: v for k, v in existing.items() if k not in ("title", "year")}
            if U.canon_record(dict(old, title=title, year=year)) == U.canon_record(record):
                skipped.append((pid, "already matches manual.yml (no-op)"))
                continue

        retained = mf.chunks[idx].citation_lines() if idx is not None else []
        chunk = Chunk(comment_block(p["reason"], p["source_url"], audit_date,
                                    primary_quote(p["fields"]), retained),
                      render_manual_entry(record))
        changed = ", ".join(sorted(new_fields))
        if idx is None:
            mf.chunks.append(chunk)
            applied.append((pid, f"added an override for {title} {year} ({changed})"))
        else:
            mf.chunks[idx] = chunk
            applied.append((pid, f"updated {title} {year} ({changed})"))
    return applied, skipped


def write_report(path, applied, skipped, errors, proposals, gated):
    lines = ["Automated deadline audit corrections.", ""]
    if not gated:
        lines += ["> [!NOTE]",
                  "> No automated verification gate ran on these proposals - every"
                  " citation below still needs a human to open the link and check"
                  " it says what the entry claims.", ""]
    if applied:
        lines += [f"**Applied ({len(applied)})**", ""]
        lines += [f"- {desc}" for _, desc in applied] + [""]
    if skipped:
        lines += [f"**Skipped ({len(skipped)})**", ""]
        lines += [f"- `{pid}` — {why}" for pid, why in skipped] + [""]
    if errors:
        lines += [f"**Rejected ({len(errors)})**", ""]
        lines += [f"- {e}" for e in errors] + [""]
    unverifiable = [u for u in (proposals.get("unverifiable") or [])]
    if unverifiable:
        lines += [f"**Unverifiable ({len(unverifiable)})**", ""]
        lines += [f"- {u.get('title')} {u.get('year')} — {u.get('cause')}"
                  for u in unverifiable] + [""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--proposals", default="audit-proposals.json")
    ap.add_argument("--verdicts")
    ap.add_argument("--ungated", action="store_true",
                    help="apply without a verification gate (PR-reviewed mode)")
    ap.add_argument("--report", default="audit-summary.md")
    ap.add_argument("--max-changes", type=int, default=DEFAULT_MAX_CHANGES)
    ap.add_argument("--watchlist",
                    help="report which watchlist records went unaddressed")
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

    if not args.validate_only and bool(args.verdicts) == bool(args.ungated):
        print("APPLY REFUSED: pass exactly one of --verdicts or --ungated")
        return 1

    path = Path(args.proposals)
    if not path.exists():
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

    targets = U.load_config()
    if not targets:
        print("APPLY REFUSED: conferences.yml unreadable")
        return 1
    targets_by_key = {t["key"]: t for t in targets}
    canonical_keys = set(targets_by_key)

    errors: list[str] = []
    proposals = [p for p in doc["proposals"]
                 if isinstance(p, dict) and validate_proposal(p, targets_by_key, errors)]

    if args.verdicts:
        try:
            verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
            status = {v["id"]: v.get("status") for v in verdicts.get("verdicts", [])}
        except Exception as exc:  # noqa: BLE001 - fail closed, never open
            print(f"APPLY REFUSED: verdict file unusable ({exc})")
            return 1
        kept = []
        for p in proposals:
            if status.get(p["id"]) == "accepted":
                kept.append(p)
            else:
                errors.append(f"{p['id']}: verdict is "
                              f"{status.get(p['id'], 'missing')!r}, not 'accepted'")
        proposals = kept

    if args.validate_only:
        for e in errors:
            print(f"  [!] {e}")
        actions = {}
        for p in doc["proposals"]:
            if isinstance(p, dict):
                actions[p.get("action")] = actions.get(p.get("action"), 0) + 1
        print(f"{len(proposals)} proposal(s) valid, {len(errors)} rejected"
              + (f" ({', '.join(f'{k}={v}' for k, v in sorted(actions.items()))})"
                 if actions else ""))
        examined, total, causes = audit_effort(doc)
        if causes:
            print("unverifiable: " + ", ".join(f"{k}={v}" for k, v in sorted(causes.items())))
        if args.watchlist:
            cov = coverage(doc, args.watchlist)
            if cov:
                wl_total, missing = cov
                print(f"coverage: {wl_total - len(missing)}/{wl_total} watchlist "
                      "record(s) accounted for")
                for title, year in missing[:20]:
                    print(f"  [!] not addressed: {title} {year}")
                if missing:
                    print("  (a record the auditor neither proposed for nor listed "
                          "as unverifiable was silently skipped)")
        if total:
            print(f"examined: {examined}/{total} record(s) actually checked")
            if examined == 0:
                print("  [!] the auditor examined nothing: every record is still "
                      "marked not_checked from the seed")
                return 1
        return 1 if errors else 0

    original = MANUAL_PATH.read_text(encoding="utf-8") if MANUAL_PATH.exists() else ""
    if original:
        problem = assert_round_trip(original)
        if problem:
            print(f"APPLY REFUSED: {problem}")
            return 1
        mf = parse_manual(original)
    else:
        mf = ManualFile(DEFAULT_PREAMBLE, [])

    audit_date = doc.get("audit_date") or dt.date.today().isoformat()
    applied, skipped = apply_proposals(proposals, mf, audit_date, canonical_keys,
                                       targets_by_key, errors)

    if len(applied) > args.max_changes:
        print(f"APPLY REFUSED: {len(applied)} changes exceeds --max-changes "
              f"{args.max_changes}; a week wanting this many corrections is a week "
              "something upstream broke")
        return 1

    if applied and not args.dry_run:
        MANUAL_PATH.write_text(render_manual(mf), encoding="utf-8")
        U.health.clear()
        U.warnings.clear()
        U.load_manual(U.load_config())
        if U.health:
            MANUAL_PATH.write_text(original, encoding="utf-8")
            for h in U.health:
                print(f"  [!] {h}")
            print("APPLY REFUSED: the written manual.yml would degrade the updater; "
                  "reverted")
            return 1

    write_report(args.report, applied, skipped, errors, doc, gated=bool(args.verdicts))
    for pid, desc in applied:
        print(f"  applied  {pid}: {desc}")
    for pid, why in skipped:
        print(f"  skipped  {pid}: {why}")
    for e in errors:
        print(f"  [!] rejected {e}")
    print(f"\n{len(applied)} applied, {len(skipped)} skipped, {len(errors)} rejected"
          + (" (dry run)" if args.dry_run else ""))
    return 3 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
