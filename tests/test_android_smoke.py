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
    r = run(["--commit", "main", "--sha256", "0" * 64, "--dry-run"], tmp_path)
    assert r.returncode != 0 and "40-hex" in r.stderr


@pytest.mark.skipif(not shutil.which("curl"), reason="curl")
def test_installer_sha_mismatch_deletes(tmp_path):
    raw = tmp_path / "raw" / C / "install" / "termux"; raw.mkdir(parents=True)
    shutil.copy(TERMUX, raw / "install.sh")
    if not os.access("/dev/tty", os.R_OK):
        pytest.skip("no /dev/tty")
    r = run(["--commit", C, "--sha256", "0" * 64, "--dry-run"], tmp_path, FAMILIA_RAW_URL=f"file://{tmp_path/'raw'}")
    assert r.returncode != 0 and "mismatch" in r.stderr
    assert not (tmp_path / "pfx" / "dl").exists()


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


def test_dolphin_registry_lists_dolphin_terms():
    import json
    p = os.path.join(ROOT, "registry", "models",
                     "RavichandranJ--Dolphin3-Cyber-8B-GGUF--Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.json")
    e = json.load(open(p))
    ids = [t["id"] for t in e["additional_terms"]]
    assert "dolphin3.0-terms" in ids
    for t in e["additional_terms"]:
        assert os.path.isfile(os.path.join(ROOT, t["text"]))
