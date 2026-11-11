"""scripts/android-cockpit-switches.sh: menu stays until q; review fixes."""
import fcntl
import struct
import termios
import os
import pty
import shutil
import stat
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "android-cockpit-switches.sh")
HOME_SH = os.path.join(ROOT, "scripts", "familia_home.sh")
COMMIT = "a" * 40
SHA256 = "b" * 64
DASH = shutil.which("dash")
MKSH = shutil.which("mksh")


def _flat(text):
    # say_row wraps at COLUMNS and prefixes continuations with 4 spaces.
    # Join those back so path and phrase assertions still match.
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n    ", "")


def _has(text, phrase):
    if phrase in text or phrase in _flat(text):
        return True
    return phrase.replace(" ", "") in _flat(text).replace(" ", "")


def _env(tmp_path, **kw):
    e = dict(os.environ)
    for k in (
        "FAMILIA_ANDROID_INSTALLER",
        "FAMILIA_SMOKE_PREFIX",
        "FAMILIA_CTX",
        "FAMILIA_ALLOW_YES",
        "FAMILIA_START",
        "FAMILIA_LICENSES",
        "FAMILIA_ACCEPT_LICENSES",
        "FAMILIA_ACCEPT_UNKNOWN_LICENSES",
        "FAMILIA_LICENSE_ACCEPT_FILE",
        "INSTALL_ACK",
        "FAMILIA_BIND",
        "FAMILIA_RAM_MIB",
        "FAMILIA_RESERVE_MIB",
        "FAMILIA_MIN_USABLE_MIB",
        "FAMILIA_MENU_TIMEOUT",
        "FAMILIA_DEV_ALLOW_HTTP",
        "FAMILIA_COCKPIT_HOOK",
    ):
        e.pop(k, None)
    e["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    e["FAMILIA_SMOKE_PREFIX"] = str(tmp_path / "pfx")
    e["NO_COLOR"] = "1"
    e["FAMILIA_COLOR"] = "never"
    e["FAMILIA_NO_TTY"] = "1"
    e["COLUMNS"] = "80"
    e["LINES"] = "50"
    e.update(kw)
    return e


def run_sw(tmp_path, *args, inp=None, exe="sh", **kw):
    return subprocess.run(
        [exe, SCRIPT, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_env(tmp_path, **kw),
        input=inp,
        stdin=None if inp is not None else subprocess.DEVNULL,
        timeout=30,
    )


def write_cfg(tmp_path, body, mode=0o600, crlf=False):
    path = tmp_path / "xdg" / "familia" / "android-cockpit.env"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = body if body.endswith("\n") else body + "\n"
    if crlf:
        data = data.replace("\n", "\r\n")
    path.write_bytes(data.encode("ascii"))
    os.chmod(path, mode)
    return path


def write_stub(tmp_path, name, extra=""):
    d = tmp_path / "John Doe" / "bin"
    d.mkdir(parents=True, exist_ok=True)
    stub = d / name
    stub.write_text(
        "#!/bin/sh\n"
        "argvf=${FAMILIA_ARGV_FILE:-/tmp/familia-cockpit-argv}\n"
        "printf 'ARGC=%s\\n' \"$#\" > \"$argvf\"\n"
        "for a in \"$@\"; do printf '%s\\n' \"$a\" >> \"$argvf\"; done\n"
        "env | grep -E '^(FAMILIA_CBL|FAMILIA_BIND|FAMILIA_ACCEPT|FAMILIA_ALLOW_|FAMILIA_RUNTIME|FAMILIA_HERMES)=' >> \"$argvf\" || true\n"
        "for v in INSTALL_ACK FAMILIA_ACCEPT_LICENSES FAMILIA_ACCEPT_UNKNOWN_LICENSES FAMILIA_LICENSE_ACCEPT_FILE FAMILIA_ALLOW_YES FAMILIA_HERMES_CTX_GATE FAMILIA_BIND FAMILIA_ALLOW_EXTRA; do "
        "if printenv \"$v\" >/dev/null 2>&1; then printf 'LEAKED %s=%s\\n' \"$v\" \"$(printenv \"$v\")\" >> \"$argvf\"; "
        "else printf 'SCRUBBED %s\\n' \"$v\" >> \"$argvf\"; fi; done\n"
        "printf 'stub:%s\\n' \"$*\"\n"
        + extra,
        encoding="ascii",
    )
    stub.chmod(0o755)
    return stub


def write_key(tmp_path, mode=0o600):
    path = tmp_path / "xdg" / "familia" / "api.key"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text("test-key-not-a-secret\n", encoding="ascii")
    os.chmod(path, mode)
    return path


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
    assert "https=OFF" in r.stdout
    assert "host=127.0.0.1" in r.stdout
    assert "port=9941" in r.stdout
    assert "url=http://127.0.0.1:9941" in r.stdout
    assert "listener: no key (loopback)" in r.stdout
    assert "example.host" not in r.stdout
    # install/termux/install.sh is already on main; smoke/hermes-android are not.
    assert ("installer=not on this commit" in r.stdout) or ("install.sh" in r.stdout)


def test_pipe_invalid_input_and_missing_installer_return_to_menu(tmp_path):
    r = run_sw(tmp_path, "--pipe", inp="x\n999\n21\nq\n")
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert out.count("ANDROID COCKPIT") >= 4
    assert out.count("isn't one of the choices") == 2
    assert "exit. settings saved" in out
    cfg = tmp_path / "xdg" / "familia" / "android-cockpit.env"
    assert cfg.is_file()
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600


def test_pipe_show_command_with_smoke_stub(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    argvf = tmp_path / "argv.txt"
    inp = "9\n127.0.0.1\n10\n8080\n20\n%s\n21\nq\n" % COMMIT
    r = run_sw(
        tmp_path,
        "--pipe",
        inp=inp,
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "isn't one of the choices" not in out
    assert "installer not available on this commit" not in out
    assert "--commit" in out and COMMIT in out
    assert "--host" in out and "127.0.0.1" in out
    assert "--port" in out and "8080" in out
    assert "--dry-run" in out
    cmd = out.split("will run:", 1)[-1] if "will run:" in out else out
    if "command:" in cmd:
        cmd = cmd.split("command:", 1)[-1]
    quoted = []
    for line in out.splitlines():
        if "will run:" in line or line.strip().startswith("'env'") or line.strip().startswith("command:"):
            quoted.append(line)
    q = "\n".join(quoted)
    assert "--allow-yes" not in q
    assert " '--yes'" not in q and " --yes'" not in q
    assert "--start" not in q
    assert "--no-ctx-gate" not in q
    assert "--licenses" not in q
    assert "--local-inference" not in q
    assert "n/a: familia-android-smoke.sh has no such flag" in out
    assert "typed ACCEPT is required; this screen never passes --yes" in out
    assert "exit. settings saved" in out


def test_no_tty_without_pipe_exits_2(tmp_path):
    r = run_sw(tmp_path)
    assert r.returncode == 2
    assert "no terminal" in (r.stdout + r.stderr)


def test_familia_home_q_does_not_open_ui_continue_does():
    text = open(HOME_SH, encoding="utf-8").read()
    arm = text.split('"Open llama-ui web cockpit")', 1)[1].split(";;", 1)[0]
    assert "scripts/android-cockpit-switches.sh" in arm
    assert "scripts/open_ui.sh" in arm
    assert "scripts/familia_home.sh" in arm
    code = "\n".join(ln for ln in arm.splitlines() if not ln.lstrip().startswith("#"))
    assert code.find("android-cockpit-switches.sh") < code.find("open_ui.sh")
    # q / other statuses re-exec home; only status 4 opens the UI.
    assert "-eq 4" in code
    assert "FAMILIA_COCKPIT_HOOK" in code
    assert code.find("open_ui.sh") < code.find('familia_home.sh')


def test_continue_item_exits_4(tmp_path):
    r = run_sw(tmp_path, "--pipe", inp="c\n", FAMILIA_COCKPIT_HOOK="1")
    assert r.returncode == 4, r.stderr + r.stdout
    assert "continue to web cockpit" in (r.stdout + r.stderr)
    # Without the hook (legacy catalog / --pipe), c stays in the menu
    # and explains that the web cockpit opens via familia_home.
    r = run_sw(tmp_path, "--pipe", inp="c\nq\n")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "familia home menu" in (r.stdout + r.stderr)


def test_crlf_config_keeps_secure_defaults(tmp_path):
    write_cfg(
        tmp_path,
        "THIN_CLIENT=1\nDRY_RUN=1\nCTX_GATE=1\nALLOW_YES=0\nSTART_FAMILIA=0\nHTTPS=0\n",
        crlf=True,
    )
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    assert "mode=thin client" in r.stdout
    assert "dry_run=ON" in r.stdout
    assert "gate=ON" in r.stdout
    assert "allow_yes=OFF" in r.stdout


def test_junk_bool_falls_back_and_warns(tmp_path):
    write_cfg(tmp_path, "THIN_CLIENT=yes\nDRY_RUN=maybe\nCTX_GATE=2\n")
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    err = r.stderr
    assert "ignoring invalid THIN_CLIENT" in err
    assert "ignoring invalid DRY_RUN" in err
    assert "ignoring invalid CTX_GATE" in err
    assert "mode=thin client" in r.stdout
    assert "dry_run=ON" in r.stdout
    assert "gate=ON" in r.stdout


def test_duplicate_key_warns_and_keeps_first(tmp_path):
    write_cfg(tmp_path, "HOST=localhost\nHOST=evil.example\nPORT=8080\n")
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    assert "duplicate settings key HOST" in r.stderr
    assert "host=localhost" in r.stdout
    assert "evil.example" not in r.stdout


def test_host_flag_injection_and_semicolon_rejected(tmp_path):
    write_cfg(tmp_path, "HOST=a;touch X\nPORT=8080\nCOMMIT=%s\n" % COMMIT)
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    assert "ignoring invalid HOST" in r.stderr
    assert "host=127.0.0.1" in r.stdout
    write_cfg(tmp_path, "HOST=--allow-yes\n")
    r = run_sw(tmp_path, "--dump")
    assert "ignoring invalid HOST" in r.stderr
    assert "host=127.0.0.1" in r.stdout


def test_run_does_not_interpret_metacharacters(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    argvf = tmp_path / "argv.txt"
    marker = tmp_path / "X_should_not_exist"
    # Valid https URL containing & must be one argv word; host stays 127.0.0.1.
    url = "https://example.com/x?a=1&b=2"
    write_cfg(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nCBL_TAG=android-b12032-1\n"
        "CBL_SHA=%s\nCBL_URL=%s\nDRY_RUN=1\n" % (COMMIT, SHA256, url),
    )
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="22\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert not marker.exists()
    text = argvf.read_text(encoding="ascii") if argvf.exists() else ""
    shown = r.stdout + r.stderr + text
    assert url in shown
    assert "--allow-yes" not in text
    assert "--yes" not in text
    # Path with spaces is one argument (installer path is passed to sh).
    assert _has(r.stdout + r.stderr, "John Doe")
    # Quoted display, not a bare sh -c string.
    assert "command:" in (r.stdout + r.stderr) or "running:" in (r.stdout + r.stderr)
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("ARGC=")]
    assert any(url in ln for ln in lines) or url in shown
    assert "--dry-run" in lines
    assert "--host" in lines
    assert "127.0.0.1" in lines
    assert "--yes" not in lines and "--allow-yes" not in lines


def test_prefix_config_is_not_loaded_even_if_writable(tmp_path):
    # XDG says thin/dry-run on; a writable prefix copy tries to flip them.
    write_cfg(tmp_path, "THIN_CLIENT=1\nDRY_RUN=1\nCTX_GATE=1\n")
    pfx = tmp_path / "pfx"
    pfx.mkdir()
    evil = pfx / "android-cockpit.env"
    evil.write_text("THIN_CLIENT=0\nDRY_RUN=0\nCTX_GATE=0\nALLOW_YES=1\n", encoding="ascii")
    os.chmod(evil, 0o666)
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    assert "mode=thin client" in r.stdout
    assert "dry_run=ON" in r.stdout
    assert "gate=ON" in r.stdout
    assert "allow_yes=OFF" in r.stdout


def test_prefix_write_replaces_symlink_not_follow(tmp_path):
    victim = tmp_path / "victim.env"
    victim.write_text("KEEPME=1\n", encoding="ascii")
    pfx = tmp_path / "pfx"
    pfx.mkdir()
    link = pfx / "android-cockpit.env"
    link.symlink_to(victim)
    r = run_sw(tmp_path, "--pipe", inp="6\nq\n")  # keep prefix on, then exit (saves)
    assert r.returncode == 0, r.stderr
    assert victim.read_text(encoding="ascii") == "KEEPME=1\n"
    assert link.is_symlink() is False or not link.samefile(victim)
    # After mv, PREFIX_FILE should be a regular file, victim unchanged.
    assert victim.read_text(encoding="ascii") == "KEEPME=1\n"


def test_world_readable_xdg_settings_ignored(tmp_path):
    write_cfg(tmp_path, "DRY_RUN=0\nALLOW_YES=1\nHOST=localhost\n", mode=0o644)
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    assert "ignoring settings file" in r.stderr
    assert "dry_run=ON" in r.stdout
    assert "allow_yes=OFF" in r.stdout
    assert "host=127.0.0.1" in r.stdout


def test_unreadable_settings_does_not_abort(tmp_path):
    path = write_cfg(tmp_path, "DRY_RUN=0\n")
    os.chmod(path, 0o000)
    try:
        r = run_sw(tmp_path, "--dump")
    finally:
        os.chmod(path, 0o600)
    assert r.returncode == 0, r.stderr
    assert "not readable" in r.stderr or "ignoring settings file" in r.stderr
    assert "dry_run=ON" in r.stdout


def test_api_key_group_readable_refused(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    key = write_key(tmp_path, mode=0o640)
    write_cfg(
        tmp_path,
        "HOST=example.host\nPORT=8080\nCOMMIT=%s\nAPI_KEY_FILE=%s\nDRY_RUN=1\n"
        % (COMMIT, key),
    )
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    assert "mode 0600 or tighter" in r.stderr or "group- or world-readable" in r.stderr
    assert "--host" not in r.stdout or "example.host" not in r.stdout.split("command:", 1)[-1] if "command:" in r.stdout else True


def test_api_key_default_uses_xdg(tmp_path):
    # Non-loopback host requires the XDG default key path.
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    write_cfg(tmp_path, "HOST=example.host\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\n" % COMMIT)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    # message must mention the xdg path, not a hardcoded ~/.config when XDG is set
    assert _has(r.stderr, str(tmp_path / "xdg" / "familia" / "api.key"))
    key = write_key(tmp_path, mode=0o600)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="12\n%s\n21\nq\n" % key,
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    assert "command:" in r.stdout
    assert "example.host" in r.stdout


def test_cbl_tag_without_sha256_not_exported(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    argvf = tmp_path / "argv.txt"
    write_cfg(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nCBL_TAG=android-b12032-1\nCBL_SHA=\nDRY_RUN=1\n"
        % COMMIT,
    )
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
    )
    assert r.returncode == 0, r.stderr
    assert "CBL override" in r.stderr
    out = r.stdout + r.stderr
    assert "FAMILIA_CBL_ANDROID_TAG=" not in out


def test_onphone_greyed_without_ctx_override(tmp_path):
    stub = write_stub(tmp_path, "install.sh")
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="1\n21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "on-phone inference is disabled" in out
    assert "phone-tier ctx" in out
    assert "mode=thin client" in out or "thin client" in out
    assert "--runtime" not in out


def test_onphone_allowed_with_ctx_override_maps_runtime(tmp_path):
    stub = write_stub(tmp_path, "install.sh")
    argvf = tmp_path / "argv.txt"
    # item 3 sets ctx 64000, item 1 toggles on-phone, 19 shows
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="3\n64000\n1\n21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
        FAMILIA_RAM_MIB="40000",
        FAMILIA_RESERVE_MIB="5120",
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "on-phone inference is disabled" not in out
    assert "RAM too low" not in out
    assert "mode=on-phone inference" in out
    assert "FAMILIA_BIND=127.0.0.1" in out
    assert "--runtime" in out
    assert "'cbl'" in out or "cbl" in out
    assert "--local-inference" not in out
    assert "--no-ctx-gate" not in out
    assert "--commit" not in out  # install.sh does not take --commit


def test_url_file_switch_passed_to_smoke(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    argvf = tmp_path / "argv.txt"
    urlf = tmp_path / "link.txt"
    urlf.write_text("http://localhost:8080/\n", encoding="ascii")
    write_cfg(tmp_path, "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\n" % COMMIT)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="11\n%s\n21\nq\n" % urlf,
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
        COLUMNS="200",
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "--url-file" in out
    assert "link.txt" in out


def test_url_file_relative_path_rejected(tmp_path):
    write_cfg(tmp_path, "URL_FILE=relative/path\n")
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    assert "ignoring invalid URL_FILE" in r.stderr
    assert "url_file=unset" in r.stdout


def test_dry_run_off_requires_typed_run(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    argvf = tmp_path / "argv.txt"
    write_cfg(tmp_path, "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nDRY_RUN=0\n" % COMMIT)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="22\nnope\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
    )
    assert r.returncode == 0, r.stderr
    assert "not confirmed" in r.stderr
    assert not argvf.exists()


@pytest.mark.skipif(DASH is None, reason="dash not installed")
def test_dash_pipe_invalid_input_stays_in_menu(tmp_path):
    r = run_sw(tmp_path, "--pipe", inp="x\n21\nq\n", exe=DASH)
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "isn't one of the choices" in out
    assert "exit. settings saved" in out
    assert out.count("ANDROID COCKPIT") >= 3


@pytest.mark.skipif(DASH is None, reason="dash not installed")
def test_dash_pty_does_not_exit_before_input(tmp_path):
    # Interactive path (no --pipe) under dash must not treat missing read -t as EOF.
    env = _env(tmp_path)
    env.pop("FAMILIA_NO_TTY", None)
    env["COLUMNS"] = "80"
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.execve(DASH, [DASH, SCRIPT], env)
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    buf = b""
    stage = 0
    deadline = time.time() + 8
    rc = None
    while time.time() < deadline:
        try:
            buf += os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.05)
        except OSError:
            break
        if stage == 0 and b"Choose" in buf:
            os.write(fd, b"x\n")
            stage = 1
        elif stage == 1 and b"isn't one of the choices" in buf:
            os.write(fd, b"\n")
            stage = 2
        elif stage == 2 and buf.count(b"Choose") >= 2:
            os.write(fd, b"q\n")
            stage = 3
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if wpid:
            rc = os.waitstatus_to_exitcode(status)
            try:
                while True:
                    buf += os.read(fd, 4096)
            except (BlockingIOError, OSError):
                pass
            break
    if rc is None:
        try:
            os.write(fd, b"q\n")
        except OSError:
            pass
        time.sleep(0.4)
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid:
                rc = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            pass
    if rc is None:
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
        out = buf.decode("utf-8", "replace")
        raise AssertionError("dash menu hung:\n" + out[-4000:])
    out = buf.decode("utf-8", "replace")
    assert rc == 0, out
    assert "ANDROID COCKPIT" in out
    assert "isn" in out and "choices" in out
    assert "exit. settings saved" in out
    assert "stdin closed without an exit pick" not in out


def test_narrow_columns_use_seven_bit_and_stay_in_menu(tmp_path):
    r = run_sw(tmp_path, "--pipe", inp="q\n", COLUMNS="40", LINES="50")
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "ANDROID COCKPIT" in out or "FAMILIA" in out
    # Under 48 columns there are no box borders, so the frame cannot wrap.
    for ln in out.splitlines():
        assert len(ln) <= 40, repr(ln)

def test_yes_never_emitted_to_install_or_hermes(tmp_path):
    write_key(tmp_path)
    for name in ("install.sh", "install-hermes-android.sh"):
        stub = write_stub(tmp_path, name)
        argvf = tmp_path / ("argv-%s.txt" % name)
        write_cfg(
            tmp_path,
            "THIN_CLIENT=0\nFAMILIA_CTX_VAL=64000\nTIER=large\nALLOW_YES=1\n"
            "START_FAMILIA=1\nHOST=127.0.0.1\nPORT=8080\nDRY_RUN=1\n",
        )
        r = run_sw(
            tmp_path,
            "--pipe",
            inp="22\nq\n",
            FAMILIA_ANDROID_INSTALLER=str(stub),
            FAMILIA_ARGV_FILE=str(argvf),
            FAMILIA_RAM_MIB="40000",
        )
        assert r.returncode == 0, name + " " + r.stderr + r.stdout
        out = r.stdout + r.stderr
        assert "typed ACCEPT is required; this screen never passes --yes" in out
        assert argvf.exists(), name + " did not run the stub\n" + out
        text = argvf.read_text(encoding="ascii")
        lines = [ln for ln in text.splitlines() if ln and not ln.startswith("ARGC=")]
        assert "--yes" not in lines
        assert "--allow-yes" not in lines
        assert not any(ln.startswith("FAMILIA_ACCEPT_LICENSES") for ln in lines)
        assert not any(ln.startswith("FAMILIA_ALLOW_YES=") for ln in lines)
        assert any(ln == "FAMILIA_BIND=127.0.0.1" or "FAMILIA_BIND=127.0.0.1" in ln for ln in lines)


def test_hermes_start_off_is_greyed_and_does_not_run(tmp_path):
    stub = write_stub(tmp_path, "install-hermes-android.sh")
    argvf = tmp_path / "argv.txt"
    write_cfg(
        tmp_path,
        "THIN_CLIENT=0\nFAMILIA_CTX_VAL=64000\nTIER=large\nSTART_FAMILIA=0\n"
        "HOST=127.0.0.1\nPORT=8080\nDRY_RUN=1\n",
    )
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\n22\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
        FAMILIA_RAM_MIB="40000",
    )
    assert r.returncode == 0, r.stderr + r.stdout
    out = r.stdout + r.stderr
    assert "always starts familia-start" in out
    assert "no skip-start flag" in out or "turn start ON" in out
    assert not argvf.exists()


def test_onphone_bind_pinned_to_loopback(tmp_path):
    stub = write_stub(tmp_path, "install.sh")
    argvf = tmp_path / "argv.txt"
    write_cfg(
        tmp_path,
        "THIN_CLIENT=0\nFAMILIA_CTX_VAL=64000\nTIER=large\nHOST=127.0.0.1\n"
        "PORT=8080\nDRY_RUN=1\n",
    )
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
        FAMILIA_RAM_MIB="40000",
    )
    assert r.returncode == 0, r.stderr + r.stdout
    text = (argvf.read_text(encoding="ascii") if argvf.exists() else "") + r.stdout + r.stderr
    assert "FAMILIA_BIND=127.0.0.1" in text


def test_is_loopback_requires_ip_not_hostname(tmp_path):
    # R2: 127.example.com is a hostname, not 127.0.0.0/8.
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    write_cfg(tmp_path, "HOST=127.example.com\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\n" % COMMIT)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    assert "requires an API key file" in r.stderr
    assert "command:" not in r.stdout
    # 127.0.0.1 is a real loopback IP; no key required when start is OFF.
    write_cfg(tmp_path, "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\n" % COMMIT)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    assert "command:" in r.stdout
    assert "127.0.0.1" in r.stdout
    # localhost is a hostname, not an IP: key still required.
    write_cfg(tmp_path, "HOST=localhost\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\nHTTPS=0\n" % COMMIT)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    assert "requires an API key file" in r.stderr
    # But localhost counts as loopback for the HTTPS default: http is OK,
    # no force-on, no plain-HTTP warning.
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "https=OFF" in r.stdout
    assert "host=localhost" in r.stdout
    assert "url=http://localhost:8080" in r.stdout
    assert "listener: key required" in r.stdout
    assert "plain HTTP" not in out
    assert "no key (loopback)" not in r.stdout


def test_onphone_ctx_override_refused_when_ram_too_low(tmp_path):
    stub = write_stub(tmp_path, "install.sh")
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="3\n64000\n1\n21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_RAM_MIB="6500",
        FAMILIA_RESERVE_MIB="5120",
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "RAM too low" in out
    assert "on-phone inference is disabled" in out or "mode=thin client" in out
    assert "--runtime" not in out


def test_persistent_install_warns_and_still_needs_typed_run(tmp_path):
    stub = write_stub(tmp_path, "install.sh")
    argvf = tmp_path / "argv.txt"
    write_key(tmp_path)
    write_cfg(
        tmp_path,
        "THIN_CLIENT=0\nFAMILIA_CTX_VAL=64000\nTIER=large\nHOST=127.0.0.1\n"
        "PORT=8080\nDRY_RUN=0\nSTART_FAMILIA=0\n",
    )
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="22\nnope\n22\nrun\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
        FAMILIA_RAM_MIB="40000",
    )
    assert r.returncode == 0, r.stderr + r.stdout
    out = r.stdout + r.stderr
    assert "persistent phone install" in out
    assert "not confirmed" in out
    assert "type 'run' to proceed" in out or "type 'run'" in out
    assert argvf.exists()
    text = argvf.read_text(encoding="ascii")
    assert "--yes" not in text
    assert "LEAKED FAMILIA_ACCEPT_LICENSES=" not in text
    assert not any(ln.startswith("FAMILIA_ACCEPT_LICENSES=") for ln in text.splitlines())


@pytest.mark.skipif(MKSH is None, reason="mksh not installed")
def test_mksh_tty_timeout_is_not_eof(tmp_path):
    # Real A57 data (galaxy1, 2026-11-10; Brian OK'd the test; via ssh
    # from miryam, read-only). /system/bin/sh is MIRBSD KSH R59
    # 2020/10/31 Android:
    #   read -t 2 on a TTY that times out returns rc=142 after 2s.
    #   read -t 2 </dev/null (EOF) returns rc=1.
    # So a TTY timeout (rc 142, like bash) must return to the menu, not
    # treat that as EOF. Do not match the bare word "timeout" (the
    # pytest tmp path can contain it).
    env = _env(tmp_path, COLUMNS="80", LINES="50", FAMILIA_MENU_TIMEOUT="2")
    env.pop("FAMILIA_NO_TTY", None)
    pid, fd = pty.fork()
    if pid == 0:
        try:
            fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 80, 0, 0))
        except OSError:
            pass
        os.chdir(ROOT)
        os.execve(MKSH, [MKSH, SCRIPT], env)
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    buf = b""
    stage = 0
    deadline = time.time() + 12
    rc = None
    while time.time() < deadline:
        try:
            buf += os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.05)
        except OSError:
            break
        if stage == 0 and b"Choose" in buf:
            stage = 1  # wait for the idle timeout
        elif stage == 1 and b"timeout; back to the menu" in buf:
            os.write(fd, b"q\n")
            stage = 2
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if wpid:
            rc = os.waitstatus_to_exitcode(status)
            try:
                while True:
                    buf += os.read(fd, 4096)
            except (BlockingIOError, OSError):
                pass
            break
    if rc is None:
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
        out = buf.decode("utf-8", "replace")
        raise AssertionError("mksh menu hung:\n" + out[-4000:])
    out = buf.decode("utf-8", "replace")
    assert rc == 0, out
    assert "timeout; back to the menu" in out
    assert "exit. settings saved" in out
    assert "stdin closed without an exit pick" not in out


