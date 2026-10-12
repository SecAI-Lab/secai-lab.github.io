#!/usr/bin/env python3
"""Return malformed auditor claims to the unfinished queue after the model retry.

Only exact-once, date-bound documents may be repaired. An invalid claim is never
published or counted as examined; the clean apply job turns its not_checked
marker into a machine deferral for the next scheduled audit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import apply_proposals as A
import audit_batches as B
import update_deadlines as U


def defer_invalid_claims(watchlist, document, targets_by_key, audit_date):
    """Return a repaired copy and diagnostics, without mutating the input."""
    B.validate_audit_document(
        watchlist, document, expected_audit_date=audit_date,
        allow_unfinished=True,
    )
    repaired = dict(document)
    repaired["proposals"] = []
    repaired["unverifiable"] = []
    diagnostics = []

    for proposal in document["proposals"]:
        errors = []
        if A.validate_proposal(proposal, targets_by_key, errors):
            repaired["proposals"].append(proposal)
            continue
        title, year = proposal["title"], proposal["year"]
        repaired["unverifiable"].append({
            "title": title, "year": year, "cause": "not_checked",
        })
        diagnostics.append((title, year, errors))

    for outcome in document["unverifiable"]:
        errors = []
        if A.validate_unverifiable([outcome], targets_by_key, errors):
            repaired["unverifiable"].append(outcome)
            continue
        title, year = outcome["title"], outcome["year"]
        repaired["unverifiable"].append({
            "title": title, "year": year, "cause": "not_checked",
        })
        diagnostics.append((title, year, errors))

    B.validate_audit_document(
        watchlist, repaired, expected_audit_date=audit_date,
        allow_unfinished=True,
    )
    return repaired, diagnostics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--watchlist", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--audit-date", required=True)
    args = parser.parse_args(argv)
    try:
        watchlist = B.validate_watchlist(json.loads(
            args.watchlist.read_text(encoding="utf-8")
        ))
        document = json.loads(args.proposals.read_text(encoding="utf-8"))
        targets = U.load_config()
        if not targets:
            raise ValueError("conferences.yml is unreadable")
        repaired, diagnostics = defer_invalid_claims(
            watchlist, document, {t["key"]: t for t in targets},
            args.audit_date,
        )
        if diagnostics:
            args.proposals.write_text(
                json.dumps(repaired, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    except (B.BatchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"audit schema deferral failed: {exc}", file=sys.stderr)
        return 1

    for title, year, errors in diagnostics:
        print(f"::warning::Deferred malformed audit claim for {title} {year}: "
              + "; ".join(errors))
    print(f"audit schema deferral: {len(diagnostics)} record(s) returned to retry queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
