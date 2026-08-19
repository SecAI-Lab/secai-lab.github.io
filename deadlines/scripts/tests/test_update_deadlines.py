#!/usr/bin/env python3
"""Regression tests for the deadline pipeline's correctness fixes.

Run: python3 deadlines/scripts/tests/test_update_deadlines.py

Every test here pins a bug that was live in the pipeline and could put a wrong
deadline - or a deadline that renders LATER than the truth - on the public page.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_deadlines as U  # noqa: E402


def cand(deadlines=(), abstracts=(), **extra):
    """An upstream candidate in the shape build_merged/manual_matches_upstream expect."""
    return {"deadlines": list(deadlines), "abstracts": list(abstracts),
            "source": "test", **extra}


class ManualMatchesUpstream(unittest.TestCase):
    """An override declared obsolete gets deleted. Both false-positive paths
    below would delete a correct, still-needed override."""

    def test_vacuous_match_is_not_agreement(self):
        # note/start/end are in MANUAL_FIELDS but are not comparable against
        # upstream. Nothing to check must not mean "upstream agrees".
        man = {"title": "X", "year": 2026, "note": "Deadline extended."}
        self.assertFalse(U.manual_matches_upstream(man, cand(["2026-02-10 23:59"])))

    def test_start_end_only_override_is_not_agreement(self):
        man = {"title": "X", "year": 2026, "start": "2026-06-29", "end": "2026-07-03"}
        self.assertFalse(U.manual_matches_upstream(man, cand(["2026-02-10 23:59"])))

    def test_null_override_survives_a_transient_upstream_omission(self):
        # The real NDSS 2026 pattern: abstract_deadline is pinned to null to
        # suppress a value both trackers fabricate. On a run where upstream
        # happens to carry no abstract, the old code saw () == () and called
        # the override obsolete - deleting the very thing suppressing the bug.
        man = {"title": "NDSS", "year": 2026, "abstract_deadline": None}
        self.assertFalse(U.manual_matches_upstream(man, cand(["2025-08-06 23:59"], [])))

    def test_null_override_still_not_obsolete_when_upstream_fabricates(self):
        man = {"title": "NDSS", "year": 2026, "abstract_deadline": None}
        self.assertFalse(U.manual_matches_upstream(
            man, cand(["2025-08-06 23:59"], ["2025-07-30 23:59"])))

    def test_genuine_agreement_is_still_reported(self):
        # The fix must not break the real signal: an override upstream has
        # caught up on should still be reported as removable.
        man = {"title": "X", "year": 2026, "deadline": "2026-02-10 23:59",
               "timezone": "AoE"}
        self.assertTrue(U.manual_matches_upstream(
            man, cand(["2026-02-10 23:59"], timezone="UTC-12")))

    def test_genuine_disagreement_is_not_agreement(self):
        man = {"title": "X", "year": 2026, "deadline": "2026-02-10 23:59"}
        self.assertFalse(U.manual_matches_upstream(man, cand(["2026-02-03 23:59"])))


class TimezoneResolvability(unittest.TestCase):
    """deadline-tracker.js falls through to -12:00 (AoE) for any zone Luxon
    cannot resolve, so an invented IANA name shows the deadline LATER than the
    truth - for a UTC-5 venue, 7 hours later."""

    def test_invented_iana_zone_is_unresolvable(self):
        if not U.TZDB_AVAILABLE:
            self.skipTest("no tz database available")
        self.assertFalse(U.tz_resolvable("Banana/Republic"))

    def test_real_iana_zone_resolves(self):
        if not U.TZDB_AVAILABLE:
            self.skipTest("no tz database available")
        self.assertTrue(U.tz_resolvable("America/Los_Angeles"))

    def test_shorthand_zones_need_no_lookup(self):
        for tz in ("AoE", "PST", "PDT", "UTC", "UTC-12", "UTC+9"):
            self.assertTrue(U.tz_resolvable(tz), tz)

    def test_validate_rejects_invented_zone(self):
        if not U.TZDB_AVAILABLE:
            self.skipTest("no tz database available")
        rec = {"title": "S&P", "year": U.TODAY.year, "deadline": "2026-02-10 23:59",
               "timezone": "Banana/Republic"}
        errors = U.validate(rec, {"S&P"})
        self.assertTrue(any("unresolvable timezone" in e for e in errors), errors)

    def test_validate_accepts_real_zone(self):
        rec = {"title": "S&P", "year": U.TODAY.year, "deadline": "2026-02-10 23:59",
               "timezone": "America/Los_Angeles"}
        self.assertEqual(U.validate(rec, {"S&P"}), [])

    def test_validate_still_rejects_malformed_shape(self):
        rec = {"title": "S&P", "year": U.TODAY.year, "deadline": "2026-02-10 23:59",
               "timezone": "not a zone!"}
        errors = U.validate(rec, {"S&P"})
        self.assertTrue(any("bad timezone" in e for e in errors), errors)


class ManualBigMoveWarning(unittest.TestCase):
    """build_merged skips the 90-day rail whenever manual.yml owns `deadline`,
    so a large override move lands silently at exit 0. It must at least warn."""

    def setUp(self):
        self._saved = list(U.warnings)
        U.warnings.clear()

    def tearDown(self):
        U.warnings[:] = self._saved

    def test_large_move_warns(self):
        future = U.TODAY + __import__("datetime").timedelta(days=200)
        far = future + __import__("datetime").timedelta(days=212)
        U.warn_manual_big_move({"deadline": f"{future} 23:59"},
                               {"deadline": f"{far} 23:59"}, "ACNS", 2027)
        self.assertTrue(any("MOVED ACNS 2027 BY" in w for w in U.warnings), U.warnings)

    def test_small_move_is_quiet(self):
        U.warn_manual_big_move({"deadline": "2026-02-03 23:59"},
                               {"deadline": "2026-02-10 23:59"}, "EuroSec", 2026)
        self.assertEqual(U.warnings, [])

    def test_no_existing_record_is_quiet(self):
        U.warn_manual_big_move(None, {"deadline": "2026-02-10 23:59"}, "X", 2026)
        self.assertEqual(U.warnings, [])

    def test_tba_placeholders_are_quiet(self):
        U.warn_manual_big_move({"deadline": "TBA"}, {"deadline": "2026-02-10 23:59"},
                               "X", 2026)
        self.assertEqual(U.warnings, [])


class TbaMetadataNomination(unittest.TestCase):
    """A record with a real deadline but TBA place/date/timezone matches no
    other watchlist reason, so the auditor is never asked to look it up.
    EuroS&P 2027 sat that way with place: TBA until 2026-08-18."""

    def test_tba_place_is_flagged(self):
        rec = {"deadline": "2026-11-20 23:59", "place": "TBA",
               "date": "TBA", "timezone": "TBA"}
        self.assertEqual(U.tba_metadata_fields(rec), ["place", "date", "timezone"])

    def test_absent_field_counts_as_tba(self):
        self.assertEqual(U.tba_metadata_fields({"deadline": "2026-11-20 23:59"}),
                         ["place", "date", "timezone"])

    def test_tbd_spelling_and_case(self):
        self.assertEqual(U.tba_metadata_fields({"place": "tbd", "date": "x", "timezone": "AoE"}),
                         ["place"])

    def test_fully_populated_record_is_quiet(self):
        rec = {"place": "Lisbon, Portugal", "date": "June 29 - July 3, 2027",
               "timezone": "AoE"}
        self.assertEqual(U.tba_metadata_fields(rec), [])

    def test_deadline_is_not_a_metadata_field(self):
        # The deadline has its own reasons; this one must not double-report it.
        self.assertNotIn("deadline", U.tba_metadata_fields(
            {"deadline": "TBA", "place": "Lisbon, Portugal",
             "date": "x", "timezone": "AoE"}))


class RepoDataIsValid(unittest.TestCase):
    """Guards the checked-in data against the same rules the pipeline enforces."""

    def test_every_manual_entry_validates(self):
        import yaml
        records = yaml.safe_load(U.MANUAL_PATH.read_text(encoding="utf-8")) or []
        targets = U.load_config()
        canonical = {t["key"] for t in targets}
        for rec in records:
            with self.subTest(title=rec.get("title"), year=rec.get("year")):
                self.assertIn(rec.get("title"), canonical)
                tz = rec.get("timezone")
                if tz is not None:
                    self.assertTrue(U.tz_resolvable(tz), f"unresolvable tz {tz!r}")

    def test_manual_entries_are_uniquely_keyed(self):
        import yaml
        records = yaml.safe_load(U.MANUAL_PATH.read_text(encoding="utf-8")) or []
        keys = [(r.get("title"), r.get("year")) for r in records]
        self.assertEqual(len(keys), len(set(keys)), "duplicate (title, year) in manual.yml")


if __name__ == "__main__":
    unittest.main(verbosity=2)
