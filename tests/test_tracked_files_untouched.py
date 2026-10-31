"""Guard: tests must not modify tracked files (issue: test isolation).

Runs the generate/modify graph tests in a subprocess and asserts that
`git status --porcelain` is unchanged. Skips outside a git checkout.
"""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _status():
    return subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(shutil.which("git") is None or not os.path.isdir(os.path.join(ROOT, ".git")),
                    reason="needs a git checkout")
def test_graph_tests_leave_tracked_files_unchanged(tmp_path):
    before = _status()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--basetemp", str(tmp_path / "bt"),
         "tests/test_node_role_private.py", "tests/test_activate_guardian_weights.py"],
        cwd=ROOT, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k != "FAMILIA_GENERATED_DIR"},
    )
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert _status() == before, "tests modified tracked files:\n" + _status()
