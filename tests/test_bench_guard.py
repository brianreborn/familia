"""scripts/bench_guard.py: metadata validation, flag rewriting, encoder ubatch, memory cap."""
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bench_guard as bg  # noqa: E402


def _gguf(path, kv):
    def s(x):
        b = x.encode()
        return struct.pack("<Q", len(b)) + b
    out = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv))
    for k, v in kv.items():
        out += s(k)
        if isinstance(v, bool):
            out += struct.pack("<I?", 7, v)
        elif isinstance(v, int):
            out += struct.pack("<II", 4, v)
        elif isinstance(v, float):
            out += struct.pack("<If", 6, v)
        elif isinstance(v, list):
            out += struct.pack("<IIQ", 9, 8, len(v)) + b"".join(s(t) for t in v)
        else:
            out += struct.pack("<I", 8) + s(v)
    path.write_bytes(out)
    return str(path)


FULL = {"general.architecture": "qwen3", "qwen3.context_length": 40960, "qwen3.rope.freq_base": 1e6,
        "tokenizer.ggml.model": "gpt2", "tokenizer.ggml.tokens": ["a"] * 100,
        "tokenizer.chat_template": "{{ x }}", "general.sampling.temp": 0.7}


def test_full_header_is_valid(tmp_path):
    m = bg.summarize(bg.read_gguf(_gguf(tmp_path / "m.gguf", FULL)))
    assert m["architecture"] == "qwen3" and m["context_length"] == 40960 and m["vocab_size"] == 100
    assert bg.validate(m) == ([], [])


def test_missing_required_is_critical_even_if_documented(tmp_path):
    kv = dict(FULL)
    del kv["qwen3.context_length"]
    m = bg.summarize(bg.read_gguf(_gguf(tmp_path / "m.gguf", kv)))
    problems, _ = bg.validate(m, {"context_length": "4096"})
    assert any("CRITICAL: context_length" in p for p in problems)


def test_missing_sampling_needs_documented_default(tmp_path):
    kv = {k: v for k, v in FULL.items() if not k.startswith("general.sampling")}
    m = bg.summarize(bg.read_gguf(_gguf(tmp_path / "m.gguf", kv)))
    assert any("sampling" in p for p in bg.validate(m)[0])
    problems, notes = bg.validate(m, {"sampling": "llama-bench samples nothing"})
    assert problems == [] and notes == ["sampling: missing, defaults used: llama-bench samples nothing"]


def test_cli_meta_accepts_documented_default(tmp_path, capsys):
    kv = {k: v for k, v in FULL.items() if not k.startswith("general.sampling")}
    f = _gguf(tmp_path / "m.gguf", kv)
    assert bg.main(["meta", f]) == 1
    capsys.readouterr()
    assert bg.main(["meta", f, "--default", "sampling=llama-bench samples nothing"]) == 0
    assert "sampling: missing, defaults used: llama-bench samples nothing" in capsys.readouterr().out
    assert bg.main(["meta", f, "--default", "context_length=4096", "--default", "sampling=x"]) == 0


def test_not_gguf(tmp_path):
    p = tmp_path / "x.gguf"
    p.write_bytes(b"nope")
    with pytest.raises(ValueError):
        bg.read_gguf(str(p))


def test_encoder_ubatch_rule():
    enc = {"causal": False}
    assert bg.encoder_batch(enc, 1024) == (2048, 1024)
    assert bg.encoder_batch({"pooling_type": 3}, 4096) == (4096, 4096)
    assert bg.encoder_batch({"causal": True}, 4096) == (2048, 512)


def test_legacy_flags_rewritten():
    a = bg.modern_args(["-m", "x", "-mmp", "0", "-md", "d", "--draft-max", "2"])
    assert a == ["-m", "x", "-lm", "none", "-md", "d", "--spec-draft-n-max", "2", "--spec-type", "draft-simple"]
    assert bg.modern_args(["--no-mmap"]) == ["-lm", "none"]


def test_flags_checked_against_pinned_build():
    if not os.path.isfile(os.path.join(ROOT, "registry", "llama-builds", "b11374.json")):
        pytest.skip("no b11374 table")
    assert bg.modern_args(["-mmp", "0", "-t", "2"], build="b11374") == ["-lm", "none", "-t", "2"]
    with pytest.raises(ValueError):
        bg.modern_args(["--definitely-not-a-flag"], build="b11374")


def test_mem_cap_from_measured_peak():
    assert bg.mem_cap_mib(1854) == 1854 + int(1854 * 0.15)
    assert bg.mem_cap_mib(500) == 756  # min margin
    assert bg.mem_cap_mib(3300, host_limit_mib=3584) == 3584
    assert bg.mem_cap_mib(3700, host_limit_mib=3584) is None


def test_effective_from_load_log():
    log = ("llama_context: n_ctx         = 8448\nllama_context: n_batch       = 2048\n"
           "llama_context: n_ubatch      = 512\nllama_context: flash_attn    = enabled\n")
    e = bg.effective(log)
    assert e["n_ctx"] == "8448" and e["n_ubatch"] == "512" and e["flash_attn"] == "enabled"


def test_graph_load_mode_reaches_server_args():
    import validate_graph as vg
    g = vg.load(os.path.join(ROOT, "graph.yaml"))
    if g["nodes"].get("coder", {}).get("load_mode") != "none":
        pytest.skip("coder has no load_mode")
    a = vg.server_args(g, "coder")
    assert a[a.index("-lm") + 1] == "none"
    g["nodes"]["coder"]["load_mode"] = "bogus"
    errs, _ = vg.validate(g, check_files=False)
    assert any("load_mode" in e for e in errs), errs


def test_model_label_is_name_and_quant_never_hash(tmp_path):
    f = _gguf(tmp_path / "Qwen3.5-9B-Q4_K_M.gguf", dict(FULL, **{"general.name": "Qwen3.5-9B", "general.file_type": 15}))
    assert bg.model_label(f) == "Qwen3.5-9B Q4_K_M"
    h = "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"
    f2 = _gguf(tmp_path / (h + ".gguf"), dict(FULL, **{"general.name": "Gpt Oss 20b", "general.file_type": 15}))
    assert h not in bg.model_label(f2) and bg.model_label(f2).startswith("Gpt Oss 20b")
    f3 = _gguf(tmp_path / "LFM2.5-8B-A1B-Q4_0.gguf", {"general.architecture": "lfm2"})
    assert bg.model_label(f3) == "LFM2.5-8B-A1B-Q4_0"
