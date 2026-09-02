#!/usr/bin/env python3
"""Tests for apply_proposals.py.

Run: python3 deadlines/scripts/tests/test_apply_proposals.py

The highest-value tests here are the round-trip and idempotence ones. manual.yml
is pipeline-owned but contains legacy curated entries, so the property that
actually matters is that a machine write never disturbs an existing entry - and
that running twice changes nothing the second time.
"""

from contextlib import redirect_stdout
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class CurrentValueMatching(unittest.TestCase):
    def test_canonical_deadline_and_timezone_match(self):
        fields = {
            "deadline": claim(["2026-02-10 23:59"]),
            "timezone": claim("AoE", "All deadlines are anywhere on Earth (AoE)."),
        }
        current = {"deadline": "2026-02-10 23:59:59", "timezone": "UTC-12"}
        self.assertTrue(A.fields_match_current(fields, current))

    def test_changed_field_does_not_match(self):
        self.assertFalse(A.fields_match_current(
            {"deadline": claim("2026-02-17 23:59")},
            {"deadline": "2026-02-10 23:59"}))

    def test_absent_field_matches_a_redundant_deletion(self):
        self.assertTrue(A.fields_match_current(
            {"abstract_deadline": {"value": None}},
            {"deadline": "2026-02-10 23:59"}))

    def test_manual_only_cycles_are_effective_for_risk_decisions(self):
        manual = {("BAR", 2027): {
            "title": "BAR", "year": 2027,
            "deadline": ["2027-03-15 23:59", "2027-09-15 23:59"],
            "timezone": "AoE",
        }}
        current = A.effective_current_records({}, manual)[("BAR", 2027)]
        candidate = proposal(title="BAR", year=2027, fields={
            "deadline": claim("2027-09-15 23:59")
        })
        action, why = A.risk_policy.decide("VERIFIED", candidate, current)
        self.assertEqual(action, "hold")
        self.assertIn("cycle", why)


