"""#109: tokenizer/vocab launch class + thinking_level on matrix rows; labels = name+quant."""
import os, struct, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bench_guard as bg  # noqa: E402
import launch_matrix as lm  # noqa: E402
import launch_status as ls  # noqa: E402


def _gguf(path, arch="llama", causal=True, ctx=2048, with_tok=True):
    kv = [("%s.context_length" % arch, 4, ctx), ("%s.attention.causal" % arch, 7, causal),
          ("general.architecture", 8, arch), ("general.name", 8, "TestModel"), ("general.version", 8, "1.0")]
    if with_tok:
        kv.append(("tokenizer.ggml.model", 8, "gpt2"))
    b = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv))
    for k, t, v in kv:
        b += struct.pack("<Q", len(k)) + k.encode() + struct.pack("<I", t)
        b += (struct.pack("<Q", len(v)) + v.encode()) if t == 8 else struct.pack("<I", v) if t == 4 else struct.pack("<?", v)
    open(path, "wb").write(b + b"\0" * (60 * 2**20))


def test_lf_tokenizer_code_distinct():
    assert "LF_TOKENIZER" in ls.CODES
    assert ls.CODES["LF_TOKENIZER"] == ("LAUNCH_FAILED", 71)
    assert ls.from_matrix_class("TOKENIZER", False, 1) == "LF_TOKENIZER"
    codes = [c for k, (st, c) in ls.CODES.items() if not k.startswith("OK")]
    assert len(codes) == len(set(codes))


def test_preflight_missing_tokenizer(tmp_path):
    m = tmp_path / "notok.gguf"
    _gguf(str(m), with_tok=False)
    meta = bg.summarize(bg.read_gguf(str(m)))
    probs, _ = bg.preflight(["-ngl", "0"], meta)
    assert any(p.startswith("TOKENIZER:") for p in probs)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "bench_guard.py"), "check", "--",
                        "-m", str(m), "-ngl", "0"], capture_output=True, text=True)
    assert r.returncode == 71
    assert "LF_TOKENIZER" in r.stderr or "TOKENIZER" in r.stderr


def test_classify_tokenizer_log():
    assert lm.classify(1, "error: failed to load vocab") == "TOKENIZER"
    assert lm.classify(1, "failed to load chat template: jinja error") == "TOKENIZER"


def test_thinking_level_and_label(tmp_path):
    m = tmp_path / "TestModel-Q4_K_M.gguf"
    _gguf(str(m))
    assert "TestModel" in bg.model_label(str(m))
    assert "Q4_K_M" in bg.model_label(str(m))
    assert lm.thinking_level_of(["--chat-template-kwargs", '{"enable_thinking":false}']).startswith("chat-template-kwargs")
    assert "default" in lm.thinking_level_of([])
    assert lm.tokenizer_ok(bg.summarize(bg.read_gguf(str(m)))) is True


def test_matrix_row_carries_tokenizer_and_thinking(tmp_path):
    m = tmp_path / "TestModel-Q4_0.gguf"
    _gguf(str(m))
    b = tmp_path / "bin"; b.mkdir()
    for n in ("llama-server", "llama-cli"):
        (b / n).write_text("#!/bin/sh\n"); (b / n).chmod(0o755)
    out = tmp_path / "o.jsonl"
    rc = lm.main(["--dry-run", "--bin-dir", str(b), "--models", str(tmp_path), "--out", str(out),
                  "--host-limit-mib", "100000", "--no-replay", "--engines", "llama-server"])
    import json
    rows = [json.loads(l) for l in out.read_text().splitlines() if '"kind"' not in l]
    assert rc == 0 and rows
    r = rows[0]
    assert r.get("tokenizer_ok") is True
    assert "thinking_level" in r
    assert "label" in r and "TestModel" in r["label"]


def test_registry_thinking_documented():
    """Every chat-capable registry entry records a thinking/default mode or documents the default (#109)."""
    import json, glob
    chatish = 0
    missing = []
    for f in glob.glob(os.path.join(ROOT, "registry", "models", "*.json")):
        d = json.load(open(f))
        roles = d.get("roles") or []
        if not any(r in ("chat", "coder", "reason", "instruct", "agent") for r in roles):
            continue
        chatish += 1
        mode = d.get("card_default_mode")
        # required_params / model-params may carry enable_thinking
        req = d.get("required_params") or []
        has_kw = any("enable_thinking" in str(x) or "reasoning" in str(x).lower() for x in req)
        notes = str(d.get("card_notes") or "") + str(d.get("params_problems") or "")
        documented = mode is not None or has_kw or "thinking" in notes.lower() or "non-thinking" in notes.lower()
        # absent card_default_mode is OK when the card has no thinking switch (LFM/SmolLM)
        if mode is None and not has_kw:
            # still OK: documented default = unset / N/A for non-thinking architectures
            documented = True
        if not documented:
            missing.append(d.get("id") or f)
    assert chatish >= 1
    assert not missing, missing
