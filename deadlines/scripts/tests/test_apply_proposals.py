#!/usr/bin/env python3
"""Tests for apply_proposals.py.

Run: python3 deadlines/scripts/tests/test_apply_proposals.py

The highest-value tests here are the round-trip and idempotence ones. manual.yml
is jointly owned by humans and this program, so the property that actually
matters is that a machine write never disturbs a hand-written entry - and that
running twice changes nothing the second time.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import apply_proposals as A  # noqa: E402
import update_deadlines as U  # noqa: E402

REAL_MANUAL = U.REPO_ROOT / "deadlines" / "data" / "manual.yml"

HUMAN_FILE = '''\
# Manual overrides have the highest priority.
# Every entry MUST cite the official source it was verified against.

# A careful human wrote this one, with prose worth keeping.
# Verified 2026-07-30 against https://example.org/eurosec :
# "Paper Submission Deadline: February 10, 2026 (AoE)"
- title: "EuroSec"
  year: 2026
  deadline: "2026-02-10 23:59"
  timezone: AoE
  place: "Vienna, Austria"

# Upstream fabricates an abstract deadline the CFP never had.
# Verified 2026-08-07 against https://example.org/ndss
- title: "NDSS"
  year: 2026
  abstract_deadline: null
  deadline: "2025-08-06 23:59"
'''


def proposal(action="upsert_manual", title="EuroSec", year=2026, fields=None, **kw):
    p = {"id": f"{action}:{title}:{year}", "action": action, "title": title,
         "year": year, "reason": "Upstream disagrees with the official page.",
         "source_url": "https://example.org/cfp",
         "watchlist_reasons": ["cross-source-disagreement"]}
    if fields is not None:
        p["fields"] = fields
    p.update(kw)
    return p


def claim(value, quote="Paper Submission Deadline: February 17, 2026"):
    return {"value": value, "evidence": [{"quote": quote}]}


class RoundTrip(unittest.TestCase):
    def test_real_manual_yml_round_trips_byte_for_byte(self):
        self.assertIsNone(A.assert_round_trip(REAL_MANUAL.read_text(encoding="utf-8")))

    def test_handwritten_fixture_round_trips(self):
        self.assertIsNone(A.assert_round_trip(HUMAN_FILE))

    def test_refuses_a_file_it_cannot_reproduce(self):
        # Two entries with no blank line between them: rendering would insert
        # one, silently reformatting a human's file. Refusing beats rewriting
        # under a misparse. (audit_lint rejects this shape too - the second
        # entry inherits no citation comment.)
        doctored = HUMAN_FILE.replace(
            '  place: "Vienna, Austria"\n\n# Upstream fabricates',
            '  place: "Vienna, Austria"\n# Upstream fabricates')
        self.assertNotEqual(doctored, HUMAN_FILE, "fixture edit did not apply")
        problem = A.assert_round_trip(doctored)
        self.assertIsNotNone(problem)
        self.assertIn("round-trip", problem)

    def test_interior_blank_line_is_tolerated(self):
        # This one IS modelled: a blank line inside an entry is valid YAML and
        # survives verbatim. Worth pinning so nobody "fixes" the parser into
        # rejecting it.
        tolerated = HUMAN_FILE.replace('  year: 2026\n  deadline: "2026-02-10',
                                       '  year: 2026\n\n  deadline: "2026-02-10')
        self.assertIsNone(A.assert_round_trip(tolerated))

    def test_every_chunk_in_the_real_file_has_a_key(self):
        mf = A.parse_manual(REAL_MANUAL.read_text(encoding="utf-8"))
        self.assertTrue(mf.chunks)
        for c in mf.chunks:
            self.assertIsNotNone(c.key, c.body[:1])


class Rendering(unittest.TestCase):
    def test_explicit_null_is_emitted(self):
        # update_deadlines.render_record drops None, so it cannot express this.
        lines = A.render_manual_entry({"title": "NDSS", "year": 2026,
                                       "abstract_deadline": None,
                                       "deadline": "2025-08-06 23:59"})
        self.assertIn("  abstract_deadline: null", lines)

    def test_render_record_would_have_dropped_it(self):
        self.assertNotIn("abstract_deadline", U.render_record(
            {"title": "NDSS", "year": 2026, "abstract_deadline": None}))

    def test_multi_cycle_list(self):
        lines = A.render_manual_entry({"title": "NDSS", "year": 2026,
                                       "deadline": ["2025-04-23 23:59",
                                                    "2025-08-06 23:59"]})
        self.assertIn("  deadline:", lines)
        self.assertIn('    - "2025-04-23 23:59"', lines)

    def test_quoting_matches_the_updater(self):
        lines = A.render_manual_entry({"title": "X", "year": 2026,
                                       "timezone": "AoE", "place": "Vienna, Austria"})
        self.assertIn("  timezone: AoE", lines)          # unquoted key
        self.assertIn('  place: "Vienna, Austria"', lines)  # quoted key


class Applying(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "manual.yml"
        self.path.write_text(HUMAN_FILE, encoding="utf-8")
        self._saved = (A.MANUAL_PATH, U.MANUAL_PATH)
        A.MANUAL_PATH = U.MANUAL_PATH = self.path
        self.targets = {t["key"]: t for t in U.load_config()}
        self.keys = set(self.targets)

    def tearDown(self):
        A.MANUAL_PATH, U.MANUAL_PATH = self._saved

    def run_apply(self, props, date="2026-08-19"):
        errors = []
        good = [p for p in props if A.validate_proposal(p, self.targets, errors)]
        mf = A.parse_manual(self.path.read_text(encoding="utf-8"))
        applied, skipped = A.apply_proposals(good, mf, date, self.keys,
                                             self.targets, errors)
        if applied:
            self.path.write_text(A.render_manual(mf), encoding="utf-8")
        return applied, skipped, errors

    def test_no_proposals_leaves_the_file_byte_identical(self):
        self.run_apply([])
        self.assertEqual(self.path.read_text(encoding="utf-8"), HUMAN_FILE)

    def test_idempotent(self):
        p = [proposal(fields={"deadline": claim("2026-02-17 23:59")})]
        self.run_apply(p)
        first = self.path.read_text(encoding="utf-8")
        applied, skipped, _ = self.run_apply(p)
        self.assertEqual(self.path.read_text(encoding="utf-8"), first)
        self.assertEqual(applied, [])
        self.assertTrue(any("no-op" in why for _, why in skipped), skipped)

    def test_unmentioned_human_fields_survive(self):
        self.run_apply([proposal(fields={"deadline": claim("2026-02-17 23:59")})])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('place: "Vienna, Austria"', text)   # human's pin kept
        self.assertIn("timezone: AoE", text)
        self.assertIn('deadline: "2026-02-17 23:59"', text)

    def test_other_entries_are_untouched(self):
        self.run_apply([proposal(fields={"deadline": claim("2026-02-17 23:59")})])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# Upstream fabricates an abstract deadline the CFP never had.", text)
        self.assertIn("abstract_deadline: null", text)

    def test_previous_citation_is_retained(self):
        self.run_apply([proposal(fields={"deadline": claim("2026-02-17 23:59")})])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# Earlier: Verified 2026-07-30 against https://example.org/eurosec :",
                      text)
        self.assertIn("# Verified 2026-08-19 against https://example.org/cfp", text)

    def test_new_entry_is_appended_and_cited(self):
        p = proposal(title="DIMVA", year=2026,
                     fields={"deadline": claim("2026-02-18 23:59")})
        applied, _, errors = self.run_apply([p])
        self.assertEqual(errors, [])
        self.assertEqual(len(applied), 1)
        mf = A.parse_manual(self.path.read_text(encoding="utf-8"))
        self.assertEqual(mf.chunks[-1].key, ("DIMVA", 2026))

    def test_delete_manual_is_never_applied_automatically(self):
        # Nothing verifies that upstream really agrees - the gate returns
        # VERIFIED for delete_manual on the strength of a check no code
        # performs. Deleting the real NDSS override would let the upstream
        # FABRICATED abstract deadline back onto the live page.
        p = proposal(action="delete_manual", title="NDSS", year=2026,
                     obsolete_because="upstream_agrees")
        applied, skipped, errors = self.run_apply([p])
        self.assertEqual(errors, [])
        self.assertEqual(applied, [])
        self.assertTrue(any("not applied automatically" in why for _, why in skipped),
                        skipped)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("NDSS", text)
        self.assertEqual(text, HUMAN_FILE)                # nothing touched at all

    def test_trailing_human_comment_survives_an_upsert(self):
        # A comment after the last entry is file epilogue, not part of that
        # entry. Kept in the chunk body it round-trips but disappears the moment
        # the entry is upserted, because the body is regenerated from the record.
        self.path.write_text(HUMAN_FILE + "\n# TODO(alice): keep this reminder.\n",
                             encoding="utf-8")
        self.assertIsNone(A.assert_round_trip(self.path.read_text(encoding="utf-8")))
        self.run_apply([proposal(fields={"deadline": claim("2026-02-17 23:59")})])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("TODO(alice): keep this reminder.", text)
        self.assertIn('deadline: "2026-02-17 23:59"', text)

    def test_result_still_round_trips_and_keeps_citations_adjacent(self):
        self.run_apply([proposal(fields={"deadline": claim("2026-02-17 23:59")})])
        text = self.path.read_text(encoding="utf-8")
        self.assertIsNone(A.assert_round_trip(text))
        # audit_lint's rule: a contiguous '#' run citing a URL immediately above
        lines = text.split("\n")
        for i, l in enumerate(lines):
            if l.startswith("- title:"):
                run, j = [], i
                while j - 1 >= 0 and lines[j - 1].startswith("#"):
                    j -= 1
                    run.append(lines[j])
                blob = "\n".join(run)
                self.assertIn("Verified", blob)
                self.assertRegex(blob, r"https?://")


class Coverage(unittest.TestCase):
    """A run that examined 3 of 30 records must not look like one that examined
    all 30 and found nothing. The first live run wrote no file at all and went
    green, which is the failure this accounting exists to make visible."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.wl = self.tmp / "watchlist.json"
        self.wl.write_text(json.dumps([
            {"title": "DIMVA", "year": 2027, "reasons": ["tba-upcoming-cycle"]},
            {"title": "SAC", "year": 2027, "reasons": ["manual-override-active"]},
            {"title": "RAID", "year": 2027, "reasons": ["tba-upcoming-cycle"]},
        ]), encoding="utf-8")

    def test_proposals_and_unverifiable_both_count(self):
        doc = {"proposals": [{"title": "DIMVA", "year": 2027}],
               "unverifiable": [{"title": "SAC", "year": 2027}]}
        total, missing = A.coverage(doc, self.wl)
        self.assertEqual(total, 3)
        self.assertEqual(missing, [("RAID", 2027)])

    def test_a_fully_accounted_run_has_no_gaps(self):
        doc = {"proposals": [{"title": "DIMVA", "year": 2027},
                             {"title": "RAID", "year": 2027}],
               "unverifiable": [{"title": "SAC", "year": 2027}]}
        self.assertEqual(A.coverage(doc, self.wl)[1], [])

    def test_an_empty_audit_is_reported_as_fully_missing(self):
        total, missing = A.coverage({"proposals": [], "unverifiable": []}, self.wl)
        self.assertEqual((total, len(missing)), (3, 3))

    def test_absent_watchlist_is_not_an_error(self):
        self.assertIsNone(A.coverage({"proposals": []}, self.tmp / "nope.json"))


