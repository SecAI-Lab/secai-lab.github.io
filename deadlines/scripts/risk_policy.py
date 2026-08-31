#!/usr/bin/env python3
"""Deterministic safety bounds for autonomously verified corrections.

The gate (verify_citations.py) answers "does the official page say this".  This
module then rejects structurally dangerous mutations (unverified data, removal
of an override without upstream agreement, or an implausibly large shift).

Direction is still computed and reported because a later displayed instant is
the higher-risk mistake.  It is not, however, a request for human intervention:
once every changed field is mechanically grounded on an official page, ordinary
extensions and cycle changes may apply automatically within conservative
bounds.  Later moves are capped much more tightly because displaying a date
later than the official deadline can cost a submission; earlier corrections
retain the existing wider wrong-cycle guard.

The effective instant is date + clock time + timezone offset. Direction is
computed on that instant, never on the date string: UTC+9 -> AoE with no date
change moves a deadline 21 hours later, and a date-only comparison sees
nothing. A record with no timezone counts as UTC-12, because that is what
deadline-tracker.js renders.

Anything outside the bounds keeps the previous value on its first observation.
The publishing layer hashes the normalized claim and promotes it only after the
official page independently verifies the identical fact on two distinct weekly
audit dates.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_deadlines as U  # noqa: E402

# No timezone means AoE on the rendered page (deadline-tracker.js:110), so that
# is the offset an absent value must be compared at.
DEFAULT_OFFSET_HOURS = -12
MAX_LATER_SHIFT_DAYS = 30   # a larger extension is too risky to publish unattended
MAX_EARLIER_SHIFT_DAYS = 120  # retain the existing wrong-cycle guard

SAFE, RISK, NEUTRAL = "safe", "risk", "neutral"


def offset_hours(tz, when: dt.date | None = None) -> float:
    """Hours from UTC for a stored timezone value, DST-correct where possible."""
    s = U.clean(tz)
    if not s or s.upper() in ("TBA", "TBD"):
        return DEFAULT_OFFSET_HOURS
    canon = U.canon_tz(s)
    if canon.startswith("UTC"):
        rest = canon[3:]
        try:
            return float(rest) if rest else 0.0
        except ValueError:
            return DEFAULT_OFFSET_HOURS
    if canon in ("PST",):
        return -8.0
    if canon in ("PDT",):
        return -7.0
    if "/" in canon and U.TZDB_AVAILABLE:
        try:
            import zoneinfo
            ref = dt.datetime.combine(when or dt.date.today(), dt.time(12))
            off = ref.replace(tzinfo=zoneinfo.ZoneInfo(canon)).utcoffset()
            if off is not None:
                return off.total_seconds() / 3600.0
        except Exception:  # noqa: BLE001 - unknown zone: assume the render default
            return DEFAULT_OFFSET_HOURS
    return DEFAULT_OFFSET_HOURS


def instant(value, tz) -> dt.datetime | None:
    """The UTC instant a stored deadline actually denotes, or None if not concrete."""
    s = U.norm_dt(value) or ""
    if not s:
        return None
    try:
        naive = dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return naive - dt.timedelta(hours=offset_hours(tz, naive.date()))


def _instants(rec, field):
    tz = rec.get("timezone")
    return [i for i in (instant(v, tz) for v in U.as_list(rec.get(field))) if i]


def conservative_shifts(before, after):
    """Signed shifts covering replacements, additions, and removed cycles.

    Positional ``zip`` is unsafe here: changing the number of submission cycles
    silently drops the extra values from the comparison.  Instead, every new
    instant is compared with its closest old instant and every old instant with
    its closest new instant.  This symmetric nearest-neighbour bound is order
    independent and makes an added or removed outlying cycle visible without
    cross-comparing two unchanged, legitimate cycles.
    """
    if not before or not after:
        return []
    shifts = []
    for new in after:
        old = min(before, key=lambda value: abs(new - value))
        shifts.append(new - old)
    for old in before:
        new = min(after, key=lambda value: abs(value - old))
        shifts.append(new - old)
    return shifts


def shift_blocker(before, after, field):
    """Return the autonomous date-shift violation for *field*, if any."""
    shifts = conservative_shifts(before, after)
    later = max((shift.total_seconds() for shift in shifts), default=0)
    if later > MAX_LATER_SHIFT_DAYS * 86400:
        days = later / 86400
        return (f"{field} moves {days:g} days later, beyond the "
                f"{MAX_LATER_SHIFT_DAYS}-day autonomous cap")
    earlier = max((-shift.total_seconds() for shift in shifts), default=0)
    if earlier > MAX_EARLIER_SHIFT_DAYS * 86400:
        days = earlier / 86400
        return (f"{field} moves {days:g} days earlier, beyond the "
                f"{MAX_EARLIER_SHIFT_DAYS}-day wrong-cycle cap")
    return None


def explicit_deadline_deletion(value):
    """Whether a proposed value explicitly deletes any stored deadline value."""
    if value is None:
        return True
    if isinstance(value, list):
        return not value or any(item is None for item in value)
    return False


def direction(old_rec, new_rec, field="deadline"):
    """SAFE / RISK / NEUTRAL for one field, judged on the effective instant."""
    before, after = _instants(old_rec, field), _instants(new_rec, field)
    if not after:
        # Removing a concrete value: the page then renders whatever the
        # frontend defaults to, which is the latest possible reading.
        return RISK if before else NEUTRAL
    if not before:
        return SAFE                       # filling an absent value
    if len(before) != len(after):
        return RISK                       # cycle added or dropped: not comparable
    if all(a <= b for a, b in zip(after, before)):
        return SAFE
    return RISK


def timezone_direction(old_rec, new_rec):
    """A zone change with no date change still moves the instant."""
    old_tz, new_tz = old_rec.get("timezone"), new_rec.get("timezone")
    if U.canon_tz(old_tz) == U.canon_tz(new_tz):
        return NEUTRAL
    if not U.clean(new_tz) or U.clean(new_tz).upper() in ("TBA", "TBD"):
        return RISK                       # falls back to the AoE default
    if not U.clean(old_tz) or U.clean(old_tz).upper() in ("TBA", "TBD"):
        # Was rendering at the AoE default; compare against that.
        old_rec = dict(old_rec, timezone="UTC-12")
    for field in ("deadline", "abstract_deadline"):
        if direction(old_rec, dict(new_rec, timezone=new_tz), field) == RISK:
            return RISK
    return SAFE


def classify(proposal, current_record):
    """-> (verdict_direction, reason). RISK if any field moves the instant later."""
    fields = proposal.get("fields") or {}
    if proposal.get("action") == "delete_manual":
        return RISK, "retiring an override is not verified by the gate"
    merged = dict(current_record or {})
    for name, claim in fields.items():
        merged[name] = claim.get("value")

    if "timezone" in fields:
        d = timezone_direction(current_record or {}, merged)
        if d == RISK:
            return RISK, "the timezone change moves the deadline later (or removes it)"

    for field in ("deadline", "abstract_deadline"):
        if field not in fields:
            continue
        d = direction(current_record or {}, merged, field)
        if d == RISK:
            return RISK, f"{field} moves later, or a cycle was added or dropped"
        before, after = _instants(current_record or {}, field), _instants(merged, field)
        blocker = shift_blocker(before, after, field)
        if blocker:
            return RISK, blocker
    return SAFE, "no field moves the effective instant later"


def autonomous_blocker(proposal, current_record):
    """Return a hard safety reason, or ``None`` when auto-apply is permitted."""
    if proposal.get("action") == "delete_manual":
        return "retiring an override needs independently persisted upstream agreement"

    fields = proposal.get("fields") or {}
    merged = dict(current_record or {})
    for name, claim in fields.items():
        merged[name] = claim.get("value")

    # Timezone deletion is rejected by proposal validation too.  Keep this
    # defence here because a missing zone renders as AoE, the latest instant.
    if "timezone" in fields:
        tz = U.clean(merged.get("timezone"))
        if not tz or tz.upper() in ("TBA", "TBD"):
            return "timezone removal falls back to AoE"

    for field in ("deadline", "abstract_deadline"):
        if field not in fields:
            continue
        proposed_value = fields[field].get("value")
        if explicit_deadline_deletion(proposed_value):
            return f"{field} deletion is never applied automatically"
        before, after = _instants(current_record or {}, field), _instants(merged, field)
        if before and not after:
            return f"{field} removal is never applied automatically"
        if len(after) < len(before):
            return f"{field} cycle removal is never applied automatically"
        blocker = shift_blocker(before, after, field)
        if blocker:
            return blocker
    return None


def decide(gate_status, proposal, current_record):
    """-> ("apply"|"hold", reason) for a fully autonomous audit."""
    if gate_status != "VERIFIED":
        return "hold", f"gate returned {gate_status}"
    blocker = autonomous_blocker(proposal, current_record)
    if blocker:
        return "hold", blocker
    direction_name, why = classify(proposal, current_record)
    if direction_name == RISK:
        return "apply", f"official evidence verified; {why}"
    return "apply", why
