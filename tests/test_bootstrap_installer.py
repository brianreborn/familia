"""The bootstrap installer follows the selected branch, not origin/main."""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLER = os.path.join(ROOT, "install.sh")


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def test_existing_bootstrap_install_tracks_and_updates_selected_branch(tmp_path):
    seed = tmp_path / "seed"
    remote = tmp_path / "remote.git"
    prefix = tmp_path / "familia"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    git(seed, "config", "user.name", "Installer test")
    git(seed, "config", "user.email", "installer@example.invalid")
    (seed / "scripts").mkdir()
    (seed / "scripts/licenses.py").write_text("raise SystemExit(0)\n")
    (seed / "scripts/configure.sh").write_text("#!/bin/sh\nexit 0\n")
    (seed / "main-only").write_text("main\n")
    git(seed, "add", ".")
    git(seed, "commit", "-qm", "initial")
    git(seed, "switch", "-qc", "feature")
    (seed / "feature-only").write_text("feature v1\n")
    git(seed, "add", ".")
    git(seed, "commit", "-qm", "feature v1")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-q", "--all", "origin")

    env = dict(os.environ, INSTALL_PREFIX=str(prefix), FAMILIA_REPO_URL=str(remote),
               INSTALL_ACK="yes", INSTALL_NO_START="1", INSTALL_NO_PATH="1")
    first = subprocess.run(["sh", INSTALLER, "--branch", "feature"], env=env,
                           capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stdout + first.stderr
    assert git(prefix, "branch", "--show-current").stdout.strip() == "feature"
    assert git(prefix, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}").stdout.strip() == "origin/feature"

    (seed / "feature-only").write_text("feature v2\n")
    git(seed, "add", "feature-only")
    git(seed, "commit", "-qm", "feature v2")
    git(seed, "push", "-q", "origin", "feature")
    second = subprocess.run(["sh", INSTALLER, "--no-start", "--no-path"], env=env,
                            capture_output=True, text=True, timeout=60)
    assert second.returncode == 0, second.stdout + second.stderr
    assert git(prefix, "branch", "--show-current").stdout.strip() == "feature"
    assert (prefix / "feature-only").read_text() == "feature v2\n"
