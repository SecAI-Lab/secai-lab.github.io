#!/usr/bin/env python3
"""Deterministic gate for the weekly audit workflow.

Fails (exit 1) unless:
  * every modified tracked file is inside the audit allowlist
    (deadlines/data/manual.yml or deadlines/data/conferences/**), and
  * every manual.yml entry is preceded by a comment block containing
    'Verified' and an http(s) URL (the citation rule).

Run from anywhere inside the repo. Read-only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_RE = re.compile(
    r"^deadlines/data/(manual\.yml|conferences/\d{4}/[a-z]+\.yml)$")


def fail(msg: str) -> None:
    print(f"AUDIT LINT FAIL: {msg}")
    sys.exit(1)


def main() -> int:
    # `git diff` does not list UNTRACKED files, but the workflow's
    # `git add -- deadlines/data` stages them anyway - and the updater
    # legitimately creates untracked files when a new year directory appears.
    # An untracked file outside the allowlist would have sailed straight past
    # this gate and into the commit. `git status --porcelain` sees them.
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    changed, litter = [], []
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        code, path = line[:2], line[3:].strip()
        if " -> " in path:  # rename: only the destination is written
            path = path.split(" -> ", 1)[1]
        path = path.strip('"').replace("\\", "/")
        # An UNTRACKED file outside the pipeline's own directories cannot reach
        # a commit - the workflow stages `git add -- deadlines/data` and nothing
        # else - so scratch files an auditor leaves lying around are litter, not
        # a violation. Report them and move on. Untracked files under
        # deadlines/ or .github/ are still checked: those are the ones that
        # would be staged, or that signal tampering.
        if code == "??" and not path.startswith(("deadlines/", ".github/")):
            litter.append(path)
            continue
        changed.append(path)
    if litter:
        print(f"note: ignoring {len(litter)} untracked file(s) outside the "
              f"pipeline's directories: {litter[:10]}")
    bad = [p for p in changed if not ALLOWED_RE.match(p)]
    if bad:
        fail(f"files outside the audit allowlist were modified: {bad}")

    manual = (REPO_ROOT / "deadlines" / "data" / "manual.yml").read_text(encoding="utf-8")
    # Split into (comment block, entry) pairs: every '- title:' line must be
    # preceded by a comment run that cites a verification URL.
    lines = manual.split("\n")
    comment_run: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("#"):
            comment_run.append(line)
            continue
        if line.startswith("- title:"):
            blob = "\n".join(comment_run)
            if "Verified" not in blob or not re.search(r"https?://", blob):
                fail(f"manual.yml entry at line {i + 1} ({line.strip()}) lacks a "
                     "'Verified <date> against <official URL>' citation comment")
            comment_run = []
        elif line.strip() == "":
            comment_run = []
    print(f"audit lint ok ({len(changed)} changed file(s), all allowlisted; "
          "all manual.yml entries cited)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
