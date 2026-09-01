#!/usr/bin/env python3
"""Trust-bind and recheck bounded negative audit outcomes.

The reconciler does not discover sources and does not decide conference facts.
It binds every attempted URL in a final unverifiable outcome to immutable
official-source trust. For ``fetch_blocked`` it also checks whether the claimed
failure is still true. An untrusted URL or reachable page is returned to the
``not_checked`` queue so the auditor must inspect it again.

Usage:
  reconcile_audit_outcomes.py --proposals audit-proposals.json \
      --watchlist watchlist.json
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
    SourceTrustPolicy,
    build_source_trust_policy,
    classify_source_trust,
    configured_official_hosts,
    source_bound_to_hosts,
    source_ok,
    stored_records,
)
import update_deadlines as U  # noqa: E402


MACHINE_NOTE_PREFIX = "Machine recheck:"
# A negative result needs only the small set of official routes actually
# attempted.  Bounding the raw list before trust resolution or fetches prevents
# model output from multiplying the verifier's timeout/backoff into a multi-hour
# availability failure.  Eight covers an edition page, CFP, dates page, and
# several organizer fallbacks without making the network work unbounded.
MAX_ATTEMPTED_URLS = 8
FINAL_UNVERIFIABLE_CAUSES = frozenset((
    "no_official_page",
    "fetch_blocked",
    "page_ambiguous",
    "javascript_only",
    "pdf_only",
))


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
    if not isinstance(value, list) or not value \
            or len(value) > MAX_ATTEMPTED_URLS:
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


def attempted_source_trust(
    outcome: object,
    *,
    source_checker: Callable[[str], tuple[bool, str]] = source_ok,
    trust_resolver: Callable[[str], tuple[object | None, str]] | None = None,
) -> tuple[list[str] | None, dict[str, object], str | None]:
    """Validate and trust-bind one final negative outcome without fetching it."""
    if not isinstance(outcome, dict) \
            or outcome.get("cause") not in FINAL_UNVERIFIABLE_CAUSES:
        return [], {}, None
    raw_attempted = outcome.get("attempted")
    if isinstance(raw_attempted, list) \
            and len(raw_attempted) > MAX_ATTEMPTED_URLS:
        return None, {}, (
            f"attempted official URLs exceed the autonomous bound of "
            f"{MAX_ATTEMPTED_URLS}"
        )
    urls = attempted_urls(
        raw_attempted, official=True,
        source_checker=source_checker,
    )
    if urls is None:
        return None, {}, "attempted official URLs are missing or malformed"

    decisions: dict[str, object] = {}
    if trust_resolver is not None:
        for url in urls:
            try:
                decision, why = trust_resolver(url)
            except (TypeError, ValueError):
                decision, why = None, "source trust resolution failed"
            if decision is None:
                return None, {}, (
                    f"attempted URL {url!r} is outside immutable source trust"
                    + (f": {why}" if why else "")
                )
            decisions[url] = decision
    return urls, decisions, None


def unverifiable_source_trust_errors(
    document: object,
    source_trust_policy: SourceTrustPolicy,
    *,
    source_checker: Callable[[str], tuple[bool, str]] = source_ok,
) -> list[str]:
    """Return value-only trust violations for all final negative outcomes.

    This performs no network I/O. It is shared with the applier so immutable
    source binding remains a final publication invariant even if workflow step
    ordering changes later.
    """
    if not isinstance(document, dict):
        return ["audit proposals must be a JSON object"]
    outcomes = document.get("unverifiable")
    if not isinstance(outcomes, list):
        return ["unverifiable must be a JSON array"]

    errors = []
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict) \
                or outcome.get("cause") not in FINAL_UNVERIFIABLE_CAUSES:
            continue
        title, year = outcome.get("title"), outcome.get("year")

        def trust_resolver(url, *, _title=title, _year=year):
            return classify_source_trust(
                url, _title, _year, source_trust_policy)

        _, _, why = attempted_source_trust(
            outcome, source_checker=source_checker,
            trust_resolver=trust_resolver,
        )
        if why:
            errors.append(f"unverifiable[{index}]: {why}")
    return errors


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
    trust_resolver: Callable[[str], tuple[object | None, str]] | None = None,
) -> tuple[object, bool]:
    """Reconcile one outcome, returning ``(new_outcome, changed)``.

    The input is never mutated.  Only ``fetch_blocked`` performs I/O, and it
    calls ``fetcher.get`` at most once for each distinct supplied URL.
    """
    if not isinstance(outcome, dict):
        return copy.deepcopy(outcome), False

    cause = outcome.get("cause")
    if cause in FINAL_UNVERIFIABLE_CAUSES:
        urls, decisions, trust_error = attempted_source_trust(
            outcome, source_checker=source_checker,
            trust_resolver=trust_resolver,
        )
        if trust_error:
            result = _with_machine_note(
                outcome,
                f"{trust_error}; Claude retry must inspect this record.",
            )
            result["cause"] = "not_checked"
            return result, result != outcome
        assert urls is not None

        # Negative outcomes still claim that the supplied URLs are the
        # conference's official sources.  Bind that claim to immutable trust
        # for every final cause, while keeping I/O limited to fetch_blocked.
        # This prevents a model-only domain from satisfying exact coverage by
        # being labelled no_official_page/page_ambiguous/etc.
        if cause != "fetch_blocked":
            return copy.deepcopy(outcome), False

        for url in urls:
            try:
                if isinstance(fetcher, Fetcher):
                    decision = decisions.get(url)
                    hosts = (decision.allowed_hosts
                             if decision is not None else allowed_hosts)
                    body, _ = fetcher.get(
                        url, hosts,
                        exact_redirect_hosts=(
                            decision is not None
                            and decision.level == "provisional"
                        ),
                    )
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

    return copy.deepcopy(outcome), False


def reconcile_document(
    document: object,
    fetcher: object,
    *,
    source_checker: Callable[[str], tuple[bool, str]] = source_ok,
    trusted_by_title: dict[str, set[str]] | None = None,
    source_trust_policy: SourceTrustPolicy | None = None,
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
        year = outcome.get("year") if isinstance(outcome, dict) else None
        allowed_hosts = ((trusted_by_title or {}).get(title, set())
                         if trusted_by_title is not None else None)

        def bounded_checker(url, *, _title=title, _hosts=allowed_hosts):
            ok, why = source_checker(url)
            if not ok or trusted_by_title is None:
                return ok, why
            return source_bound_to_hosts(url, _hosts, _title or "")

        def trust_resolver(url, *, _title=title, _year=year):
            return classify_source_trust(
                url, _title, _year, source_trust_policy)

        new_outcome, outcome_changed = reconcile_outcome(
            outcome, fetcher, source_checker=bounded_checker,
            allowed_hosts=allowed_hosts,
            trust_resolver=(trust_resolver
                            if source_trust_policy is not None else None),
        )
        reconciled.append(new_outcome)
        changed = changed or outcome_changed
    if changed:
        result["unverifiable"] = reconciled
    return result, changed


def source_trust_policy_for_watchlist(
    watchlist_path: str | Path,
    targets: list[dict] | None = None,
) -> SourceTrustPolicy:
    """Build immutable source trust for workflow and applier validation."""
    watchlist = json.loads(Path(watchlist_path).read_text(encoding="utf-8"))
    if not isinstance(watchlist, list):
        raise ValueError("watchlist must be a JSON array")
    targets = U.load_config() if targets is None else targets
    if not targets:
        raise ValueError("conferences.yml did not yield any targets")
    return build_source_trust_policy(
        watchlist, stored_records(), configured_official_hosts(targets)
    )


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
    trust_policy = None
    if watchlist_path is not None:
        trust_policy = source_trust_policy_for_watchlist(watchlist_path)
    reconciled, changed = reconcile_document(
        document, fetcher if fetcher is not None else Fetcher(),
        source_checker=source_checker, source_trust_policy=trust_policy,
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
