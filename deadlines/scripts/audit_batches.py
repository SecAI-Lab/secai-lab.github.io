#!/usr/bin/env python3
"""Split deadline-audit work into shards and merge it without losing coverage.

The web auditor is intentionally nondeterministic; deciding which records it
was asked to cover is not.  This helper keeps batching deterministic and fails
closed if shard output duplicates, invents, skips, or leaves a watchlist record
unfinished.

Usage::

    audit_batches.py split watchlist.json --output-dir audit-shards
    audit_batches.py merge watchlist.json audit-proposals.json \
        audit-shards/audit-proposals-*.json
    audit_batches.py validate watchlist.json audit-proposals.json

``split`` writes ``watchlist-001.json``, ``watchlist-002.json``, ... and
prints their paths in order.  Shards contain at most 10 records by default.
``merge`` preserves watchlist order within both output arrays.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_SHARD_SIZE = 10
MACHINE_DEFERRED_REASONS = frozenset((
    "source-recheck-requeued",
    "audit-incomplete-after-retry",
))


class BatchError(ValueError):
    """An invalid batching input that should fail the audit run."""


def _read_json(path: str | Path, label: str) -> Any:
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BatchError(f"{label} does not exist: {path}") from exc
    except OSError as exc:
        raise BatchError(f"cannot read {label} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BatchError(
            f"{label} is not valid JSON: {path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc


def _write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    try:
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise BatchError(f"cannot write {path}: {exc}") from exc


def _record_key(record: Any, where: str) -> tuple[str, int]:
    if not isinstance(record, dict):
        raise BatchError(f"{where} must be a JSON object")
    title = record.get("title")
    year = record.get("year")
    if not isinstance(title, str) or not title.strip():
        raise BatchError(f"{where}.title must be a non-empty string")
    if not isinstance(year, int) or isinstance(year, bool):
        raise BatchError(f"{where}.year must be an integer")
    return title, year


def _format_key(key: tuple[str, int]) -> str:
    return f"{key[0]} {key[1]}"


def validate_watchlist(value: Any) -> list[dict[str, Any]]:
    """Return a watchlist after validating its identity/order contract."""
    if not isinstance(value, list):
        raise BatchError("watchlist must be a JSON array")

    seen: set[tuple[str, int]] = set()
    for index, record in enumerate(value):
        key = _record_key(record, f"watchlist[{index}]")
        if key in seen:
            raise BatchError(f"duplicate watchlist record: {_format_key(key)}")
        seen.add(key)
    return value


def split_watchlist(
    watchlist: Sequence[dict[str, Any]], shard_size: int = DEFAULT_SHARD_SIZE
) -> list[list[dict[str, Any]]]:
    """Split *watchlist* into stable, bounded, contiguous shards."""
    validate_watchlist(watchlist)
    if not isinstance(shard_size, int) or isinstance(shard_size, bool) or shard_size < 1:
        raise BatchError("shard size must be a positive integer")
    return [list(watchlist[start : start + shard_size])
            for start in range(0, len(watchlist), shard_size)]


def write_watchlist_shards(
    watchlist_path: str | Path,
    output_dir: str | Path,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> list[Path]:
    """Write numbered watchlist shards and return their paths in order."""
    watchlist = validate_watchlist(_read_json(watchlist_path, "watchlist"))
    shards = split_watchlist(watchlist, shard_size)
    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BatchError(f"cannot create shard directory {output_dir}: {exc}") from exc

    # A stale fourth file after a 4 -> 3 shard change is indistinguishable from
    # current input to a shell glob.  Refuse to mix generations rather than
    # silently merge old work.
    stale = sorted(output_dir.glob("watchlist-[0-9][0-9][0-9].json"))
    if stale:
        names = ", ".join(str(path) for path in stale[:5])
        suffix = " ..." if len(stale) > 5 else ""
        raise BatchError(
            f"shard directory already contains watchlist shards: {names}{suffix}"
        )

    paths: list[Path] = []
    for number, shard in enumerate(shards, start=1):
        path = output_dir / f"watchlist-{number:03d}.json"
        _write_json(path, shard)
        paths.append(path)
    return paths


def _audit_date(doc: dict[str, Any], where: str) -> str:
    audit_date = doc.get("audit_date")
    if not isinstance(audit_date, str):
        raise BatchError(f"{where}.audit_date must be a YYYY-MM-DD string")
    try:
        parsed = dt.date.fromisoformat(audit_date)
    except ValueError as exc:
        raise BatchError(f"{where}.audit_date is not a valid date: {audit_date!r}") from exc
    if parsed.isoformat() != audit_date:
        raise BatchError(f"{where}.audit_date must use YYYY-MM-DD: {audit_date!r}")
    return audit_date


def _audit_entries(
    doc: Any,
    where: str,
    allowed: set[tuple[str, int]],
    *,
    allow_machine_deferred: bool = False,
    allow_unfinished: bool = False,
) -> tuple[
    str,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Validate one complete-or-partial audit document and return its entries."""
    if allow_machine_deferred and allow_unfinished:
        raise BatchError(
            "allow_machine_deferred and allow_unfinished are mutually exclusive"
        )
    if not isinstance(doc, dict):
        raise BatchError(f"{where} must be a JSON object")
    audit_date = _audit_date(doc, where)

    proposals = doc.get("proposals")
    unverifiable = doc.get("unverifiable")
    if "machine_deferred" in doc and not allow_machine_deferred:
        raise BatchError(
            f"{where}.machine_deferred is reserved for trusted finalization"
        )
    machine_deferred = doc.get("machine_deferred", [])
    if not isinstance(proposals, list):
        raise BatchError(f"{where}.proposals must be a JSON array")
    if not isinstance(unverifiable, list):
        raise BatchError(f"{where}.unverifiable must be a JSON array")
    if not isinstance(machine_deferred, list):
        raise BatchError(f"{where}.machine_deferred must be a JSON array")

    seen: dict[tuple[str, int], str] = {}
    for group_name, entries in (
        ("proposals", proposals),
        ("unverifiable", unverifiable),
        ("machine_deferred", machine_deferred),
    ):
        for index, entry in enumerate(entries):
            location = f"{where}.{group_name}[{index}]"
            key = _record_key(entry, location)
            if key not in allowed:
                raise BatchError(f"unknown audit record at {location}: {_format_key(key)}")
            if key in seen:
                raise BatchError(
                    f"duplicate audit record {_format_key(key)} at {location}; "
                    f"first seen at {seen[key]}"
                )
            seen[key] = location
            if entry.get("cause") == "not_checked":
                if group_name != "unverifiable":
                    raise BatchError(
                        f"unfinished marker is invalid at {location}: "
                        "not_checked belongs only in unverifiable"
                    )
                if not allow_unfinished:
                    raise BatchError(
                        f"unfinished audit record at {location}: {_format_key(key)} "
                        "is still not_checked"
                    )
            if group_name == "machine_deferred":
                expected_keys = {"title", "year", "reason"}
                if set(entry) != expected_keys:
                    raise BatchError(
                        f"{location} must contain exactly title, year, and reason"
                    )
                reason = entry.get("reason")
                if reason not in MACHINE_DEFERRED_REASONS:
                    raise BatchError(
                        f"{location}.reason is not a machine-owned deferral reason: "
                        f"{reason!r}"
                    )

    size = doc.get("watchlist_size")
    if not isinstance(size, int) or isinstance(size, bool):
        raise BatchError(f"{where}.watchlist_size must be an integer")
    actual_size = len(proposals) + len(unverifiable) + len(machine_deferred)
    if size != actual_size:
        raise BatchError(
            f"{where}.watchlist_size is {size}, but the document accounts for "
            f"{actual_size} record(s)"
        )
    return audit_date, proposals, unverifiable, machine_deferred


