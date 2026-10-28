"""Race seatbelts for #83 (ngl0 / Vulkan) and #82 (ngram opt-in). No GPU required."""
import copy
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import miryam_perf_seatbelts as mps  # noqa: E402
import validate_graph  # noqa: E402

GRAPH = validate_graph.load(os.path.join(ROOT, "graph.yaml"))


def g():
    return copy.deepcopy(GRAPH)


def test_bin_pack_detection():
    assert mps.bin_is_vulkan_pack("code-bootstraps-llama.cpp/bin/llama-b11374-linux-x64-vulkan/llama-server")
    assert not mps.bin_is_cpu_pack("code-bootstraps-llama.cpp/bin/llama-b11374-linux-x64-vulkan/llama-server")
    assert mps.bin_is_cpu_pack("code-bootstraps-llama.cpp/bin/llama-b11669-linux-x64-cpu/llama-server")
    assert not mps.bin_is_vulkan_pack("code-bootstraps-llama.cpp/bin/llama-b11669-linux-x64-cpu/llama-server")


def test_coder_default_is_cpu_pack_without_ngram():
    """#82/#83: stock coder uses CPU pack and does not emit speculative flags."""
    a = validate_graph.server_args(g(), "coder")
    assert mps.bin_is_cpu_pack(a[0]) or not mps.bin_is_vulkan_pack(a[0])
    assert "--spec-type" not in a
    assert "--no-op-offload" not in a  # CPU pack: no need


def test_coder_ngram_is_planned_opt_in():
    x = g()
    sp = x["speculative"]["coder-ngram"]
    assert sp["status"] == "planned"
    assert sp["spec_type"] == "ngram-mod"
    sp["status"] = "experimental"
    a = validate_graph.server_args(x, "coder")
    assert a[a.index("--spec-type") + 1] == "ngram-mod"


def test_prefer_cpu_runtime_rewrites_vulkan_ngl0(tmp_path):
    x = g()
    x["_path"] = os.path.join(ROOT, "graph.yaml")
    # Point coder at a Vulkan runtime that exists in the graph.
    assert "llama-b11374" in x["runtimes"]
    x["nodes"]["coder"]["runtime"] = "llama-b11374"
    x["nodes"]["coder"]["offload"] = {"backend": "cpu", "ngl": 0, "split": "none", "main_gpu": 0}
    bin_path, rt_used, notes = mps.prefer_cpu_runtime_bin(x, "coder")
    assert not mps.bin_is_vulkan_pack(bin_path), (bin_path, notes)
    assert rt_used != "llama-b11374" or mps.bin_is_cpu_pack(bin_path)
    a = validate_graph.server_args(x, "coder")
    assert not mps.bin_is_vulkan_pack(a[0])


def test_no_op_offload_when_stuck_on_vulkan_only(tmp_path):
    x = g()
    x["_path"] = str(tmp_path / "graph.yaml")
    # Synthetic: only a Vulkan runtime on this host; no CPU pack available.
    x["runtimes"] = {
        "only-vk": {
            "kind": "llama-server",
            "build": "b99999",
            "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "bin": "pack/llama-b99999-linux-x64-vulkan/llama-server",
            "hosts": ["miryam"],
            "supported_archs": ["qwen35"],
            "backends": ["cpu", "vulkan"],
            "spec_types": ["ngram-mod"],
        }
    }
    x["nodes"]["coder"]["runtime"] = "only-vk"
    x["nodes"]["coder"]["offload"] = {"backend": "cpu", "ngl": 0, "split": "none", "main_gpu": 0}
    for sp in x["speculative"].values():
        sp["status"] = "planned"
    bin_path, _, notes = mps.prefer_cpu_runtime_bin(x, "coder")
    assert mps.bin_is_vulkan_pack(bin_path)
    assert any("no CPU runtime" in n or "--no-op-offload" in n for n in notes)
    assert mps.needs_no_op_offload(x, "coder", bin_path)
    a = validate_graph.server_args(x, "coder")
    assert a[0].endswith("vulkan/llama-server") or "vulkan" in a[0]
    assert "--no-op-offload" in a


def test_server_env_hides_vk_for_backend_cpu():
    x = g()
    name = "coder"
    assert x["nodes"][name]["offload"]["ngl"] == 0
    assert validate_graph.server_env(x, name, {})["GGML_VK_VISIBLE_DEVICES"] == ""
    assert validate_graph.server_env(x, name, {"GGML_VK_VISIBLE_DEVICES": "0"})["GGML_VK_VISIBLE_DEVICES"] == "0"


def test_check_soname_skew_skips_without_platform():
    notes = []
    assert mps.check_soname_skew("/nonexistent/llama-server", note_sink=notes) is True
    assert any("not importable" in n for n in notes)


def test_apply_no_op_offload_idempotent():
    a = mps.apply_no_op_offload(["/bin/llama-server", "-ngl", "0"])
    assert a[1] == "--no-op-offload"
    assert mps.apply_no_op_offload(a) == a


def test_thread_oversubscribe_note_when_vulkan_peer_active():
    x = g()
    x["nodes"]["miryam-gpu-decision"]["status"] = "active"
    x["nodes"]["coder"]["threads"] = 8
    notes = mps.warn_thread_oversubscribe(x, "coder")
    assert any("Vulkan peer" in n for n in notes)


