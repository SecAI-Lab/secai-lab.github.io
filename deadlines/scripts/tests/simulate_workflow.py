#!/usr/bin/env python3
"""Run the audit workflow's real shell steps locally, Claude step stubbed.

Extracts each `run:` block verbatim from the YAML so we are testing the text
that will actually execute in CI, not a paraphrase of it.

Run: python3 deadlines/scripts/tests/simulate_workflow.py

Requires a CLEAN working tree. The tamper check and audit_lint will correctly
flag your own uncommitted edits to pipeline files, so commit first, then run.
"""
import re
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
import yaml  # noqa: E402

WF = yaml.safe_load((REPO / ".github/workflows/audit-deadlines.yml").read_text(encoding="utf-8"))
STEPS = {s.get("name"): s for s in WF["jobs"]["audit"]["steps"]}


def run_step(name, subs, env_extra=None):
    """Execute a step's run: block with GitHub expressions substituted."""
    script = STEPS[name]["run"]
    for k, v in subs.items():
        script = script.replace(k, v)
    if re.search(r"\$\{\{", script):
        leftover = re.findall(r"\$\{\{[^}]*\}\}", script)
        return None, f"UNSUBSTITUTED EXPRESSION(S): {leftover}"
    env = dict(os.environ)
    env.update(env_extra or {})
    p = subprocess.run(["bash", "-e", "-c", script], cwd=REPO, env=env,
                       capture_output=True, text=True)
    return p, None


def main():
    tmp = Path(tempfile.mkdtemp())
    out, summary = tmp / "gh_output", tmp / "gh_summary"
    out.touch(); summary.touch()
    env = {"GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)}
    subs = {"${{ steps.today.outputs.date }}": "2026-08-19",
            "${{ steps.watchlist.outputs.count }}": "30",
            "${{ steps.converge.outputs.degraded }}": "",
            "${{ github.token }}": "dummy"}
    failures = []

    def check(label, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    print("== Run pipeline tests ==")
    p, err = run_step("Run pipeline tests", subs, env)
    check("tests pass", err is None and p.returncode == 0, err or p.stderr[-200:])

    print("== Build watchlist ==")
    p, err = run_step("Build watchlist", subs, env)
    count = re.search(r"count=(\d+)", out.read_text(encoding="utf-8"))
    check("watchlist built", err is None and p.returncode == 0 and count is not None,
          f"count={count.group(1) if count else '?'}")

    print("== Assert the auditor touched only its proposals file ==")
    p, err = run_step("Assert the auditor touched only its proposals file", subs, env)
    check("clean tree passes tamper check", err is None and p.returncode == 0,
          (p.stdout + p.stderr)[-200:] if p else err)

    print("== Validate proposals: NO FILE (must fail) ==")
    (REPO / "audit-proposals.json").unlink(missing_ok=True)
    p, err = run_step("Validate proposals", subs, env)
    check("missing file fails the step", err is None and p.returncode == 1,
          f"exit={p.returncode if p else err}")
    check("missing file is reported as an error",
          p is not None and "::error::" in p.stdout)

    print("== Validate proposals: EMPTY-EFFORT FILE (must fail) ==")
    subprocess.run([sys.executable, "deadlines/scripts/apply_proposals.py",
                    "--seed-from-watchlist", "watchlist.json",
                    "--audit-date", "2026-08-19"], cwd=REPO, capture_output=True)
    p, err = run_step("Validate proposals", subs, env)
    check("0-examined file fails the step (PIPESTATUS wiring)",
          err is None and p.returncode == 1, f"exit={p.returncode if p else err}")
    check("examined line reached the summary", "examined: 0/30" in summary.read_text(encoding="utf-8"))

    print("== Validate proposals: REAL WORK (must pass) ==")
    import json
    d = json.loads((REPO / "audit-proposals.json").read_text(encoding="utf-8"))
    moved = d["unverifiable"][:2]
    d["proposals"] = [{"id": f"no_change:{m['title']}:{m['year']}", "action": "no_change",
                       "title": m["title"], "year": m["year"],
                       "reason": "Checked against the official CFP; record is correct.",
                       "source_url": "https://example.org/cfp",
                       "watchlist_reasons": ["tba-upcoming-cycle"],
                       "checked_fields": ["deadline"]} for m in moved]
    d["unverifiable"] = d["unverifiable"][2:]
    for u in d["unverifiable"]:
        u["cause"] = "no_official_page"
    (REPO / "audit-proposals.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
    p, err = run_step("Validate proposals", subs, env)
    check("worked file passes", err is None and p.returncode == 0,
          f"exit={p.returncode if p else err}")

    print("== Apply proposals (all no_change -> nothing applied) ==")
    p, err = run_step("Apply proposals", subs, env)
    check("apply succeeds", err is None and p.returncode == 0,
          (p.stdout.strip().splitlines() or [""])[-1] if p else err)

    print("== Converge and lint ==")
    p, err = run_step("Converge and lint", subs, env)
    check("converge+lint pass", err is None and p.returncode == 0,
          (p.stdout + p.stderr).strip().splitlines()[-1] if p else err)

    print("== Data untouched ==")
    g = subprocess.run(["git", "status", "--porcelain", "--", "deadlines/data"],
                       cwd=REPO, capture_output=True, text=True)
    check("no data changes", g.stdout.strip() == "", g.stdout.strip())

    for f in ("audit-proposals.json", "watchlist.json", "audit-summary.md"):
        (REPO / f).unlink(missing_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'ALL STEPS PASS' if not failures else 'FAILURES: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