def validate_audit_document(
    watchlist: Sequence[dict[str, Any]], doc: Any, where: str = "audit",
    expected_audit_date: str | None = None,
    *,
    allow_machine_deferred: bool = False,
    allow_unfinished: bool = False,
) -> dict[str, Any]:
    """Require a final audit document to cover the watchlist exactly once."""
    watchlist = validate_watchlist(watchlist)
    wanted = [_record_key(record, f"watchlist[{index}]")
              for index, record in enumerate(watchlist)]
    allowed = set(wanted)
    audit_date, proposals, unverifiable, machine_deferred = _audit_entries(
        doc, where, allowed,
        allow_machine_deferred=allow_machine_deferred,
        allow_unfinished=allow_unfinished,
    )
    if expected_audit_date is not None and audit_date != expected_audit_date:
        raise BatchError(
            f"{where}.audit_date is {audit_date}, expected {expected_audit_date}"
        )
    present = {
        _record_key(entry, f"{where}.proposals[{index}]")
        for index, entry in enumerate(proposals)
    }
    present.update(
        _record_key(entry, f"{where}.unverifiable[{index}]")
        for index, entry in enumerate(unverifiable)
    )
    present.update(
        _record_key(entry, f"{where}.machine_deferred[{index}]")
        for index, entry in enumerate(machine_deferred)
    )
    missing = [key for key in wanted if key not in present]
    if missing:
        rendered = ", ".join(_format_key(key) for key in missing)
        raise BatchError(f"{where} is missing watchlist record(s): {rendered}")
    return doc


