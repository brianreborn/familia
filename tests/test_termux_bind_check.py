"""familia-start bind/key-file gate (install/termux/install.sh, generated launcher)."""
import os, re, shutil, subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "install/termux/install.sh")).read()
BLOCK = re.search(r"# BEGIN familia-bind-check.*?\n(.*?)# END familia-bind-check", SRC, re.S).group(1).replace("\\$", "$")
pytestmark = pytest.mark.skipif(not shutil.which("sh") or not shutil.which("stat"), reason="needs sh+stat")


def run(script, env):
    return subprocess.run(["sh", "-c", BLOCK + script], env={"PATH": os.environ["PATH"], **env}, capture_output=True, text=True)


@pytest.mark.parametrize("addr,ok", [
    ("127.0.0.1", True), ("127.1.2.3", True), ("localhost", True), ("::1", True),
    ("127.example", False), ("127.0.0.1.evil.com", False), ("127.0.0", False), ("127.0.0.256", False),
    ("127.0.0.1a", False), ("127..0.1", False), ("0.0.0.0", False), ("192.168.1.36", False), ("", False),
])
def test_is_loopback(addr, ok):
    r = run('is_loopback "$A" && echo YES || echo NO', {"A": addr})
    assert r.stdout.strip() == ("YES" if ok else "NO"), (addr, r.stderr)


def gate(env):
    return run('familia_key_args; printf "KF=[%s]\\n" "$FAMILIA_KF"', env)


def test_loopback_needs_no_key():
    r = gate({}); assert r.returncode == 0 and "KF=[]" in r.stdout


def test_non_loopback_requires_key(tmp_path):
    r = gate({"FAMILIA_BIND": "127.example"}); assert r.returncode == 2 and "not loopback" in r.stderr


def test_key_file_with_spaces_is_quoted(tmp_path):
    kf = tmp_path / "my key"; kf.write_text("k"); kf.chmod(0o600)
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(kf)})
    assert r.returncode == 0, r.stderr; assert f"KF=[{kf}]" in r.stdout


def test_key_file_symlink_refused(tmp_path):
    kf = tmp_path / "real"; kf.write_text("k"); kf.chmod(0o600); ln = tmp_path / "link"; ln.symlink_to(kf)
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(ln)})
    assert r.returncode == 2 and "symlink" in r.stderr


def test_key_file_bad_mode_refused(tmp_path):
    kf = tmp_path / "k"; kf.write_text("k"); kf.chmod(0o644)
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(kf)})
    assert r.returncode == 2 and "0600" in r.stderr


def test_key_file_missing_refused(tmp_path):
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(tmp_path / "nope")})
    assert r.returncode == 2 and "not a regular file" in r.stderr


def test_launcher_passes_key_as_single_arg():
    assert '"\\$@" \\${FAMILIA_EXTRA:-}' in SRC and "KEYARGS" not in SRC


def test_sshd_disables_password_auth():
    assert "PasswordAuthentication no" in SRC
    i = SRC.index('if [ "$SSHD" = 1 ]; then\n  # Key auth'); assert SRC.index("PasswordAuthentication no", i) < SRC.index("run sshd", i)
