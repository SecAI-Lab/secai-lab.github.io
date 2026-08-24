#!/usr/bin/env python3
"""Tests for risk_policy.py - which corrections may publish themselves.

The asymmetry these pin: too early costs hurried hours, too late costs the
paper. Every test here is about not confusing the two.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import risk_policy as R  # noqa: E402


def prop(fields, action="upsert_manual"):
    return {"id": f"{action}:X:2027", "action": action, "title": "X", "year": 2027,
            "source_url": "https://x.example/",
            "fields": {k: {"value": v} for k, v in fields.items()}}


class Offsets(unittest.TestCase):
    def test_absent_timezone_is_the_render_default(self):
        # deadline-tracker.js renders a missing zone as AoE, so that is the
        # offset a comparison must assume.
        self.assertEqual(R.offset_hours(None), -12)
        self.assertEqual(R.offset_hours("TBA"), -12)

    def test_utc_offsets_parse_with_sign(self):
        self.assertEqual(R.offset_hours("UTC+9"), 9)
        self.assertEqual(R.offset_hours("UTC-5"), -5)
        self.assertEqual(R.offset_hours("AoE"), -12)

    def test_iana_zone_is_dst_correct(self):
        import datetime as dt
        if not R.U.TZDB_AVAILABLE:
            self.skipTest("no tz database")
        # The SAC case: October 2 is EDT (-4), not EST (-5).
        self.assertEqual(R.offset_hours("America/New_York", dt.date(2026, 10, 2)), -4)
        self.assertEqual(R.offset_hours("America/New_York", dt.date(2026, 1, 15)), -5)


class Direction(unittest.TestCase):
    def test_earlier_deadline_is_safe(self):
        self.assertEqual(R.direction({"deadline": "2026-02-10 23:59", "timezone": "AoE"},
                                     {"deadline": "2026-02-03 23:59", "timezone": "AoE"}),
                         R.SAFE)

    def test_later_deadline_is_risk(self):
        self.assertEqual(R.direction({"deadline": "2026-02-03 23:59", "timezone": "AoE"},
                                     {"deadline": "2026-02-10 23:59", "timezone": "AoE"}),
                         R.RISK)

    def test_filling_an_absent_deadline_is_safe(self):
        self.assertEqual(R.direction({}, {"deadline": "2026-02-10 23:59"}), R.SAFE)

    def test_removing_a_deadline_is_risk(self):
        self.assertEqual(R.direction({"deadline": "2026-02-10 23:59"}, {}), R.RISK)

    def test_a_dropped_cycle_is_risk(self):
        self.assertEqual(R.direction(
            {"deadline": ["2026-01-15 23:59", "2026-02-15 23:59"], "timezone": "AoE"},
            {"deadline": "2026-01-15 23:59", "timezone": "AoE"}), R.RISK)


class TimezoneMoves(unittest.TestCase):
    """A zone change with no date change still moves the instant - the case a
    date-only comparison cannot see."""

    def test_utc9_to_aoe_is_risk(self):
        # Same date, 21 hours later.
        self.assertEqual(R.classify(
            prop({"timezone": "AoE"}),
            {"deadline": "2026-11-20 23:59", "timezone": "UTC+9"})[0], R.RISK)

    def test_aoe_to_utc9_is_safe(self):
        self.assertEqual(R.classify(
            prop({"timezone": "UTC+9"}),
            {"deadline": "2026-11-20 23:59", "timezone": "AoE"})[0], R.SAFE)

    def test_removing_a_timezone_is_risk(self):
        self.assertEqual(R.classify(
            prop({"timezone": "TBA"}),
            {"deadline": "2026-11-20 23:59", "timezone": "UTC+9"})[0], R.RISK)

    def test_est_to_edt_correction_is_safe(self):
        # The real SAC fix: UTC-5 -> America/New_York on an October date moves
        # the instant an hour EARLIER, which is the safe direction.
        if not R.U.TZDB_AVAILABLE:
            self.skipTest("no tz database")
        self.assertEqual(R.classify(
            prop({"timezone": "America/New_York"}),
            {"deadline": "2026-10-02 23:59", "timezone": "UTC-5"})[0], R.SAFE)

    def test_an_unchanged_zone_is_neutral(self):
        self.assertEqual(R.timezone_direction({"timezone": "AoE"},
                                              {"timezone": "UTC-12"}), R.NEUTRAL)


class Decisions(unittest.TestCase):
    def test_verified_and_safe_applies(self):
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2026-02-03 23:59"}),
                                  {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                         "apply")

    def test_verified_but_later_is_held(self):
        # An extension is the commonest real correction and still waits: this is
        # the direction that costs the paper.
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2026-02-17 23:59"}),
                                  {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                         "hold")

    def test_unverified_is_held_whatever_the_direction(self):
        for status in ("UNCONFIRMED", "UNCHECKED", "UNREACHABLE", "REJECTED_SOURCE"):
            with self.subTest(status):
                self.assertEqual(R.decide(status, prop({"deadline": "2026-02-03 23:59"}),
                                          {"deadline": "2026-02-10 23:59"})[0], "hold")

    def test_filling_a_tba_applies(self):
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2026-02-10 23:59"}),
                                  {"deadline": "TBA"})[0], "apply")

    def test_delete_manual_is_always_held(self):
        self.assertEqual(R.decide("VERIFIED", prop({}, action="delete_manual"),
                                  {"deadline": "2026-02-10 23:59"})[0], "hold")

    def test_a_huge_earlier_move_is_held(self):
        # Safe direction, but a shift this large is more likely a wrong-cycle
        # pick than a real correction.
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2025-06-01 23:59"}),
                                  {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                         "hold")

    def test_metadata_only_change_applies(self):
        self.assertEqual(R.decide("VERIFIED", prop({"place": "Lisbon, Portugal"}),
                                  {"deadline": "2026-11-20 23:59", "place": "TBA"})[0],
                         "apply")


if __name__ == "__main__":
    unittest.main(verbosity=2)
