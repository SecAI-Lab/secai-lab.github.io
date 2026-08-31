#!/usr/bin/env python3
"""Offline tests for reconcile_audit_outcomes.py."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reconcile_audit_outcomes as R  # noqa: E402


class FakeFetcher:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return self.responses.get(url, (None, "unreachable"))


class ReconcileOutcome(unittest.TestCase):
    def test_reachable_fetch_returns_record_to_claude_retry(self):
        first = "https://conf.example/2027"
        second = "https://conf.example/cfp"
        original = {
            "title": "X",
            "year": 2027,
            "cause": "fetch_blocked",
            "attempted": [first, second],
            "note": "The site rejected the auditor request.",
            "extra": {"preserved": True},
        }
        before = copy.deepcopy(original)
        fetcher = FakeFetcher({
            first: (None, "HTTP 403"),
            second: ("<html>CFP</html>", None),
        })

        result, changed = R.reconcile_outcome(original, fetcher)

        self.assertTrue(changed)
        self.assertEqual(result["cause"], "not_checked")
        self.assertIn("Claude retry must inspect this source", result["note"])
        self.assertIn("The site rejected", result["note"])
        self.assertEqual(result["extra"], {"preserved": True})
        self.assertEqual(fetcher.calls, [first, second])
        self.assertEqual(original, before)

    def test_exhausted_fetch_preserves_blocked_and_adds_machine_note(self):
        urls = ["https://conf.example/2027", "https://conf.example/cfp"]
        original = {
            "title": "X", "year": 2027, "cause": "fetch_blocked",
            "attempted": urls,
        }
        fetcher = FakeFetcher({
            urls[0]: (None, "robots.txt disallows this path"),
            urls[1]: (None, "HTTP 403"),
        })

        result, changed = R.reconcile_outcome(original, fetcher)

        self.assertTrue(changed)
        self.assertEqual(result["cause"], "fetch_blocked")
        self.assertEqual(result["attempted"], urls)
        self.assertIn("all remain unreachable or robots-denied", result["note"])
        self.assertEqual(fetcher.calls, urls)
        again, changed_again = R.reconcile_outcome(result, fetcher)
        self.assertEqual(again, result)
        self.assertFalse(changed_again)

    def test_missing_or_malformed_fetch_attempts_return_to_retry(self):
        cases = (None, [], "https://conf.example", ["not a URL"], ["https://["],
                 ["https://ccfddl.github.io/conference/X"])
        for attempted in cases:
            with self.subTest(attempted=attempted):
                outcome = {"title": "X", "year": 2027,
                           "cause": "fetch_blocked"}
                if attempted is not None:
                    outcome["attempted"] = attempted
                fetcher = FakeFetcher()
                result, changed = R.reconcile_outcome(outcome, fetcher)
                self.assertTrue(changed)
                self.assertEqual(result["cause"], "not_checked")
                self.assertEqual(fetcher.calls, [])

    def test_no_official_page_check_is_bounded_and_never_fetches(self):
        fetcher = FakeFetcher({"https://conf.example/": ("page", None)})
        complete = {
            "title": "X", "year": 2027, "cause": "no_official_page",
            "attempted": ["https://conf.example/"],
            "note": "No edition page was published.",
        }
        result, changed = R.reconcile_outcome(complete, fetcher)
        self.assertEqual(result, complete)
        self.assertFalse(changed)
        self.assertEqual(fetcher.calls, [])

        incomplete = {"title": "Y", "year": 2027,
                      "cause": "no_official_page", "attempted": []}
        result, changed = R.reconcile_outcome(incomplete, fetcher)
        self.assertTrue(changed)
        self.assertEqual(result["cause"], "not_checked")
        self.assertEqual(fetcher.calls, [])

    def test_other_causes_are_untouched_and_never_fetched(self):
        fetcher = FakeFetcher()
        for cause in ("not_checked", "page_ambiguous", "javascript_only", "pdf_only"):
            with self.subTest(cause=cause):
                original = {"title": "X", "year": 2027, "cause": cause,
                            "attempted": ["https://conf.example/"]}
                result, changed = R.reconcile_outcome(original, fetcher)
                self.assertEqual(result, original)
                self.assertFalse(changed)
        self.assertEqual(fetcher.calls, [])


class ReconcileDocumentAndFile(unittest.TestCase):
    def test_document_preserves_top_level_and_outcome_order(self):
        document = {
            "audit_date": "2026-08-31",
            "watchlist_size": 2,
            "proposals": [{"id": "no_change:A:2027"}],
            "unverifiable": [
                {"title": "A", "year": 2027, "cause": "page_ambiguous"},
                {"title": "B", "year": 2027, "cause": "fetch_blocked",
                 "attempted": []},
            ],
            "telemetry": {"kept": True},
        }
        result, changed = R.reconcile_document(document, FakeFetcher())
        self.assertTrue(changed)
        self.assertEqual(list(result), list(document))
        self.assertEqual([u["title"] for u in result["unverifiable"]], ["A", "B"])
        self.assertEqual(result["proposals"], document["proposals"])
        self.assertEqual(result["telemetry"], document["telemetry"])

    def test_file_is_not_written_when_nothing_changes(self):
        document = {
            "proposals": [],
            "unverifiable": [{
                "title": "X", "year": 2027, "cause": "no_official_page",
                "attempted": ["https://conf.example/"],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit-proposals.json"
            original_text = json.dumps(document, separators=(",", ":"))
            path.write_text(original_text, encoding="utf-8")
            changed = R.reconcile_file(path, FakeFetcher())
            self.assertFalse(changed)
            self.assertEqual(path.read_text(encoding="utf-8"), original_text)

    def test_production_trust_binding_never_fetches_model_supplied_host(self):
        document = {
            "proposals": [],
            "unverifiable": [{
                "title": "X", "year": 2027, "cause": "fetch_blocked",
                "attempted": ["https://model-supplied.example/cfp"],
            }],
        }
        fetcher = FakeFetcher({
            "https://model-supplied.example/cfp": ("page", None),
        })
        result, changed = R.reconcile_document(
            document, fetcher,
            trusted_by_title={"X": {"official.example"}},
        )
        self.assertTrue(changed)
        self.assertEqual(result["unverifiable"][0]["cause"], "not_checked")
        self.assertEqual(fetcher.calls, [])


if __name__ == "__main__":
    unittest.main()
