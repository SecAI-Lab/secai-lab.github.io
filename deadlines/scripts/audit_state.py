#!/usr/bin/env python3
"""Persistent, deterministic state for autonomous deadline-audit retries.

The weekly evidence gate is intentionally stateless, but a few destructive or
large corrections should not be published after a single observation.  This
module records only a hash of a validated proposal (never model prose) and
promotes it after the same official-page claim is independently VERIFIED on two
distinct audit dates.  It also keeps deferred identities on the watchlist so a
year boundary cannot silently abandon an unresolved correction.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, NamedTuple


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "deadlines" / "data" / "audit-state.json"
STATE_VERSION = 1
REQUIRED_VERIFIED_RUNS = 2
MIN_CORROBORATION_DAYS = 6
MAX_STATE_ENTRIES = 500
DELETE_SCOPE = "@delete_manual"
ALLOWED_SCOPE_FIELDS = frozenset((
    "abstract_deadline", "deadline", "timezone", "place", "date", "link",
    "note", "start", "end", DELETE_SCOPE,
))
RETRY_REASONS = frozenset((
    "citation", "corroboration", "change-budget", "unverifiable",
))
CLAIM_ACTIONS = frozenset((
    "upsert_manual", "create_record", "delete_manual", "no_change",
))


class StateError(ValueError):
    """Corrupt or unsafe persistent audit state."""


class ClaimRef(NamedTuple):
    """Value-free reference to one corroboration claim in memory."""

    identity: str
    scope_id: str


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "corroboration": {}, "retry": {}}


def identity_key(title: str, year: int) -> str:
    if not isinstance(title, str) or not title or "\t" in title:
        raise StateError("audit-state title must be a non-empty string without tabs")
    if not isinstance(year, int) or isinstance(year, bool):
        raise StateError("audit-state year must be an integer")
    return f"{title}\t{year}"


def split_identity(key: str) -> tuple[str, int]:
    try:
        title, raw_year = key.rsplit("\t", 1)
        year = int(raw_year)
    except (AttributeError, ValueError) as exc:
        raise StateError(f"invalid audit-state identity key: {key!r}") from exc
    if str(year) != raw_year:
        raise StateError(f"invalid audit-state year in key: {key!r}")
    identity_key(title, year)
    return title, year


def _date(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise StateError(f"{where} must be a YYYY-MM-DD string")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise StateError(f"{where} is not a valid date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise StateError(f"{where} must use YYYY-MM-DD: {value!r}")
    return value


def _scope_fields(value: Any, where: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise StateError(f"{where} must be a list of strings")
    if not allow_empty and not value:
        raise StateError(f"{where} must not be empty")
    if len(set(value)) != len(value) or value != sorted(value):
        raise StateError(f"{where} must be unique and sorted")
    unknown = set(value) - ALLOWED_SCOPE_FIELDS
    if unknown:
        raise StateError(f"{where} contains unknown field(s): {', '.join(sorted(unknown))}")
    return value


def _proposal_scope(action: Any, normalized_fields: dict[str, Any]) -> list[str]:
    if action == "delete_manual":
        return [DELETE_SCOPE]
    if not isinstance(normalized_fields, dict):
        raise StateError("normalized proposal fields must be an object")
    return _scope_fields(sorted(normalized_fields), "proposal scope")


def claim_scope_id(action: str, fields: list[str] | set[str]) -> str:
    """Return a deterministic, value-free slot for one logical claim."""
    canonical = _scope_fields(sorted(fields), "claim scope")
    if action == "delete_manual" or canonical == [DELETE_SCOPE]:
        if action != "delete_manual" or canonical != [DELETE_SCOPE]:
            raise StateError("delete claim scope must be action:delete_manual")
        return "action:delete_manual"
    return "fields:" + ",".join(canonical)


def _validate_claim(claim: Any, where: str) -> None:
    if not isinstance(claim, dict):
        raise StateError(f"{where} must be an object")
    allowed = {
        "fingerprint", "action", "fields", "first_seen", "last_seen",
        "verified_runs",
    }
    if set(claim) - allowed:
        raise StateError(f"{where} contains unexpected data")
    fingerprint = claim.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.startswith("sha256:") \
            or len(fingerprint) != 71:
        raise StateError(f"{where} has an invalid fingerprint")
    action = claim.get("action")
    if action not in CLAIM_ACTIONS:
        raise StateError(f"{where} has an invalid action")
    raw_fields = claim.get("fields")
    legacy_delete = action == "delete_manual" and raw_fields == ["upstream_agreement"]
    fields = raw_fields if legacy_delete else _scope_fields(raw_fields, f"{where}.fields")
    if action == "delete_manual" and fields not in ([DELETE_SCOPE], ["upstream_agreement"]):
        raise StateError(f"{where} has an invalid delete scope")
    if action != "delete_manual" and DELETE_SCOPE in fields:
        raise StateError(f"{where} has an invalid action scope")
    runs = claim.get("verified_runs")
    if not isinstance(runs, int) or isinstance(runs, bool) or runs < 1:
        raise StateError(f"{where} has an invalid run count")
    first = _date(claim.get("first_seen"), f"{where}.first_seen")
    last = _date(claim.get("last_seen"), f"{where}.last_seen")
    if first > last:
        raise StateError(f"{where} first_seen is after last_seen")


def _canonical_claim(claim: dict[str, Any]) -> dict[str, Any]:
    fields = ([DELETE_SCOPE] if claim.get("action") == "delete_manual"
              else sorted(claim["fields"]))
    return {
        "fingerprint": claim["fingerprint"],
        "action": claim["action"],
        "fields": fields,
        "first_seen": claim["first_seen"],
        "last_seen": claim["last_seen"],
        "verified_runs": claim["verified_runs"],
    }


def _migrate_in_place(state: dict[str, Any]) -> None:
    """Canonicalize legacy version-1 singleton claims and unscoped retries."""
    for key, entry in list(state["corroboration"].items()):
        if "claims" in entry:
            claims = entry["claims"]
        else:
            claim = _canonical_claim(entry)
            claims = {claim_scope_id(claim["action"], claim["fields"]): claim}
        canonical = {}
        for _, raw_claim in claims.items():
            claim = _canonical_claim(raw_claim)
            canonical[claim_scope_id(claim["action"], claim["fields"])] = claim
        state["corroboration"][key] = {"claims": dict(sorted(canonical.items()))}

    for key, entry in list(state["retry"].items()):
        fields = sorted(entry.get("fields") or [])
        whole_record = entry.get("whole_record")
        if whole_record is None:
            whole_record = "fields" not in entry
        state["retry"][key] = {
            "last_seen": entry["last_seen"],
            "reason": entry["reason"],
            "fields": fields,
            "whole_record": bool(whole_record),
        }


def validate(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise StateError(f"audit-state version must be {STATE_VERSION}")
    corroboration = state.get("corroboration")
    retry = state.get("retry")
    if not isinstance(corroboration, dict) or not isinstance(retry, dict):
        raise StateError("audit-state corroboration and retry must be objects")
    if len(corroboration) > MAX_STATE_ENTRIES or len(retry) > MAX_STATE_ENTRIES:
        raise StateError("audit-state exceeds its bounded entry limit")

    claim_count = 0
    for key, entry in corroboration.items():
        split_identity(key)
        if not isinstance(entry, dict):
            raise StateError(f"corroboration {key!r} must be an object")
        if "claims" in entry:
            if set(entry) != {"claims"} or not isinstance(entry["claims"], dict) \
                    or not entry["claims"]:
                raise StateError(f"corroboration {key!r}.claims must be a non-empty object")
            claim_count += len(entry["claims"])
            for scope_id, claim in entry["claims"].items():
                _validate_claim(claim, f"corroboration {key!r}.{scope_id!r}")
                expected = claim_scope_id(claim["action"], claim["fields"])
                if scope_id != expected:
                    raise StateError(f"corroboration {key!r} has a mismatched scope id")
        else:
            # Version 1 originally stored one claim directly under the identity.
            claim_count += 1
            _validate_claim(entry, f"corroboration {key!r}")

    if claim_count > MAX_STATE_ENTRIES:
        raise StateError("audit-state exceeds its bounded claim limit")

    for key, entry in retry.items():
        split_identity(key)
        if not isinstance(entry, dict):
            raise StateError(f"retry {key!r} must be an object")
        if set(entry) - {"last_seen", "reason", "fields", "whole_record"}:
            raise StateError(f"retry {key!r} contains unexpected data")
        _date(entry.get("last_seen"), f"retry {key!r}.last_seen")
        if entry.get("reason") not in RETRY_REASONS:
            raise StateError(f"retry {key!r} has an invalid reason")
        if "fields" in entry:
            _scope_fields(entry["fields"], f"retry {key!r}.fields", allow_empty=True)
        if "whole_record" in entry and not isinstance(entry["whole_record"], bool):
            raise StateError(f"retry {key!r}.whole_record must be boolean")
        if entry.get("whole_record") is False and not entry.get("fields"):
            raise StateError(f"retry {key!r} has no unresolved scope")
    return state


def load(path: str | Path = STATE_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return empty_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read audit state {path}: {exc}") from exc
    validate(value)
    _migrate_in_place(value)
    return validate(value)


def render(state: dict[str, Any]) -> str:
    validate(state)
    _migrate_in_place(state)
    validate(state)
    ordered = {
        "version": STATE_VERSION,
        "corroboration": {
            key: {"claims": dict(sorted(entry["claims"].items()))}
            for key, entry in sorted(state["corroboration"].items())
        },
        "retry": dict(sorted(state["retry"].items())),
    }
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def save(state: dict[str, Any], path: str | Path = STATE_PATH) -> bool:
    """Atomically save changed state; return whether the file changed."""
    path = Path(path)
    text = render(state)
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
        # Do not create an empty state file merely because the audit had
        # nothing to remember. Once present, keep the canonical empty shell.
        if not path.exists() and state == empty_state():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        raise StateError(f"cannot write audit state {path}: {exc}") from exc


def proposal_fingerprint(proposal: dict[str, Any], normalized_fields: dict[str, Any]) -> str:
    """Hash only validated identity/action/values, excluding model prose."""
    payload = {
        "action": proposal.get("action"),
        "title": proposal.get("title"),
        "year": proposal.get("year"),
        "fields": normalized_fields,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def observe_verified_claim(
    state: dict[str, Any],
    proposal: dict[str, Any],
    normalized_fields: dict[str, Any],
    audit_date: str,
) -> tuple[bool, ClaimRef]:
    """Record one verified risky claim without disturbing disjoint claims."""
    validate(state)
    _migrate_in_place(state)
    audit_date = _date(audit_date, "audit_date")
    key = identity_key(proposal.get("title"), proposal.get("year"))
    action = proposal.get("action")
    if action not in CLAIM_ACTIONS:
        raise StateError("verified proposal has an invalid action")
    fields = _proposal_scope(action, normalized_fields)
    scope_id = claim_scope_id(action, fields)
    fingerprint = proposal_fingerprint(proposal, normalized_fields)
    container = state["corroboration"].setdefault(key, {"claims": {}})
    claims = container["claims"]
    old = claims.get(scope_id)

    # A new observation supersedes only claims about the same logical field(s).
    # Disjoint deferred work for this identity must survive.
    for old_scope, old_claim in list(claims.items()):
        if old_scope != scope_id and set(old_claim["fields"]) <= set(fields):
            del claims[old_scope]

    if old and old.get("fingerprint") == fingerprint:
        if audit_date < old["last_seen"]:
            raise StateError(
                f"audit date {audit_date} predates corroboration for {key!r}"
            )
        elapsed = (dt.date.fromisoformat(audit_date)
                   - dt.date.fromisoformat(old["last_seen"])).days
        qualifies = elapsed >= MIN_CORROBORATION_DAYS
        runs = min(REQUIRED_VERIFIED_RUNS, old["verified_runs"] + qualifies)
        first_seen = old["first_seen"]
        last_seen = audit_date if qualifies else old["last_seen"]
    else:
        runs = 1
        first_seen = audit_date
        last_seen = audit_date
    claims[scope_id] = {
        "fingerprint": fingerprint,
        "action": action,
        "fields": fields,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "verified_runs": runs,
    }
    container["claims"] = dict(sorted(claims.items()))
    mark_retry_fields(state, proposal.get("title"), proposal.get("year"),
                      audit_date, "corroboration", fields)
    return runs >= REQUIRED_VERIFIED_RUNS, ClaimRef(key, scope_id)


def observe_verified(
    state: dict[str, Any],
    proposal: dict[str, Any],
    normalized_fields: dict[str, Any],
    audit_date: str,
) -> tuple[bool, str]:
    """Backward-compatible wrapper returning the identity rather than claim ref."""
    promoted, ref = observe_verified_claim(
        state, proposal, normalized_fields, audit_date)
    return promoted, ref.identity


def finish_corroboration_claims(
    state: dict[str, Any],
    audited_fields: dict[str, set[str] | None],
    observed: set[ClaimRef],
) -> None:
    """Reset only audited claims that were not re-verified in this run."""
    validate(state)
    _migrate_in_place(state)
    for key, scope in audited_fields.items():
        split_identity(key)
        if scope is not None:
            _scope_fields(sorted(scope), f"audited scope for {key!r}")
    for ref in observed:
        if not isinstance(ref, ClaimRef):
            raise StateError("observed corroboration reference is invalid")

    for key, container in list(state["corroboration"].items()):
        if key not in audited_fields:
            continue
        audited = audited_fields[key]
        claims = container["claims"]
        for scope_id, claim in list(claims.items()):
            if ClaimRef(key, scope_id) in observed:
                continue
            if audited is None or set(claim["fields"]) <= audited:
                del claims[scope_id]
        if not claims:
            del state["corroboration"][key]


def finish_corroboration(
    state: dict[str, Any],
    audited: set[str],
    observed: set[str],
) -> None:
    """Backward-compatible identity-wide finish operation."""
    validate(state)
    _migrate_in_place(state)
    observed_refs = {
        ClaimRef(key, scope_id)
        for key in observed
        for scope_id in (state["corroboration"].get(key) or {}).get("claims", {})
    }
    finish_corroboration_claims(
        state, {key: None for key in audited}, observed_refs)


def _mark_retry(
    state: dict[str, Any], title: str, year: int, audit_date: str, reason: str,
    fields: list[str] | set[str] | None,
) -> None:
    validate(state)
    _migrate_in_place(state)
    key = identity_key(title, year)
    _date(audit_date, "audit_date")
    if reason not in RETRY_REASONS:
        raise StateError(f"invalid retry reason: {reason}")
    scoped = [] if fields is None else _scope_fields(sorted(fields), "retry scope")
    old = state["retry"].get(key) or {
        "fields": [], "whole_record": False,
    }
    state["retry"][key] = {
        "last_seen": audit_date,
        "reason": reason,
        "fields": sorted(set(old.get("fields") or []) | set(scoped)),
        "whole_record": bool(old.get("whole_record")) or fields is None,
    }


def mark_retry(
    state: dict[str, Any], title: str, year: int, audit_date: str, reason: str
) -> None:
    """Mark a legacy/record-wide retry that partial facts cannot resolve."""
    _mark_retry(state, title, year, audit_date, reason, None)


def mark_retry_fields(
    state: dict[str, Any], title: str, year: int, audit_date: str, reason: str,
    fields: list[str] | set[str],
) -> None:
    """Union a value-free field scope into the identity's deferred work."""
    _mark_retry(state, title, year, audit_date, reason, fields)


