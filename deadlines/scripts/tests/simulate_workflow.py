#!/usr/bin/env python3
"""Offline structural/integration simulation of the sharded audit workflow.

This deliberately does not invoke Claude, fetch the network, touch repository
data, or require a clean working tree. It checks the actual workflow graph and
then exercises the deterministic split/merge and two-run promotion primitives
with temporary files.

Run: python3 deadlines/scripts/tests/simulate_workflow.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "deadlines" / "scripts"))

import audit_batches as B  # noqa: E402
import audit_state as S  # noqa: E402


class SimulationFailure(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise SimulationFailure(message)


def named_step(job, name):
    for step in job.get("steps") or []:
        if step.get("name") == name:
            return step
    raise SimulationFailure(f"missing workflow step: {name}")


def trigger_config(workflow):
    # PyYAML 1.1 treats the unquoted GitHub key `on` as boolean true.
    return workflow.get("on", workflow.get(True, {})) or {}


def workflow_contract():
    path = REPO / ".github" / "workflows" / "audit-deadlines.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs") or {}
    require(set(jobs) == {"prepare", "audit_shard", "apply", "lifecycle"},
            f"unexpected job graph: {sorted(jobs)}")
    require(workflow.get("permissions") == {}, "top-level permissions must be empty")
    require(trigger_config(workflow).get("schedule") == [{"cron": "17 23 * * 0"}],
            "weekly Claude audit schedule drifted from Sunday 23:17 UTC")
    require((workflow.get("concurrency") or {}).get("group") == "deadline-pipeline",
            "weekly audit must serialize with the daily updater")

    prepare = jobs["prepare"]
    require((prepare.get("permissions") or {}).get("contents") == "read",
            "prepare must be read-only")
    require((prepare.get("outputs") or {}).get("source_sha"),
            "prepare must export the immutable repository revision")
    test_script = named_step(prepare, "Run pipeline tests").get("run", "")
    for suite in (
        "test_update_deadlines.py", "test_audit_lint.py",
        "test_apply_proposals.py", "test_audit_state.py",
        "test_audit_batches.py", "test_reconcile_audit_outcomes.py",
        "test_risk_policy.py", "test_verify_citations.py",
        "simulate_workflow.py",
    ):
        require(suite in test_script, f"prepare does not run {suite}")

    shard = jobs["audit_shard"]
    require((shard.get("strategy") or {}).get("max-parallel") == 1,
            "audit shards must be serial to bound subscription usage")
    require((shard.get("permissions") or {}).get("contents") == "read",
            "model job must not receive contents:write")
    checkouts = [step for step in shard.get("steps") or []
                 if str(step.get("uses", "")).startswith("actions/checkout@")]
    require(checkouts and all((step.get("with") or {}).get("persist-credentials") is False
                              for step in checkouts),
            "model checkout must not persist a push credential")
    require(checkouts and all("source_sha" in str((step.get("with") or {}).get("ref", ""))
                              for step in checkouts),
            "model shards must check out the immutable prepare-stage revision")
    tamper_steps = [step.get("run", "") for step in shard.get("steps") or []
                    if "WATCHLIST_SHA" in str(step.get("run", ""))]
    require(len(tamper_steps) == 2
            and all("sha256sum --check --strict" in str(run) for run in tamper_steps),
            "both model attempts must detect root watchlist tampering")
    reconcile = named_step(shard, "Reconcile transient fetch outcomes").get("run", "")
    require("--watchlist watchlist.json" in reconcile,
            "transient re-fetches must remain bound to immutable trusted hosts")
    first_check = named_step(shard, "Check first auditor output completeness").get(
        "run", ""
    )
    require("--require-some-proposal" in first_check,
            "an all-unverifiable first pass must receive the bounded retry")
    final_check = named_step(shard, "Validate final shard contract").get("run", "")
    require("--require-some-proposal" not in final_check,
            "a fully checked all-unverifiable second pass must be allowed to finish")

    claude_steps = [step for step in shard.get("steps") or []
                    if str(step.get("uses", "")).startswith(
                        "anthropics/claude-code-action@")]
    require(len(claude_steps) == 2, "expected a bounded first attempt plus one retry")
    for step in claude_steps:
        ref = step["uses"].split("@", 1)[1]
        require(bool(re.fullmatch(r"[0-9a-f]{40}", ref)),
                "Claude action must be pinned to a full commit SHA")
        require(isinstance(step.get("timeout-minutes"), int),
                "each Claude attempt needs its own timeout")
        args = str((step.get("with") or {}).get("claude_args", ""))
        require("WebFetch" in args and "WebSearch" in args,
                "auditor needs bounded web tools")
        require("Bash" not in args, "model job must not have arbitrary shell access")

    apply = jobs["apply"]
    require((apply.get("permissions") or {}).get("contents") == "write",
            "only apply should publish repository contents")
    apply_checkout = named_step(apply, "Check out trusted repository")
    require("source_sha" in str((apply_checkout.get("with") or {}).get("ref", "")),
            "write-capable apply must start from the immutable source revision")
    names = [step.get("name") for step in apply.get("steps") or []]
    require(names.index("Check out trusted repository")
            < names.index("Download all completed shard outputs")
            < names.index("Merge exact-once audit output"),
            "apply must start fresh, then download and merge untrusted JSON")
    merge_script = named_step(apply, "Merge exact-once audit output").get("run", "")
    require("audit_batches.py merge" in merge_script
            and "--audit-date" in merge_script
            and "--require-complete" in merge_script,
            "apply must enforce date-bound exact complete coverage")
    publish = named_step(apply, "Commit verified corrections to default branch").get(
        "run", ""
    )
    require(publish.index('steps.converge.outputs.degraded')
            < publish.index('git status --porcelain -- deadlines/data'),
            "a degraded no-diff audit must fail instead of closing alerts as healthy")
    require(publish.index('git fetch origin "$DEFAULT_BRANCH"')
            < publish.index('git status --porcelain -- deadlines/data'),
            "input drift must be checked even when the audit produces no data diff")
    require('git diff --quiet "$SOURCE_SHA" "$latest"' in publish
            and "deadlines/" in publish,
            "publication must reject drift anywhere under the deadline application")
    require('git rebase "$latest"' in publish,
            "verified corrections must rebase onto the checked default-branch tip")

    lifecycle = jobs["lifecycle"]
    require(set(lifecycle.get("needs") or []) == {"prepare", "audit_shard", "apply"},
            "lifecycle must reflect every preceding job")
    require((lifecycle.get("env") or {}).get("GH_REPO"),
            "failure alerts need an explicit repository even if checkout failed")
    keepalive = named_step(lifecycle, "Keep the schedule alive").get("run", "")
    require("|| true" not in keepalive,
            "weekly schedule keepalive failures must not be hidden")
    named_step(lifecycle, "File an alert if audit lifecycle maintenance failed")


def daily_workflow_contract():
    path = REPO / ".github" / "workflows" / "update-deadlines.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(trigger_config(workflow).get("schedule") == [{"cron": "17 21 * * *"}],
            "daily static updater schedule drifted from 21:17 UTC")
    require((workflow.get("concurrency") or {}).get("group") == "deadline-pipeline",
            "daily updater must serialize with the weekly audit")
    permissions = workflow.get("permissions") or {}
    require(permissions.get("contents") == "write"
            and permissions.get("issues") == "write",
            "daily updater needs scoped publication and alert permissions")

    jobs = workflow.get("jobs") or {}
    require(set(jobs) == {"update"}, f"unexpected daily job graph: {sorted(jobs)}")
    update = jobs["update"]
    require((update.get("env") or {}).get("DEFAULT_BRANCH"),
            "daily push must target the repository default branch")
    checkout = named_step(update, "Check out repository")
    require("default_branch" in str((checkout.get("with") or {}).get("ref", "")),
            "daily checkout must not assume a branch name")
    activity = named_step(update, "Prevent schedule inactivity disablement").get(
        "run", ""
    )
    require("45 * 24 * 60 * 60" in activity
            and "git commit --allow-empty" in activity
            and 'git push origin "HEAD:$DEFAULT_BRANCH"' in activity,
            "daily workflow needs bounded repository activity before 60-day disablement")
    publish = named_step(update, "Commit and push changes").get("run", "")
    for contract in (
        'git fetch origin "$DEFAULT_BRANCH"',
        'git rebase "$latest"',
        'git merge --ff-only "$latest"',
        "update_deadlines.py --dry-run",
        "audit_lint.py",
        'git push origin "HEAD:$DEFAULT_BRANCH"',
    ):
        require(contract in publish, f"daily post-rebase gate is missing {contract!r}")
    require(publish.index('git fetch origin "$DEFAULT_BRANCH"')
            < publish.index("update_deadlines.py --dry-run"),
            "daily no-op runs must validate the current default-branch tip")
    close = named_step(update, "Close stale pipeline alerts on a healthy run").get(
        "run", ""
    )
    require('title == "Deadline auto-update needs attention"' in close,
            "daily health must not close unrelated deadline-pipeline issues")
    names = [step.get("name") for step in update.get("steps") or []]
    keepalive = named_step(update, "Keep the schedule alive").get("run", "")
    require("|| true" not in keepalive,
            "daily schedule keepalive failures must not be hidden")
    require(names.index("Keep the schedule alive")
            < names.index("File an alert issue on failure"),
            "daily keepalive faults must reach the issue alert step")


def deterministic_integration():
    temp = Path(tempfile.mkdtemp())
    try:
        watchlist = [
            {"title": f"C{i:02d}", "year": 2027, "record": {},
             "reasons": ["scheduled-full-audit"]}
            for i in range(23)
        ]
        watchlist_path = temp / "watchlist.json"
        watchlist_path.write_text(json.dumps(watchlist), encoding="utf-8")
        shard_paths = B.write_watchlist_shards(watchlist_path, temp / "shards", 10)
        require([len(json.loads(path.read_text(encoding="utf-8")))
                 for path in shard_paths] == [10, 10, 3],
                "23 records did not split into stable 10/10/3 shards")

        empty_watchlist_path = temp / "empty-watchlist.json"
        empty_watchlist_path.write_text("[]\n", encoding="utf-8")
        empty_paths = B.write_watchlist_shards(
            empty_watchlist_path, temp / "empty-shards", 10)
        require(empty_paths == [], "an empty watchlist unexpectedly created work")
        # Mirrors the workflow's matrix-safe fallback: the sole shard remains
        # valid input and exact coverage requires zero records.
        fallback = temp / "empty-shards" / "watchlist-001.json"
        fallback.write_text(empty_watchlist_path.read_text(encoding="utf-8"),
                            encoding="utf-8")
        B.validate_audit_document([], {
            "audit_date": "2026-08-31", "watchlist_size": 0,
            "proposals": [], "unverifiable": [],
        }, "empty fallback", "2026-08-31")

        documents = []
        for number, shard_path in enumerate(shard_paths, 1):
            shard = json.loads(shard_path.read_text(encoding="utf-8"))
            doc = {
                "audit_date": "2026-08-31",
                "watchlist_size": len(shard),
                "proposals": [],
                "unverifiable": [
                    {"title": item["title"], "year": item["year"],
                     "cause": "no_official_page",
                     "attempted": [f"https://official.example/{item['title']}"]}
                    for item in shard
                ],
            }
            B.validate_audit_document(
                shard, doc, f"shard {number}", "2026-08-31")
            documents.append((f"shard {number}", doc))

        merged = B.merge_audit_documents(
            watchlist, documents, "2026-08-31")
        require(merged["watchlist_size"] == 23
                and len(merged["unverifiable"]) == 23,
                "exact-once merge lost work")
        require([item["title"] for item in merged["unverifiable"]]
                == [item["title"] for item in watchlist],
                "merge did not preserve stable watchlist order")

        state = S.empty_state()
        proposal = {
            "action": "upsert_manual", "title": "C00", "year": 2027,
            "fields": {"deadline": {"value": "2027-03-15 23:59"}},
        }
        first, _ = S.observe_verified(
            state, proposal, {"deadline": "2027-03-15 23:59"}, "2026-08-31")
        second, _ = S.observe_verified(
            state, proposal, {"deadline": "2027-03-15 23:59"}, "2026-09-07")
        require(not first and second,
                "two distinct identical verified runs did not promote deterministically")
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main():
    checks = [
        ("workflow trust/coverage contract", workflow_contract),
        ("daily static workflow contract", daily_workflow_contract),
        ("deterministic shard/state integration", deterministic_integration),
    ]
    failures = []
    for label, check in checks:
        try:
            check()
            print(f"PASS  {label}")
        except Exception as exc:  # noqa: BLE001 - report every structural failure
            failures.append(f"{label}: {exc}")
            print(f"FAIL  {label}: {exc}")
    if failures:
        print("\n" + "\n".join(failures))
        return 1
    print("\nALL WORKFLOW SIMULATIONS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
