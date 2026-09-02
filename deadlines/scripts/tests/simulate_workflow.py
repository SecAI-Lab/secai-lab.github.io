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
import reconcile_audit_outcomes as R  # noqa: E402


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
    require(int(shard.get("timeout-minutes", 0)) >= 120,
            "the shard envelope must fit both reconciliations, two model "
            "attempts, and citation backoff")
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
    reconcile = named_step(
        shard, "Reconcile first-pass transient fetch outcomes"
    ).get("run", "")
    require("--watchlist watchlist.json" in reconcile,
            "transient re-fetches must remain bound to immutable trusted hosts")
    first_check = named_step(shard, "Check first auditor output and citations").get(
        "run", "")
    require("--require-some-proposal" in first_check,
            "an all-unverifiable first pass must receive the bounded retry")
    require("verify_citations.py" in first_check
            and "audit-preflight.json" in first_check
            and '!= "VERIFIED"' in first_check,
            "a complete first pass with weak evidence must receive citation repair")
    final_check = named_step(shard, "Validate final shard contract").get("run", "")
    require("--require-some-proposal" not in final_check,
            "a fully checked all-unverifiable second pass must be allowed to finish")
    require("--allow-unfinished" in final_check
            and "--require-complete" not in final_check,
            "shards must retain raw unfinished checkpoints for clean global finalization")
    require("AUDITOR1_OUTCOME" in final_check and "AUDITOR2_OUTCOME" in final_check,
            "continued auditor action failures must be reported explicitly")

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
    retry_prompt = str((claude_steps[1].get("with") or {}).get("prompt", ""))
    require("audit-preflight.json" in retry_prompt
            and "detail.status" in retry_prompt
            and "REJECTED_SOURCE" in retry_prompt
            and "UNREACHABLE" in retry_prompt
            and retry_prompt.index("REJECTED_SOURCE")
            < retry_prompt.index("repair every field")
            and "strict subset" in retry_prompt
            and "complete atomic deadline context" in retry_prompt,
            "the bounded retry must repair top-level source/reachability "
            "failures before consuming field-level citation diagnostics")
    step_names = [step.get("name") for step in shard.get("steps") or []]
    require("Reconcile final unverifiable source claims" not in step_names,
            "model shards must not perform publication-authority finalization")
    shard_name = named_step(shard, "Name shard output")
    require(str(shard_name.get("if", "")).strip() == "always()",
            "failed shard validation must still retain its raw checkpoint")

    apply = jobs["apply"]
    require(int(apply.get("timeout-minutes", 0)) >= 360,
            "the merged verifier must fit worst-case bounded retries for the full watchlist")
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
    clean_reconcile_name = "Reconcile merged unverifiable source claims independently"
    clean_reconcile = named_step(apply, clean_reconcile_name)
    require(names.index("Merge exact-once audit output")
            < names.index(clean_reconcile_name)
            < names.index("Verify official citations independently"),
            "clean apply job must reconcile negative claims before citation verification")
    clean_reconcile_run = str(clean_reconcile.get("run", ""))
    require("--watchlist watchlist.json" in clean_reconcile_run
            and "--finalize-deferred" in clean_reconcile_run
            and "--require-substantive" in clean_reconcile_run
            and "audit_batches.py validate" in clean_reconcile_run
            and "--audit-date" in clean_reconcile_run
            and "--allow-machine-deferred" in clean_reconcile_run
            and "--require-complete" in clean_reconcile_run
            and "AUDIT DEGRADED" in clean_reconcile_run,
            "clean apply reconciliation must canonicalize retry-only deferrals, "
            "reject total idleness, report degradation, and enforce the strict "
            "final contract")
    require(clean_reconcile.get("continue-on-error") is not True,
            "clean apply reconciliation must fail closed")
    merge_script = named_step(apply, "Merge exact-once audit output").get("run", "")
    require("audit_batches.py merge" in merge_script
            and "--audit-date" in merge_script
            and merge_script.count("--allow-unfinished") >= 3,
            "apply must enforce date-bound exact merge coverage while retaining "
            "raw unfinished checkpoints")
    apply_run = named_step(apply, "Apply independently verified fields").get(
        "run", "")
    require("--allow-machine-deferred" in apply_run
            and "--require-complete" in apply_run,
            "production mutation must independently require canonical finalizer output")
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


def documentation_contract():
    auditor = (REPO / "deadlines" / "scripts" / "AUDITOR.md").read_text(
        encoding="utf-8")
    require("`detail.status` first" in auditor
            and "`REJECTED_SOURCE`" in auditor
            and "`UNREACHABLE`" in auditor
            and auditor.index("`REJECTED_SOURCE`")
            < auditor.index("`detail.fields`"),
            "auditor retry guidance must repair top-level source/reachability "
            "failures before per-field evidence")
    require("never counts as examined" in auditor
            and "zero-work circuit breaker" in auditor,
            "auditor docs must distinguish unfinished checkpoints from findings")

    readme = (REPO / "deadlines" / "scripts" / "README.md").read_text(
        encoding="utf-8")
    require("repairs `REJECTED_SOURCE`/`UNREACHABLE` failures first" in readme,
            "operator docs must describe the retry failure hierarchy")
    require("`machine_deferred`" in readme
            and "global zero-substantive-work guard" in readme
            and "cannot block independently safe corrections" in readme,
            "operator docs must describe safe partial publication and retry")

    design = (REPO / "deadlines" / "scripts" /
              "AUTO-APPLY-DESIGN.md").read_text(encoding="utf-8")
    for stale_claim in (
        "Held items still land as a PR",
        "`AUDIT_AUTO_APPLY=false`",
        "There are no tests in this repo today",
        "## 11. Build order",
    ):
        require(stale_claim not in design,
                f"design record still presents retired behavior: {stale_claim}")
    require("There is no `AUDIT_AUTO_APPLY` PR-mode switch" in design
            and "## 11. Deployed execution order and tests" in design,
            "design record must identify the live no-review state/telemetry flow")
    require("`machine_deferred`" in design
            and "rejects a global zero-substantive-work run" in design,
            "design record must include trusted terminal deferral finalization")


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

        raw_partial = {
            "audit_date": "2026-08-31", "watchlist_size": 2,
            "proposals": [{"title": "C00", "year": 2027}],
            "unverifiable": [{
                "title": "C01", "year": 2027, "cause": "not_checked",
            }],
        }
        B.validate_audit_document(
            watchlist[:2], raw_partial, "raw partial", "2026-08-31",
            allow_unfinished=True)
        finalized, _ = R.finalize_machine_deferred(raw_partial)
        B.validate_audit_document(
            watchlist[:2], finalized, "trusted final", "2026-08-31",
            allow_machine_deferred=True)
        require(R.substantive_work_count(finalized) == 1
                and finalized["machine_deferred"] == [{
                    "title": "C01", "year": 2027,
                    "reason": "audit-incomplete-after-retry",
                }],
                "partial finalization did not retain safe work and queue the idle record")

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
        ("auditor/operator documentation contract", documentation_contract),
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
