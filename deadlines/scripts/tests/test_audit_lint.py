#!/usr/bin/env python3
"""Tests for audit_lint.py, run against throwaway git repos.

Run: python3 deadlines/scripts/tests/test_audit_lint.py

The lint is the gate that stops the audit writing outside deadlines/data, so
it has to be exercised in isolation - running it in the real working tree only
ever tells you about the real working tree.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LINT = Path(__file__).resolve().parents[1] / "audit_lint.py"

CITED_MANUAL = """\
# Header comment for the file.

# Upstream is wrong about this one.
# Verified 2026-08-18 against https://example.org/cfp
- title: "EuroSec"
  year: 2026
  deadline: "2026-02-10 23:59"
"""


class AuditLintInTempRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "deadlines" / "scripts").mkdir(parents=True)
        (self.tmp / "deadlines" / "data" / "conferences" / "2026").mkdir(parents=True)
        shutil.copy(LINT, self.tmp / "deadlines" / "scripts" / "audit_lint.py")
        (self.tmp / "deadlines" / "scripts" / "update_deadlines.py").write_text(
            "# stand-in for the real updater\n", encoding="utf-8")
        self.manual = self.tmp / "deadlines" / "data" / "manual.yml"
        self.manual.write_text(CITED_MANUAL, encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.email", "t@t.t")
        self._git("config", "user.name", "t")
        self._git("add", "-A")
        self._git("commit", "-qm", "base")

    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=self.tmp,
                              capture_output=True, text=True, check=True)

    def _lint(self):
        return subprocess.run(
            [sys.executable, str(self.tmp / "deadlines" / "scripts" / "audit_lint.py")],
            cwd=self.tmp, capture_output=True, text=True)

    def test_clean_tree_passes(self):
        r = self._lint()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_tracked_data_edit_passes(self):
        self.manual.write_text(
            CITED_MANUAL.replace("2026-02-10", "2026-02-17"), encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_untracked_data_file_with_valid_path_passes(self):
        # A new year directory is legitimate: update_deadlines.py creates one
        # with mkdir(parents=True) and its file starts life untracked.
        (self.tmp / "deadlines" / "data" / "conferences" / "2027").mkdir()
        (self.tmp / "deadlines" / "data" / "conferences" / "2027"
         / "security.yml").write_text("[]\n", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_scratch_files_at_the_repo_root_are_litter_not_violations(self):
        # The first live run failed on exactly this: the auditor used curl and
        # left *_fetch.html at the repo root. The workflow stages only
        # `git add -- deadlines/data`, so those files can never reach a commit.
        for name in ("ndss_fetch.html", "acns_fetch.html"):
            (self.tmp / name).write_text("<html>", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ignoring 2 untracked file(s)", r.stdout)

    def test_untracked_file_outside_allowlist_is_caught(self):
        # The regression this fix exists for: `git diff` cannot see this file,
        # but `git add -- deadlines/data` in the workflow would stage it.
        (self.tmp / "deadlines" / "data" / "evil.txt").write_text("x", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("outside the audit allowlist", r.stdout)

    def test_untracked_script_edit_is_caught(self):
        # A prompt-injected auditor rewriting the gate itself.
        (self.tmp / "deadlines" / "scripts" / "sneaky.py").write_text("x", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_tracked_script_edit_is_caught(self):
        (self.tmp / "deadlines" / "scripts" / "update_deadlines.py").write_text(
            "# tampered\n", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_lint_cannot_police_itself(self):
        """Documents WHY the workflow must run the gate from a pristine copy.

        A lint executed from the working tree is exactly as trustworthy as the
        working tree. Overwrite it and it approves everything - no allowlist
        check runs at all. This is not fixable inside audit_lint.py; the
        workflow restores it from HEAD into a temp dir before running it.
        """
        (self.tmp / "deadlines" / "scripts" / "audit_lint.py").write_text(
            "# tampered\n", encoding="utf-8")
        (self.tmp / "deadlines" / "data" / "evil.txt").write_text("x", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 0,
                         "if this now fails, the workflow's pristine-copy step "
                         "may no longer be necessary - recheck before removing it")

    def test_uncited_manual_entry_is_caught(self):
        self.manual.write_text(CITED_MANUAL + """
- title: "DIMVA"
  year: 2026
  deadline: "2026-02-18 23:59"
""", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("citation", r.stdout)

    def test_adjacent_entry_does_not_inherit_the_previous_citation(self):
        # Confirms the comment run resets at each '- title:'. This was reported
        # as a bug during design review; it is not one, and this pins it.
        self.manual.write_text(CITED_MANUAL.rstrip("\n") + """
- title: "DIMVA"
  year: 2026
  deadline: "2026-02-18 23:59"
""", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_ignored_artifacts_do_not_trip_the_allowlist(self):
        (self.tmp / ".gitignore").write_text(
            "__pycache__/\n/watchlist.json\n/audit-summary.md\n", encoding="utf-8")
        self._git("add", ".gitignore")
        self._git("commit", "-qm", "ignore")
        (self.tmp / "watchlist.json").write_text("[]", encoding="utf-8")
        (self.tmp / "audit-summary.md").write_text("x", encoding="utf-8")
        (self.tmp / "deadlines" / "scripts" / "__pycache__").mkdir()
        (self.tmp / "deadlines" / "scripts" / "__pycache__"
         / "m.pyc").write_text("x", encoding="utf-8")
        r = self._lint()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
