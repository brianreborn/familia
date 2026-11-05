"""packaging/android/familia-android-smoke.sh + Termux installer license order (no phone)."""
import hashlib
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMOKE = os.path.join(ROOT, "packaging", "android", "familia-android-smoke.sh")
TERMUX = os.path.join(ROOT, "install", "termux", "install.sh")
LIC = os.path.join(ROOT, "packaging", "android", "licenses")
C = "a" * 40


def run(args, tmp_path, **env):
    e = dict(os.environ, FAMILIA_SMOKE_PREFIX=str(tmp_path / "pfx"), NO_COLOR="1", **env)
    return subprocess.run(["sh", SMOKE] + args, capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)


def test_yes_refused(tmp_path):
    r = run(["--yes"], tmp_path)
    assert r.returncode != 0 and "refused" in r.stderr


def test_commit_must_be_pinned(tmp_path):
    r = run(["--commit", "main", "--host", "h", "--port", "1", "--dry-run"], tmp_path)
    assert r.returncode != 0 and "40-hex" in r.stderr


@pytest.mark.parametrize("host,port,msg", [
    ("", "8080", "--host"), ("bad host", "8080", "--host"), ("h;rm -rf /", "8080", "--host"),
    ("h", "", "--port"), ("h", "0", "--port"), ("h", "70000", "--port"), ("h", "80x", "--port"),
])
def test_host_port_validated(tmp_path, host, port, msg):
    r = run(["--commit", C, "--host", host, "--port", port, "--dry-run"], tmp_path)
    assert r.returncode != 0 and msg in r.stderr


def _tamper(tmp_path):
    raw = tmp_path / "raw" / C / "packaging" / "android" / "licenses"; raw.mkdir(parents=True)
    for f in os.listdir(LIC):
        shutil.copy(os.path.join(LIC, f), raw / f)
    (raw / "DOLPHIN-3.0-MODEL-TERMS.txt").write_text("tampered")
    return f"file://{tmp_path / 'raw'}"


@pytest.mark.skipif(not shutil.which("curl") or not os.access("/dev/tty", os.R_OK), reason="curl/tty")
def test_license_text_mismatch_stops_and_cleans(tmp_path):
    r = run(["--commit", C, "--host", "192.168.1.5", "--port", "8642", "--dry-run"], tmp_path, FAMILIA_RAW_URL=_tamper(tmp_path))
    assert r.returncode != 0 and "mismatch" in r.stderr
    assert not (tmp_path / "pfx").exists()


@pytest.mark.skipif(not shutil.which("curl") or not os.access("/dev/tty", os.R_OK), reason="curl/tty")
def test_url_file_token_never_logged(tmp_path):
    uf = tmp_path / "link"; uf.write_text("http://192.168.1.5:8642/?token=SECRET123\n")
    r = run(["--commit", C, "--host", "192.168.1.5", "--port", "8642", "--url-file", str(uf), "--dry-run"],
            tmp_path, FAMILIA_RAW_URL=_tamper(tmp_path))
    assert "SECRET123" not in r.stderr + r.stdout
    assert "http://192.168.1.5:8642/" in r.stderr


def test_url_file_must_match_host(tmp_path):
    uf = tmp_path / "link"; uf.write_text("http://evil:1/?token=SECRET123\n")
    r = run(["--commit", C, "--host", "h", "--port", "8642", "--url-file", str(uf), "--dry-run"], tmp_path)
    assert r.returncode != 0 and "SECRET123" not in r.stderr


def test_cbl_pin_matches_installer():
    s, t = open(SMOKE).read(), open(TERMUX).read()
    for k in ("CBL_TAR=llama-b11969-bin-android-arm64-cbl1.tar.gz",
              "158db5deb3e39f20b0e4e26e265dfc242030823e96537df4dfbfe7b0557ffcc9", "android-b11969-1"):
        assert k in s and k in t


def test_output_is_ascii_and_no_color_respected(tmp_path):
    raw = open(SMOKE, "rb").read()
    assert all(b < 128 for b in raw)
    assert "\x1b" not in run(["--yes"], tmp_path).stderr


def test_pinned_license_sums_match_files():
    sums = open(os.path.join(LIC, "SHA256SUMS")).read().split("\n")
    body = open(SMOKE).read()
    for line in filter(None, sums):
        h, name = line.split()
        assert hashlib.sha256(open(os.path.join(LIC, name), "rb").read()).hexdigest() == h
        assert f"{h}  {name}" in body


def test_remove_cleans_prefix(tmp_path):
    (tmp_path / "pfx" / "x").mkdir(parents=True)
    r = run(["--remove"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "pfx").exists()


def test_termux_license_gate_before_any_download():
    s = open(TERMUX).read()
    gate = s.index("License gate FIRST")
    assert gate < s.index("run pkg install -y $PKGS")
    assert gate < s.index("git clone -q")
    assert "note9" not in s


def test_termux_defaults_to_thin_client_and_cbl_runtime():
    s = open(TERMUX).read()
    assert "RUNTIME=0;" in s and "--runtime) RUNTIME=1" in s
    assert "llama-cpp" not in s.split("set -eu", 1)[1]  # no Termux llama-cpp pkg in code
    assert 'exec "$LLAMA_SERVER"' in s


def test_termux_dry_run_runtime_uses_cbl(tmp_path):
    e = dict(os.environ, FAMILIA_PREFIX=str(tmp_path / "p"), HOME=str(tmp_path))
    r = subprocess.run(["sh", TERMUX, "--dry-run", "--runtime", "--name", "t", "--no-path"],
                       capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)
    assert "android-b11969-1" in r.stderr and "pkg install -y git python getconf" in r.stderr
    assert "llama-cpp" not in r.stderr


def test_dolphin_registry_lists_dolphin_terms():
    import json
    p = os.path.join(ROOT, "registry", "models",
                     "RavichandranJ--Dolphin3-Cyber-8B-GGUF--Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.json")
    e = json.load(open(p))
    ids = [t["id"] for t in e["additional_terms"]]
    assert "dolphin3.0-terms" in ids
    for t in e["additional_terms"]:
        assert os.path.isfile(os.path.join(ROOT, t["text"]))
