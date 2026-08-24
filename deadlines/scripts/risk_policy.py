#!/usr/bin/env python3
"""Which verified corrections may publish themselves, and which wait for a human.

The gate (verify_citations.py) answers "does the page say this". It cannot
answer "what does being wrong cost". That is this module's job, and the answer
turns on DIRECTION.

Showing a deadline EARLIER than the truth costs a researcher some hurried
hours. Showing one LATER costs them the paper, silently, with this site as the
proximate cause. The two are not symmetric, so they do not get the same bar:

  safe-direction   moves the effective instant earlier, leaves it unchanged, or
                   fills a field that was absent      -> may auto-apply
  risk-direction   moves it later, or removes a value -> always held for a human

The effective instant is date + clock time + timezone offset. Direction is
computed on that instant, never on the date string: UTC+9 -> AoE with no date
change moves a deadline 21 hours later, and a date-only comparison sees
nothing. A record with no timezone counts as UTC-12, because that is what
deadline-tracker.js renders.

Held items are not discarded - they go to the pull request with their evidence.
The gate has a measured false-negative rate, so "held" must mean "a human
looks", never "it vanishes".
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
MAX_SHIFT_DAYS = 120        # beyond this, even earlier-moving changes wait
MAX_AUTO_APPLY = 6          # a week wanting more than this is a broken upstream

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
        if before and after:
            shift = max(abs((a - b).days) for a, b in zip(after, before))
            if shift > MAX_SHIFT_DAYS:
                return RISK, f"{field} moves {shift} days, beyond the {MAX_SHIFT_DAYS}-day cap"
    return SAFE, "no field moves the effective instant later"


def decide(gate_status, proposal, current_record):
    """-> ("apply"|"hold", reason). Only a VERIFIED, safe-direction change applies."""
    if gate_status != "VERIFIED":
        return "hold", f"gate returned {gate_status}"
    d, why = classify(proposal, current_record)
    return ("apply", why) if d == SAFE else ("hold", why)
