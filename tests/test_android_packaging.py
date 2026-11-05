"""Android one-tap packaging: cbl runtime default, RAM-tier model, licenses, widget."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMUX = os.path.join(ROOT, "install", "termux")
DOLPHIN_DB = (
    "RavichandranJ--Dolphin3-Cyber-8B-GGUF--"
    "Dolphin3.0-Llama3.1-8B-abliterated.Q2_K"
)


def _sh_n(path: str) -> None:
    assert subprocess.run(["sh", "-n", path], cwd=ROOT).returncode == 0


def test_termux_scripts_syntax():
    for name in (
        "install.sh",
        "cbl-runtime.sh",
        "install-hermes-android.sh",
        "deps.sh",
        "widget/familia-hermes-android.sh",
    ):
        _sh_n(os.path.join(TERMUX, name))


def test_install_sh_defaults_to_cbl_runtime():
    text = open(os.path.join(TERMUX, "install.sh"), encoding="utf-8").read()
    assert "RUNTIME_KIND=${FAMILIA_RUNTIME:-cbl}" in text
    assert "--runtime)" in text
    assert "cbl-runtime.sh" in text
    assert "android-b12032-1" in text
    assert "android-b11969-1" in text
    # pkg is opt-in; llama-cpp only when RUNTIME_KIND=pkg
    assert 'RUNTIME_KIND" = pkg' in text or "RUNTIME_KIND\" = pkg" in text
    assert "llama-cpp" in text
    # no note9 references
    assert "note9" not in text.lower()
    # launcher prefers cbl binary
    assert 'runtime/current' in text
    assert "CBL_BIN=" in text


def test_cbl_runtime_never_curl_pipe_sh_and_verifies_sha():
    text = open(os.path.join(TERMUX, "cbl-runtime.sh"), encoding="utf-8").read()
    # Ignore comment lines; ensure no live curl|sh / curl|bash pipeline.
    code_lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    assert not re.search(r"curl[^\n]*\|\s*(sh|bash)\b", code)
    assert "SHA256SUMS" in text
    assert "sha256 mismatch" in text
    assert "llama-server" in text
    # named download path under runtime/.download
    assert "runtime/.download" in text or "/.download" in text
    # Downloads go to a named file via curl -o (not piped to a shell).
    assert re.search(r"curl\b[^\n]*\s-o\s+", text)


def test_phone_model_default_tiers():
    script = os.path.join(TERMUX, "phone-model-default.py")
    r = subprocess.run(
        [sys.executable, script, "--list-tiers", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(r.stdout)
    tiers = {t["tier"]: t["model"] for t in data["tiers"]}
    assert tiers["tiny"] == "smollm2-135m-q4-phone"
    assert tiers["small"] == "qwen25-05b-q4km-phone"
    assert tiers["medium"] == "lfm3-17b-uncensored-q4km"
    assert tiers["large"] == "dolphin3-cyber-8b-q2k"
    # A57-class: 7570 total - 5120 reserve ~= 2450 usable -> medium
    r2 = subprocess.run(
        [sys.executable, script, "--ram-mib", "7570", "--reserve-mib", "5120", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    pick = json.loads(r2.stdout)
    assert pick["tier"] == "medium"
    assert pick["model"] == "lfm3-17b-uncensored-q4km"
    # override
    env = dict(os.environ, FAMILIA_PHONE_MODEL="dolphin3-cyber-8b-q2k")
    r3 = subprocess.run(
        [sys.executable, script, "--ram-mib", "7570", "--json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(r3.stdout)["model"] == "dolphin3-cyber-8b-q2k"


def test_licenses_add_model_and_require_llama31():
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(ROOT, "scripts", "licenses.py"),
            "list",
            "--json",
            "--add-model",
            DOLPHIN_DB,
            "--require-llama31",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(r.stdout)
    ids = {i["id"] for i in data["items"]}
    assert any("Dolphin3" in i or "dolphin" in i.lower() for i in ids) or any(
        "RavichandranJ" in i for i in ids
    )
    assert any("Llama 3.1" in i for i in ids)
    licenses = {i["license"] for i in data["items"]}
    assert any("llama3.1" in (x or "").lower() or "llama 3.1" in (x or "").lower() for x in licenses)


def test_install_hermes_android_dry_run(tmp_path):
    env = dict(
        os.environ,
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        # Avoid interactive / missing MemTotal edge cases inside nested install.
        FAMILIA_PHONE_MODEL="smollm2-135m-q4-phone",
    )
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "install-hermes-android.sh"), "--dry-run", "--yes", "--skip-install"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "licenses.py" in r.stderr or "dry-run" in r.stderr
    assert "webapp" in r.stderr.lower()
    assert "Office 3D" in r.stderr or "office-3d" in r.stderr.lower() or "Desktop" in r.stderr


def test_termux_install_dry_run_cbl_mentions_download(tmp_path):
    env = dict(
        os.environ,
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_RUNTIME="cbl",
    )
    r = subprocess.run(
        [
            "sh",
            os.path.join(TERMUX, "install.sh"),
            "--dry-run",
            "--yes",
            "--name",
            "galaxy1",
            "--no-path",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    # Dry-run may still hit the network for cbl release metadata; accept 0 or a
    # clear cbl query error if GitHub is unreachable, but must not install llama-cpp pkg.
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    # Default cbl path: dry-run must mention cbl runtime and must NOT pkg-install llama-cpp.
    assert "dry-run" in combined.lower()
    assert "cbl" in combined.lower()
    assert "pkg install -y git python getconf llama-cpp" not in combined
    assert "note9" not in combined.lower()


def test_widget_points_at_install_hermes_android():
    text = open(
        os.path.join(TERMUX, "widget", "familia-hermes-android.sh"), encoding="utf-8"
    ).read()
    assert "install-hermes-android.sh" in text
    assert "~/.shortcuts" in text or "Termux:Widget" in text


def test_android_docs_present():
    assert os.path.isfile(os.path.join(ROOT, "docs", "android-hermes.md"))
    assert os.path.isfile(os.path.join(ROOT, "packaging", "android", "README.md"))
    doc = open(os.path.join(ROOT, "docs", "android-hermes.md"), encoding="utf-8").read()
    assert "webapp" in doc.lower()
    assert "Office 3D" in doc or "office-3d" in doc
    assert "android-b12032-1" in doc
    assert "note9" not in doc.lower()
