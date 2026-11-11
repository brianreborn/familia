"""scripts/android-cockpit-switches.sh: --pipe stays in the menu until q; missing installer degrades."""
import os
import stat
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "android-cockpit-switches.sh")
HOME_SH = os.path.join(ROOT, "scripts", "familia_home.sh")
COMMIT = "a" * 40


def _env(tmp_path, **kw):
    e = dict(os.environ)
    e.pop("FAMILIA_ANDROID_INSTALLER", None)
    e.pop("FAMILIA_SMOKE_PREFIX", None)
    e.pop("FAMILIA_CTX", None)
    e.pop("FAMILIA_ALLOW_YES", None)
    e.pop("FAMILIA_START", None)
    e.pop("FAMILIA_LICENSES", None)
    e["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    e["FAMILIA_SMOKE_PREFIX"] = str(tmp_path / "pfx")
    e["NO_COLOR"] = "1"
    e["FAMILIA_COLOR"] = "never"
    e["FAMILIA_NO_TTY"] = "1"
    e.update(kw)
    return e


def run_sw(tmp_path, *args, inp=None, **kw):
    return subprocess.run(
        ["sh", SCRIPT, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_env(tmp_path, **kw),
        input=inp,
        stdin=None if inp is not None else subprocess.DEVNULL,
        timeout=30,
    )


def test_help_lists_usage():
    r = subprocess.run(
        ["sh", SCRIPT, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=15,
    )
    assert r.returncode == 0, r.stderr
    assert "usage" in (r.stdout + r.stderr).lower()


def test_dump_secure_defaults_when_installer_missing(tmp_path):
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "mode=thin client" in r.stdout
    assert "dry_run=ON" in r.stdout
    assert "allow_yes=OFF" in r.stdout
    assert "start=OFF" in r.stdout
    assert "gate=ON" in r.stdout
    assert "installer=not on this commit" in r.stdout
    assert "installer not available on this commit" in out


def test_pipe_invalid_input_and_missing_installer_return_to_menu(tmp_path):
    # x and 999 are invalid; 19 show-command degrades; q is the only exit.
    r = run_sw(tmp_path, "--pipe", inp="x\n999\n19\n20\nq\n")
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert out.count("ANDROID COCKPIT") >= 5
    assert out.count("isn't one of the choices") == 2
    assert out.count("installer not available on this commit") >= 2
    assert "exit. settings saved" in out
    cfg = tmp_path / "xdg" / "familia" / "android-cockpit.env"
    assert cfg.is_file()
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600


def test_pipe_show_command_with_stub_installer(tmp_path):
    stub = tmp_path / "install-android.sh"
    stub.write_text("#!/bin/sh\nprintf 'stub:%s\\n' \"$*\"\n", encoding="ascii")
    stub.chmod(0o755)
    inp = "9\nexample.host\n10\n8080\n17\n%s\n19\nq\n" % COMMIT
    r = run_sw(tmp_path, "--pipe", inp=inp, FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "isn't one of the choices" not in out
    assert "installer not available on this commit" not in out
    assert "--commit %s" % COMMIT in out
    assert "--host example.host" in out
    assert "--port 8080" in out
    assert "--dry-run" in out
    assert "--licenses llama31,dolphin" in out
    assert "--local-inference" not in out
    assert "--allow-yes" not in out
    assert "--start" not in out
    assert "exit. settings saved" in out


def test_no_tty_without_pipe_exits_2(tmp_path):
    r = run_sw(tmp_path)
    assert r.returncode == 2
    assert "no terminal" in (r.stdout + r.stderr)


def test_familia_home_runs_switches_before_open_ui():
    text = open(HOME_SH, encoding="utf-8").read()
    arm = text.split('"Open llama-ui web cockpit")', 1)[1].split(";;", 1)[0]
    assert "scripts/android-cockpit-switches.sh" in arm
    assert "scripts/open_ui.sh" in arm
    assert arm.find("android-cockpit-switches.sh") < arm.find("open_ui.sh")
