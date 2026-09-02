#!/usr/bin/env python3
"""Offline tests for reconcile_audit_outcomes.py."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reconcile_audit_outcomes as R  # noqa: E402


class FakeFetcher:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return self.responses.get(url, (None, "unreachable"))


class TypedRecordingFetcher(R.Fetcher):
    """Fetcher-shaped recorder so redirect confinement is observable offline."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def get(self, url, allowed_hosts=None, *, exact_redirect_hosts=False):
        self.calls.append((url, set(allowed_hosts or ()), exact_redirect_hosts))
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

    def test_oversized_attempt_list_requeues_without_network_io(self):
        attempted = [f"https://conf.example/route-{index}"
                     for index in range(R.MAX_ATTEMPTED_URLS + 1)]
        original = {
            "title": "X", "year": 2027, "cause": "fetch_blocked",
            "attempted": attempted,
        }
        fetcher = FakeFetcher({url: ("page", None) for url in attempted})

        result, changed = R.reconcile_outcome(original, fetcher)

        self.assertTrue(changed)
        self.assertEqual(result["cause"], "not_checked")
        self.assertIn("autonomous bound", result["note"])
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

    def test_every_final_nonfetch_cause_rejects_model_only_host(self):
        policy = R.build_source_trust_policy(
            [{"title": "X", "year": 2027, "record": {}}], [])
        for cause in (
                "no_official_page", "page_ambiguous",
                "javascript_only", "pdf_only"):
            with self.subTest(cause=cause):
                document = {
                    "proposals": [],
                    "unverifiable": [{
                        "title": "X", "year": 2027, "cause": cause,
                        "attempted": ["https://model-only.example/cfp"],
                    }],
                }
                fetcher = TypedRecordingFetcher()

                result, changed = R.reconcile_document(
                    document, fetcher, source_trust_policy=policy)

                self.assertTrue(changed)
                self.assertEqual(
                    result["unverifiable"][0]["cause"], "not_checked")
                self.assertIn(
                    "outside immutable source trust",
                    result["unverifiable"][0]["note"],
                )
                self.assertEqual(fetcher.calls, [])

    def test_every_final_nonfetch_cause_accepts_trusted_attempt_without_io(self):
        url = "https://x2027.official.example/cfp"
        policy = R.build_source_trust_policy([{
            "title": "X", "year": 2027, "record": {},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": url},
            ],
        }], [])
        for cause in (
                "no_official_page", "page_ambiguous",
                "javascript_only", "pdf_only"):
            with self.subTest(cause=cause):
                document = {
                    "proposals": [],
                    "unverifiable": [{
                        "title": "X", "year": 2027, "cause": cause,
                        "attempted": [url],
                    }],
                }
                fetcher = TypedRecordingFetcher()

                result, changed = R.reconcile_document(
                    document, fetcher, source_trust_policy=policy)

                self.assertFalse(changed)
                self.assertEqual(result, document)
                self.assertEqual(fetcher.calls, [])

    def test_nonfetch_cause_requeues_inadmissible_tracker_url(self):
        original = {
            "title": "X", "year": 2027, "cause": "no_official_page",
            "attempted": ["https://ccfddl.github.io/conference/X"],
        }
        result, changed = R.reconcile_outcome(original, FakeFetcher())
        self.assertTrue(changed)
        self.assertEqual(result["cause"], "not_checked")

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

    def test_typed_policy_rechecks_exact_provisional_host_with_confined_redirects(self):
        url = "https://x2027.official.example/cfp"
        watchlist = [{
            "title": "X", "year": 2027, "record": {},
            "upstream_link_candidates": [
                {"source": "ccfddl", "link": url},
            ],
        }]
        policy = R.build_source_trust_policy(watchlist, [])
        document = {
            "proposals": [],
            "unverifiable": [{
                "title": "X", "year": 2027, "cause": "fetch_blocked",
                "attempted": [url],
            }],
        }
        fetcher = TypedRecordingFetcher({url: ("<html>CFP</html>", None)})

        result, changed = R.reconcile_document(
            document, fetcher, source_trust_policy=policy)

        self.assertTrue(changed)
        self.assertEqual(result["unverifiable"][0]["cause"], "not_checked")
        self.assertEqual(fetcher.calls, [(url, {"x2027.official.example"}, True)])

    def test_typed_policy_never_rechecks_unrelated_model_only_host(self):
        url = "https://model-only.example/cfp"
        policy = R.build_source_trust_policy(
            [{"title": "X", "year": 2027, "record": {}}], [])
        document = {
            "proposals": [],
            "unverifiable": [{
                "title": "X", "year": 2027, "cause": "fetch_blocked",
                "attempted": [url],
            }],
        }
        fetcher = TypedRecordingFetcher({url: ("<html>CFP</html>", None)})

        result, changed = R.reconcile_document(
            document, fetcher, source_trust_policy=policy)

        self.assertTrue(changed)
        self.assertEqual(result["unverifiable"][0]["cause"], "not_checked")
        self.assertEqual(fetcher.calls, [])

    def test_finalizer_replaces_forged_machine_group_with_value_free_records(self):
        document = {
            "audit_date": "2026-08-31", "watchlist_size": 1,
            "proposals": [],
            "unverifiable": [{
                "title": "X", "year": 2027, "cause": "not_checked",
                "attempted": ["https://model.example/"],
                "note": "model prose must not survive",
            }],
            "machine_deferred": [{
                "title": "FORGED", "year": 2027, "reason": "model-says-so",
            }],
        }

        result, changed = R.finalize_machine_deferred(document)

        self.assertTrue(changed)
        self.assertEqual(result["unverifiable"], [])
        self.assertEqual(result["machine_deferred"], [{
            "title": "X", "year": 2027,
            "reason": "audit-incomplete-after-retry",
        }])
        self.assertNotIn("model prose", json.dumps(result))
        self.assertNotIn("model.example", json.dumps(result))

    def test_finalizer_distinguishes_same_process_source_invalidation(self):
        document = {
            "proposals": [],
            "unverifiable": [
                {"title": "X", "year": 2027, "cause": "not_checked"},
                {"title": "Y", "year": 2027, "cause": "not_checked"},
            ],
        }
        result, _ = R.finalize_machine_deferred(
            document, requeued={("Y", 2027)})
        self.assertEqual(
            [item["reason"] for item in result["machine_deferred"]],
            ["audit-incomplete-after-retry", "source-recheck-requeued"],
        )
        # Neither reason is an examined audit outcome; the latter only proves
        # activity for the global total-outage circuit breaker.
        self.assertEqual(R.substantive_work_count(result), 1)

    def test_zero_substantive_finalization_fails_without_writing(self):
        document = {
            "audit_date": "2026-08-31", "watchlist_size": 1,
            "proposals": [],
            "unverifiable": [{
                "title": "X", "year": 2027, "cause": "not_checked",
                "attempted": [],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit-proposals.json"
            watchlist = Path(directory) / "watchlist.json"
            original = json.dumps(document)
            path.write_text(original, encoding="utf-8")
            watchlist.write_text(json.dumps([{
                "title": "X", "year": 2027,
            }]), encoding="utf-8")
            with mock.patch.object(
                    R, "source_trust_policy_for_watchlist", return_value=None):
                with self.assertRaisesRegex(ValueError, "zero substantive"):
                    R.reconcile_file(
                        path, FakeFetcher(), watchlist_path=watchlist,
                        finalize_deferred=True, require_substantive=True,
                    )
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_partial_finalization_keeps_safe_result_and_defers_idle_record(self):
        document = {
            "audit_date": "2026-08-31", "watchlist_size": 2,
            "proposals": [{
                "id": "no_change:X:2027", "action": "no_change",
                "title": "X", "year": 2027,
            }],
            "unverifiable": [{
                "title": "Y", "year": 2027, "cause": "not_checked",
                "attempted": [],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit-proposals.json"
            watchlist = Path(directory) / "watchlist.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            watchlist.write_text(json.dumps([
                {"title": "X", "year": 2027},
                {"title": "Y", "year": 2027},
            ]), encoding="utf-8")
            with mock.patch.object(
                    R, "source_trust_policy_for_watchlist", return_value=None):
                changed = R.reconcile_file(
                    path, FakeFetcher(), watchlist_path=watchlist,
                    finalize_deferred=True, require_substantive=True,
                )
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(changed)
            self.assertEqual([p["title"] for p in result["proposals"]], ["X"])
            self.assertEqual(result["machine_deferred"], [{
                "title": "Y", "year": 2027,
                "reason": "audit-incomplete-after-retry",
            }])

    def test_finalize_entrypoint_rejects_preexisting_machine_group(self):
        document = {
            "audit_date": "2026-08-31", "watchlist_size": 1,
            "proposals": [], "unverifiable": [],
            "machine_deferred": [{
                "title": "X", "year": 2027,
                "reason": "audit-incomplete-after-retry",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit-proposals.json"
            watchlist = Path(directory) / "watchlist.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            watchlist.write_text(
                json.dumps([{"title": "X", "year": 2027}]),
                encoding="utf-8")
            with mock.patch.object(
                    R, "source_trust_policy_for_watchlist", return_value=None):
                with self.assertRaisesRegex(
                        R.B.BatchError, "reserved for trusted finalization"):
                    R.reconcile_file(
                        path, FakeFetcher(), watchlist_path=watchlist,
                        finalize_deferred=True,
                    )


if __name__ == "__main__":
    unittest.main()
