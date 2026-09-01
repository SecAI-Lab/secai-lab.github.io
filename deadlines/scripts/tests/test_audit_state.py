#!/usr/bin/env python3
"""Offline tests for persistent autonomous-audit corroboration."""

import json
import itertools
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_state as S  # noqa: E402


def proposal(value="2027-03-15 23:59"):
    return {
        "action": "upsert_manual", "title": "FSE", "year": 2027,
        "fields": {"deadline": {"value": value}},
    }


def place_proposal(value="Lisbon, Portugal"):
    return {
        "action": "upsert_manual", "title": "FSE", "year": 2027,
        "fields": {"place": {"value": value}},
    }


def claims(state, key):
    return state["corroboration"][key]["claims"]


def claim_for(state, key, scope):
    return claims(state, key)[scope]


class Corroboration(unittest.TestCase):
    def test_two_distinct_dates_promote_identical_values(self):
        state = S.empty_state()
        p = proposal()
        promoted, key = S.observe_verified(
            state, p, {"deadline": "2027-03-15 23:59"}, "2026-08-31")
        self.assertFalse(promoted)
        promoted, _ = S.observe_verified(
            state, p, {"deadline": "2027-03-15 23:59"}, "2026-09-07")
        self.assertTrue(promoted)
        self.assertEqual(
            claim_for(state, key, "fields:deadline")["verified_runs"], 2)

    def test_promoted_run_count_is_capped(self):
        state = S.empty_state()
        p = proposal()
        for audit_date in ("2026-08-31", "2026-09-07", "2026-09-14"):
            promoted, key = S.observe_verified(
                state, p, {"deadline": "2027-03-15 23:59"}, audit_date)
        self.assertTrue(promoted)
        self.assertEqual(
            claim_for(state, key, "fields:deadline")["verified_runs"],
            S.REQUIRED_VERIFIED_RUNS,
        )

    def test_rerun_on_same_date_does_not_promote(self):
        state = S.empty_state()
        p = proposal()
        S.observe_verified(state, p, {"deadline": "2027-03-15 23:59"}, "2026-08-31")
        promoted, key = S.observe_verified(
            state, p, {"deadline": "2027-03-15 23:59"}, "2026-08-31")
        self.assertFalse(promoted)
        self.assertEqual(
            claim_for(state, key, "fields:deadline")["verified_runs"], 1)

    def test_back_to_back_manual_dispatches_do_not_fake_weekly_confirmation(self):
        state = S.empty_state()
        p = proposal()
        S.observe_verified(state, p, {"deadline": "2027-03-15 23:59"},
                           "2026-08-31")
        promoted, key = S.observe_verified(
            state, p, {"deadline": "2027-03-15 23:59"}, "2026-09-01")
        self.assertFalse(promoted)
        current = claim_for(state, key, "fields:deadline")
        self.assertEqual(current["verified_runs"], 1)
        self.assertEqual(current["last_seen"], "2026-08-31")

    def test_changed_value_resets_streak(self):
        state = S.empty_state()
        S.observe_verified(state, proposal(), {"deadline": "2027-03-15 23:59"},
                           "2026-08-31")
        promoted, key = S.observe_verified(
            state, proposal("2027-03-16 23:59"),
            {"deadline": "2027-03-16 23:59"}, "2026-09-07")
        self.assertFalse(promoted)
        current = claim_for(state, key, "fields:deadline")
        self.assertEqual(current["verified_runs"], 1)
        self.assertEqual(current["first_seen"], "2026-09-07")

    def test_changed_machine_verification_basis_resets_streak(self):
        state = S.empty_state()
        first_basis = "sha256:" + "a" * 64
        second_basis = "sha256:" + "b" * 64
        S.observe_verified(
            state, proposal(), {"deadline": "2027-03-15 23:59"},
            "2026-08-31", basis_digest=first_basis)
        promoted, key = S.observe_verified(
            state, proposal(), {"deadline": "2027-03-15 23:59"},
            "2026-09-07", basis_digest=second_basis)
        self.assertFalse(promoted)
        current = claim_for(state, key, "fields:deadline")
        self.assertEqual(current["verified_runs"], 1)
        self.assertEqual(current["first_seen"], "2026-09-07")
        rendered = S.render(state)
        self.assertNotIn(first_basis, rendered)
        self.assertNotIn(second_basis, rendered)

    def test_invalid_machine_verification_basis_fails_closed(self):
        with self.assertRaises(S.StateError):
            S.observe_verified(
                S.empty_state(), proposal(),
                {"deadline": "2027-03-15 23:59"}, "2026-08-31",
                basis_digest="sha256:not-a-digest")

    def test_unverified_completed_audit_resets_streak(self):
        state = S.empty_state()
        _, key = S.observe_verified(
            state, proposal(), {"deadline": "2027-03-15 23:59"}, "2026-08-31")
        S.finish_corroboration(state, {key}, set())
        self.assertNotIn(key, state["corroboration"])
        self.assertIn(key, state["retry"])

    def test_disjoint_claims_coexist_and_promote_independently(self):
        state = S.empty_state()
        _, deadline_ref = S.observe_verified_claim(
            state, proposal(), {"deadline": "2027-03-15 23:59"}, "2026-08-31")
        _, place_ref = S.observe_verified_claim(
            state, place_proposal(), {"place": "Lisbon, Portugal"}, "2026-08-31")
        self.assertEqual(set(claims(state, deadline_ref.identity)),
                         {"fields:deadline", "fields:place"})

        promoted, observed = S.observe_verified_claim(
            state, proposal(), {"deadline": "2027-03-15 23:59"}, "2026-09-07")
        self.assertTrue(promoted)
        self.assertEqual(observed, deadline_ref)
        self.assertEqual(claim_for(state, deadline_ref.identity,
                                   "fields:deadline")["verified_runs"], 2)
        self.assertEqual(claim_for(state, place_ref.identity,
                                   "fields:place")["verified_runs"], 1)

    def test_finish_resets_only_a_fully_covered_unobserved_claim(self):
        state = S.empty_state()
        _, deadline_ref = S.observe_verified_claim(
            state, proposal(), {"deadline": "2027-03-15 23:59"}, "2026-08-31")
        S.observe_verified_claim(
            state, place_proposal(), {"place": "Lisbon, Portugal"}, "2026-08-31")

        S.finish_corroboration_claims(
            state, {deadline_ref.identity: {"place"}}, set())
        self.assertEqual(set(claims(state, deadline_ref.identity)),
                         {"fields:deadline"})

    def test_partial_finish_does_not_erase_a_multi_field_claim(self):
        state = S.empty_state()
        multi = proposal()
        multi["fields"]["place"] = {"value": "Lisbon, Portugal"}
        _, ref = S.observe_verified_claim(
            state, multi,
            {"deadline": "2027-03-15 23:59", "place": "Lisbon, Portugal"},
            "2026-08-31")
        S.finish_corroboration_claims(state, {ref.identity: {"place"}}, set())
        self.assertIn(ref.scope_id, claims(state, ref.identity))
        S.finish_corroboration_claims(state, {ref.identity: None}, set())
        self.assertNotIn(ref.identity, state["corroboration"])

    def test_separate_field_resolutions_eventually_clear_multi_field_claim(self):
        state = S.empty_state()
        multi = proposal()
        multi["fields"]["place"] = {"value": "Lisbon, Portugal"}
        _, ref = S.observe_verified_claim(
            state, multi,
            {"deadline": "2027-03-15 23:59", "place": "Lisbon, Portugal"},
            "2026-08-31")
        S.resolve_fields(state, "FSE", 2027, {"place"})
        self.assertIn(ref.identity, state["corroboration"])
        self.assertEqual(state["retry"][ref.identity]["fields"], ["deadline"])
        S.resolve_fields(state, "FSE", 2027, {"deadline"})
        self.assertNotIn(ref.identity, state["corroboration"])
        self.assertNotIn(ref.identity, state["retry"])


