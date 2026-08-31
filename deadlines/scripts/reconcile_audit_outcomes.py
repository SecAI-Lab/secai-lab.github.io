#!/usr/bin/env python3
"""Recheck bounded audit outcomes before the automated auditor retries.

The reconciler does not discover sources and does not decide conference facts.
It only checks whether an auditor's claimed fetch failure is still true for the
official URLs the auditor recorded.  A reachable page is returned to the
``not_checked`` queue so the next auditor invocation must inspect it.

Usage:
  reconcile_audit_outcomes.py --proposals audit-proposals.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_citations import (  # noqa: E402
    Fetcher,
    configured_official_hosts,
    source_bound_to_hosts,
    source_ok,
    stored_records,
    trusted_hosts_by_title,
)
import update_deadlines as U  # noqa: E402


MACHINE_NOTE_PREFIX = "Machine recheck:"


def _http_url(url: object) -> bool:
    """Whether *url* is a syntactically usable absolute HTTP(S) URL."""
    if not isinstance(url, str) or not url or url != url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def attempted_urls(
    value: object,
    *,
    official: bool,
    source_checker: Callable[[str], tuple[bool, str]] = source_ok,
) -> list[str] | None:
    """Validate an ``attempted`` list without changing or expanding its scope.

    ``None`` means the evidence is missing or malformed.  Duplicate URLs are
    retried once, in first-seen order, while the original list remains intact.
    """
    if not isinstance(value, list) or not value:
        return None

    urls: list[str] = []
    seen: set[str] = set()
    for url in value:
        if not _http_url(url):
            return None
        if official:
            try:
                admissible, _ = source_checker(url)
            except (TypeError, ValueError):
                return None
            if not admissible:
                return None
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _with_machine_note(outcome: dict, message: str) -> dict:
    """Return a copy with one idempotent machine note, retaining human text."""
    result = copy.deepcopy(outcome)
    machine_note = f"{MACHINE_NOTE_PREFIX} {message}"
    old_note = result.get("note")
    human_note = old_note if isinstance(old_note, str) else ""
    marker = human_note.find(MACHINE_NOTE_PREFIX)
    if marker >= 0:
        human_note = human_note[:marker]
    human_note = human_note.rstrip()
    result["note"] = f"{human_note} {machine_note}" if human_note else machine_note
    return result


def reconcile_outcome(
    outcome: object,
    fetcher: object,
    *,
    source_checker: Callable[[str], tuple[bool, str]] = source_ok,
    allowed_hosts: set[str] | None = None,
) -> tuple[object, bool]:
    """Reconcile one outcome, returning ``(new_outcome, changed)``.

    The input is never mutated.  Only ``fetch_blocked`` performs I/O, and it
    calls ``fetcher.get`` at most once for each distinct supplied URL.
    """
    if not isinstance(outcome, dict):
        return copy.deepcopy(outcome), False

    cause = outcome.get("cause")
    if cause == "fetch_blocked":
        urls = attempted_urls(
            outcome.get("attempted"), official=True,
            source_checker=source_checker,
        )
        if urls is None:
            result = _with_machine_note(
                outcome,
                "attempted official URLs are missing or malformed; "
                "Claude retry must inspect this record.",
            )
            result["cause"] = "not_checked"
            return result, result != outcome

        for url in urls:
            try:
                if isinstance(fetcher, Fetcher):
                    body, _ = fetcher.get(url, allowed_hosts)
                else:
                    body, _ = fetcher.get(url)
            except Exception:  # noqa: BLE001 - a retry failure remains blocked
                body = None
            if body is not None:
                result = _with_machine_note(
                    outcome,
                    f"fetched {url}; Claude retry must inspect this source.",
                )
                result["cause"] = "not_checked"
                return result, result != outcome

        result = _with_machine_note(
            outcome,
            f"retried {len(urls)} official URL(s); all remain unreachable "
            "or robots-denied.",
        )
        return result, result != outcome

    if cause == "no_official_page":
        urls = attempted_urls(outcome.get("attempted"), official=False)
        if urls is None:
            result = _with_machine_note(
                outcome,
                "attempted URLs are missing or malformed; Claude retry must "
                "inspect this record.",
            )
            result["cause"] = "not_checked"
            return result, result != outcome

    return copy.deepcopy(outcome), False


def reconcile_document(
    document: object,
    fetcher: object,
    *,
    source_checker: Callable[[str], tuple[bool, str]] = source_ok,
    trusted_by_title: dict[str, set[str]] | None = None,
) -> tuple[object, bool]:
    """Return a reconciled copy of an audit document and whether it changed."""
    if not isinstance(document, dict):
        raise ValueError("audit proposals must be a JSON object")

    result = copy.deepcopy(document)
    outcomes = result.get("unverifiable")
    if not isinstance(outcomes, list):
        return result, False

    changed = False
    reconciled = []
    for outcome in outcomes:
        title = outcome.get("title") if isinstance(outcome, dict) else None
        allowed_hosts = ((trusted_by_title or {}).get(title, set())
                         if trusted_by_title is not None else None)

        def bounded_checker(url, *, _title=title, _hosts=allowed_hosts):
            ok, why = source_checker(url)
            if not ok or trusted_by_title is None:
                return ok, why
            return source_bound_to_hosts(url, _hosts, _title or "")

        new_outcome, outcome_changed = reconcile_outcome(
            outcome, fetcher, source_checker=bounded_checker,
            allowed_hosts=allowed_hosts,
        )
        reconciled.append(new_outcome)
        changed = changed or outcome_changed
    if changed:
        result["unverifiable"] = reconciled
    return result, changed


def reconcile_file(
    path: str | Path,
    fetcher: object | None = None,
    *,
    watchlist_path: str | Path | None = None,
    source_checker: Callable[[str], tuple[bool, str]] = source_ok,
) -> bool:
    """Reconcile *path* and write it only when its data actually changes."""
    proposals_path = Path(path)
    document = json.loads(proposals_path.read_text(encoding="utf-8"))
    trusted = None
    if watchlist_path is not None:
        watchlist = json.loads(Path(watchlist_path).read_text(encoding="utf-8"))
        if not isinstance(watchlist, list):
            raise ValueError("watchlist must be a JSON array")
        targets = U.load_config()
        if not targets:
            raise ValueError("conferences.yml did not yield any targets")
        trusted = trusted_hosts_by_title(
            watchlist, stored_records(), configured_official_hosts(targets)
        )
    reconciled, changed = reconcile_document(
        document, fetcher if fetcher is not None else Fetcher(),
        source_checker=source_checker, trusted_by_title=trusted,
    )
    if changed:
        proposals_path.write_text(
            json.dumps(reconciled, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--proposals", default="audit-proposals.json")
    parser.add_argument("--watchlist", required=True)
    args = parser.parse_args(argv)
    try:
        changed = reconcile_file(args.proposals, watchlist_path=args.watchlist)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"audit outcome reconciliation failed: {exc}", file=sys.stderr)
        return 1
    print("audit outcomes reconciled" if changed else "audit outcomes unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
