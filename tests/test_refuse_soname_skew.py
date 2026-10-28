"""refuse_soname_skew: pack bin/lib atomicity before llama-server start."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import refuse_soname_skew as rss  # noqa: E402


def test_env_enabled_default_on(monkeypatch):
    monkeypatch.delenv("FAMILIA_REFUSE_SONAME_SKEW", raising=False)
    assert rss.env_enabled({}) is True
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": ""}) is True
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": "1"}) is True
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": "true"}) is True
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": "YES"}) is True


def test_env_enabled_off(monkeypatch):
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": "0"}) is False
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": "false"}) is False
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": "off"}) is False
    assert rss.env_enabled({"FAMILIA_REFUSE_SONAME_SKEW": "no"}) is False


def test_is_pack_soname():
    assert rss.is_pack_soname("libggml.so")
    assert rss.is_pack_soname("libggml-base.so.0")
    assert rss.is_pack_soname("libggml-vulkan.so")
    assert rss.is_pack_soname("libllama.so.0")
    assert rss.is_pack_soname("libllama-server-impl.so")
    assert not rss.is_pack_soname("libc.so.6")
    assert not rss.is_pack_soname("libstdc++.so.6")
    assert not rss.is_pack_soname("libvulkan.so.1")


def test_disabled_skips_missing_bin():
    r = rss.refuse_soname_skew("/no/such/bin", environ={"FAMILIA_REFUSE_SONAME_SKEW": "0"})
    assert r["ok"] is True and r["reason"] == "disabled"


def test_win_skipped(monkeypatch):
    monkeypatch.setattr(rss.sys, "platform", "win32")
    r = rss.refuse_soname_skew("/anything", environ={})
    assert r["ok"] is True and r["reason"] == "skipped_win"


def test_ok_with_injected_needed(tmp_path):
    bindir = tmp_path / "rt"
    bindir.mkdir()
    bin_path = bindir / "llama-server"
    bin_path.write_bytes(b"\x7fELF stub")  # not parsed — injected needed_fn
    lib = bindir / "libggml-base.so"
    lib.write_bytes(b"lib-a")
    lib2 = bindir / "libllama.so"
    lib2.write_bytes(b"lib-b")

    def needed(path):
        if os.path.realpath(path) == os.path.realpath(bin_path):
            return ["libggml-base.so", "libllama.so", "libc.so.6"]
        return []

    r = rss.refuse_soname_skew(str(bin_path), needed_fn=needed, environ={})
    assert r["ok"] is True, r
    assert r["reason"] == "ok"
    assert "libggml-base.so" in r["resolved"]
    assert r["fingerprint"]["bin"]["size"] == len(b"\x7fELF stub")
    assert len(r["fingerprint"]["libs"]) >= 2


def test_missing_pack_lib(tmp_path):
    bindir = tmp_path / "rt"
    bindir.mkdir()
    bin_path = bindir / "llama-server"
    bin_path.write_bytes(b"x")

    def needed(path):
        return ["libggml-vulkan.so", "libc.so.6"]

    r = rss.refuse_soname_skew(str(bin_path), needed_fn=needed, environ={})
    assert r["ok"] is False
    assert r["reason"] == "soname_skew"
    assert any(m.get("soname") == "libggml-vulkan.so" and m.get("error") == "missing_in_pack" for m in r["mismatches"])


def test_bin_lib_disagree(tmp_path):
    root = tmp_path / "grz-runtime"
    bindir = root / "bin"
    libdir = root / "lib"
    bindir.mkdir(parents=True)
    libdir.mkdir()
    bin_path = bindir / "llama-server"
    bin_path.write_bytes(b"bin")
    (bindir / "libggml-base.so").write_bytes(b"FROM-BIN-PACK")
    (libdir / "libggml-base.so").write_bytes(b"FROM-LIB-PACK-DIFFERENT")

    def needed(path):
        return ["libggml-base.so"]

    r = rss.refuse_soname_skew(str(bin_path), needed_fn=needed, environ={})
    assert r["ok"] is False
    assert r["reason"] == "soname_skew"
    m = next(x for x in r["mismatches"] if x.get("soname") == "libggml-base.so")
    assert m["error"] == "bin_lib_pack_disagree"
    assert len(m["lib_packs"]) == 2
    assert set(r["lib_packs_mismatched"]) == {str(bindir.resolve()), str(libdir.resolve())}


def test_bin_lib_hardlink_ok(tmp_path):
    root = tmp_path / "grz-runtime"
    bindir = root / "bin"
    libdir = root / "lib"
    bindir.mkdir(parents=True)
    libdir.mkdir()
    bin_path = bindir / "llama-server"
    bin_path.write_bytes(b"bin")
    src = bindir / "libllama.so"
    src.write_bytes(b"same")
    os.link(src, libdir / "libllama.so")

    def needed(path):
        return ["libllama.so"]

    r = rss.refuse_soname_skew(str(bin_path), needed_fn=needed, environ={})
    assert r["ok"] is True, r


def test_fingerprint_stable_and_cheap(tmp_path):
    bindir = tmp_path / "rt"
    bindir.mkdir()
    bin_path = bindir / "llama-server"
    bin_path.write_bytes(b"bin")
    (bindir / "libllama.so").write_bytes(b"L")

    def needed(path):
        return ["libllama.so"] if "llama-server" in path else []

    a = rss.fingerprint(str(bin_path), needed_fn=needed)
    b = rss.fingerprint(str(bin_path), needed_fn=needed)
    assert a["bin"]["ino"] == b["bin"]["ino"]
    assert a["bin"]["mtime_ns"] == b["bin"]["mtime_ns"]
    assert a["ok_paths"] == b["ok_paths"]
    # mutate lib → fingerprint changes
    (bindir / "libllama.so").write_bytes(b"L2")
    c = rss.fingerprint(str(bin_path), needed_fn=needed)
    assert c["libs"][0]["size"] != a["libs"][0]["size"] or c["libs"][0]["mtime_ns"] != a["libs"][0]["mtime_ns"]


def test_pack_search_dirs_bin_layout(tmp_path):
    root = tmp_path / "grz-runtime"
    (root / "bin").mkdir(parents=True)
    (root / "lib").mkdir()
    (root / "lib" / "libggml.so").write_bytes(b"g")
    bin_path = root / "bin" / "llama-server"
    bin_path.write_bytes(b"b")
    dirs = rss.pack_search_dirs(str(bin_path))
    assert str((root / "bin").resolve()) in dirs
    assert str((root / "lib").resolve()) in dirs


def test_pack_search_dirs_no_usr_lib_for_tmp(tmp_path):
    bin_path = tmp_path / "llama-server"
    bin_path.write_bytes(b"b")
    dirs = rss.pack_search_dirs(str(bin_path))
    assert all("/usr/lib" not in d and d != "/lib" for d in dirs)


def test_cli_json(tmp_path):
    bindir = tmp_path / "rt"
    bindir.mkdir()
    bin_path = bindir / "llama-server"
    bin_path.write_bytes(b"#!/bin/sh\n")  # not ELF → ok reason not_elf
    bin_path.chmod(0o755)
    p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "refuse_soname_skew.py"), "--bin", str(bin_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["ok"] is True and data["hook"] == "refuse_soname_skew"


def test_serve_sh_refuses_skew(tmp_path):
    """Integration: serve.sh fails closed when packs disagree (env on)."""
    import shutil

    root = tmp_path / "familia"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(os.path.join(ROOT, "scripts", "serve.sh"), scripts / "serve.sh")
    shutil.copy(os.path.join(ROOT, "scripts", "refuse_soname_skew.py"), scripts / "refuse_soname_skew.py")
    # validate_graph prints argv; licenses no-op
    pack = tmp_path / "grz-runtime"
    (pack / "bin").mkdir(parents=True)
    (pack / "lib").mkdir()
    # Use a real ELF so NEEDED is read; inject via copying a tiny real binary if available,
    # else shell stub + we need the check to see disagreement from directory scan.
    # Directory scan catches duplicate sonames even without DT_NEEDED.
    bin_path = pack / "bin" / "llama-server"
    bin_path.write_text("#!/bin/sh\necho should-not-run\n")
    bin_path.chmod(0o755)
    (pack / "bin" / "libggml-base.so").write_bytes(b"BINPACK")
    (pack / "lib" / "libggml-base.so").write_bytes(b"LIBPACK!!")

    (scripts / "validate_graph.py").write_text(
        "print(%r)\n" % (str(bin_path) + " -m " + str(tmp_path / "m.gguf") + " -ngl 0")
    )
    (scripts / "licenses.py").write_text("import sys; sys.exit(0)\n")
    (tmp_path / "m.gguf").write_bytes(b"GGUF")
    (root / "graph.yaml").write_text("")

    p = subprocess.run(
        ["sh", str(scripts / "serve.sh"), "coder"],
        capture_output=True,
        text=True,
        env=dict(os.environ, FAMILIA_MEMCAP="0", FAMILIA_GUARD="0"),
        timeout=60,
    )
    assert p.returncode == 1, (p.stdout, p.stderr)
    assert "refuse_soname_skew" in p.stderr
    assert "should-not-run" not in p.stdout