class Persistence(unittest.TestCase):
    def test_round_trip_and_retry_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            state = S.empty_state()
            S.mark_retry(state, "NSDI", 2027, "2026-08-31", "citation")
            self.assertTrue(S.save(state, path))
            self.assertFalse(S.save(state, path))
            loaded = S.load(path)
            self.assertEqual(S.retry_identities(loaded), {("NSDI", 2027)})
            S.resolve(loaded, "NSDI", 2027)
            self.assertTrue(S.save(loaded, path))

    def test_missing_empty_state_is_not_created(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            self.assertFalse(S.save(S.empty_state(), path))
            self.assertFalse(path.exists())

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            path.write_text(json.dumps({"version": 99}), encoding="utf-8")
            with self.assertRaises(S.StateError):
                S.load(path)

    def test_entry_limit_is_bounded(self):
        state = S.empty_state()
        state["retry"] = {
            f"X{i}\t2027": {"last_seen": "2026-08-31", "reason": "citation"}
            for i in range(S.MAX_STATE_ENTRIES + 1)
        }
        with self.assertRaises(S.StateError):
            S.validate(state)

    def test_old_editions_are_pruned_outside_rendered_window(self):
        state = S.empty_state()
        for year in (2024, 2025, 2027, 2028):
            S.mark_retry(state, "FSE", year, "2026-08-31", "citation")
        S.prune_years(state, 2025, 2027)
        self.assertEqual(S.retry_identities(state), {("FSE", 2025), ("FSE", 2027)})

    def test_retry_scopes_union_and_resolve_independently(self):
        state = S.empty_state()
        key = S.identity_key("FSE", 2027)
        S.mark_retry_fields(state, "FSE", 2027, "2026-08-31", "citation",
                            {"deadline"})
        S.mark_retry_fields(state, "FSE", 2027, "2026-09-01", "citation",
                            {"place"})
        self.assertEqual(state["retry"][key]["fields"], ["deadline", "place"])
        S.resolve_fields(state, "FSE", 2027, {"place"})
        self.assertEqual(state["retry"][key]["fields"], ["deadline"])
        S.resolve_fields(state, "FSE", 2027, {"deadline"})
        self.assertNotIn(key, state["retry"])

    def test_legacy_unscoped_retry_survives_partial_resolution(self):
        state = S.empty_state()
        key = S.identity_key("FSE", 2027)
        state["retry"][key] = {
            "last_seen": "2026-08-31", "reason": "citation",
        }
        S.resolve_fields(state, "FSE", 2027, {"place"})
        self.assertTrue(state["retry"][key]["whole_record"])
        S.resolve(state, "FSE", 2027)
        self.assertNotIn(key, state["retry"])

    def test_legacy_singleton_claim_loads_and_renders_canonically(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            key = S.identity_key("FSE", 2027)
            legacy = S.empty_state()
            legacy["corroboration"][key] = {
                "fingerprint": "sha256:" + "a" * 64,
                "action": "upsert_manual", "fields": ["deadline"],
                "first_seen": "2026-08-31", "last_seen": "2026-08-31",
                "verified_runs": 1,
            }
            path.write_text(json.dumps(legacy), encoding="utf-8")
            loaded = S.load(path)
            self.assertIn("fields:deadline", claims(loaded, key))
            self.assertIn('"claims"', S.render(loaded))

    def test_nested_claim_count_is_bounded(self):
        state = S.empty_state()
        key = S.identity_key("FSE", 2027)
        fields = sorted(S.ALLOWED_SCOPE_FIELDS - {S.DELETE_SCOPE})
        scopes = list(itertools.chain.from_iterable(
            itertools.combinations(fields, size)
            for size in range(1, len(fields) + 1)
        ))[:S.MAX_STATE_ENTRIES + 1]
        state["corroboration"][key] = {"claims": {
            "fields:" + ",".join(scope): {
                "fingerprint": "sha256:" + "a" * 64,
                "action": "upsert_manual", "fields": list(scope),
                "first_seen": "2026-08-31", "last_seen": "2026-08-31",
                "verified_runs": 1,
            }
            for scope in scopes
        }}
        with self.assertRaises(S.StateError):
            S.validate(state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
