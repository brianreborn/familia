"""Root attestation in install/linux/install.sh (fresh root-only bootstrap).

Fakes EUID with an `id` stub first on PATH; uses --uninstall --dry-run so
nothing is touched and no network is used.
"""
import os
import pty
import select
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, "install/linux/install.sh")
DEPS = os.path.join(ROOT, "install/linux/deps.sh")


def _env(tmp_path, uid, **extra):
    stub = tmp_path / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "id").write_text('#!/bin/sh\n[ "$1" = -u ] && { echo %d; exit 0; }\nexec /usr/bin/id "$@"\n' % uid)
    (stub / "id").chmod(0o755)
    env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}",
               FAMILIA_PREFIX=str(tmp_path / "prefix"), FAMILIA_BIN_DIR=str(tmp_path / "bin"))
    env.pop("FAMILIA_ALLOW_ROOT", None)
    env.update(extra)
    return env


def _run(tmp_path, uid, *args, **extra):
    return subprocess.run(["sh", INSTALL, "--uninstall", "--dry-run", *args], cwd=ROOT,
                          env=_env(tmp_path, uid, **extra), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=30)


def _run_tty(tmp_path, uid, answer):
    """Run with a pseudo-terminal on stdin and type `answer`."""
    master, slave = pty.openpty()
    p = subprocess.Popen(["sh", INSTALL, "--uninstall", "--dry-run"], cwd=ROOT,
                         env=_env(tmp_path, uid), stdin=slave,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    os.close(slave)
    os.write(master, (answer + "\n").encode())
    out, err = p.communicate(timeout=30)
    os.close(master)
    return p.returncode, err


def test_non_root_unaffected(tmp_path):
    r = _run(tmp_path, 1000)
    assert r.returncode == 0, r.stderr
    assert "as root" not in r.stderr and "uninstalled" in r.stderr


def test_root_non_interactive_refused_with_one_line_attestation(tmp_path):
    r = _run(tmp_path, 0)
    assert r.returncode != 0
    assert "warning: do not run as root" in r.stderr
    assert f"FAMILIA_ALLOW_ROOT=yes sh {INSTALL} --uninstall --dry-run" in r.stderr
    assert "uninstalled" not in r.stderr


def test_root_attested_by_env_or_flag(tmp_path):
    for args, extra in (((), {"FAMILIA_ALLOW_ROOT": "yes"}), (("--allow-root",), {}), (("--yes",), {})):
        r = _run(tmp_path, 0, *args, **extra)
        assert r.returncode == 0, (args, r.stderr)
        assert "continuing as root" in r.stderr and "uninstalled" in r.stderr


def test_root_interactive_yes_allowed(tmp_path):
    rc, err = _run_tty(tmp_path, 0, "YES")
    assert rc == 0, err
    assert "Type yes to continue as root:" in err and "uninstalled" in err


def test_root_interactive_other_answer_aborts(tmp_path):
    for ans in ("no", "y", ""):
        rc, err = _run_tty(tmp_path, 0, ans)
        assert rc != 0, (ans, err)
        assert "not confirmed; aborting" in err and "uninstalled" not in err


def _deps_cmd(tmp_path, uid):
    # Minimal PATH (no git/curl/python3) so deps.sh always has something to install;
    # --dry-run only prints the command.
    import shutil
    d = tmp_path / f"min{uid}"
    d.mkdir()
    (d / "id").write_text("#!/bin/sh\necho %d\n" % uid)
    (d / "id").chmod(0o755)
    for t in ("uname", "sed", "cat", "grep", "tr"):
        os.symlink(shutil.which(t), d / t)
    (d / "apt-get").write_text("#!/bin/sh\nexit 0\n")
    (d / "apt-get").chmod(0o755)
    r = subprocess.run(["/bin/sh", DEPS, "--install", "--dry-run", "--yes"], cwd=ROOT,
                       env={"PATH": str(d), "HOME": str(tmp_path)}, capture_output=True, text=True, timeout=30)
    return [l for l in r.stderr.splitlines() if "suggested:" in l]


def test_deps_as_root_skips_sudo(tmp_path):
    root = _deps_cmd(tmp_path, 0)
    assert root and "apt-get install" in root[0] and "sudo" not in root[0], root
    user = _deps_cmd(tmp_path, 1000)
    assert user and "sudo apt-get install" in user[0], user