@pytest.mark.skipif(MKSH is None, reason="mksh not installed")
def test_mksh_tty_immediate_eof_is_not_timeout(tmp_path):
    # galaxy1 mksh: immediate EOF (Ctrl-D / hangup) is rc 1, not a
    # timeout. Two EOFs stop (exit 2).
    rc, out = _pty_run(
        tmp_path, 80, 50, keys=b"\x04\x04", timeout=6,
        extra_env={"FAMILIA_MENU_TIMEOUT": "30"},
        exe=MKSH,
    )
    assert rc == 2, out
    assert "end of input" in out or "stdin closed without an exit pick" in out
    assert "timeout; back to the menu" not in out


def test_tilde_path_expands_to_home(tmp_path):
    # R1: a typed ~/key must expand to $HOME/key (quoted case patterns).
    home = tmp_path / "home"
    home.mkdir()
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="12\n~/k\nq\n",
        HOME=str(home),
    )
    assert r.returncode == 0, r.stderr
    cfg = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    expected = str(home / "k")
    assert "API_KEY_FILE=%s\n" % expected in cfg
    assert "API_KEY_FILE=~/k" not in cfg
    # Bare tilde alone also expands.
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="12\n~\nq\n",
        HOME=str(home),
    )
    assert r.returncode == 0, r.stderr
    cfg = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    assert "API_KEY_FILE=%s\n" % home in cfg


