#!/usr/bin/env python3
"""Tests for deterministic deadline-audit splitting and merging.

Run: python3 deadlines/scripts/tests/test_audit_batches.py
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audit_batches as B  # noqa: E402


AUDIT_DATE = "2026-08-31"


def watch_record(number):
    return {
        "title": f"CONF-{number:02d}",
        "year": 2027,
        "reasons": ["tba-upcoming-cycle"],
        "file": "deadlines/data/conferences/2027/security.yml",
        "record": {"title": f"CONF-{number:02d}", "year": 2027},
    }


def proposal(record, action="no_change"):
    return {
        "id": f"{action}:{record['title']}:{record['year']}",
        "action": action,
        "title": record["title"],
        "year": record["year"],
    }


def unverifiable(record, cause="no_official_page"):
    return {
        "title": record["title"],
        "year": record["year"],
        "cause": cause,
        "attempted": ["https://example.org/"],
    }


def machine_deferred(record, reason="audit-incomplete-after-retry"):
    return {
        "title": record["title"],
        "year": record["year"],
        "reason": reason,
    }


def audit(proposals=(), unverifiable_records=(), machine_records=None,
          audit_date=AUDIT_DATE):
    proposals = list(proposals)
    unverifiable_records = list(unverifiable_records)
    machine_records = None if machine_records is None else list(machine_records)
    result = {
        "audit_date": audit_date,
        "watchlist_size": (len(proposals) + len(unverifiable_records)
                           + len(machine_records or [])),
        "proposals": proposals,
        "unverifiable": unverifiable_records,
    }
    if machine_records is not None:
        result["machine_deferred"] = machine_records
    return result


class Split(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_default_split_of_26_is_10_10_6_and_preserves_order(self):
        watchlist = [watch_record(number) for number in range(26)]
        source = self.tmp / "watchlist.json"
        source.write_text(json.dumps(watchlist), encoding="utf-8")

        paths = B.write_watchlist_shards(source, self.tmp / "shards")

        self.assertEqual([path.name for path in paths], [
            "watchlist-001.json", "watchlist-002.json", "watchlist-003.json"
        ])
        shards = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        self.assertEqual([len(shard) for shard in shards], [10, 10, 6])
        self.assertEqual([record for shard in shards for record in shard], watchlist)

    def test_split_rejects_nonpositive_bound(self):
        with self.assertRaisesRegex(B.BatchError, "positive integer"):
            B.split_watchlist([watch_record(0)], 0)


class Merge(unittest.TestCase):
    def setUp(self):
        self.watchlist = [watch_record(number) for number in range(4)]

    def merge(self, *docs):
        return B.merge_audit_documents(
            self.watchlist,
            [(f"shard-{index}.json", doc) for index, doc in enumerate(docs, 1)],
        )

    def test_exact_merge_preserves_original_order_in_each_output_array(self):
        # Deliberately reverse records within and across shards.  Output order
        # must come from the authoritative watchlist, not completion timing.
        first = audit(
            proposals=[proposal(self.watchlist[2])],
            unverifiable_records=[unverifiable(self.watchlist[3])],
        )
        second = audit(
            proposals=[proposal(self.watchlist[0])],
            unverifiable_records=[unverifiable(self.watchlist[1])],
        )

        merged = self.merge(first, second)

        self.assertEqual(merged["audit_date"], AUDIT_DATE)
        self.assertEqual(merged["watchlist_size"], 4)
        self.assertEqual(
            [entry["title"] for entry in merged["proposals"]],
            ["CONF-00", "CONF-02"],
        )
        self.assertEqual(
            [entry["title"] for entry in merged["unverifiable"]],
            ["CONF-01", "CONF-03"],
        )
        self.assertIs(B.validate_audit_document(self.watchlist, merged), merged)

    def test_duplicate_record_across_shards_is_rejected(self):
        duplicate = self.watchlist[0]
        docs = (
            audit(proposals=[proposal(duplicate), proposal(self.watchlist[1])]),
            audit(
                proposals=[proposal(duplicate), proposal(self.watchlist[2])],
                unverifiable_records=[unverifiable(self.watchlist[3])],
            ),
        )
        with self.assertRaisesRegex(B.BatchError, "duplicate audit record CONF-00 2027"):
            self.merge(*docs)

    def test_unknown_record_is_rejected(self):
        unknown = {"title": "INVENTED", "year": 2027}
        doc = audit(
            proposals=[proposal(record) for record in self.watchlist],
            unverifiable_records=[unverifiable(unknown)],
        )
        with self.assertRaisesRegex(B.BatchError, "unknown audit record.*INVENTED 2027"):
            self.merge(doc)

    def test_missing_record_is_rejected(self):
        doc = audit(proposals=[proposal(record) for record in self.watchlist[:-1]])
        with self.assertRaisesRegex(B.BatchError, "missing.*CONF-03 2027"):
            self.merge(doc)

    def test_final_not_checked_is_rejected(self):
        doc = audit(
            proposals=[proposal(record) for record in self.watchlist[:-1]],
            unverifiable_records=[unverifiable(self.watchlist[-1], "not_checked")],
        )
        with self.assertRaisesRegex(B.BatchError, "still not_checked"):
            self.merge(doc)

    def test_raw_not_checked_requires_explicit_unfinished_stage(self):
        doc = audit(
            proposals=[proposal(record) for record in self.watchlist[:-1]],
            unverifiable_records=[unverifiable(self.watchlist[-1], "not_checked")],
        )
        merged = B.merge_audit_documents(
            self.watchlist, [("raw.json", doc)],
            allow_unfinished=True,
        )
        self.assertEqual(merged["unverifiable"][-1]["cause"], "not_checked")

    def test_machine_deferred_requires_explicit_trusted_stage(self):
        doc = audit(
            proposals=[proposal(record) for record in self.watchlist[:-1]],
            machine_records=[machine_deferred(self.watchlist[-1])],
        )
        with self.assertRaisesRegex(B.BatchError, "reserved for trusted finalization"):
            self.merge(doc)
        merged = B.merge_audit_documents(
            self.watchlist, [("final.json", doc)],
            allow_machine_deferred=True,
        )
        self.assertEqual(len(merged["machine_deferred"]), 1)

    def test_machine_deferred_shape_and_reason_are_fixed(self):
        item = machine_deferred(self.watchlist[-1], "model-says-so")
        item["note"] = "forged"
        doc = audit(
            proposals=[proposal(record) for record in self.watchlist[:-1]],
            machine_records=[item],
        )
        with self.assertRaisesRegex(B.BatchError, "exactly title, year, and reason"):
            B.validate_audit_document(
                self.watchlist, doc, allow_machine_deferred=True)

    def test_unfinished_and_machine_deferred_stages_are_mutually_exclusive(self):
        doc = audit(proposals=[proposal(record) for record in self.watchlist])
        with self.assertRaisesRegex(B.BatchError, "mutually exclusive"):
            B.validate_audit_document(
                self.watchlist, doc,
                allow_unfinished=True, allow_machine_deferred=True,
            )

    def test_audit_date_mismatch_is_rejected(self):
        left = audit(proposals=[proposal(record) for record in self.watchlist[:2]])
        right = audit(
            proposals=[proposal(record) for record in self.watchlist[2:]],
            audit_date="2026-09-01",
        )
        with self.assertRaisesRegex(B.BatchError, "audit_date mismatch"):
            self.merge(left, right)


class ValidateCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.watchlist = [watch_record(0), watch_record(1)]
        self.watchlist_path = self.tmp / "watchlist.json"
        self.audit_path = self.tmp / "audit-proposals.json"
        self.watchlist_path.write_text(json.dumps(self.watchlist), encoding="utf-8")

    def run_validate(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = B.main([
                "validate", str(self.watchlist_path), str(self.audit_path)
            ])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_validate_accepts_exactly_once_final_document(self):
        self.audit_path.write_text(json.dumps(audit(
            proposals=[proposal(self.watchlist[0])],
            unverifiable_records=[unverifiable(self.watchlist[1])],
        )), encoding="utf-8")

        code, stdout, stderr = self.run_validate()

        self.assertEqual(code, 0, stderr)
        self.assertIn("2 watchlist record(s) accounted for exactly once", stdout)

    def test_validate_returns_nonzero_with_clear_error(self):
        self.audit_path.write_text(json.dumps(audit(
            proposals=[proposal(self.watchlist[0])],
        )), encoding="utf-8")

        code, _, stderr = self.run_validate()

        self.assertNotEqual(code, 0)
        self.assertIn("missing watchlist record(s): CONF-01 2027", stderr)

    def test_validate_rejects_a_stale_audit_date(self):
        self.audit_path.write_text(json.dumps(audit(
            proposals=[proposal(self.watchlist[0]), proposal(self.watchlist[1])],
            audit_date="2026-08-30",
        )), encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = B.main([
                "validate", str(self.watchlist_path), str(self.audit_path),
                "--audit-date", AUDIT_DATE,
            ])
        self.assertNotEqual(code, 0)
        self.assertIn(f"expected {AUDIT_DATE}", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