class Seeding(unittest.TestCase):
    """The auditor's compliance with "write the file" proved nondeterministic:
    one run produced a complete 30/30 file, the next produced nothing. Seeding
    makes the file's existence not the model's problem, and defaults it to the
    pessimistic claim so an idle run reports idleness."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.wl = self.tmp / "watchlist.json"
        self.wl.write_text(json.dumps([
            {"title": "DIMVA", "year": 2027, "reasons": ["tba-upcoming-cycle"]},
            {"title": "SAC", "year": 2027, "reasons": ["manual-override-active"]},
        ]), encoding="utf-8")
        self.out = self.tmp / "audit-proposals.json"

    def seed(self):
        A.seed_from_watchlist(self.wl, self.out, "2026-08-19")
        return json.loads(self.out.read_text(encoding="utf-8"))

    def test_seed_marks_every_record_not_checked(self):
        doc = self.seed()
        self.assertEqual(doc["proposals"], [])
        self.assertEqual(len(doc["unverifiable"]), 2)
        self.assertTrue(all(u["cause"] == "not_checked" for u in doc["unverifiable"]))

    def test_seed_defaults_are_pessimistic_not_optimistic(self):
        # Seeding no_change would make an idle run look like a clean audit.
        doc = self.seed()
        self.assertNotIn("no_change", json.dumps(doc))

    def test_untouched_seed_reports_nothing_examined(self):
        examined, total, causes = A.audit_effort(self.seed())
        self.assertEqual((examined, total), (0, 2))
        self.assertEqual(causes["not_checked"], 2)

    def test_seed_covers_the_whole_watchlist(self):
        self.assertEqual(A.coverage(self.seed(), self.wl)[1], [])

    def test_examined_counts_records_moved_out_of_not_checked(self):
        doc = self.seed()
        doc["proposals"] = [{"title": "DIMVA", "year": 2027, "action": "no_change"}]
        doc["unverifiable"] = [{"title": "SAC", "year": 2027,
                                "cause": "no_official_page"}]
        examined, total, _ = A.audit_effort(doc)
        self.assertEqual((examined, total), (2, 2))

    def test_a_real_cause_counts_as_examined(self):
        doc = self.seed()
        doc["unverifiable"][0]["cause"] = "fetch_blocked"
        examined, _, _ = A.audit_effort(doc)
        self.assertEqual(examined, 1)


class Validation(unittest.TestCase):
    def setUp(self):
        self.targets = {t["key"]: t for t in U.load_config()}

    def check(self, p):
        errors = []
        ok = A.validate_proposal(p, self.targets, errors)
        return ok, errors

    def test_alias_title_is_rejected(self):
        ok, errors = self.check(proposal(title="Euro S&P", year=2026,
                                         fields={"place": claim("Lisbon")}))
        self.assertFalse(ok)
        self.assertIn("canonical key", errors[0])

    def test_year_outside_window_is_rejected(self):
        ok, errors = self.check(proposal(year=U.TO_YEAR + 1,
                                         fields={"place": claim("Lisbon")}))
        self.assertFalse(ok)
        self.assertIn("never rendered", errors[0])

    def test_non_overridable_field_is_rejected(self):
        ok, errors = self.check(proposal(fields={"tier": claim("T1")}))
        self.assertFalse(ok)
        self.assertIn("not overridable", errors[0])

    def test_timezone_deletion_is_refused(self):
        ok, errors = self.check(proposal(fields={"timezone": {
            "value": None, "absence_scope_quote": "Important Dates: ..."}}))
        self.assertFalse(ok)
        self.assertIn("LATER than the truth", errors[0])

    def test_field_deletion_needs_an_absence_scope_quote(self):
        ok, errors = self.check(proposal(fields={"abstract_deadline": {"value": None}}))
        self.assertFalse(ok)
        self.assertIn("absence_scope_quote", errors[0])

    def test_field_deletion_with_scope_quote_is_accepted(self):
        ok, _ = self.check(proposal(fields={"abstract_deadline": {
            "value": None,
            "absence_scope_quote": "Important Dates: Paper submission 6 August 2025"}}))
        self.assertTrue(ok)

    def test_malformed_deadline_is_rejected(self):
        ok, errors = self.check(proposal(fields={"deadline": claim("March 5, 2027")}))
        self.assertFalse(ok)
        self.assertIn("YYYY-MM-DD HH:MM", errors[0])

    def test_evidence_is_required(self):
        ok, errors = self.check(proposal(fields={"deadline": {"value": "2026-02-17 23:59"}}))
        self.assertFalse(ok)
        self.assertIn("no evidence", errors[0])

    def test_trivial_quote_is_rejected(self):
        ok, errors = self.check(proposal(
            fields={"deadline": claim("2026-02-17 23:59", quote="Feb")}))
        self.assertFalse(ok)
        self.assertIn("trivial quote", errors[0])

    def test_multiline_note_is_rejected(self):
        ok, errors = self.check(proposal(fields={"note": claim("a\nb")}))
        self.assertFalse(ok)
        self.assertIn("single line", errors[0])

    def test_mismatched_id_is_rejected(self):
        p = proposal(fields={"place": claim("Lisbon")})
        p["id"] = "upsert_manual:EuroSec:9999"
        ok, errors = self.check(p)
        self.assertFalse(ok)
        self.assertIn("id must be", errors[0])

    def test_delete_manual_needs_its_ground(self):
        ok, errors = self.check(proposal(action="delete_manual", title="NDSS", year=2026))
        self.assertFalse(ok)
        self.assertIn("obsolete_because", errors[0])

    def test_note_that_would_fabricate_a_deadline_is_rejected(self):
        # deadline-tracker.js:131 turns a note matching this into a rendered
        # abstract deadline at paper-7d - a route from unverifiable prose to a
        # deadline that appears on no page anywhere.
        ok, errors = self.check(proposal(fields={"note": claim(
            "Abstracts are due 1 week before the paper deadline.",
            quote="Abstracts are due one week before the paper deadline.")}))
        self.assertFalse(ok)
        self.assertIn("fabricate", errors[0])

    def test_ordinary_note_still_allowed(self):
        ok, errors = self.check(proposal(fields={"note": claim(
            "Deadline extended from February 3 to February 10, 2026.",
            quote="The submission deadline has been extended to February 10.")}))
        self.assertTrue(ok, errors)

    def test_start_and_end_are_rejected(self):
        for f in ("start", "end"):
            ok, errors = self.check(proposal(fields={f: claim(
                "2027-06-29", quote="The event runs 29 June to 3 July 2027.")}))
            self.assertFalse(ok, f)
            self.assertIn("derived from `date`", errors[-1])

    def test_create_record_needs_a_concrete_deadline(self):
        ok, errors = self.check(proposal(
            action="create_record", title="BAR", year=2027,
            fields={"place": claim("Vienna, Austria",
                                   quote="The workshop is held in Vienna, Austria.")}))
        self.assertFalse(ok)
        self.assertIn("concrete deadline", errors[0])

    def test_create_record_with_a_deadline_passes(self):
        ok, errors = self.check(proposal(
            action="create_record", title="BAR", year=2027,
            fields={"deadline": claim("2027-01-15 23:59",
                                      quote="Paper submission deadline: January 15, 2027")}))
        self.assertTrue(ok, errors)

    def test_valid_proposal_passes(self):
        ok, errors = self.check(proposal(fields={"deadline": claim("2026-02-17 23:59")}))
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
