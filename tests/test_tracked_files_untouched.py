"""Guard: tests must not modify tracked files (issue: test isolation, #241).

Runs the graph, guardian-weights and menu tests in a subprocess and asserts that
`git status --porcelain -z` is unchanged. Skips only outside a git work tree
(a worktree, where .git is a file, still runs the guard).
"""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARDED = (
    "tests/test_node_role_private.py",
    "tests/test_activate_guardian_weights.py",
    "tests/test_menu.py",
)

# Failures already present on main (tracked in the 31-failure baseline). Any other
# inner failure, or any pytest error exit (rc >= 2), fails this guard.
KNOWN_FAILING = {
    "tests/test_menu.py::test_item_has_real_command_and_dry_runs[test.offline-secbench]",
    "tests/test_menu.py::test_every_user_facing_script_is_in_the_menu",
    "tests/test_menu.py::test_internal_list_is_current",
    "tests/test_menu.py::test_no_hardcoded_homes",
    "tests/test_menu.py::test_commands_doc_lists_every_item",
}


def _in_work_tree():
    if shutil.which("git") is None:
        return False
    r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def _status():
    return subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=no"],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(not _in_work_tree(), reason="needs a git work tree")
def test_guarded_tests_leave_tracked_files_unchanged(tmp_path):
    before = _status()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-rf", "--basetemp", str(tmp_path / "bt"), *GUARDED],
        cwd=ROOT, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items()
             if k not in ("FAMILIA_GENERATED_DIR", "FAMILIA_MODEL_DB_DIR")},
    )
    after = _status()
    assert after == before, "tests modified tracked files:\n" + after.replace("\0", "\n")
    out = r.stdout + r.stderr
    assert r.returncode in (0, 1), "inner pytest errored (rc=%d):\n%s" % (r.returncode, out[-4000:])
    failed = {ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("FAILED ")}
    assert (r.returncode == 1) == bool(failed), out[-4000:]
    new = failed - KNOWN_FAILING
    assert not new, "new failures in guarded tests:\n" + "\n".join(sorted(new))
