"""install/freebsd/install-familia.sh: POSIX sh, opt-in root, 0600 key, F-6 refusal."""
import os, shutil, subprocess, stat
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "install" / "freebsd" / "install-familia.sh"


def _env(tmp_path, with_llama=True):
    log = tmp_path / "calls.log"
    shim = tmp_path / "bin"; shim.mkdir()
    for name in ("sudo", "doas", "pkg"):
        p = shim / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit 99\n'); p.chmod(0o755)
    if with_llama:
        p = shim / "llama-server"
        p.write_text(f'#!/bin/sh\necho "llama-server $*" >> "{log}"\n'); p.chmod(0o755)
    src = tmp_path / "src"; src.mkdir()
    g = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (src / "README").write_text("x\n")
    for a in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "s"]):
        subprocess.run(["git", *a], cwd=src, check=True, env=g, capture_output=True)
    home = tmp_path / "home"; home.mkdir()
    return log, {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "HOME": str(home),
                 "FAMILIA_REPO_URL": str(src), "FAMILIA_ALLOW_NON_FREEBSD": "yes",
                 "PYTHONUSERBASE": os.environ.get("PYTHONUSERBASE", os.path.expanduser("~/.local"))}


def _sh(args, env, shell="sh", **kw):
    return subprocess.run([shell, str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL, **kw)


@pytest.mark.parametrize("shell", ["sh", "dash", "posh"])
def test_syntax(shell):
    if not shutil.which(shell):
        pytest.skip(shell)
    subprocess.run([shell, "-n", str(SCRIPT)], check=True)


def test_shellcheck():
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck")
    subprocess.run(["shellcheck", "-s", "sh", str(SCRIPT)], check=True)


def test_missing_deps_halts_without_root(tmp_path):
    log, env = _env(tmp_path, with_llama=False)
    r = _sh([], env)
    assert r.returncode != 0 and "missing dependencies" in r.stderr
    assert not log.exists() or not log.read_text()
    r = _sh(["--auto-deps"], env)  # no tty: must refuse, not call sudo/doas
    assert r.returncode != 0
    assert not log.exists() or not log.read_text()


def test_dry_run_changes_nothing(tmp_path):
    log, env = _env(tmp_path)
    r = _sh(["--dry-run"], env)
    assert r.returncode == 0, r.stderr
    assert list(Path(env["HOME"]).iterdir()) == []


def test_install_key_and_launcher(tmp_path):
    log, env = _env(tmp_path)
    r = _sh(["--yes"], env)
    assert r.returncode == 0, r.stderr
    home = Path(env["HOME"])
    key = home / ".config/familia/api.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600 and len(key.read_text()) == 64
    assert (home / ".local/share/familia/repo/README").exists()
    launch = home / ".local/bin/familia-start"
    model = tmp_path / "m.gguf"; model.write_text("")
    base = {**env, "FAMILIA_MODEL": str(model)}
    for extra in ("--host 0.0.0.0", "--port=1", "--api-key x", "--ssl-key-file k"):
        r = subprocess.run(["sh", str(launch)], env={**base, "FAMILIA_EXTRA": extra},
                           capture_output=True, text=True)
        assert r.returncode == 2 and "refusing" in r.stderr, extra
    r = subprocess.run(["sh", str(launch), "--host=0.0.0.0"], env=base, capture_output=True, text=True)
    assert r.returncode == 2
    r = subprocess.run(["sh", str(launch)], env={**base, "FAMILIA_BIND": "0.0.0.0"}, capture_output=True, text=True)
    assert r.returncode == 2
    key.chmod(0o644)
    r = subprocess.run(["sh", str(launch)], env=base, capture_output=True, text=True)
    assert r.returncode == 2 and "0600" in r.stderr
    key.chmod(0o600)
    r = subprocess.run(["sh", str(launch)], env=base, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    call = log.read_text()
    assert "--host 127.0.0.1" in call and f"--api-key-file {key}" in call
    assert "sudo" not in call and "doas" not in call and "pkg " not in call
    # idempotent: second run keeps the key
    k1 = key.read_text(); assert _sh(["--yes"], env).returncode == 0; assert key.read_text() == k1