class FieldLevelVerdicts(unittest.TestCase):
    def verdict(self, statuses, top="rejected"):
        return {"status": top, "detail": {"fields": {
            name: {"status": status, "reason": "fixture"}
            for name, status in statuses.items()
        }}}

    def test_bad_place_does_not_discard_verified_deadline(self):
        p = proposal(fields={"deadline": claim("2026-02-17 23:59"),
                             "place": claim("Lisbon, Portugal")})
        accepted, pending = A.split_verified_fields(
            p, self.verdict({"deadline": "VERIFIED", "place": "UNCONFIRMED"}))
        self.assertEqual(set(accepted["fields"]), {"deadline"})
        self.assertEqual(set(pending["fields"]), {"place"})

    def test_deadline_and_timezone_are_atomic(self):
        p = proposal(fields={"deadline": claim("2026-02-17 23:59"),
                             "timezone": claim("UTC+9")})
        accepted, pending = A.split_verified_fields(
            p, self.verdict({"deadline": "VERIFIED", "timezone": "UNCONFIRMED"}))
        self.assertIsNone(accepted)
        self.assertEqual(set(pending["fields"]), {"deadline", "timezone"})

    def test_independent_metadata_can_apply_while_deadline_group_waits(self):
        p = proposal(fields={"deadline": claim("2026-02-17 23:59"),
                             "timezone": claim("UTC+9"),
                             "date": claim("April 1-3, 2027")})
        accepted, pending = A.split_verified_fields(
            p, self.verdict({"deadline": "VERIFIED", "timezone": "UNCONFIRMED",
                             "date": "VERIFIED"}))
        self.assertEqual(set(accepted["fields"]), {"date"})
        self.assertEqual(set(pending["fields"]), {"deadline", "timezone"})

    def test_top_level_accepted_never_carries_an_unchecked_field(self):
        p = proposal(fields={"deadline": claim("2026-02-17 23:59"),
                             "note": claim("Uncheckable free-form text")})
        accepted, pending = A.split_verified_fields(
            p, self.verdict({"deadline": "VERIFIED", "note": "UNCHECKED"},
                            top="accepted"))
        self.assertEqual(set(accepted["fields"]), {"deadline"})
        self.assertEqual(set(pending["fields"]), {"note"})

    def test_deadline_abstract_and_timezone_are_one_atomic_group(self):
        p = proposal(fields={
            "deadline": claim("2026-02-17 23:59"),
            "abstract_deadline": claim("2026-02-10 23:59"),
            "timezone": claim("UTC+9"),
            "place": claim("Lisbon, Portugal"),
        })
        accepted, pending = A.split_verified_fields(p, self.verdict({
            "deadline": "VERIFIED", "abstract_deadline": "VERIFIED",
            "timezone": "UNCHECKED", "place": "VERIFIED",
        }, top="accepted"))
        self.assertEqual(set(accepted["fields"]), {"place"})
        self.assertEqual(set(pending["fields"]),
                         {"deadline", "abstract_deadline", "timezone"})

    def test_scheduled_full_audit_is_a_known_watchlist_reason(self):
        self.assertIn("scheduled-full-audit", A.WATCHLIST_REASONS)
        self.assertIn("audit-deferred", A.WATCHLIST_REASONS)

    def test_change_budget_makes_stable_progress_and_defers_the_tail(self):
        proposals = [proposal(title="EuroSec", year=2026 + i) for i in range(4)]
        accepted, deferred = A.bound_autonomous_changes(proposals, 2)
        self.assertEqual(accepted, proposals[:2])
        self.assertEqual([item for item, _ in deferred], proposals[2:])
        self.assertTrue(all("later audit" in reason for _, reason in deferred))

    def test_outcome_accounting_separates_proposals_from_field_groups(self):
        first = proposal(title="EuroSec", year=2026,
                         fields={"date": claim("April 1-3, 2027")})
        second = proposal(title="DIMVA", year=2026,
                          fields={"place": claim("Paris, France")})
        pending = dict(first)
        pending["fields"] = {"place": claim("Lisbon, Portugal")}
        accounting = A.outcome_accounting(
            {"proposals": [first, second]},
            applied=[(first["id"], "changed date")],
            skipped=[], held=[(pending, "citation failed")])

        self.assertEqual(accounting["proposals"], 2)
        self.assertEqual(accounting["field_groups"], 2)
        self.assertEqual(accounting["split_proposals"], 1)
        self.assertEqual(accounting["unaccounted"], [second["id"]])
        self.assertEqual(accounting["unexpected"], [])

    def test_scope_accounting_accepts_an_exact_disjoint_partition(self):
        p = proposal(fields={
            "date": claim("April 1-3, 2027"),
            "place": claim("Lisbon, Portugal"),
        })
        pending = dict(p)
        pending["fields"] = {"place": p["fields"]["place"]}
        accounting = A.outcome_accounting(
            {"proposals": [p]}, applied=[(p["id"], "changed date")],
            skipped=[], held=[(pending, "weak place quote")],
            scope_rows=[
                ("applied", p["id"], {"date"}),
                ("deferred", p["id"], {"place"}),
            ])
        self.assertEqual(accounting["scope_errors"], [])

    def test_scope_accounting_detects_a_missing_field_fragment(self):
        p = proposal(fields={
            "date": claim("April 1-3, 2027"),
            "place": claim("Lisbon, Portugal"),
        })
        accounting = A.outcome_accounting(
            {"proposals": [p]}, applied=[(p["id"], "changed date")],
            skipped=[], held=[],
            scope_rows=[("applied", p["id"], {"date"})])
        self.assertTrue(any("unaccounted field(s): place" in error
                            for error in accounting["scope_errors"]), accounting)

    def test_scope_accounting_detects_duplicate_fragments(self):
        p = proposal(fields={"date": claim("April 1-3, 2027")})
        held = [(p, "first"), (p, "duplicate")]
        accounting = A.outcome_accounting(
            {"proposals": [p]}, applied=[], skipped=[], held=held,
            scope_rows=[
                ("deferred", p["id"], {"date"}),
                ("deferred", p["id"], {"date"}),
            ])
        self.assertTrue(any("duplicate field fragment" in error
                            for error in accounting["scope_errors"]), accounting)

    def test_scope_accounting_detects_overlapping_fragments(self):
        p = proposal(fields={
            "date": claim("April 1-3, 2027"),
            "place": claim("Lisbon, Portugal"),
        })
        pending = dict(p)
        pending["fields"] = {"place": p["fields"]["place"]}
        accounting = A.outcome_accounting(
            {"proposals": [p]}, applied=[(p["id"], "changed both")],
            skipped=[], held=[(pending, "duplicate place handling")],
            scope_rows=[
                ("applied", p["id"], {"date", "place"}),
                ("deferred", p["id"], {"place"}),
            ])
        self.assertTrue(any("overlapping outcome field(s): place" in error
                            for error in accounting["scope_errors"]), accounting)


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
        self.assertEqual(mf.chunks[-1].record()["timezone"], "AoE")

    def test_main_applies_only_verified_fields_even_when_top_gate_is_accepted(self):
        proposals_path = self.tmp / "audit-proposals.json"
        verdicts_path = self.tmp / "audit-verdicts.json"
        report_path = self.tmp / "audit-summary.md"
        p = proposal(fields={
            "place": claim("Lisbon, Portugal", "Conference venue: Lisbon, Portugal"),
            "note": claim("Unchecked text must never reach manual.yml"),
        })
        proposals_path.write_text(json.dumps({
            "audit_date": "2026-08-19", "proposals": [p], "unverifiable": []
        }), encoding="utf-8")
        verdicts_path.write_text(json.dumps({"verdicts": [{
            "id": p["id"], "status": "accepted", "gate": "VERIFIED",
            "detail": {"status": "VERIFIED", "source_trust": "trusted", "fields": {
                "place": {"status": "VERIFIED"},
                "note": {"status": "UNCHECKED", "reason": "no surface form"},
            }},
        }]}), encoding="utf-8")
        existing = {(2026, "system"): {"items": [{"data": {
            "title": "EuroSec", "year": 2026,
            "deadline": "2026-02-10 23:59", "timezone": "AoE",
            "place": "Vienna, Austria",
        }}]}}
        argv = ["apply_proposals.py", "--proposals", str(proposals_path),
                "--verdicts", str(verdicts_path), "--report", str(report_path)]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(U, "load_existing", return_value=existing):
            code = A.main()

        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn('place: "Lisbon, Portugal"', text)
        self.assertNotIn("Unchecked text must never reach manual.yml", text)
        self.assertIn("note", report_path.read_text(encoding="utf-8"))

    def test_partial_no_change_reports_proposals_and_field_groups_truthfully(self):
        proposals_path = self.tmp / "partial-proposals.json"
        verdicts_path = self.tmp / "partial-verdicts.json"
        report_path = self.tmp / "partial-summary.md"
        p = proposal(action="no_change", fields={
            "place": claim("Vienna, Austria", "Conference venue: Vienna, Austria"),
            "date": claim("April 1-3, 2027", "Conference dates: April 1-3, 2027"),
        })
        proposals_path.write_text(json.dumps({
            "audit_date": "2026-08-19", "proposals": [p], "unverifiable": []
        }), encoding="utf-8")
        verdicts_path.write_text(json.dumps({"verdicts": [{
            "id": p["id"], "status": "rejected", "gate": "UNCONFIRMED",
            "detail": {"status": "UNCONFIRMED", "source_trust": "trusted", "fields": {
                "place": {"status": "VERIFIED"},
                "date": {"status": "UNCONFIRMED", "reason": "weak quote"},
            }},
        }]}), encoding="utf-8")
        existing = {(2026, "system"): {"items": [{"data": {
            "title": "EuroSec", "year": 2026,
            "deadline": "2026-02-10 23:59", "timezone": "AoE",
            "place": "Vienna, Austria",
        }}]}}
        argv = ["apply_proposals.py", "--proposals", str(proposals_path),
                "--verdicts", str(verdicts_path), "--report", str(report_path)]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(U, "load_existing", return_value=existing), \
                redirect_stdout(output):
            code = A.main()

        self.assertEqual(code, 0)
        rendered = output.getvalue()
        self.assertIn("Proposal accounting: 1 proposal record(s); 1 split by field; "
                      "2 field-group outcomes", rendered)
        self.assertIn("Field-group outcomes: 0 applied, 1 deferred, "
                      "1 confirmed/no-op", rendered)
        self.assertIn("Apply/schema errors: 0", rendered)
        self.assertIn("confirmed/no-op  no_change:EuroSec:2026: [fields: place]",
                      rendered)
        self.assertIn("deferred no_change:EuroSec:2026 [fields: date]", rendered)
        self.assertIn("deferred fields kept unchanged", rendered)
        self.assertNotIn("existing data kept", rendered)

        report = report_path.read_text(encoding="utf-8")
        self.assertIn("**Proposal accounting:** 1 proposal record(s); 1 split by field; "
                      "2 field-group outcomes.", report)
        self.assertIn("**Deferred field groups (1)**", report)
        self.assertIn("**Confirmed/no-op field groups (1)**", report)
        self.assertIn("fields: date", report)
        self.assertIn("[fields: place]", report)

    def test_unaccounted_proposal_refuses_before_writing(self):
        proposals_path = self.tmp / "unaccounted-proposals.json"
        verdicts_path = self.tmp / "unaccounted-verdicts.json"
        report_path = self.tmp / "unaccounted-summary.md"
        p = proposal(fields={
            "place": claim("Lisbon, Portugal", "Conference venue: Lisbon, Portugal")
        })
        proposals_path.write_text(json.dumps({
            "audit_date": "2026-08-19", "proposals": [p], "unverifiable": []
        }), encoding="utf-8")
        verdicts_path.write_text(json.dumps({"verdicts": [{
            "id": p["id"], "status": "accepted", "gate": "VERIFIED",
            "detail": {"status": "VERIFIED", "source_trust": "trusted", "fields": {
                "place": {"status": "VERIFIED"},
            }},
        }]}), encoding="utf-8")
        existing = {(2026, "system"): {"items": [{"data": {
            "title": "EuroSec", "year": 2026,
            "deadline": "2026-02-10 23:59", "timezone": "AoE",
            "place": "Vienna, Austria",
        }}]}}
        argv = ["apply_proposals.py", "--proposals", str(proposals_path),
                "--verdicts", str(verdicts_path), "--report", str(report_path)]
        before = self.path.read_bytes()
        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(U, "load_existing", return_value=existing), \
                mock.patch.object(A, "apply_proposals", return_value=([], [])), \
                redirect_stdout(output):
            code = A.main()

        self.assertEqual(code, 1)
        self.assertIn("unaccounted input proposal(s): " + p["id"],
                      output.getvalue())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(report_path.exists())

    def test_mixed_valid_and_invalid_document_is_rejected_before_mutation(self):
        proposals_path = self.tmp / "mixed-proposals.json"
        report_path = self.tmp / "mixed-summary.md"
        good = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        bad = proposal(title="DIMVA", fields={"deadline": claim("2027-02-29 23:59")})
        proposals_path.write_text(json.dumps({
            "audit_date": "2026-08-19", "proposals": [good, bad],
            "unverifiable": [],
        }), encoding="utf-8")
        argv = ["apply_proposals.py", "--proposals", str(proposals_path),
                "--ungated", "--report", str(report_path)]
        before = self.path.read_bytes()
        with mock.patch.object(sys, "argv", argv):
            code = A.main()
        self.assertEqual(code, 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(report_path.exists())

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
        for i, line in enumerate(lines):
            if line.startswith("- title:"):
                run, j = [], i
                while j - 1 >= 0 and lines[j - 1].startswith("#"):
                    j -= 1
                    run.append(lines[j])
                blob = "\n".join(run)
                self.assertIn("Verified", blob)
                self.assertRegex(blob, r"https?://")


class PersistentPromotion(unittest.TestCase):
    """Risky facts need two independent weekly observations, never a person."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.manual = self.tmp / "manual.yml"
        self.manual.write_text(HUMAN_FILE, encoding="utf-8")
        self.state = self.tmp / "audit-state.json"
        self.proposals = self.tmp / "audit-proposals.json"
        self.verdicts = self.tmp / "audit-verdicts.json"
        self.watchlist = self.tmp / "watchlist.json"
        self.report = self.tmp / "audit-summary.md"
        self.saved = (A.MANUAL_PATH, A.AUDIT_STATE_PATH, U.MANUAL_PATH)
        A.MANUAL_PATH = U.MANUAL_PATH = self.manual
        A.AUDIT_STATE_PATH = self.state

    def tearDown(self):
        A.MANUAL_PATH, A.AUDIT_STATE_PATH, U.MANUAL_PATH = self.saved

    def run_main(self, p, audit_date, current, marker=None, statuses=None,
                 source_trust="trusted", source_basis=None):
        item = {
            "title": p["title"], "year": p["year"], "record": current,
            "reasons": ["audit-deferred"],
        }
        if marker is not None:
            item["upstream_agreement"] = marker
        self.watchlist.write_text(json.dumps([item]), encoding="utf-8")
        self.proposals.write_text(json.dumps({
            "audit_date": audit_date, "watchlist_size": 1,
            "proposals": [p], "unverifiable": [],
        }), encoding="utf-8")
        if p["action"] == "delete_manual":
            verdict = {"id": p["id"], "status": "accepted", "gate": "VERIFIED"}
        else:
            statuses = statuses or {name: "VERIFIED" for name in p["fields"]}
            detail = {
                "status": "VERIFIED", "source_trust": source_trust,
                "fields": {
                    name: {"status": statuses.get(name, "UNCONFIRMED")}
                    for name in p["fields"]
                },
            }
            if source_basis is not None:
                detail["source_trust_basis"] = source_basis
            verdict = {
                "id": p["id"], "status": "accepted", "gate": "VERIFIED",
                "detail": detail,
            }
        self.verdicts.write_text(
            json.dumps({"verdicts": [verdict]}), encoding="utf-8")
        argv = [
            "apply_proposals.py", "--proposals", str(self.proposals),
            "--verdicts", str(self.verdicts), "--watchlist", str(self.watchlist),
            "--require-complete", "--report", str(self.report),
        ]
        existing = {(2026, "system"): {"items": [{"data": {
            "title": p["title"], "year": p["year"], **current,
        }}]}}
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(U, "load_existing", return_value=existing):
            return A.main()

    def test_large_shift_is_deferred_then_applied_on_second_week(self):
        p = proposal(fields={
            "deadline": claim("2026-04-20 23:59"),
            "timezone": claim("AoE", "All deadlines are anywhere on Earth (AoE)."),
        })
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE"}

        self.assertEqual(self.run_main(p, "2026-08-31", current), 0)
        self.assertIn('deadline: "2026-02-10 23:59"',
                      self.manual.read_text(encoding="utf-8"))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        container = next(iter(saved["corroboration"].values()))
        self.assertEqual(next(iter(container["claims"].values()))["verified_runs"], 1)

        self.assertEqual(self.run_main(p, "2026-09-07", current), 0)
        self.assertIn('deadline: "2026-04-20 23:59"',
                      self.manual.read_text(encoding="utf-8"))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["corroboration"], {})
        self.assertEqual(saved["retry"], {})

    def test_machine_deferral_queues_retry_without_resetting_corroboration(self):
        pending = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        state = A.AS.empty_state()
        _, ref = A.AS.observe_verified_claim(
            state, pending, {"place": "Lisbon, Portugal"}, "2026-08-24")
        A.AS.save(state, self.state)
        self.watchlist.write_text(json.dumps([{
            "title": "EuroSec", "year": 2026, "record": {},
            "reasons": ["audit-deferred"],
        }]), encoding="utf-8")
        self.proposals.write_text(json.dumps({
            "audit_date": "2026-08-31", "watchlist_size": 1,
            "proposals": [], "unverifiable": [],
            "machine_deferred": [{
                "title": "EuroSec", "year": 2026,
                "reason": "audit-incomplete-after-retry",
            }],
        }), encoding="utf-8")
        self.verdicts.write_text(json.dumps({"verdicts": []}), encoding="utf-8")
        argv = [
            "apply_proposals.py", "--proposals", str(self.proposals),
            "--verdicts", str(self.verdicts), "--watchlist", str(self.watchlist),
            "--require-complete", "--allow-machine-deferred",
            "--report", str(self.report),
        ]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(U, "load_existing", return_value={}):
            self.assertEqual(A.main(), 0)

        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn(ref.scope_id, saved["corroboration"][ref.identity]["claims"])
        self.assertTrue(saved["retry"][ref.identity]["whole_record"])
        self.assertIn("Machine-deferred (1)", self.report.read_text(encoding="utf-8"))

        # A later substantive result removes the whole-record scheduling flag
        # and resolves the verified scope normally; it cannot persist forever.
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        confirmed = proposal(action="no_change", fields={"place": claim(
            "Vienna, Austria", "Conference venue: Vienna, Austria")})
        self.assertEqual(self.run_main(
            confirmed, "2026-09-07", current), 0)
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertNotIn(ref.identity, saved["retry"])
        self.assertNotIn(ref.identity, saved["corroboration"])

    def test_rejected_followup_keeps_the_whole_record_completion_retry(self):
        state = A.AS.empty_state()
        A.AS.mark_retry(
            state, "EuroSec", 2026, "2026-08-31", "unverifiable")
        A.AS.save(state, self.state)
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        rejected = proposal(action="no_change", fields={"place": claim(
            "Vienna, Austria", "Conference venue: Vienna, Austria")})
        self.watchlist.write_text(json.dumps([{
            "title": "EuroSec", "year": 2026, "record": current,
            "reasons": ["audit-deferred"],
        }]), encoding="utf-8")
        self.proposals.write_text(json.dumps({
            "audit_date": "2026-09-07", "watchlist_size": 1,
            "proposals": [rejected], "unverifiable": [],
        }), encoding="utf-8")
        self.verdicts.write_text(json.dumps({"verdicts": [{
            "id": rejected["id"], "status": "rejected",
            "gate": "REJECTED_SOURCE",
            "detail": {"status": "REJECTED_SOURCE", "fields": {}},
        }]}), encoding="utf-8")
        argv = [
            "apply_proposals.py", "--proposals", str(self.proposals),
            "--verdicts", str(self.verdicts), "--watchlist", str(self.watchlist),
            "--require-complete", "--report", str(self.report),
        ]
        existing = {(2026, "system"): {"items": [{"data": {
            "title": "EuroSec", "year": 2026, **current,
        }}]}}
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(U, "load_existing", return_value=existing):
            self.assertEqual(A.main(), 0)

        saved = json.loads(self.state.read_text(encoding="utf-8"))
        retry = saved["retry"][A.AS.identity_key("EuroSec", 2026)]
        self.assertTrue(retry["whole_record"])
        self.assertEqual(retry["fields"], ["place"])

    def test_provisional_host_mutation_needs_two_provenance_bound_weeks(self):
        p = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        basis = "sha256:" + "a" * 64

        self.assertEqual(self.run_main(
            p, "2026-08-31", current, source_trust="provisional",
            source_basis=basis), 0)
        self.assertIn('place: "Vienna, Austria"',
                      self.manual.read_text(encoding="utf-8"))
        state_text = self.state.read_text(encoding="utf-8")
        self.assertNotIn(p["source_url"], state_text)
        self.assertNotIn(basis, state_text)

        self.assertEqual(self.run_main(
            p, "2026-09-07", current, source_trust="provisional",
            source_basis=basis), 0)
        self.assertIn('place: "Lisbon, Portugal"',
                      self.manual.read_text(encoding="utf-8"))

    def test_changed_provisional_provenance_resets_the_two_run_streak(self):
        p = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        first = "sha256:" + "a" * 64
        second = "sha256:" + "b" * 64

        self.assertEqual(self.run_main(
            p, "2026-08-31", current, source_trust="provisional",
            source_basis=first), 0)
        self.assertEqual(self.run_main(
            p, "2026-09-07", current, source_trust="provisional",
            source_basis=second), 0)
        self.assertIn('place: "Vienna, Austria"',
                      self.manual.read_text(encoding="utf-8"))
        self.assertEqual(self.run_main(
            p, "2026-09-14", current, source_trust="provisional",
            source_basis=second), 0)
        self.assertIn('place: "Lisbon, Portugal"',
                      self.manual.read_text(encoding="utf-8"))

    def test_provisional_noop_confirms_without_clearing_retry_state(self):
        p = proposal(action="no_change", fields={"place": claim(
            "Vienna, Austria", "Conference venue: Vienna, Austria")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        basis = "sha256:" + "a" * 64
        self.assertEqual(self.run_main(
            p, "2026-08-31", current, source_trust="provisional",
            source_basis=basis), 0)
        self.assertIn('place: "Vienna, Austria"',
                      self.manual.read_text(encoding="utf-8"))
        self.assertIn("provisional source confirms the rendered fields",
                      self.report.read_text(encoding="utf-8"))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["corroboration"], {})
        self.assertTrue(saved["retry"])

        self.assertEqual(self.run_main(
            p, "2026-09-07", current, source_trust="provisional",
            source_basis=basis), 0)
        self.assertIn("confirmed/no-op", self.report.read_text(encoding="utf-8"))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["corroboration"], {})
        self.assertTrue(saved["retry"])

    def test_provisional_noop_preserves_same_scope_pending_correction(self):
        pending = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        state = A.AS.empty_state()
        _, ref = A.AS.observe_verified_claim(
            state, pending, {"place": "Lisbon, Portugal"}, "2026-08-24")
        A.AS.mark_retry_fields(
            state, "EuroSec", 2026, "2026-08-24", "corroboration", {"place"})
        expected = state["corroboration"][ref.identity]["claims"][ref.scope_id][
            "fingerprint"]
        A.AS.save(state, self.state)

        confirm = proposal(action="no_change", fields={"place": claim(
            "Vienna, Austria", "Conference venue: Vienna, Austria")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        self.assertEqual(self.run_main(
            confirm, "2026-08-31", current, source_trust="provisional",
            source_basis="sha256:" + "a" * 64), 0)

        saved = json.loads(self.state.read_text(encoding="utf-8"))
        claim_state = saved["corroboration"][ref.identity]["claims"][ref.scope_id]
        self.assertEqual(claim_state["fingerprint"], expected)
        self.assertEqual(saved["retry"][ref.identity]["fields"], ["place"])

    def test_missing_source_trust_class_cannot_mutate(self):
        p = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        self.assertEqual(self.run_main(
            p, "2026-08-31", current, source_trust=None), 0)
        self.assertIn('place: "Vienna, Austria"',
                      self.manual.read_text(encoding="utf-8"))
        self.assertIn("no valid source-trust class",
                      self.report.read_text(encoding="utf-8"))

    def test_invalid_provisional_basis_never_accumulates_a_streak(self):
        p = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        for audit_date, bad_basis in (
                ("2026-08-31", None),
                ("2026-09-07", "sha256:" + "A" * 64)):
            self.assertEqual(self.run_main(
                p, audit_date, current, source_trust="provisional",
                source_basis=bad_basis), 0)
            saved = json.loads(self.state.read_text(encoding="utf-8"))
            self.assertEqual(saved["corroboration"], {})
            self.assertIn("no valid lowercase sha256 source-trust basis",
                          self.report.read_text(encoding="utf-8"))

        # The first valid observation must still be quarantined; invalid
        # attempts above cannot count toward the two-run streak.
        self.assertEqual(self.run_main(
            p, "2026-09-14", current, source_trust="provisional",
            source_basis="sha256:" + "b" * 64), 0)
        self.assertIn('place: "Vienna, Austria"',
                      self.manual.read_text(encoding="utf-8"))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(saved["corroboration"])

    def test_deadline_only_mutation_is_deferred_for_missing_timezone(self):
        p = proposal(fields={"deadline": claim("2026-02-17 23:59")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE"}

        self.assertEqual(self.run_main(p, "2026-08-31", current), 0)
        self.assertEqual(self.run_main(p, "2026-09-07", current), 0)
        self.assertIn('deadline: "2026-02-10 23:59"',
                      self.manual.read_text(encoding="utf-8"))
        self.assertIn("missing verified atomic context field(s): timezone",
                      self.report.read_text(encoding="utf-8"))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["corroboration"], {})
        key = A.AS.identity_key("EuroSec", 2026)
        self.assertEqual(saved["retry"][key]["fields"], ["deadline", "timezone"])

    def test_timezone_only_mutation_is_deferred_for_missing_deadline(self):
        p = proposal(fields={
            "timezone": claim("UTC+0", "All deadlines use UTC+0 timezone."),
        })
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE"}

        self.assertEqual(self.run_main(p, "2026-08-31", current), 0)
        self.assertIn("timezone: AoE", self.manual.read_text(encoding="utf-8"))
        self.assertIn("missing verified atomic context field(s): deadline",
                      self.report.read_text(encoding="utf-8"))

    def test_create_without_timezone_is_deferred(self):
        p = proposal(action="create_record", title="BAR", year=2027, fields={
            "deadline": claim(
                "2027-01-15 23:59",
                "Paper submission deadline: January 15, 2027"),
        })
        self.assertEqual(self.run_main(p, "2026-08-31", {}), 0)
        self.assertNotIn('title: "BAR"', self.manual.read_text(encoding="utf-8"))
        self.assertIn("missing verified atomic context field(s): timezone",
                      self.report.read_text(encoding="utf-8"))

    def test_complete_effective_deadline_group_can_mutate(self):
        p = proposal(fields={
            "deadline": claim("2026-02-17 23:59"),
            "abstract_deadline": claim(
                "2026-02-10 23:59", "Paper abstracts due: February 10, 2026"),
            "timezone": claim("AoE", "All deadlines are anywhere on Earth (AoE)."),
        })
        current = {
            "deadline": "2026-02-10 23:59",
            "abstract_deadline": "2026-02-03 23:59",
            "timezone": "AoE",
        }
        self.assertEqual(self.run_main(p, "2026-08-31", current), 0)
        text = self.manual.read_text(encoding="utf-8")
        self.assertIn('deadline: "2026-02-17 23:59"', text)
        self.assertIn('abstract_deadline: "2026-02-10 23:59"', text)

    def test_exact_deadline_only_upsert_remains_a_noop_confirmation(self):
        p = proposal(fields={"deadline": claim("2026-02-10 23:59")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE"}
        self.assertEqual(self.run_main(p, "2026-08-31", current), 0)
        self.assertIn("confirmed/no-op", self.report.read_text(encoding="utf-8"))

    def test_post_merge_validation_error_aborts_manual_and_state_transaction(self):
        p = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        before = self.manual.read_bytes()
        real_apply = A.apply_proposals

        def inject_late_error(*args, **kwargs):
            applied, skipped = real_apply(*args, **kwargs)
            args[5].append("simulated post-merge validation failure")
            return applied, skipped

        with mock.patch.object(A, "apply_proposals", side_effect=inject_late_error):
            self.assertEqual(self.run_main(p, "2026-08-31", current), 1)
        self.assertEqual(self.manual.read_bytes(), before)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.report.exists())

    def test_obsolete_override_needs_static_agreement_then_two_weeks(self):
        p = proposal(action="delete_manual", title="NDSS", year=2026,
                     obsolete_because="upstream_agrees")
        current = {"deadline": "2025-08-06 23:59", "abstract_deadline": None}
        marker = {"agrees": True, "all_fetches_healthy": True,
                  "sources": ["ccfddl", "secdl"],
                  "basis_digest": "sha256:" + "a" * 64}

        self.assertEqual(self.run_main(p, "2026-08-31", current, marker), 0)
        self.assertIn('title: "NDSS"', self.manual.read_text(encoding="utf-8"))
        self.assertEqual(self.run_main(p, "2026-09-07", current, marker), 0)
        self.assertNotIn('title: "NDSS"', self.manual.read_text(encoding="utf-8"))

    def test_model_cannot_promote_delete_without_static_agreement(self):
        p = proposal(action="delete_manual", title="NDSS", year=2026,
                     obsolete_because="upstream_agrees")
        current = {"deadline": "2025-08-06 23:59", "abstract_deadline": None}
        marker = {"agrees": False, "all_fetches_healthy": True,
                  "sources": ["ccfddl", "secdl"]}
        self.assertEqual(self.run_main(p, "2026-08-31", current, marker), 0)
        self.assertEqual(self.run_main(p, "2026-09-07", current, marker), 0)
        self.assertIn('title: "NDSS"', self.manual.read_text(encoding="utf-8"))
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["corroboration"], {})

    def test_state_save_failure_restores_a_previously_absent_manual_file(self):
        self.manual.unlink()
        p = proposal(fields={"place": claim(
            "Lisbon, Portugal", "Conference venue: Lisbon, Portugal")})
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        with mock.patch.object(
                A.AS, "save", side_effect=A.AS.StateError("simulated write fault")):
            self.assertEqual(self.run_main(p, "2026-08-31", current), 1)
        self.assertFalse(self.manual.exists())

    def seed_deadline_claim(self, year, value, audit_date="2026-08-24"):
        state = A.AS.empty_state()
        p = proposal(title="EuroSec", year=year,
                     fields={"deadline": claim(value)})
        _, ref = A.AS.observe_verified_claim(
            state, p, {"deadline": value}, audit_date)
        A.AS.save(state, self.state)
        return ref, A.AS.proposal_fingerprint(p, {"deadline": value})

    def test_partial_current_finding_preserves_prior_year_deadline_work(self):
        year = U.TODAY.year - 1
        current = {"deadline": f"{year}-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        for action in ("no_change", "upsert_manual"):
            with self.subTest(action=action):
                self.state.unlink(missing_ok=True)
                ref, fingerprint = self.seed_deadline_claim(
                    year, f"{year}-04-20 23:59")
                p = proposal(action=action, title="EuroSec", year=year,
                             fields={"place": claim(
                                 "Vienna, Austria", "Conference venue: Vienna, Austria")})
                self.assertEqual(self.run_main(p, "2026-08-31", current), 0)

                saved = json.loads(self.state.read_text(encoding="utf-8"))
                claim_state = saved["corroboration"][ref.identity]["claims"][
                    "fields:deadline"]
                self.assertEqual(claim_state["fingerprint"], fingerprint)
                self.assertEqual(saved["retry"][ref.identity]["fields"], ["deadline"])

    def test_same_scope_no_change_resolves_old_deadline_claim(self):
        year = U.TODAY.year - 1
        ref, _ = self.seed_deadline_claim(year, f"{year}-04-20 23:59")
        current = {"deadline": f"{year}-02-10 23:59", "timezone": "AoE"}
        p = proposal(action="no_change", title="EuroSec", year=year,
                     fields={"deadline": claim(f"{year}-02-10 23:59")})
        self.assertEqual(self.run_main(p, "2026-08-31", current), 0)
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertNotIn(ref.identity, saved["corroboration"])
        self.assertNotIn(ref.identity, saved["retry"])

    def test_promoted_deadline_keeps_pending_place_scope_and_no_model_prose(self):
        secret_value = "UNVERIFIED_SECRET_PROSE"
        secret_quote = "UNVERIFIED_SECRET_QUOTE_FROM_MODEL"
        secret_url = "https://unverified.invalid/SECRET_URL"
        secret_reason = "UNVERIFIED_SECRET_REASON"
        p = proposal(fields={
            "deadline": claim("2026-04-20 23:59"),
            "timezone": claim("AoE", "All deadlines are anywhere on Earth (AoE)."),
            "place": claim(secret_value, secret_quote),
        }, source_url=secret_url, reason=secret_reason)
        current = {"deadline": "2026-02-10 23:59", "timezone": "AoE",
                   "place": "Vienna, Austria"}
        statuses = {"deadline": "VERIFIED", "timezone": "VERIFIED",
                    "place": "UNCONFIRMED"}

        self.assertEqual(
            self.run_main(p, "2026-08-31", current, statuses=statuses), 0)
        first_state = self.state.read_text(encoding="utf-8")
        for secret in (secret_value, secret_quote, secret_url, secret_reason):
            self.assertNotIn(secret, first_state)

        self.assertEqual(
            self.run_main(p, "2026-09-07", current, statuses=statuses), 0)
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        key = A.AS.identity_key("EuroSec", 2026)
        self.assertEqual(saved["corroboration"], {})
        self.assertEqual(saved["retry"][key]["fields"], ["place"])
        self.assertIn('deadline: "2026-04-20 23:59"',
                      self.manual.read_text(encoding="utf-8"))


class GateRejectionIsDeferred(unittest.TestCase):
    """A gate rejection is autonomous telemetry, not a request for a person.

    The gate has a measured false-negative rate on live data - it wrongly
    refused SAC 2027's real deadline because the row also mentions SRC
    abstracts. Filing rejections as bare ids under "Rejected" destroys roughly
    one correct correction in ten and leaves a human nothing to act on.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def report_for(self, held):
        path = self.tmp / "report.md"
        A.write_report(path, applied=[], skipped=[], errors=[],
                       proposals={"proposals": [p for p, _ in held],
                                  "unverifiable": []},
                       gated=True, held=held)
        return path.read_text(encoding="utf-8")

    def test_deferred_proposal_carries_venue_values_source_and_quote(self):
        p = proposal(title="SAC", year=2027, fields={"deadline": claim(
            "2026-10-02 23:59",
            quote="October 2, 2026 (EST) Submission of regular papers")})
        p["source_url"] = "https://www.sigapp.org/sac/sac2027"
        body = self.report_for([(p, "rejected")])
        self.assertIn("Deferred field groups (1)", body)
        self.assertIn("SAC 2027", body)
        self.assertIn("2026-10-02 23:59", body)
        self.assertIn("https://www.sigapp.org/sac/sac2027", body)
        self.assertIn("October 2, 2026 (EST)", body)

    def test_the_scheduler_is_told_to_retry(self):
        p = proposal(fields={"deadline": claim("2026-02-17 23:59")})
        body = self.report_for([(p, "rejected")])
        self.assertIn("retry", body)

    def test_no_deferred_section_when_nothing_is_deferred(self):
        self.assertNotIn("Deferred field groups", self.report_for([]))


class Coverage(unittest.TestCase):
    """A run that examined 3 of 30 records must not look like one that examined
    all 30 and found nothing. The first live run wrote no file at all and went
    green, which is the failure this accounting exists to make visible."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.wl = self.tmp / "watchlist.json"
        reasons = {
            "DIMVA": "tba-upcoming-cycle",
            "SAC": "manual-override-active",
            "RAID": "tba-upcoming-cycle",
        }
        self.wl.write_text(json.dumps([
            {
                "title": title, "year": 2027, "reasons": [reason],
                "upstream_link_candidates": [{
                    "source": "ccfddl",
                    "link": f"https://official.example/{title}",
                }],
            }
            for title, reason in reasons.items()
        ]), encoding="utf-8")

    def test_proposals_and_unverifiable_both_count(self):
        doc = {"proposals": [{"title": "DIMVA", "year": 2027}],
               "unverifiable": [{"title": "SAC", "year": 2027}]}
        total, missing = A.coverage(doc, self.wl)
        self.assertEqual(total, 3)
        self.assertEqual(missing, [("RAID", 2027)])

    def test_machine_deferred_participates_in_exact_coverage_but_not_effort(self):
        doc = {
            "proposals": [{"title": "DIMVA", "year": 2027}],
            "unverifiable": [{"title": "SAC", "year": 2027,
                               "cause": "no_official_page"}],
            "machine_deferred": [{
                "title": "RAID", "year": 2027,
                "reason": "audit-incomplete-after-retry",
            }],
        }
        self.assertEqual(A.coverage(doc, self.wl)[1], [])
        self.assertEqual(A.exact_coverage(doc, self.wl), [])
        examined, total, causes = A.audit_effort(doc)
        self.assertEqual((examined, total), (2, 3))
        self.assertEqual(causes["machine_deferred"], 1)

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

    def test_exact_coverage_accepts_each_record_once(self):
        doc = {"proposals": [{"title": "DIMVA", "year": 2027},
                              {"title": "RAID", "year": 2027}],
               "unverifiable": [{"title": "SAC", "year": 2027,
                                  "cause": "no_official_page"}]}
        self.assertEqual(A.exact_coverage(doc, self.wl), [])

    def test_exact_coverage_rejects_duplicate_and_missing_records(self):
        doc = {"proposals": [{"title": "DIMVA", "year": 2027},
                              {"title": "DIMVA", "year": 2027}],
               "unverifiable": [{"title": "SAC", "year": 2027}]}
        problems = A.exact_coverage(doc, self.wl)
        self.assertTrue(any("appears 2 times" in p for p in problems), problems)
        self.assertTrue(any("missing RAID 2027" in p for p in problems), problems)

    def test_exact_coverage_rejects_unknown_records(self):
        doc = {"proposals": [{"title": "DIMVA", "year": 2027},
                              {"title": "RAID", "year": 2027}],
               "unverifiable": [{"title": "SAC", "year": 2027},
                                  {"title": "CCS", "year": 2027}]}
        self.assertTrue(any("unexpected CCS 2027" in p
                            for p in A.exact_coverage(doc, self.wl)))

    def test_all_unverifiable_first_pass_requests_one_retry(self):
        proposals = self.tmp / "all-unverifiable.json"
        proposals.write_text(json.dumps({
            "audit_date": "2026-08-31",
            "proposals": [],
            "unverifiable": [
                {"title": title, "year": 2027, "cause": "no_official_page",
                 "attempted": [f"https://official.example/{title}"]}
                for title in ("DIMVA", "SAC", "RAID")
            ],
        }), encoding="utf-8")
        argv = ["apply_proposals.py", "--proposals", str(proposals),
                "--validate-only", "--require-complete",
                "--require-some-proposal", "--watchlist", str(self.wl)]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 1)

        # The final validation deliberately omits --require-some-proposal, so
        # a second diligent pass that truly found no page can finish green.
        argv.remove("--require-some-proposal")
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 0)

    def test_validate_only_rejects_model_only_unverifiable_sources(self):
        proposals = self.tmp / "untrusted-unverifiable.json"
        proposals.write_text(json.dumps({
            "audit_date": "2026-08-31",
            "proposals": [],
            "unverifiable": [
                {"title": title, "year": 2027,
                 "cause": "no_official_page",
                 "attempted": [f"https://model-only.example/{title}"]}
                for title in ("DIMVA", "SAC", "RAID")
            ],
        }), encoding="utf-8")
        argv = ["apply_proposals.py", "--proposals", str(proposals),
                "--validate-only", "--require-complete",
                "--watchlist", str(self.wl)]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 1)

    def test_validate_only_refuses_oversized_attempt_list(self):
        proposals = self.tmp / "oversized-attempts.json"
        outcomes = []
        for title in ("DIMVA", "SAC", "RAID"):
            count = A.RA.MAX_ATTEMPTED_URLS + 1 if title == "DIMVA" else 1
            outcomes.append({
                "title": title,
                "year": 2027,
                "cause": "no_official_page",
                "attempted": [
                    f"https://official.example/{title}/route-{index}"
                    for index in range(count)
                ],
            })
        proposals.write_text(json.dumps({
            "audit_date": "2026-08-31",
            "proposals": [],
            "unverifiable": outcomes,
        }), encoding="utf-8")
        argv = ["apply_proposals.py", "--proposals", str(proposals),
                "--validate-only", "--require-complete",
                "--watchlist", str(self.wl)]

        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 1)

    def test_raw_unfinished_shard_is_allowed_only_by_explicit_stage_flag(self):
        proposals = self.tmp / "unfinished.json"
        proposals.write_text(json.dumps({
            "audit_date": "2026-08-31", "watchlist_size": 3,
            "proposals": [],
            "unverifiable": [
                {"title": title, "year": 2027, "cause": "not_checked",
                 "attempted": []}
                for title in ("DIMVA", "SAC", "RAID")
            ],
        }), encoding="utf-8")
        argv = ["apply_proposals.py", "--proposals", str(proposals),
                "--validate-only"]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 1)
        argv.append("--allow-unfinished")
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 0)

    def test_explicit_checkpoint_stage_rejects_a_missing_proposal_file(self):
        missing = self.tmp / "missing.json"
        argv = ["apply_proposals.py", "--proposals", str(missing),
                "--validate-only", "--allow-unfinished"]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 1)

    def test_all_machine_deferred_is_safe_degraded_and_never_examined(self):
        proposals = self.tmp / "machine-deferred.json"
        proposals.write_text(json.dumps({
            "audit_date": "2026-08-31", "watchlist_size": 3,
            "proposals": [], "unverifiable": [],
            "machine_deferred": [
                {"title": title, "year": 2027,
                 "reason": "source-recheck-requeued"}
                for title in ("DIMVA", "SAC", "RAID")
            ],
        }), encoding="utf-8")
        base = ["apply_proposals.py", "--proposals", str(proposals),
                "--validate-only", "--require-complete",
                "--watchlist", str(self.wl)]
        with mock.patch.object(sys, "argv", base):
            self.assertEqual(A.main(), 1)
        with mock.patch.object(
                sys, "argv", base + ["--allow-machine-deferred"]):
            self.assertEqual(A.main(), 0)

    def test_require_complete_blocks_raw_checkpoint_before_ungated_apply(self):
        proposals = self.tmp / "raw-production.json"
        proposals.write_text(json.dumps({
            "audit_date": "2026-08-31", "watchlist_size": 3,
            "proposals": [],
            "unverifiable": [
                {"title": title, "year": 2027, "cause": "not_checked",
                 "attempted": []}
                for title in ("DIMVA", "SAC", "RAID")
            ],
        }), encoding="utf-8")
        argv = ["apply_proposals.py", "--proposals", str(proposals),
                "--ungated", "--require-complete",
                "--watchlist", str(self.wl)]
        with mock.patch.object(sys, "argv", argv):
            self.assertEqual(A.main(), 1)


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

    def check_unverifiable(self, item):
        errors = []
        ok = A.validate_unverifiable([item], self.targets, errors)
        return ok, errors

    def test_unverifiable_outcome_needs_a_known_cause(self):
        ok, errors = self.check_unverifiable(
            {"title": "SAC", "year": 2027, "cause": "model_gave_up",
             "attempted": ["https://example.org/"]})
        self.assertFalse(ok)
        self.assertIn("unknown cause", errors[0])

    def test_concrete_unverifiable_outcome_needs_attempted_urls(self):
        ok, errors = self.check_unverifiable(
            {"title": "SAC", "year": 2027, "cause": "no_official_page",
             "attempted": []})
        self.assertFalse(ok)
        self.assertIn("requires attempted", errors[0])

    def test_bounded_no_page_outcome_passes(self):
        ok, errors = self.check_unverifiable(
            {"title": "SAC", "year": 2027, "cause": "no_official_page",
             "attempted": ["https://www.sigapp.org/sac/sac2027"]})
        self.assertTrue(ok, errors)

    def test_not_checked_is_valid_as_an_intermediate_checkpoint(self):
        ok, errors = self.check_unverifiable(
            {"title": "SAC", "year": 2027, "cause": "not_checked",
             "attempted": []})
        self.assertTrue(ok, errors)

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

    def test_metadata_object_cannot_be_stringified_into_public_yaml(self):
        ok, errors = self.check(proposal(fields={
            "place": claim({"San": "Diego"}, "Conference venue San Diego")
        }))
        self.assertFalse(ok)
        self.assertTrue(any("must be a string" in error for error in errors), errors)

    def test_evidence_must_be_a_list_of_quote_objects(self):
        ok, errors = self.check(proposal(fields={"place": {
            "value": "San Diego, USA", "evidence": "not-an-array"
        }}))
        self.assertFalse(ok)
        self.assertTrue(any("has no evidence" in error for error in errors), errors)

    def test_multicycle_deadline_exact_evidence_bindings_pass(self):
        first = "2026-02-17 23:59"
        second = "2026-05-14 23:59"
        ok, errors = self.check(proposal(fields={"deadline": {
            "value": [first, second],
            "evidence": [
                {"for_value": second,
                 "quote": "Full paper submission due: May 14, 2026"},
                {"for_value": first,
                 "quote": "Full paper submission due: February 17, 2026"},
            ],
        }}))
        self.assertTrue(ok, errors)

    def test_multicycle_deadline_rejects_missing_for_value_binding(self):
        first = "2026-02-17 23:59"
        second = "2026-05-14 23:59"
        ok, errors = self.check(proposal(fields={"deadline": {
            "value": [first, second],
            "evidence": [
                {"for_value": first,
                 "quote": "Full paper submission due: February 17, 2026"},
                {"quote": "Full paper submission due: May 14, 2026"},
            ],
        }}))
        self.assertFalse(ok)
        self.assertTrue(any("missing exact for_value binding" in error
                            for error in errors), errors)
        self.assertTrue(any(f"for_value {second!r}" in error
                            for error in errors), errors)

    def test_multicycle_deadline_rejects_unknown_for_value_binding(self):
        first = "2026-02-17 23:59"
        second = "2026-05-14 23:59"
        unknown = "2026-09-24 23:59"
        ok, errors = self.check(proposal(fields={"deadline": {
            "value": [first, second],
            "evidence": [
                {"for_value": first,
                 "quote": "Full paper submission due: February 17, 2026"},
                {"for_value": unknown,
                 "quote": "Full paper submission due: September 24, 2026"},
            ],
        }}))
        self.assertFalse(ok)
        self.assertTrue(any(f"unknown for_value {unknown!r}" in error
                            for error in errors), errors)

    def test_multicycle_deadline_rejects_duplicate_evidence_binding(self):
        first = "2026-02-17 23:59"
        second = "2026-05-14 23:59"
        ok, errors = self.check(proposal(fields={"deadline": {
            "value": [first, second],
            "evidence": [
                {"for_value": first,
                 "quote": "Full paper submission due: February 17, 2026"},
                {"for_value": first,
                 "quote": "Paper deadline cycle one: February 17, 2026"},
            ],
        }}))
        self.assertFalse(ok)
        self.assertTrue(any("duplicate evidence bindings" in error
                            for error in errors), errors)
        self.assertTrue(any(f"for_value {second!r}" in error
                            for error in errors), errors)

    def test_multicycle_deadline_rejects_duplicate_concrete_value(self):
        cycle = "2026-02-17 23:59"
        ok, errors = self.check(proposal(fields={"deadline": {
            "value": [cycle, cycle],
            "evidence": [{
                "for_value": cycle,
                "quote": "Full paper submission due: February 17, 2026",
            }],
        }}))
        self.assertFalse(ok)
        self.assertTrue(any("repeats concrete cycle value" in error
                            for error in errors), errors)

    def test_abstract_multicycle_binding_ignores_null_cycle_safely(self):
        first = "2026-02-10 23:59"
        second = "2026-05-07 23:59"
        ok, errors = self.check(proposal(fields={"abstract_deadline": {
            "value": [None, first, second],
            "evidence": [
                {"for_value": first,
                 "quote": "Paper abstracts due: February 10, 2026"},
                {"for_value": second,
                 "quote": "Paper abstracts due: May 7, 2026"},
            ],
        }}))
        self.assertTrue(ok, errors)

    def test_single_concrete_abstract_cycle_keeps_unbound_compatibility(self):
        ok, errors = self.check(proposal(fields={"abstract_deadline": {
            "value": [None, "2026-02-10 23:59"],
            "evidence": [{"quote": "Paper abstracts due: February 10, 2026"}],
        }}))
        self.assertTrue(ok, errors)

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

    def test_impossible_calendar_instant_is_rejected(self):
        ok, errors = self.check(proposal(fields={
            "deadline": claim("2027-02-29 23:59")
        }))
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
