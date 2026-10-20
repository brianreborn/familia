"""scripts/launch_matrix.py dry-run + bench_guard preflight/check (launch guard)."""
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bench_guard as bg  # noqa: E402
import launch_matrix as lm  # noqa: E402


def _gguf(path, arch="llama", causal=True, ctx=2048):
    kv = [("general.architecture", 8, arch), ("%s.context_length" % arch, 4, ctx),
          ("tokenizer.ggml.model", 8, "gpt2"), ("%s.attention.causal" % arch, 7, causal)]
    b = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv))
    for k, t, v in kv:
        b += struct.pack("<Q", len(k)) + k.encode() + struct.pack("<I", t)
        b += (struct.pack("<Q", len(v)) + v.encode()) if t == 8 else struct.pack("<I", v) if t == 4 else struct.pack("<?", v)
    open(path, "wb").write(b + b"\0" * (60 * 2**20))  # > 50 MiB so the matrix picks it up


def test_preflight_flags_past_crash_params(tmp_path):
    m = tmp_path / "enc.gguf"; _gguf(str(m), "bert", causal=False)
    meta = bg.summarize(bg.read_gguf(str(m)))
    probs, _ = bg.preflight(["-ub", "64", "-p", "1024"], meta)
    assert any("encoder" in p for p in probs)
    assert bg.preflight(["-ctv", "q8_0", "-fa", "off"])[0]
    assert bg.preflight(["-ngl", "99"], legacy_gpu=True)[0]
    assert bg.preflight(["-c", "8192"], {"context_length": 2048, "architecture": "x", "tokenizer_model": "y"})[0]
    assert bg.preflight(["-mmp", "0"])[1] == ["-lm", "none"]
    assert not bg.preflight(["-ub", "2048", "-p", "1024"], meta)[0]


def test_check_cli_refuses_with_message(tmp_path):
    m = tmp_path / "enc.gguf"; _gguf(str(m), "bert", causal=False)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "bench_guard.py"), "check", "--",
                        "-m", str(m), "-ub", "64", "-p", "1024"], capture_output=True, text=True)
    assert r.returncode == 3 and "refusing launch" in r.stderr


def test_classify():
    assert lm.classify(-6, "GGML_ASSERT(n_ubatch >= n_tokens)") == "BAD_PARAMS"
    assert lm.classify(-11, "Segmentation fault") == "ENGINE_BUG"
    assert lm.classify(127, "") == "MISSING_RUNTIME"
    assert lm.classify(-9, "", capkill=True) == "OOM"
    assert lm.classify(1, "error: invalid parameter for argument: -mmp") == "BAD_PARAMS"
    assert lm.classify(1, "llama_model_load: error loading model: unknown model architecture: 'x'") == "MODEL_FILE"


def test_matrix_dry_run(tmp_path):
    _gguf(str(tmp_path / "m.gguf"))
    b = tmp_path / "bin"; b.mkdir()
    for n in ("llama-server", "llama-cli"):
        (b / n).write_text("#!/bin/sh\n"); (b / n).chmod(0o755)
    out = tmp_path / "o.jsonl"
    rc = lm.main(["--dry-run", "--bin-dir", str(b), "--models", str(tmp_path), "--out", str(out),
                  "--host-limit-mib", "100000"])
    lines = out.read_text().splitlines()
    assert rc == 0 and len([l for l in lines if '"replay"' not in l]) == len(lm.ENGINES)