def test_https_warning_on_dump_show_and_before_run_confirm(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    write_key(tmp_path)
    write_cfg(
        tmp_path,
        "HOST=example.host\nPORT=8080\nCOMMIT=%s\nDRY_RUN=0\nHTTPS=0\n"
        "DEV_ALLOW_HTTP=1\n" % COMMIT,
    )
    warn = "dev: allow plain HTTP is ON*; remote host uses plain HTTP"
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    assert _has(r.stdout + r.stderr, warn)
    r = run_sw(tmp_path, "--show", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    assert _has(r.stdout + r.stderr, warn)
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="22\nnope\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert _has(out, warn)
    assert "type 'run' to proceed" in out
    flat = _flat(out)
    assert flat.find(warn) != -1 or _has(out, warn)
    # Warning must appear before the run confirm (join wrapped lines first).
    pos_w = _flat(out).find(warn) if warn in _flat(out) else _flat(out).replace(" ", "").find(warn.replace(" ", ""))
    pos_c = _flat(out).find("type 'run' to proceed")
    assert pos_w != -1 and pos_c != -1 and pos_w < pos_c
    assert "not confirmed" in out
    # Loopback IPs do not warn.
    write_cfg(tmp_path, "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\nHTTPS=0\n" % COMMIT)
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    assert not _has(r.stdout + r.stderr, warn)


def test_http_cbl_url_rejected_on_load_and_menu(tmp_path):
    write_cfg(
        tmp_path,
        "CBL_TAG=android-b12032-1\nCBL_SHA=%s\nCBL_URL=http://example.com/cbl.tgz\n" % SHA256,
    )
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    assert "ignoring invalid CBL_URL" in r.stderr
    cfg_out = r.stdout + r.stderr
    assert "http://example.com/cbl.tgz" not in r.stdout
    # Menu path: typed http URL is also rejected.
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="19\nandroid-b12032-1\n%s\n\nhttp://example.com/cbl.tgz\nq\n" % SHA256,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "CBL URL must be https:// only" in out
    saved = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    assert "http://example.com/cbl.tgz" not in saved


def test_eight_gb_phone_passes_at_64000_with_default_reserve(tmp_path):
    # 8 GB phone (~7600 MiB MemTotal) minus #321 reserve 5120 = 2480 usable,
    # which must clear the 2048 MiB measured floor at ctx 64000.
    stub = write_stub(tmp_path, "install.sh")
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="3\n64000\n1\n21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_RAM_MIB="7600",
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "RAM too low" not in out
    assert "on-phone inference is disabled" not in out
    assert "mode=on-phone inference" in out
    # The same phone fails if the operator raises the floor above 2480.
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="3\n64000\n1\n21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_RAM_MIB="7600",
        FAMILIA_MIN_USABLE_MIB="3072",
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "RAM too low" in out
    assert "on-phone inference is disabled" in out or "mode=thin client" in out


def test_save_trap_exits_130():
    text = Path(SCRIPT).read_text(encoding="ascii") if False else open(SCRIPT, encoding="ascii").read()
    assert "trap 'rm -f \"$_tmp\"; exit 130' INT TERM" in text
    assert "trap 'rm -f \"$_tmp\"' INT TERM" not in text


def test_inherited_license_accept_env_is_scrubbed(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    argvf = tmp_path / "argv.txt"
    write_cfg(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\n" % COMMIT,
    )
    names = (
        "INSTALL_ACK",
        "FAMILIA_ACCEPT_LICENSES",
        "FAMILIA_ACCEPT_UNKNOWN_LICENSES",
        "FAMILIA_LICENSE_ACCEPT_FILE",
        "FAMILIA_ALLOW_YES",
        "FAMILIA_HERMES_CTX_GATE",
        "FAMILIA_BIND",
        "FAMILIA_ALLOW_EXTRA",
    )
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="22\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_ARGV_FILE=str(argvf),
        INSTALL_ACK="yes",
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_LICENSE_ACCEPT_FILE="/tmp/should-not-be-used",
        FAMILIA_ALLOW_YES="yes",
        FAMILIA_HERMES_CTX_GATE="off",
        FAMILIA_BIND="0.0.0.0",
        FAMILIA_ALLOW_EXTRA="yes",
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert argvf.exists(), r.stdout + r.stderr
    text = argvf.read_text(encoding="ascii")
    for name in names:
        assert "SCRUBBED %s\n" % name in text, text
        assert "LEAKED %s=" % name not in text
        assert "should-not-be-used" not in text
    # Parent still had the leftover exports; only the child must be clean.
    out = r.stdout + r.stderr
    assert "FAMILIA_ACCEPT_LICENSES=yes" not in out.split("command:", 1)[-1] if "command:" in out else True
    assert "--yes" not in [ln for ln in text.splitlines() if not ln.startswith("SCRUBBED") and not ln.startswith("LEAKED") and not ln.startswith("ARGC=") and not ln.startswith("FAMILIA_CBL") and not ln.startswith("FAMILIA_BIND") and not ln.startswith("FAMILIA_RUNTIME")]


def test_allow_yes_switch_is_visible_but_inert(tmp_path):
    write_cfg(tmp_path, "ALLOW_YES=1\n")
    r = run_sw(tmp_path, "--pipe", inp="4\nq\n")
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "4) Allow --yes" in out
    assert "typed ACCEPT is required; this screen never passes --yes" in out
    assert "allow --yes=ON" not in out
    cfg = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    assert "ALLOW_YES=1" not in cfg
    assert "ALLOW_YES=0" in cfg


def _pty_run(tmp_path, cols, rows, keys=b"q\n", timeout=8, extra_env=None, exe=None):
    env = _env(tmp_path, COLUMNS=str(cols), LINES=str(rows))
    env.pop("FAMILIA_NO_TTY", None)
    if extra_env:
        env.update(extra_env)
    if not exe:
        exe = shutil.which("sh") or "/bin/sh"
    pid, fd = pty.fork()
    if pid == 0:
        try:
            fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass
        os.chdir(ROOT)
        os.execve(exe, [exe, SCRIPT], env)
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    buf = b""
    sent = False
    deadline = time.time() + timeout
    rc = None
    while time.time() < deadline:
        try:
            buf += os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.05)
        except OSError:
            break
        if (not sent) and b"Choose" in buf:
            os.write(fd, keys)
            sent = True
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if wpid:
            rc = os.waitstatus_to_exitcode(status)
            try:
                while True:
                    buf += os.read(fd, 4096)
            except (BlockingIOError, OSError):
                pass
            break
    if rc is None:
        try:
            os.write(fd, b"q\n")
        except OSError:
            pass
        time.sleep(0.4)
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid:
                rc = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            pass
    if rc is None:
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
        raise AssertionError("pty menu hung:\n" + buf.decode("utf-8", "replace")[-4000:])
    return rc, buf.decode("utf-8", "replace")


def _first_paint_lines(out):
    # From the first title through (and including) the first Choose prompt.
    lines = out.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if "FAMILIA" in ln or "ANDROID COCKPIT" in ln or ln.strip().startswith("status"):
            start = i
            break
    end = len(lines)
    for i, ln in enumerate(lines):
        if "Choose" in ln:
            end = i + 1
            break
    return lines[start:end]


def test_paint_fits_40x24_and_80x24(tmp_path):
    for cols, rows in ((40, 24), (80, 24)):
        rc, out = _pty_run(tmp_path, cols, rows, keys=b"q\n")
        assert rc == 0, out
        paint = _first_paint_lines(out)
        assert paint, out
        for ln in paint:
            assert len(ln) <= cols, "cols=%s line %r" % (cols, ln)
        assert len(paint) <= rows, "rows=%s paint=%s\n%s" % (rows, len(paint), "\n".join(paint))
        assert "ANDROID COCKPIT" in out or "FAMILIA" in out
        if cols < 48:
            # No box borders under 48 columns.
            assert not any(ln.strip().startswith("+") and set(ln.strip()) <= set("+\\-") for ln in paint)


def test_tty_immediate_eof_is_not_timeout(tmp_path):
    # Ctrl-D is an immediate rc 1 on a TTY; that is EOF, not a timeout.
    # Two EOFs stop the menu (exit 2).
    rc, out = _pty_run(
        tmp_path, 80, 50, keys=b"\x04\x04", timeout=6,
        extra_env={"FAMILIA_MENU_TIMEOUT": "30"},
    )
    assert rc == 2, out
    assert "end of input" in out or "stdin closed without an exit pick" in out
    assert "timeout; back to the menu" not in out


def test_tty_elapsed_timeout_returns_to_menu(tmp_path):
    # First Choose is left idle until the timed read expires, then q.
    # bash (and mksh) implement read -t; dash / Debian sh do not.
    env = _env(tmp_path, COLUMNS="80", LINES="50", FAMILIA_MENU_TIMEOUT="2")
    env.pop("FAMILIA_NO_TTY", None)
    exe = shutil.which("bash") or "/bin/bash"
    pid, fd = pty.fork()
    if pid == 0:
        try:
            fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 80, 0, 0))
        except OSError:
            pass
        os.chdir(ROOT)
        os.execve(exe, [exe, SCRIPT], env)
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    buf = b""
    stage = 0
    deadline = time.time() + 10
    rc = None
    while time.time() < deadline:
        try:
            buf += os.read(fd, 4096)
        except BlockingIOError:
            time.sleep(0.05)
        except OSError:
            break
        if stage == 0 and b"Choose" in buf:
            stage = 1  # wait for the idle timeout message (not a path)
        elif stage == 1 and b"timeout; back to the menu" in buf:
            os.write(fd, b"q\n")
            stage = 2
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if wpid:
            rc = os.waitstatus_to_exitcode(status)
            try:
                while True:
                    buf += os.read(fd, 4096)
            except (BlockingIOError, OSError):
                pass
            break
    if rc is None:
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
        raise AssertionError("timeout pty hung:\n" + buf.decode("utf-8", "replace")[-4000:])
    out = buf.decode("utf-8", "replace")
    assert rc == 0, out
    assert "timeout; back to the menu" in out
    assert "exit. settings saved" in out
    assert "stdin closed without an exit pick" not in out