def merge_audit_documents(
    watchlist: Sequence[dict[str, Any]],
    documents: Iterable[tuple[str, Any]],
    expected_audit_date: str | None = None,
    *,
    allow_machine_deferred: bool = False,
    allow_unfinished: bool = False,
) -> dict[str, Any]:
    """Merge completed shard documents, rejecting any coverage ambiguity."""
    watchlist = validate_watchlist(watchlist)
    wanted = [_record_key(record, f"watchlist[{index}]")
              for index, record in enumerate(watchlist)]
    allowed = set(wanted)
    documents = list(documents)
    if not documents:
        raise BatchError("merge requires at least one shard audit document")

    dates: dict[str, str] = {}
    combined_proposals: list[dict[str, Any]] = []
    combined_unverifiable: list[dict[str, Any]] = []
    combined_machine_deferred: list[dict[str, Any]] = []
    owner: dict[tuple[str, int], str] = {}
    for where, doc in documents:
        audit_date, proposals, unverifiable, machine_deferred = _audit_entries(
            doc, where, allowed,
            allow_machine_deferred=allow_machine_deferred,
            allow_unfinished=allow_unfinished,
        )
        if expected_audit_date is not None and audit_date != expected_audit_date:
            raise BatchError(
                f"{where}.audit_date is {audit_date}, expected {expected_audit_date}"
            )
        dates[where] = audit_date
        for group_name, entries, destination in (
            ("proposals", proposals, combined_proposals),
            ("unverifiable", unverifiable, combined_unverifiable),
            ("machine_deferred", machine_deferred, combined_machine_deferred),
        ):
            for index, entry in enumerate(entries):
                key = _record_key(entry, f"{where}.{group_name}[{index}]")
                if key in owner:
                    raise BatchError(
                        f"duplicate audit record {_format_key(key)} across shards "
                        f"{owner[key]} and {where}"
                    )
                owner[key] = where
                destination.append(entry)

    distinct_dates = set(dates.values())
    if len(distinct_dates) != 1:
        detail = ", ".join(f"{where}={date}" for where, date in dates.items())
        raise BatchError(f"shard audit_date mismatch: {detail}")

    missing = [key for key in wanted if key not in owner]
    if missing:
        rendered = ", ".join(_format_key(key) for key in missing)
        raise BatchError(f"shard audits are missing watchlist record(s): {rendered}")

    order = {key: index for index, key in enumerate(wanted)}
    combined_proposals.sort(
        key=lambda entry: order[_record_key(entry, "merged proposal")]
    )
    combined_unverifiable.sort(
        key=lambda entry: order[_record_key(entry, "merged unverifiable entry")]
    )
    combined_machine_deferred.sort(
        key=lambda entry: order[_record_key(entry, "merged machine-deferred entry")]
    )
    merged = {
        "audit_date": next(iter(distinct_dates)),
        "watchlist_size": len(watchlist),
        "proposals": combined_proposals,
        "unverifiable": combined_unverifiable,
    }
    if allow_machine_deferred:
        merged["machine_deferred"] = combined_machine_deferred
    validate_audit_document(
        watchlist, merged, "merged audit", expected_audit_date,
        allow_machine_deferred=allow_machine_deferred,
        allow_unfinished=allow_unfinished,
    )
    return merged


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    split = commands.add_parser("split", help="write bounded watchlist shards")
    split.add_argument("watchlist", type=Path)
    split.add_argument("--output-dir", type=Path, required=True)
    split.add_argument(
        "--size", "--shard-size", dest="shard_size", type=int,
        default=DEFAULT_SHARD_SIZE,
        help=f"maximum records per shard (default: {DEFAULT_SHARD_SIZE})",
    )

    merge = commands.add_parser("merge", help="merge completed shard audits")
    merge.add_argument("watchlist", type=Path)
    merge.add_argument("output", type=Path)
    merge.add_argument("shards", type=Path, nargs="+")
    merge.add_argument("--audit-date", dest="expected_audit_date")
    merge.add_argument(
        "--allow-machine-deferred", action="store_true",
        help="accept trusted-finalizer deferrals (post-model stages only)",
    )
    merge.add_argument(
        "--allow-unfinished", action="store_true",
        help="accept raw not_checked checkpoints (pre-finalization stages only)",
    )

    validate = commands.add_parser(
        "validate", help="validate exact coverage of one final audit document"
    )
    validate.add_argument("watchlist", type=Path)
    validate.add_argument("audit_proposals", type=Path)
    validate.add_argument("--audit-date", dest="expected_audit_date")
    validate.add_argument(
        "--allow-machine-deferred", action="store_true",
        help="accept trusted-finalizer deferrals (post-model stages only)",
    )
    validate.add_argument(
        "--allow-unfinished", action="store_true",
        help="accept raw not_checked checkpoints (pre-finalization stages only)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "split":
            paths = write_watchlist_shards(
                args.watchlist, args.output_dir, args.shard_size
            )
            for path in paths:
                print(path)
            return 0

        watchlist = validate_watchlist(_read_json(args.watchlist, "watchlist"))
        if args.command == "validate":
            doc = _read_json(args.audit_proposals, "audit proposals")
            validate_audit_document(
                watchlist, doc, str(args.audit_proposals),
                args.expected_audit_date,
                allow_machine_deferred=args.allow_machine_deferred,
                allow_unfinished=args.allow_unfinished,
            )
            print(f"valid: {len(watchlist)} watchlist record(s) accounted for exactly once")
            return 0

        documents = [
            (str(path), _read_json(path, "shard audit")) for path in args.shards
        ]
        merged = merge_audit_documents(
            watchlist, documents, args.expected_audit_date,
            allow_machine_deferred=args.allow_machine_deferred,
            allow_unfinished=args.allow_unfinished,
        )
        _write_json(args.output, merged)
        print(
            f"merged {len(documents)} shard audit(s) into {args.output}; "
            f"{len(watchlist)} record(s) accounted for"
        )
        return 0
    except BatchError as exc:
        print(f"audit_batches: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
