#!/usr/bin/env python3
"""Tests for the autonomous correction safety policy."""

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

    def test_verified_extension_applies_without_a_human(self):
        # A grounded official extension is a normal autonomous correction.
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2026-02-17 23:59"}),
                                  {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                         "apply")

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

    def test_verified_cycle_addition_applies(self):
        self.assertEqual(R.decide(
            "VERIFIED",
            prop({"deadline": ["2026-02-10 23:59", "2026-03-01 23:59"]}),
            {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0], "apply")

    def test_deadline_deletion_is_always_held(self):
        for value in (None, [], [None]):
            with self.subTest(value=value):
                self.assertEqual(R.decide(
                    "VERIFIED", prop({"deadline": value}),
                    {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                    "hold")

    def test_abstract_deadline_deletion_is_always_held(self):
        self.assertEqual(R.decide(
            "VERIFIED", prop({"abstract_deadline": None}),
            {"abstract_deadline": "2026-02-01 23:59",
             "deadline": "2026-02-10 23:59", "timezone": "AoE"})[0], "hold")

    def test_tba_cannot_remove_a_concrete_deadline(self):
        self.assertEqual(R.decide(
            "VERIFIED", prop({"deadline": "TBA"}),
            {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0], "hold")

    def test_extension_at_thirty_days_applies(self):
        self.assertEqual(R.decide(
            "VERIFIED", prop({"deadline": "2026-03-12 23:59"}),
            {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0], "apply")

    def test_extension_beyond_thirty_days_is_held(self):
        self.assertEqual(R.decide(
            "VERIFIED", prop({"deadline": "2026-03-13 23:59"}),
            {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0], "hold")

    def test_cycle_addition_cannot_bypass_later_cap(self):
        self.assertEqual(R.decide(
            "VERIFIED",
            prop({"deadline": ["2026-02-10 23:59", "2026-06-10 23:59"]}),
            {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0], "hold")

    def test_replacement_with_fewer_cycles_cannot_bypass_cap(self):
        self.assertEqual(R.decide(
            "VERIFIED", prop({"deadline": "2026-09-10 23:59"}),
            {"deadline": ["2026-02-10 23:59", "2026-06-10 23:59"],
             "timezone": "AoE"})[0], "hold")

    def test_dropping_one_close_cycle_is_still_a_deletion(self):
        self.assertEqual(R.decide(
            "VERIFIED", prop({"deadline": "2026-02-10 23:59"}),
            {"deadline": ["2026-02-10 23:59", "2026-03-01 23:59"],
             "timezone": "AoE"})[0], "hold")

    def test_unchanged_cycles_do_not_cross_compare_against_each_other(self):
        deadlines = ["2026-02-10 23:59", "2026-09-10 23:59"]
        self.assertEqual(R.decide(
            "VERIFIED", prop({"deadline": deadlines}),
            {"deadline": deadlines, "timezone": "AoE"})[0], "apply")

    def test_huge_cycle_count_change_is_held(self):
        self.assertEqual(R.decide(
            "VERIFIED",
            prop({"deadline": ["2025-01-01 23:59", "2027-12-31 23:59"]}),
            {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0], "hold")

    def test_a_huge_earlier_move_is_held(self):
        # Safe direction, but a shift this large is more likely a wrong-cycle
        # pick than a real correction.
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2025-06-01 23:59"}),
                                  {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                         "hold")

    def test_a_huge_later_move_is_held(self):
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2026-08-15 23:59"}),
                                  {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                         "hold")

    def test_existing_safe_earlier_window_is_retained(self):
        self.assertEqual(R.decide("VERIFIED", prop({"deadline": "2025-11-12 23:59"}),
                                  {"deadline": "2026-02-10 23:59", "timezone": "AoE"})[0],
                         "apply")

    def test_metadata_only_change_applies(self):
        self.assertEqual(R.decide("VERIFIED", prop({"place": "Lisbon, Portugal"}),
                                  {"deadline": "2026-11-20 23:59", "place": "TBA"})[0],
                         "apply")


if __name__ == "__main__":
    unittest.main(verbosity=2)