def test_host_url_cr_rejected_on_load(tmp_path):
    path = write_cfg(tmp_path, "PORT=8080\n")
    # Mid-value CR is not a CRLF line ending; must be rejected.
    path.write_bytes(b"HOST=127.0.0.1\rmalicious.example\nPORT=8080\nCBL_URL=https://example.com/x\revil\n")
    os.chmod(path, 0o600)
    r = run_sw(tmp_path, "--dump")
    assert r.returncode == 0, r.stderr
    err = r.stderr
    assert "ignoring invalid HOST" in err
    assert "ignoring invalid CBL_URL" in err
    assert "host=127.0.0.1" in r.stdout
    assert "malicious.example" not in r.stdout
    assert "https://example.com/x" not in r.stdout


def test_invalid_host_edit_keeps_old_value(tmp_path):
    write_cfg(tmp_path, "HOST=127.0.0.1\nPORT=8080\n")
    r = run_sw(tmp_path, "--pipe", inp="9\n-evil\nq\n")
    assert r.returncode == 0, r.stderr
    assert "left unchanged" in (r.stdout + r.stderr)
    cfg = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    assert "HOST=127.0.0.1\n" in cfg
    assert "-evil" not in cfg


def test_lfm_enabled_shows_pinned_text_warning(tmp_path):
    r = run_sw(tmp_path, "--pipe", inp="17\nq\n")
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "no pinned license text" in out
    assert "lfm=ON" in out or "LFM" in out


