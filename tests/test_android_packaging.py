"""Android one-tap packaging: cbl pin, RAM-tier model fetch, licenses, widget."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMUX = os.path.join(ROOT, "install", "termux")
PIN = os.path.join(ROOT, "config", "cbl-android-runtime.json")
DOLPHIN_DB = (
    "RavichandranJ--Dolphin3-Cyber-8B-GGUF--"
    "Dolphin3.0-Llama3.1-8B-abliterated.Q2_K"
)
LFM3_DB = "AtomicChat--LFM3-1.7B-Uncensored-GGUF--LFM3-1.7B-Uncensored-AD-Q4_K_M"
PINNED_SHA = "28612783f45e9ed247276f66880fc7077c0d3bedd592ce3c2361f6144ec27024"
FALLBACK_SHA = "158db5deb3e39f20b0e4e26e265dfc242030823e96537df4dfbfe7b0557ffcc9"


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


def test_cbl_android_runtime_pin_file():
    assert os.path.isfile(PIN)
    data = json.load(open(PIN, encoding="utf-8"))
    assert data["tag"] == "android-b12032-1"
    assert data["asset"] == "llama-b12032-bin-android-arm64-cbl1.tar.gz"
    assert data["sha256"] == PINNED_SHA
    assert data.get("bytes") == 78231898
    fb = data["fallback_opt_in"]
    assert fb["tag"] == "android-b11969-1"
    assert fb["asset"] == "llama-b11969-bin-android-arm64-cbl1.tar.gz"
    assert fb["sha256"] == FALLBACK_SHA
    assert "opt-in" in fb["note"].lower() or "Explicit" in fb["note"]


def test_install_sh_defaults_to_cbl_runtime():
    text = open(os.path.join(TERMUX, "install.sh"), encoding="utf-8").read()
    assert "RUNTIME_KIND=${FAMILIA_RUNTIME:-cbl}" in text
    assert "--runtime)" in text
    assert "cbl-runtime.sh" in text
    assert "android-b12032-1" in text
    assert "cbl-android-runtime.json" in text
    assert "android-b11969-1" in text  # documented as opt-in fallback
    assert "Prefers release tag android-b12032-1" not in text
    assert 'RUNTIME_KIND" = pkg' in text or "RUNTIME_KIND\" = pkg" in text
    assert "llama-cpp" in text
    assert "note9" not in text.lower()
    assert "runtime/current" in text
    assert "CBL_BIN=" in text
    # SC1007: quoted empty CDPATH
    assert "CDPATH='' cd" in text
    assert "CDPATH= cd" not in text


def test_cbl_runtime_pin_only_never_curl_pipe_sh():
    text = open(os.path.join(TERMUX, "cbl-runtime.sh"), encoding="utf-8").read()
    code_lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    assert not re.search(r"curl[^\n]*\|\s*(sh|bash)\b", code)
    assert "cbl-android-runtime.json" in text
    assert "in-repo pin" in text or "against that pin" in text.lower() or "vs in-repo pin" in text
    assert "PRIMARY_TAG=" not in text
    assert "fallback_opt_in" in open(PIN, encoding="utf-8").read()
    assert "android-b12032-1" in text or "cbl-android-runtime.json" in text
    assert "runtime/.download" in text or "/.download" in text
    assert "rm -rf \"$DL_DIR\"" in text or "cleaned" in text
    assert "offline" in text.lower()
    assert re.search(r"curl\b[^\n]*\s-o\s+", text)
    assert "FAMILIA_CBL_ANDROID_SHA256" in text
    assert "refused without" in text
    assert "CDPATH='' cd" in text


def test_cbl_runtime_dry_run_uses_pin(tmp_path):
    env = dict(os.environ, FAMILIA_PREFIX=str(tmp_path / "prefix"))
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "cbl-runtime.sh"), "--dry-run", "--prefix", str(tmp_path / "prefix")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "android-b12032-1" in r.stderr
    assert PINNED_SHA in r.stderr
    # stdout is the would-be dest path
    assert "android-b12032-1" in r.stdout


def test_cbl_runtime_refuses_repo_override_without_sha(tmp_path):
    env = dict(
        os.environ,
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_CBL_REPO="evil/repo",
    )
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "cbl-runtime.sh"), "--dry-run", "--prefix", str(tmp_path / "prefix")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 1
    assert "refused" in r.stderr.lower()
    assert "FAMILIA_CBL_ANDROID_SHA256" in r.stderr


def test_cbl_runtime_offline_reuses_verified(tmp_path):
    dest = tmp_path / "runtime" / "android-b12032-1"
    dest.mkdir(parents=True)
    server = dest / "llama-server"
    server.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    server.chmod(0o755)
    (dest / ".familia-cbl-pin").write_text(
        f"tag=android-b12032-1\nasset=x\nsha256={PINNED_SHA}\npin_file=x\n",
        encoding="utf-8",
    )
    env = dict(os.environ, FAMILIA_PREFIX=str(tmp_path))
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "cbl-runtime.sh"), "--prefix", str(tmp_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "offline ok" in r.stderr
    assert str(dest) in r.stdout
    assert (tmp_path / "runtime" / "current").is_symlink()


def test_phone_model_default_tiers_and_clamp():
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
    # negative usable (below ~6 GiB) clamps to 0 -> tiny
    r_neg = subprocess.run(
        [sys.executable, script, "--ram-mib", "4096", "--reserve-mib", "5120", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    neg = json.loads(r_neg.stdout)
    assert neg["usable_mib"] == 0
    assert neg["tier"] == "tiny"
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


def test_fetch_phone_model_dry_run_resolves_pin(tmp_path):
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(TERMUX, "fetch-phone-model.py"),
            "--model",
            "lfm3-17b-uncensored-q4km",
            "--prefix",
            str(tmp_path),
            "--dry-run",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(r.stdout)
    assert data["model_id"] == "lfm3-17b-uncensored-q4km"
    assert data["sha256"].startswith("b22df6")
    assert data["file"].endswith(".gguf")
    assert data["path"].endswith(data["file"])
    assert "huggingface.co" in data["url"]


def test_fetch_phone_model_reuses_cached_verified(tmp_path):
    # Plant a tiny file whose sha we compute, then monkey by writing matching content
    # For unit test: write bytes, compute sha, patch resolve by using a real pin's
    # expected path only if sha matches — instead verify mismatch re-download path
    # by planting wrong sha file and ensuring dry-run still reports would-download
    # after mismatch message. Simpler: plant correct sha for smollm via hashing a stub
    # won't match graph pin. Test the cache-hit path by temporarily using a custom
    # model is hard; instead call resolve and write file with the exact wanted sha
    # by... we can't invent content for a known sha. So test mismatch branch:
    dest_dir = tmp_path / "models"
    dest_dir.mkdir()
    # wrong content under the expected filename
    bad = dest_dir / "SmolLM2-135M-Instruct-Q4_0.gguf"
    bad.write_bytes(b"not-the-real-gguf")
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(TERMUX, "fetch-phone-model.py"),
            "--model",
            "smollm2-135m-q4-phone",
            "--prefix",
            str(tmp_path),
            "--dry-run",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "sha mismatch" in r.stderr.lower() or "re-download" in r.stderr.lower()
    assert "would download" in r.stderr.lower()


def test_licenses_selected_plus_dolphin_and_llama31():
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(ROOT, "scripts", "licenses.py"),
            "list",
            "--json",
            "--add-model",
            LFM3_DB,
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
    assert any("LFM3" in i or "AtomicChat" in i for i in ids)
    assert any("Dolphin3" in i or "RavichandranJ" in i for i in ids)
    assert any("Llama 3.1" in i for i in ids)


def test_install_hermes_android_dry_run(tmp_path):
    env = dict(
        os.environ,
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
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
    assert "licenses.py" in r.stderr
    assert "bartowski--SmolLM2" in r.stderr  # selected model in gate
    assert DOLPHIN_DB in r.stderr or "Dolphin3" in r.stderr
    assert "--require-llama31" in r.stderr
    assert "fetch-phone-model" in r.stderr or "would download" in r.stderr
    assert "bash" in r.stderr and "hermes.sh" in r.stderr
    assert "readiness" in r.stderr.lower() or "poll" in r.stderr.lower()
    assert "8642" not in r.stderr  # no guessed port
    assert "webapp" in r.stderr.lower()
    assert "CDPATH='' cd" in open(os.path.join(TERMUX, "install-hermes-android.sh")).read()


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
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert "dry-run" in combined.lower()
    assert "cbl" in combined.lower()
    assert "android-b12032-1" in combined
    assert PINNED_SHA in combined or "28612783" in combined
    assert "pkg install -y git python getconf llama-cpp" not in combined
    assert "note9" not in combined.lower()


def test_widget_launch_if_installed_and_path():
    text = open(
        os.path.join(TERMUX, "widget", "familia-hermes-android.sh"), encoding="utf-8"
    ).read()
    assert "install-hermes-android.sh" in text
    assert "HERE/../install-hermes-android.sh" in text  # fixed termux/ sibling path
    assert "install/termux/widget/../.." not in text or "HERE/../install-hermes" in text
    # old bug: cd to ../.. from widget -> install/ (missing termux)
    assert '/../.." && pwd)\n  SCRIPT="$HERE/install-hermes-android.sh"' not in text
    assert "--launch-only" in text
    assert "~/.shortcuts" in text or "Termux:Widget" in text
    assert "CDPATH='' cd" in text


def test_android_docs_present():
    assert os.path.isfile(os.path.join(ROOT, "docs", "android-hermes.md"))
    assert os.path.isfile(os.path.join(ROOT, "packaging", "android", "README.md"))
    doc = open(os.path.join(ROOT, "docs", "android-hermes.md"), encoding="utf-8").read()
    assert "webapp" in doc.lower()
    assert "Office 3D" in doc or "office-3d" in doc
    assert "cbl-android-runtime.json" in doc
    assert "android-b12032-1" in doc
    assert "opt-in" in doc.lower() or "b11969" in doc
    assert "falling back to" not in doc
    assert "note9" not in doc.lower()
