"""Race seatbelts for #83 (ngl0 / Vulkan) and #82 (ngram opt-in). No GPU required."""
import copy
import os
import sys

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
