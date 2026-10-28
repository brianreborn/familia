"""install.sh must never reach sudo / package installs without an explicit --auto-deps.

sudo can succeed silently from its credential cache, so a prompt is never
consent. A PATH shim records any sudo call; a stub install/deps.sh records
any --install call.
"""
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _setup(tmp_path):
    log = tmp_path / "calls.log"
    src = tmp_path / "src"
    (src / "install").mkdir(parents=True)
    (src / "install" / "deps.sh").write_text(
        f'#!/bin/sh\necho "deps.sh $*" >> "{log}"\n'
        'echo "deps.sh: missing: python3-yaml; suggested: sudo apt-get install -y python3-yaml" >&2\nexit 1\n')
    _git("init", "-q", "-b", "main", cwd=src)
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "stub", cwd=src)
    prefix = tmp_path / "prefix"
    _git("clone", "-q", str(src), str(prefix), cwd=tmp_path)
    shim = tmp_path / "bin"
    shim.mkdir()
    for name in ("sudo", "apt-get", "pacman", "dnf", "zypper", "doas"):
        p = shim / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit 99\n')
        p.chmod(0o755)
    env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "INSTALL_PREFIX": str(prefix),
           "HOME": str(tmp_path / "home"), "PIP_NO_INDEX": "1", "PYTHONUSERBASE": str(tmp_path / "pyuser")}
    env.pop("AUTO_DEPS", None)
    shutil.copy(REPO / "install.sh", tmp_path / "install-familia.sh")
    return log, env


def _run(tmp_path, env, *args):
    return subprocess.run(["sh", str(tmp_path / "install-familia.sh"), "--no-start", "--no-path", *args],
                          env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)


def test_install_ack_does_not_sudo(tmp_path):
    log, env = _setup(tmp_path)
    env["INSTALL_ACK"] = "yes"
    r = _run(tmp_path, env)
    calls = log.read_text() if log.exists() else ""
    assert r.returncode != 0
    assert "sudo" not in calls and "apt-get" not in calls and "pacman" not in calls
    assert "--install" not in calls
    assert "--auto-deps" in r.stderr


def test_yes_flag_does_not_sudo(tmp_path):
    log, env = _setup(tmp_path)
    r = _run(tmp_path, env, "--yes")
    calls = log.read_text() if log.exists() else ""
    assert r.returncode != 0
    assert "--install" not in calls and "sudo" not in calls


def test_auto_deps_warns_before_root(tmp_path):
    log, env = _setup(tmp_path)
    env["INSTALL_ACK"] = "yes"
    r = _run(tmp_path, env, "--auto-deps")
    calls = log.read_text()
    assert "deps.sh --install" in calls
    assert "AS ROOT" in r.stderr
