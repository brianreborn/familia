"""Android one-tap packaging: cbl pin, RAM-tier model fetch, licenses, widget."""
from __future__ import annotations

import json
import os
import re
import shutil
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
    assert "FAMILIA_CBL_PIN_FILE" in text
    assert "FAMILIA_CBL_DOWNLOAD_URL" in text
    assert "manifest_begin" in text and "llama-server" in text
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
    so = dest / "libfoo.so"
    so.write_bytes(b"so")
    def _sha(p):
        return __import__("hashlib").sha256(p.read_bytes()).hexdigest()
    size = server.stat().st_size
    mtime = int(server.stat().st_mtime)
    so_size = so.stat().st_size
    so_mtime = int(so.stat().st_mtime)
    (dest / ".familia-cbl-pin").write_text(
        f"tag=android-b12032-1\nasset=x\nsha256={PINNED_SHA}\npin_file=x\n"
        f"manifest_begin\n"
        f"libfoo.so {so_size} {so_mtime} {_sha(so)}\n"
        f"llama-server {size} {mtime} {_sha(server)}\n"
        f"manifest_end\n",
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
    tiers = {t["tier"]: t for t in data["tiers"]}
    assert tiers["tiny"]["model"] == "smollm2-135m-q4-phone"
    assert tiers["tiny"]["ctx"] == 2048
    assert tiers["medium"]["ctx"] == 4096
    assert tiers["large"]["ctx"] == 8192
    tiers = {k: v["model"] for k, v in tiers.items()}
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
    assert pick["ctx"] == 4096
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
    assert neg["ctx"] == 2048
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


def _sparse_phone_tree(tmp_path):
    """Checkout-shaped tree with graph pin and no registry/models."""
    tree = tmp_path / "tree"
    termux = tree / "install" / "termux"
    termux.mkdir(parents=True)
    for name in ("fetch-phone-model.py", "phone-model-default.py", "install-hermes-android.sh"):
        shutil.copy(os.path.join(TERMUX, name), termux / name)
    mid = "smollm2-135m-q4-phone"
    db = "bartowski--SmolLM2-135M-Instruct-GGUF--SmolLM2-135M-Instruct-Q4_0"
    sha = "bcc3af2849ad6095af57e9b5cd43775256efdc66e306acb529172f92d0c04b03"
    (tree / "graph.yaml").write_text(
        "models:\n"
        f"  {mid}:\n"
        f"    sha256: {sha}\n"
        f"    db: {db}\n",
        encoding="utf-8",
    )
    return tree, mid, db, sha


def test_fetch_phone_model_dry_run_without_registry(tmp_path):
    """--dry-run reports the graph pin when registry/models is absent."""
    tree, mid, db, sha = _sparse_phone_tree(tmp_path)
    dest_prefix = tmp_path / "prefix"
    r = subprocess.run(
        [
            sys.executable,
            str(tree / "install" / "termux" / "fetch-phone-model.py"),
            "--model",
            mid,
            "--prefix",
            str(dest_prefix),
            "--dry-run",
            "--json",
        ],
        cwd=str(tree),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["model_id"] == mid
    assert data["db"] == db
    assert data["sha256"] == sha
    assert data["registry_missing"] is True
    assert data["file"] is None
    assert data["path"].endswith("<file from registry>")
    assert "would read" in r.stderr and "registry/models" in r.stderr
    assert sha in r.stderr
    assert "would download" in r.stderr
    assert "error:" not in r.stderr


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
    """Unset FAMILIA_CTX is raised to 65536 and a typical 8 GiB phone is admitted."""
    env = dict(
        os.environ,
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_PHONE_MODEL="smollm2-135m-q4-phone",
        FAMILIA_RAM_MIB="7570",
        FAMILIA_RESERVE_MIB="5120",
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
    assert "default phone model tier=" in r.stderr
    assert "raising ctx" in r.stderr and "65536" in r.stderr
    assert "64k admit ok" in r.stderr
    assert "REFUSE" not in r.stderr
    assert "licenses.py" in r.stderr
    assert "FAMILIA_CTX=65536" in r.stderr
    assert "FAMILIA_KV=q8_0" in r.stderr
    assert "FAMILIA_PARALLEL=1" in r.stderr
    assert "127.0.0.1" in r.stderr
    assert "8642" not in r.stderr  # no guessed port
    hermes = open(os.path.join(TERMUX, "install-hermes-android.sh"), encoding="utf-8").read()
    assert "hermes.sh" in hermes
    assert "CDPATH='' cd" in hermes
    assert "redact" in hermes.lower() or "REDACTED" in hermes
    assert "have_tty" in hermes or "Widget taps do not" in hermes
    assert DOLPHIN_DB in hermes
    assert "HERMES_CTX_DEFAULT=65536" in hermes
    assert "required_usable_for_ctx" in hermes


def test_install_hermes_android_dry_run_without_registry(tmp_path):
    """Hermes --dry-run must not fail when registry/models is omitted."""
    tree, mid, db, sha = _sparse_phone_tree(tmp_path)
    env = dict(
        os.environ,
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_PHONE_MODEL=mid,
        FAMILIA_RAM_MIB="7570",
        FAMILIA_RESERVE_MIB="5120",
    )
    env.pop("FAMILIA_ACCEPT_LICENSES", None)
    env.pop("FAMILIA_ACCEPT_UNKNOWN_LICENSES", None)
    env.pop("INSTALL_ACK", None)
    r = subprocess.run(
        ["sh", str(tree / "install" / "termux" / "install-hermes-android.sh"), "--dry-run", "--skip-install"],
        cwd=str(tree),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert "REFUSE" not in r.stderr
    assert "64k admit ok" in r.stderr
    assert "would read" in r.stderr and "registry/models" in r.stderr
    assert sha in r.stderr
    assert "could not fetch/verify phone model" not in r.stderr
    assert "missing registry" not in r.stderr
    # dry-run reports the license gate without a license --yes
    license_lines = [ln for ln in r.stderr.splitlines() if "licenses.py" in ln]
    assert license_lines
    assert all("--yes" not in ln for ln in license_lines)
    assert "FAMILIA_ACCEPT_LICENSES" not in r.stderr


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
    assert "HERE/../install-hermes-android.sh" in text
    assert "--launch-only" in text
    assert 'exec sh "$SCRIPT" --launch-only --yes' not in text
    assert 'exec sh "$SCRIPT" --launch-only' in text
    assert "does NOT accept licenses" in text
    assert '-L "$SOURCE"' in text
    assert "~/.shortcuts" in text or "Termux:Widget" in text
    assert "CDPATH='' cd" in text
    assert "ignoring" in text
    assert "widget taps do not accept licenses" in text.lower() or "do not accept licenses" in text.lower()
    assert "FAMILIA_LICENSE_ACCEPT_FILE" in text and "unset INSTALL_ACK" in text



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
    assert "familia-start" in doc and "loads and serves" in doc
    assert "4096" in doc and "8192" in doc  # phone ctx tiers
    assert "api.key" in doc
    assert "64000" in doc and "MINIMUM_CONTEXT_LENGTH" in doc
    assert "65536" in doc and "q8_0" in doc
    assert "127.0.0.1" in doc
    assert "self-host" in doc.lower()
    assert "FAMILIA_MIN_USABLE_MIB" in doc
    assert "non-loopback" in doc.lower()
    assert "PIN_FILE" in doc or "DOWNLOAD_URL" in doc
    assert "note9" not in doc.lower()


def test_cbl_runtime_refuses_fake_pin_file_without_sha(tmp_path):
    fake = tmp_path / "fake-pin.json"
    fake.write_text(
        json.dumps(
            {
                "repo": "evil/repo",
                "tag": "android-evil-1",
                "asset": "evil.tar.gz",
                "sha256": "0" * 64,
                "download_url": "https://example.invalid/evil.tar.gz",
            }
        ),
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_CBL_PIN_FILE=str(fake),
    )
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "cbl-runtime.sh"), "--dry-run", "--prefix", str(tmp_path / "prefix")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 1, r.stderr
    assert "refused" in r.stderr.lower()
    assert "FAMILIA_CBL_PIN_FILE" in r.stderr
    assert "FAMILIA_CBL_ANDROID_SHA256" in r.stderr


def test_cbl_runtime_refuses_download_url_without_sha(tmp_path):
    env = dict(
        os.environ,
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_CBL_DOWNLOAD_URL="https://example.invalid/evil.tar.gz",
    )
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "cbl-runtime.sh"), "--dry-run", "--prefix", str(tmp_path / "prefix")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 1, r.stderr
    assert "refused" in r.stderr.lower()
    assert "FAMILIA_CBL_DOWNLOAD_URL" in r.stderr


def test_cbl_runtime_mtime_mismatch_not_offline(tmp_path):
    dest = tmp_path / "runtime" / "android-b12032-1"
    dest.mkdir(parents=True)
    server = dest / "llama-server"
    server.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    server.chmod(0o755)
    size = server.stat().st_size
    digest = __import__("hashlib").sha256(server.read_bytes()).hexdigest()
    (dest / ".familia-cbl-pin").write_text(
        f"tag=android-b12032-1\nasset=x\nsha256={PINNED_SHA}\npin_file=x\n"
        f"manifest_begin\n"
        f"llama-server {size} 1 {digest}\n"
        f"manifest_end\n",
        encoding="utf-8",
    )
    env = dict(os.environ, FAMILIA_PREFIX=str(tmp_path))
    # dry-run: should NOT take the offline short-circuit (mtime mismatch)
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "cbl-runtime.sh"), "--dry-run", "--prefix", str(tmp_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "offline ok" not in r.stderr
    assert "would download" in r.stderr or "mismatch" in r.stderr.lower()


def test_fetch_phone_model_cheap_skips_rehash(tmp_path):
    # Plant a file + matching marker; --cheap must accept without network.
    models = tmp_path / "models"
    models.mkdir()
    # Use a tiny stub; marker claims the graph sha — cheap trusts marker+size+mtime.
    # For a real sha match we'd need the real file; instead test marker miss then
    # full path: write marker with wrong sha -> cheap fails into dry-run re-download.
    dest = models / "SmolLM2-135M-Instruct-Q4_0.gguf"
    dest.write_bytes(b"stub-not-real")
    marker = {
        "model_id": "smollm2-135m-q4-phone",
        "sha256": "bcc3af2849ad6095af57e9b5cd43775256efdc66e306acb529172f92d0c04b03",
        "size": dest.stat().st_size,
        "mtime": int(dest.stat().st_mtime),
        "file": dest.name,
    }
    (Path(str(dest) + ".familia-verified")).write_text(json.dumps(marker), encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(TERMUX, "fetch-phone-model.py"),
            "--model",
            "smollm2-135m-q4-phone",
            "--prefix",
            str(tmp_path),
            "--cheap",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "cheap ok" in r.stderr
    assert str(dest) in r.stdout


def test_install_sh_done_line_mentions_familia_start_serves():
    text = open(os.path.join(TERMUX, "install.sh"), encoding="utf-8").read()
    assert "familia-start serves the GGUF" in text
    assert "install-hermes-android.sh" in text


def test_widget_clears_accept_env_and_never_yes():
    text = open(os.path.join(TERMUX, "widget", "familia-hermes-android.sh"), encoding="utf-8").read()
    assert "FAMILIA_ACCEPT_LICENSES" in text
    assert "INSTALL_ACK" in text
    assert 'exec sh "$SCRIPT" --launch-only --yes' not in text


def test_redaction_patterns_in_hermes_android():
    text = open(os.path.join(TERMUX, "install-hermes-android.sh"), encoding="utf-8").read()
    for pat in ("/auth/", "/s/", "#t=", "[?]k=", "&k=", "[?]code=", "[?]session=", "&session=", "REDACTED"):
        assert pat in text
    # Bare s/?k= must not appear (GNU sed -E rejects it).
    assert "s/?k=" not in text
    assert "s/?code=" not in text
    assert "s/?session=" not in text
    # Replacement must use a plain ?, never leave literal "[?]" in output.
    assert "/[?]k=[REDACTED]" not in text
    assert "?k=[REDACTED]" in text
    assert "?session=[REDACTED]" in text


def test_redaction_runs_under_gnu_sed_and_busybox():
    """Actually execute the sed -E patterns (GNU sed; busybox when present)."""
    script = r"""
sed -E \
  -e 's/[Bb]earer[[:space:]]+[A-Za-z0-9._~+\/=-]+/[REDACTED_BEARER]/g' \
  -e 's|/auth/[A-Za-z0-9._~+/=-]+|/auth/[REDACTED]|g' \
  -e 's|/s/[A-Za-z0-9._~+/=-]+|/s/[REDACTED]|g' \
  -e 's/#t=[^[:space:]&"]+/#t=[REDACTED]/g' \
  -e 's/[?]k=[^[:space:]&"]+/?k=[REDACTED]/g' \
  -e 's/&k=[^[:space:]&"]+/\&k=[REDACTED]/g' \
  -e 's/[?]code=[^[:space:]&"]+/?code=[REDACTED]/g' \
  -e 's/&code=[^[:space:]&"]+/\&code=[REDACTED]/g' \
  -e 's/[?]session=[^[:space:]&"]+/?session=[REDACTED]/g' \
  -e 's/&session=[^[:space:]&"]+/\&session=[REDACTED]/g'
"""
    sample = (
        "Bearer SECRETtok visit /auth/xyzzy /s/sessTok "
        "?k=abc&code=99&session=sess99 #t=onetimenear\n"
    )
    r = subprocess.run(["sh", "-c", script], input=sample, capture_output=True, text=True, check=True)
    assert "SECRETtok" not in r.stdout
    assert "[REDACTED_BEARER]" in r.stdout
    assert "/auth/[REDACTED]" in r.stdout
    assert "/s/[REDACTED]" in r.stdout
    assert "?k=[REDACTED]" in r.stdout
    assert "?session=[REDACTED]" in r.stdout or "&session=[REDACTED]" in r.stdout
    assert "[?]" not in r.stdout  # never leave literal [? ] in output
    assert "abc" not in r.stdout
    assert "sessTok" not in r.stdout
    assert "sess99" not in r.stdout
    # BusyBox when available
    bb = subprocess.run(["sh", "-c", "command -v busybox"], capture_output=True, text=True)
    if bb.returncode == 0 and bb.stdout.strip():
        r2 = subprocess.run(
            ["busybox", "sh", "-c", script],
            input=sample, capture_output=True, text=True, check=True,
        )
        assert "[REDACTED_BEARER]" in r2.stdout
        assert "SECRETtok" not in r2.stdout
        assert "[?]" not in r2.stdout


def test_hermes_refused_when_phone_ctx_below_64000(tmp_path):
    """Explicit FAMILIA_CTX below the floor is still refused (do not lower min_ctx)."""
    env = dict(
        os.environ,
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_PHONE_MODEL="smollm2-135m-q4-phone",
        FAMILIA_CTX="4096",
        FAMILIA_RAM_MIB="7570",
    )
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "install-hermes-android.sh"), "--dry-run", "--yes", "--skip-install"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "REFUSE" in r.stderr
    assert "64000" in r.stderr
    assert "MINIMUM_CONTEXT" in r.stderr or "hermes-agent" in r.stderr
    assert "raising ctx" not in r.stderr
    # Early: nothing past the ctx/RAM admit runs.
    assert "licenses.py" not in r.stderr
    assert "familia-start" not in r.stderr or "can still serve" in r.stderr


def test_hermes_refused_when_usable_ram_below_64k_floor(tmp_path):
    """#548 floor: usable (MemTotal-5120) below 2048 MiB at 64k is a RAM refuse."""
    env = dict(
        os.environ,
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_PHONE_MODEL="smollm2-135m-q4-phone",
        FAMILIA_RAM_MIB="4096",
        FAMILIA_RESERVE_MIB="5120",
    )
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "install-hermes-android.sh"), "--dry-run", "--yes", "--skip-install"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "raising ctx" in r.stderr and "65536" in r.stderr
    assert "REFUSE" in r.stderr
    assert "usable RAM 0 MiB" in r.stderr or "usable RAM 0 " in r.stderr
    assert "FAMILIA_MIN_USABLE_MIB" in r.stderr
    assert "licenses.py" not in r.stderr


def test_termux_familia_start_uses_q8_kv_and_single_slot():
    """REQUIREMENTS.md / #203: Android familia-start uses -np 1 and q8_0 KV."""
    text = open(os.path.join(TERMUX, "install.sh"), encoding="utf-8").read()
    assert r'-np "\${FAMILIA_PARALLEL:-1}"' in text
    assert r'-ctk "\${FAMILIA_KV:-q8_0}"' in text
    assert r'-ctv "\${FAMILIA_KV:-q8_0}"' in text


def test_widget_clears_license_accept_file():
    text = open(os.path.join(TERMUX, "widget", "familia-hermes-android.sh"), encoding="utf-8").read()
    assert "FAMILIA_LICENSE_ACCEPT_FILE" in text


def test_dry_run_prints_no_open_only_when_set(tmp_path):
    env = dict(
        os.environ,
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_ACCEPT_UNKNOWN_LICENSES="yes",
        FAMILIA_PREFIX=str(tmp_path / "prefix"),
        FAMILIA_PHONE_MODEL="smollm2-135m-q4-phone",
        FAMILIA_CTX="65536",  # meet Hermes floor so dry-run reaches open/no-open lines
        FAMILIA_RAM_MIB="7570",
        FAMILIA_RESERVE_MIB="5120",
    )
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "install-hermes-android.sh"), "--dry-run", "--yes", "--skip-install"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "REFUSE" not in r.stderr
    assert "licenses.py" in r.stderr  # past early gate when ctx>=64k
    assert "familia-start" in r.stderr
    # without --no-open, should mention would open, not "--no-open: would not"
    assert "--no-open: would not" not in r.stderr
    r2 = subprocess.run(
        ["sh", os.path.join(TERMUX, "install-hermes-android.sh"), "--dry-run", "--yes", "--skip-install", "--no-open"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert r2.returncode == 0, r2.stderr
    assert "--no-open" in r2.stderr



def test_cbl_runtime_stale_names_file(tmp_path):
    dest = tmp_path / "runtime" / "android-b12032-1"
    dest.mkdir(parents=True)
    server = dest / "llama-server"
    server.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    server.chmod(0o755)
    so = dest / "libfoo.so"
    so.write_bytes(b"so")
    import hashlib
    def _sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    # Wrong sha for libfoo.so, correct size/mtime
    (dest / ".familia-cbl-pin").write_text(
        f"tag=android-b12032-1\nasset=x\nsha256={PINNED_SHA}\npin_file=x\n"
        f"manifest_begin\n"
        f"libfoo.so {so.stat().st_size} {int(so.stat().st_mtime)} {'0'*64}\n"
        f"llama-server {server.stat().st_size} {int(server.stat().st_mtime)} {_sha(server)}\n"
        f"manifest_end\n",
        encoding="utf-8",
    )
    env = dict(os.environ, FAMILIA_PREFIX=str(tmp_path))
    r = subprocess.run(
        ["sh", os.path.join(TERMUX, "cbl-runtime.sh"), "--dry-run", "--prefix", str(tmp_path)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "offline ok" not in r.stderr
    assert "libfoo.so" in r.stderr  # names the stale file