def test_api_key_shows_resolved_path_not_default_label(tmp_path):
    r = run_sw(tmp_path, "--pipe", inp="q\n")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "[default]" not in out
    assert _has(out, "api.key")
    key = write_key(tmp_path)
    write_cfg(tmp_path, "API_KEY_FILE=%s\n" % key)
    r = run_sw(tmp_path, "--pipe", inp="q\n")
    assert r.returncode == 0, r.stderr
    assert _has(r.stdout, str(key))
    assert "[default]" not in r.stdout


def test_remote_host_defaults_to_https_without_dev_switch(tmp_path):
    # Brian F2: remote hosts default to HTTPS; saved HTTPS=0 is forced on.
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    write_key(tmp_path)
    write_cfg(
        tmp_path,
        "HOST=example.host\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\nHTTPS=0\n" % COMMIT,
    )
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "https=ON" in r.stdout
    assert "dev_allow_http=OFF" in r.stdout
    assert "plain HTTP" not in out
    assert "--https" in r.stdout
    # Toggle 8 cannot turn HTTPS off without the dev switch.
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="8\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    assert "HTTPS left ON" in (r.stdout + r.stderr)
    cfg = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    assert "HTTPS=1\n" in cfg
    assert "DEV_ALLOW_HTTP=0\n" in cfg