def _install_fake_refuse(monkeypatch, *, refuse_result=None, fingerprint_fn=None):
    """Inject a fake Platform refuse_soname_skew module into sys.modules."""
    mod = types.ModuleType("refuse_soname_skew")
    if refuse_result is None:
        refuse_result = {"ok": True, "reason": "ok"}
    if callable(refuse_result):
        mod.refuse_soname_skew = refuse_result
    else:
        mod.refuse_soname_skew = lambda bin_path, **kw: refuse_result
    if fingerprint_fn is None:
        fingerprint_fn = lambda bin_path, **kw: {
            "bin": {"path": bin_path, "ino": 1, "mtime_ns": 100, "size": 10, "dev": 1},
            "libs": [],
        }
    mod.fingerprint = fingerprint_fn
    monkeypatch.setitem(sys.modules, "refuse_soname_skew", mod)
    return mod


def test_check_soname_skew_hard_refuses_platform_dict(monkeypatch):
    _install_fake_refuse(
        monkeypatch,
        refuse_result={"ok": False, "reason": "soname_skew", "mismatches": [{"soname": "libggml.so"}]},
    )
    notes = []
    assert mps.check_soname_skew("/x/llama-server", note_sink=notes) is False
    assert any("refused" in n for n in notes)


def test_check_soname_skew_allows_platform_ok(monkeypatch):
    _install_fake_refuse(monkeypatch, refuse_result={"ok": True, "reason": "ok"})
    notes = []
    assert mps.check_soname_skew("/x/llama-server", note_sink=notes) is True


def test_assert_fingerprint_stable_refuses_lib_ino_drift(monkeypatch):
    fps = [
        {
            "bin": {"path": "/x/llama-server", "ino": 1, "mtime_ns": 100, "size": 10, "dev": 1},
            "libs": [
                {"path": "/x/libggml.so", "ino": 2, "mtime_ns": 100, "size": 5, "dev": 1},
            ],
        },
        {
            "bin": {"path": "/x/llama-server", "ino": 1, "mtime_ns": 100, "size": 10, "dev": 1},
            "libs": [
                # attacker swapped the .so — same path, new inode
                {"path": "/x/libggml.so", "ino": 99, "mtime_ns": 100, "size": 5, "dev": 1},
            ],
        },
    ]

    def fingerprint(bin_path, **kw):
        return fps.pop(0)

    _install_fake_refuse(monkeypatch, fingerprint_fn=fingerprint)
    cap = mps.capture_spawn_fingerprint("/x/llama-server")
    assert cap is not None
    result = mps.assert_fingerprint_stable("/x/llama-server", cap)
    assert result["ok"] is False
    assert result["reason"] == "soname_fingerprint_drift"
    assert result["drift"]["lib"] == "/x/libggml.so"


def test_assert_fingerprint_stable_refuses_bin_mtime_drift(monkeypatch):
    fps = [
        {
            "bin": {"path": "/x/llama-server", "ino": 1, "mtime_ns": 100, "size": 10, "dev": 1},
            "libs": [],
        },
        {
            "bin": {"path": "/x/llama-server", "ino": 1, "mtime_ns": 999, "size": 10, "dev": 1},
            "libs": [],
        },
    ]

    def fingerprint(bin_path, **kw):
        return fps.pop(0)

    _install_fake_refuse(monkeypatch, fingerprint_fn=fingerprint)
    cap = mps.capture_spawn_fingerprint("/x/llama-server")
    result = mps.assert_fingerprint_stable("/x/llama-server", cap)
    assert result["ok"] is False
    assert result["reason"] == "soname_fingerprint_drift"
    assert "bin" in result["drift"]


def test_assert_fingerprint_stable_allows_stable(monkeypatch):
    stable_fp = {
        "bin": {"path": "/x/llama-server", "ino": 1, "mtime_ns": 100, "size": 10, "dev": 1},
        "libs": [
            {"path": "/x/libllama.so", "ino": 3, "mtime_ns": 50, "size": 20, "dev": 1},
        ],
    }

    def fingerprint(bin_path, **kw):
        return {
            "bin": dict(stable_fp["bin"]),
            "libs": [dict(stable_fp["libs"][0])],
        }

    _install_fake_refuse(monkeypatch, fingerprint_fn=fingerprint)
    cap = mps.capture_spawn_fingerprint("/x/llama-server")
    result = mps.assert_fingerprint_stable("/x/llama-server", cap)
    assert result["ok"] is True
    assert result["reason"] == "ok"


def test_assert_fingerprint_stable_skips_without_platform():
    notes = []
    # Ensure Platform module is not importable for this test.
    sys.modules.pop("refuse_soname_skew", None)
    result = mps.assert_fingerprint_stable("/x/llama-server", {"bin": {}}, note_sink=notes)
    assert result["ok"] is True
    assert result["reason"] == "skipped_no_platform"
    assert any("not importable" in n for n in notes)


def test_assert_fingerprint_stable_skips_without_prior_capture(monkeypatch):
    _install_fake_refuse(monkeypatch)
    notes = []
    result = mps.assert_fingerprint_stable("/x/llama-server", None, note_sink=notes)
    assert result["ok"] is True
    assert result["reason"] == "skipped_no_prior_capture"
