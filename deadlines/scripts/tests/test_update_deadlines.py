#!/usr/bin/env python3
"""Regression tests for the deadline pipeline's correctness fixes.

Run: python3 deadlines/scripts/tests/test_update_deadlines.py

Every test here pins a bug that was live in the pipeline and could put a wrong
deadline - or a deadline that renders LATER than the truth - on the public page.
"""

import datetime as dt
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

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

    def test_comparable_match_cannot_discard_an_unverifiable_note_override(self):
        man = {"title": "X", "year": 2026,
               "deadline": "2026-02-10 23:59", "note": "Official clarification."}
        self.assertFalse(U.manual_matches_upstream(
            man, cand(["2026-02-10 23:59"])))

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

    def test_abstract_cycle_position_must_match_before_retirement(self):
        man = {"title": "X", "year": 2027,
               "abstract_deadline": "2027-05-01 23:59"}
        upstream = cand(
            ["2027-05-08 23:59", "2027-09-08 23:59"],
            [None, "2027-05-01 23:59"],
        )
        self.assertFalse(U.manual_matches_upstream(man, upstream))

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

    def test_retirement_marker_requires_every_covering_source_to_agree(self):
        man = {"title": "X", "year": 2026, "deadline": "2026-02-10 23:59"}
        target = {"key": "X", "priority": ["ccfddl", "secdl"]}
        candidates = [
            cand(["2026-02-10 23:59"], source="ccfddl"),
            cand(["2026-02-03 23:59"], source="secdl"),
        ]
        marker = U.upstream_agreement_marker(man, candidates, target, {})
        self.assertFalse(marker["agrees"])
        self.assertEqual(marker["sources"], ["ccfddl", "secdl"])

    def test_retirement_marker_fails_closed_when_a_source_fetch_failed(self):
        man = {"title": "X", "year": 2026, "deadline": "2026-02-10 23:59"}
        target = {"key": "X", "priority": ["ccfddl", "secdl"]}
        candidates = [cand(["2026-02-10 23:59"], source="ccfddl")]
        marker = U.upstream_agreement_marker(
            man, candidates, target, {"secdl": {"X"}})
        self.assertFalse(marker["agrees"])
        self.assertFalse(marker["all_fetches_healthy"])

    def test_retirement_marker_accepts_complete_multi_source_agreement(self):
        man = {"title": "X", "year": 2026, "deadline": "2026-02-10 23:59"}
        target = {"key": "X", "priority": ["ccfddl", "secdl"]}
        candidates = [
            cand(["2026-02-10 23:59"], source="ccfddl"),
            cand(["2026-02-10 23:59"], source="secdl"),
        ]
        self.assertTrue(
            U.upstream_agreement_marker(man, candidates, target, {})["agrees"])

    def test_retirement_digest_binds_manual_and_every_source_value(self):
        target = {"key": "X", "priority": ["ccfddl", "secdl"]}
        man = {"title": "X", "year": 2026, "deadline": "2026-02-10 23:59"}
        candidates = [
            cand(["2026-02-10 23:59"], source="ccfddl"),
            cand(["2026-02-10 23:59"], source="secdl"),
        ]
        first = U.upstream_agreement_marker(man, candidates, target, {})
        changed_manual = U.upstream_agreement_marker(
            {**man, "deadline": "2026-02-11 23:59"}, candidates, target, {})
        changed_source = U.upstream_agreement_marker(
            man, [candidates[0], cand(["2026-02-11 23:59"], source="secdl")],
            target, {})
        self.assertRegex(first["basis_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(first["basis_digest"], changed_manual["basis_digest"])
        self.assertNotEqual(first["basis_digest"], changed_source["basis_digest"])


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

    def test_impossible_fixed_offsets_are_rejected(self):
        for tz in ("UTC+15", "UTC-13", "UTC+99"):
            with self.subTest(tz=tz):
                rec = {"title": "S&P", "year": U.TODAY.year,
                       "deadline": "2026-02-10 23:59", "timezone": tz}
                errors = U.validate(rec, {"S&P"})
                self.assertTrue(any("unresolvable timezone" in e for e in errors),
                                errors)

    def test_edge_fixed_offsets_are_accepted(self):
        for tz in ("UTC-12", "UTC+14"):
            with self.subTest(tz=tz):
                rec = {"title": "S&P", "year": U.TODAY.year,
                       "deadline": "2026-02-10 23:59", "timezone": tz}
                self.assertEqual(U.validate(rec, {"S&P"}), [])


class DeadlineValidity(unittest.TestCase):
    def test_normalizer_rejects_impossible_calendar_and_clock_values(self):
        for value in ("2027-99-99 23:59", "2027-02-29 23:59",
                      "2027-10-02 24:00", "2027-10-02 12:60"):
            with self.subTest(value=value):
                self.assertIsNone(U.norm_dt(value))

    def test_leap_day_is_accepted_only_in_a_leap_year(self):
        self.assertEqual(U.norm_dt("2028-02-29 5:07"), "2028-02-29 05:07")
        self.assertTrue(U.valid_deadline("2028-02-29 05:07"))

    def test_validator_rejects_shape_correct_but_impossible_instants(self):
        for value in ("2027-99-99 23:59", "2027-02-29 23:59",
                      "2027-10-02 24:00"):
            with self.subTest(value=value):
                rec = {"title": "S&P", "year": U.TODAY.year,
                       "deadline": value, "timezone": "AoE"}
                errors = U.validate(rec, {"S&P"})
                self.assertTrue(any("bad deadline" in e for e in errors), errors)


class UpstreamDeadlineParsing(unittest.TestCase):
    def test_ccfddl_invalid_instant_is_a_source_failure_not_silent_tba(self):
        doc = [{"confs": [{
            "year": U.TODAY.year,
            "timeline": [{"deadline": f"{U.TODAY.year}-99-99 23:59"}],
        }]}]
        with self.assertRaisesRegex(RuntimeError, "invalid deadline value"):
            U.convert_ccfddl(doc, "X")

    def test_explicit_tba_still_means_no_candidate(self):
        doc = [{"confs": [{
            "year": U.TODAY.year,
            "timeline": [{"deadline": "TBA"}],
        }]}]
        self.assertEqual(U.convert_ccfddl(doc, "X"), {})

    def test_invalid_explicit_timezone_is_not_silently_replaced_with_aoe(self):
        with self.assertRaisesRegex(RuntimeError, "invalid ccfddl timezone"):
            U.map_ccfddl_tz("UTC+99")

    def test_ccfddl_iana_timezone_is_preserved(self):
        self.assertEqual(U.map_ccfddl_tz("America/New_York"),
                         "America/New_York")

    def test_one_bad_secdl_target_does_not_poison_every_other_target(self):
        records = [
            {"name": "Good", "year": U.TODAY.year,
             "deadline": f"{U.TODAY.year}-09-01 23:59"},
            {"name": "Bad", "year": U.TODAY.year,
             "deadline": f"{U.TODAY.year}-99-99 23:59"},
        ]
        targets = [
            {"key": "Good", "sources": {"secdl": "Good"}},
            {"key": "Bad", "sources": {"secdl": "Bad"}},
        ]
        saved_health, saved_warnings = list(U.health), list(U.warnings)
        U.health.clear()
        U.warnings.clear()
        def restore_diagnostics():
            U.health[:] = saved_health
            U.warnings[:] = saved_warnings
        self.addCleanup(restore_diagnostics)
        with mock.patch.object(U, "http_get", return_value=__import__("yaml").safe_dump(records)):
            data, failed, _, any_ok = U.fetch_upstream(targets)
        self.assertTrue(any_ok)
        self.assertIn(U.TODAY.year, data["secdl"]["Good"])
        self.assertEqual(failed["secdl"], {"Bad"})
        self.assertTrue(any("secdl parse failed for Bad" in item for item in U.health))


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


class WatchlistPriority(unittest.TestCase):
    """Every shard is required, but ordering still puts urgent records into the
    earliest shard so they receive the first completion-retry opportunity."""

    RANK = ["deadline-within-45-days", "audit-deferred", "tba-upcoming-cycle",
            "manual-override-active",
            "cross-source-disagreement", "stale-placeholder-note", "coverage-gap",
            "tba-metadata", "scheduled-full-audit"]

    def test_priority_order_matches_auditor_md(self):
        # Scope to the numbered Priorities section: these reason names also
        # appear elsewhere in the document (create_record cites coverage-gap).
        doc = (U.REPO_ROOT / "deadlines" / "scripts" / "AUDITOR.md").read_text(encoding="utf-8")
        section = doc.split("## Priorities", 1)[1].split("\n## ", 1)[0]
        order = [m for m in re.findall(r"^\d+\.\s+`([a-z0-9-]+)`", section, re.M)]
        self.assertEqual(order, self.RANK,
                         "AUDITOR.md's priority list and the watchlist sort disagree; "
                         "the sort decides which records the bounded run ever reaches")

    def test_persisted_retry_survives_an_edition_year_boundary(self):
        rec = {"deadline": "2025-08-01 23:59", "timezone": "AoE"}
        reasons = U.audit_reasons_for_record(
            "FSE", 2025, rec, set(), set(), {("FSE", 2025)},
            today=dt.date(2026, 1, 2))
        self.assertEqual(reasons, ["audit-deferred"])

    def test_resolved_past_edition_is_not_scheduled_forever(self):
        rec = {"deadline": "2025-08-01 23:59", "timezone": "AoE"}
        reasons = U.audit_reasons_for_record(
            "FSE", 2025, rec, set(), set(), set(),
            today=dt.date(2026, 1, 2))
        self.assertEqual(reasons, [])

    def test_manual_only_rendered_row_remains_in_weekly_audit_records(self):
        rec = {"title": "BAR", "year": 2027, "deadline": "2026-12-01 23:59"}
        manual = {("BAR", 2027): rec}
        rows = U.audit_record_rows({}, [], manual, [("BAR", 2027)])
        self.assertEqual(rows, [("BAR", 2027, rec)])

    def test_deferred_gap_survives_january_rollover_without_a_record(self):
        deferred = {("BAR", 2027)}
        missing = U.missing_deferred_audits(
            deferred, {("BAR", 2028)}, {"BAR": {"category": "security"}}
        )
        self.assertEqual(missing, [("BAR", 2027)])


class ExplicitTimezone(unittest.TestCase):
    """AoE is the CFP convention when a page states no timezone, and it is what
    the frontend renders anyway. Recording it changes no instant but makes the
    assumption auditable: an absent field cannot be told apart from an
    oversight."""

    def test_concrete_deadline_gets_aoe_when_unstated(self):
        rec = {"deadline": "2026-11-20 23:59"}
        U.default_timezone(rec)
        self.assertEqual(rec["timezone"], "AoE")
        self.assertIn("AoE assumed", rec["note"])

    def test_tba_string_is_treated_as_unstated(self):
        rec = {"deadline": "2026-11-20 23:59", "timezone": "TBA"}
        U.default_timezone(rec)
        self.assertEqual(rec["timezone"], "AoE")

    def test_a_stated_timezone_is_never_overwritten(self):
        rec = {"deadline": "2026-10-02 23:59", "timezone": "America/New_York"}
        U.default_timezone(rec)
        self.assertEqual(rec["timezone"], "America/New_York")
        self.assertNotIn("note", rec)

    def test_tba_deadline_gets_no_timezone(self):
        # No instant to place in a zone.
        rec = {"deadline": "TBA"}
        U.default_timezone(rec)
        self.assertNotIn("timezone", rec)

    def test_the_note_is_not_duplicated_on_repeat_runs(self):
        rec = {"deadline": "2026-11-20 23:59"}
        U.default_timezone(rec)
        first = rec["note"]
        rec.pop("timezone")
        U.default_timezone(rec)
        self.assertEqual(rec["note"], first)

    def test_every_repo_record_with_a_deadline_states_its_timezone(self):
        import yaml
        bad = []
        for f in U.DATA_DIR.glob("*/*.yml"):
            for rec in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
                concrete = [d for d in U.as_list(rec.get("deadline"))
                            if d and str(d).upper() not in ("TBA", "TBD")]
                tz = rec.get("timezone")
                if concrete and (not tz or str(tz).upper() in ("TBA", "TBD")):
                    bad.append(f"{rec['title']} {rec['year']}")
        self.assertEqual(bad, [], "these render as AoE by silent default")


class NoFabricatedAbstracts(unittest.TestCase):
    """deadline-tracker.js:131 invents an abstract deadline at paper-7d from any
    note matching this regex, and renders it as fact though no data file holds
    it. Four records were doing that - CCS 2026's two invented instants had no
    basis at all, since its site states no abstract deadline. The applier
    rejects such notes; this pins the checked-in data too, since notes can also
    arrive by hand or from upstream."""

    REGEX = re.compile(r"abstract.*1 week before|1 week before.*abstract", re.I)

    def test_no_record_arms_the_frontend_fabricator(self):
        import yaml
        armed = []
        for f in (U.DATA_DIR).glob("*/*.yml"):
            for rec in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
                if rec.get("note") and self.REGEX.search(str(rec["note"])):
                    armed.append(f"{rec['title']} {rec['year']}")
        self.assertEqual(armed, [], "these notes make the page invent an "
                                    "abstract deadline at paper-7 days")

    def test_no_manual_override_arms_it_either(self):
        import yaml
        recs = yaml.safe_load(U.MANUAL_PATH.read_text(encoding="utf-8")) or []
        armed = [f"{r.get('title')} {r.get('year')}" for r in recs
                 if r.get("note") and self.REGEX.search(str(r["note"]))]
        self.assertEqual(armed, [])


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