def test_dev_allow_plain_http_switch_and_env(tmp_path):
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    write_key(tmp_path)
    write_cfg(
        tmp_path,
        "HOST=example.host\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\nHTTPS=0\n" % COMMIT,
    )
    warn = "dev: allow plain HTTP is ON*; remote host uses plain HTTP"
    # Env turns the switch on for the session, so saved HTTPS=0 stays plain HTTP.
    r = run_sw(
        tmp_path,
        "--dump",
        FAMILIA_ANDROID_INSTALLER=str(stub),
        FAMILIA_DEV_ALLOW_HTTP="1",
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "dev_allow_http=ON" in r.stdout
    assert _has(out, warn)
    # Menu: 24 enables the dev switch (*), 8 then turns HTTPS off, warning shows.
    r = run_sw(
        tmp_path,
        "--pipe",
        inp="24\n8\n21\nq\n",
        FAMILIA_ANDROID_INSTALLER=str(stub),
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "dev: allow plain HTTP=ON" in out
    assert "https=OFF" in out
    assert "[ON]*" in out
    assert _has(out, warn)
    cfg = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    assert "DEV_ALLOW_HTTP=1\n" in cfg
    assert "HTTPS=0\n" in cfg
    r = run_sw(tmp_path, "--show", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert _has(r.stdout + r.stderr, warn)
    # Loopback stays HTTP-OK even with the switch off.
    write_cfg(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\nHTTPS=0\n"
        "DEV_ALLOW_HTTP=0\n" % COMMIT,
    )
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "https=OFF" in r.stdout
    assert not _has(out, warn)


def test_self_host_defaults_loopback_no_key(tmp_path):
    # Brian, 2026-11-10 11:15 PM PT ("each its own" / self-hosting):
    # each device serves its own webapp at http://127.0.0.1:9941.
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "host=127.0.0.1" in r.stdout
    assert "port=9941" in r.stdout
    assert "url=http://127.0.0.1:9941" in r.stdout
    assert "https=OFF" in r.stdout
    assert "listener: no key (loopback)" in r.stdout
    assert "plain HTTP" not in out
    assert "example.host" not in r.stdout
    # Show works without an API key for the loopback IP default.
    write_cfg(tmp_path, "COMMIT=%s\nDRY_RUN=1\n" % COMMIT)
    r = run_sw(tmp_path, "--show", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    assert "command:" in r.stdout or "--host" in r.stdout
    assert "127.0.0.1" in r.stdout
    assert "9941" in r.stdout
    assert "requires an API key file" not in r.stderr
    assert "--https" not in r.stdout
    # Thin client never starts with a fixed remote; reset keeps loopback.
    r = run_sw(tmp_path, "--pipe", inp="d\nq\n")
    assert r.returncode == 0, r.stderr
    cfg = (tmp_path / "xdg" / "familia" / "android-cockpit.env").read_text(encoding="ascii")
    assert "HOST=127.0.0.1\n" in cfg
    assert "PORT=9941\n" in cfg
    assert "HOST=example.host" not in cfg


def test_localhost_https_ok_but_key_still_required(tmp_path):
    # Literal localhost: HTTP is OK (HTTPS default); key rule stays IP-only.
    stub = write_stub(tmp_path, "familia-android-smoke.sh")
    write_cfg(
        tmp_path,
        "HOST=localhost\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\nHTTPS=0\n"
        "DEV_ALLOW_HTTP=0\n" % COMMIT,
    )
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "https=OFF" in r.stdout
    assert "url=http://localhost:8080" in r.stdout
    assert "listener: key required" in r.stdout
    assert "plain HTTP" not in out
    r = run_sw(tmp_path, "--show", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert "requires an API key file" in r.stderr
    assert "command:" not in r.stdout
    write_key(tmp_path)
    r = run_sw(tmp_path, "--show", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    assert "localhost" in r.stdout
    assert "--https" not in r.stdout
    assert "plain HTTP" not in (r.stdout + r.stderr)
    # Contrast: a remote host still wants HTTPS + key (F2).
    write_cfg(
        tmp_path,
        "HOST=example.host\nPORT=8080\nCOMMIT=%s\nDRY_RUN=1\nHTTPS=0\n" % COMMIT,
    )
    write_key(tmp_path)
    r = run_sw(tmp_path, "--dump", FAMILIA_ANDROID_INSTALLER=str(stub))
    assert r.returncode == 0, r.stderr
    assert "https=ON" in r.stdout
    assert "url=https://example.host:8080" in r.stdout
    assert "listener: key required" in r.stdout
    assert "--https" in r.stdout