def resolve_fields(
    state: dict[str, Any], title: str, year: int, fields: list[str] | set[str],
) -> None:
    """Resolve only matching retry and corroboration claims."""
    validate(state)
    _migrate_in_place(state)
    key = identity_key(title, year)
    resolved = set(_scope_fields(sorted(fields), "resolved scope"))

    retry = state["retry"].get(key)
    resolved_entire_retry = False
    if retry is not None and not retry["whole_record"]:
        remaining = sorted(set(retry["fields"]) - resolved)
        if remaining:
            retry["fields"] = remaining
        else:
            del state["retry"][key]
            resolved_entire_retry = True

    container = state["corroboration"].get(key)
    if container is not None:
        if resolved_entire_retry:
            # A multi-field fingerprint cannot be safely split after separate
            # partial resolutions. Once every retry scope is resolved, the
            # whole identity's remaining streaks are necessarily obsolete.
            del state["corroboration"][key]
            return
        for scope_id, claim in list(container["claims"].items()):
            if set(claim["fields"]) <= resolved:
                del container["claims"][scope_id]
        if not container["claims"]:
            del state["corroboration"][key]


def resolve(state: dict[str, Any], title: str, year: int) -> None:
    """Explicitly resolve every claim for an identity (legacy API)."""
    key = identity_key(title, year)
    state["corroboration"].pop(key, None)
    state["retry"].pop(key, None)


def prune_years(state: dict[str, Any], first_year: int, last_year: int) -> None:
    """Drop identities outside the frontend's moving rendered-year window."""
    if not isinstance(first_year, int) or not isinstance(last_year, int) \
            or first_year > last_year:
        raise StateError("invalid audit-state year window")
    for group in ("corroboration", "retry"):
        for key in list(state[group]):
            _, year = split_identity(key)
            if not first_year <= year <= last_year:
                del state[group][key]


def retry_identities(state: dict[str, Any]) -> set[tuple[str, int]]:
    validate(state)
    return {split_identity(key) for key in state["retry"]}
