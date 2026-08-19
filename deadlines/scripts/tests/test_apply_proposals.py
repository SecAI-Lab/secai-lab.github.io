#!/usr/bin/env python3
"""Tests for apply_proposals.py.

Run: python3 deadlines/scripts/tests/test_apply_proposals.py

The highest-value tests here are the round-trip and idempotence ones. manual.yml
is jointly owned by humans and this program, so the property that actually
matters is that a machine write never disturbs a hand-written entry - and that
running twice changes nothing the second time.
"""

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

    def test_delete_manual_removes_the_chunk(self):
        p = proposal(action="delete_manual", title="NDSS", year=2026,
                     obsolete_because="upstream_agrees")
        applied, _, errors = self.run_apply([p])
        self.assertEqual(errors, [])
        self.assertEqual(len(applied), 1)
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("NDSS", text)
        self.assertIn("EuroSec", text)                    # neighbour intact
        self.assertIsNone(A.assert_round_trip(text))

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

    def test_valid_proposal_passes(self):
        ok, errors = self.check(proposal(fields={"deadline": claim("2026-02-17 23:59")}))
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
