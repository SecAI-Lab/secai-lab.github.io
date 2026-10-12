#!/usr/bin/env python3
"""Offline tests for schema repair at the end of an audit shard."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audit_batches as B  # noqa: E402
import defer_invalid_audit_claims as D  # noqa: E402
import reconcile_audit_outcomes as R  # noqa: E402
import update_deadlines as U  # noqa: E402


class DeferInvalidAuditClaims(unittest.TestCase):
    def setUp(self):
        self.targets = {target["key"]: target for target in U.load_config()}
        self.watchlist = [
            {"title": "EuroS&P", "year": 2027},
            {"title": "SAC", "year": 2027},
        ]
        self.good = {
            "id": "no_change:SAC:2027", "action": "no_change",
            "title": "SAC", "year": 2027,
            "source_url": "https://www.sigapp.org/sac/sac2027/",
            "reason": "The official page confirms the recorded place.",
            "fields": {"place": {
                "value": "Gwangju, South Korea",
                "evidence": [{"quote": "Conference venue: Gwangju, South Korea"}],
            }},
        }
        self.bad = {
            "id": "upsert_manual:EuroS&P:2027", "action": "upsert_manual",
            "title": "EuroS&P", "year": 2027,
            "source_url": "https://example.org/eurosp-2027/",
            "reason": "The official page updates the record.",
            "fields": {"note": {"value": "Call for papers is available."}},
        }

    def document(self):
        return {
            "audit_date": "2026-10-12", "watchlist_size": 2,
            "proposals": [self.bad, self.good], "unverifiable": [],
        }

    def test_unevidenced_note_is_deferred_without_losing_valid_record(self):
        original = self.document()
        before = copy.deepcopy(original)
        repaired, diagnostics = D.defer_invalid_claims(
            self.watchlist, original, self.targets, "2026-10-12"
        )
        self.assertEqual(original, before)
        self.assertEqual(repaired["proposals"], [self.good])
        self.assertEqual(repaired["unverifiable"], [{
            "title": "EuroS&P", "year": 2027, "cause": "not_checked",
        }])
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("field 'note' has no evidence", diagnostics[0][2][0])
        B.validate_audit_document(
            self.watchlist, repaired, allow_unfinished=True
        )
        finalized, changed = R.finalize_machine_deferred(repaired)
        self.assertTrue(changed)
        self.assertEqual(finalized["proposals"], [self.good])
        self.assertEqual(finalized["machine_deferred"], [{
            "title": "EuroS&P", "year": 2027,
            "reason": "audit-incomplete-after-retry",
        }])
        B.validate_audit_document(
            self.watchlist, finalized, allow_machine_deferred=True
        )

    def test_valid_document_is_unchanged(self):
        original = self.document()
        original["proposals"] = [self.good]
        original["unverifiable"] = [{
            "title": "EuroS&P", "year": 2027,
            "cause": "no_official_page",
            "attempted": ["https://example.org/eurosp-2027/"],
        }]
        repaired, diagnostics = D.defer_invalid_claims(
            self.watchlist, original, self.targets, "2026-10-12"
        )
        self.assertEqual(repaired, original)
        self.assertEqual(diagnostics, [])

    def test_invalid_coverage_and_date_are_not_repaired(self):
        original = self.document()
        original["proposals"].append(copy.deepcopy(self.good))
        with self.assertRaisesRegex(B.BatchError, "duplicate"):
            D.defer_invalid_claims(
                self.watchlist, original, self.targets, "2026-10-12"
            )
        original = self.document()
        with self.assertRaisesRegex(B.BatchError, "expected 2026-10-13"):
            D.defer_invalid_claims(
                self.watchlist, original, self.targets, "2026-10-13"
            )

    def test_malformed_negative_outcome_is_deferred(self):
        original = self.document()
        original["proposals"] = [self.good]
        original["unverifiable"] = [{
            "title": "EuroS&P", "year": 2027,
            "cause": "no_official_page", "attempted": [],
        }]
        repaired, diagnostics = D.defer_invalid_claims(
            self.watchlist, original, self.targets, "2026-10-12"
        )
        self.assertEqual(repaired["proposals"], [self.good])
        self.assertEqual(repaired["unverifiable"][0]["cause"], "not_checked")
        self.assertIn("requires attempted official URL(s)", diagnostics[0][2][0])


if __name__ == "__main__":
    unittest.main()
