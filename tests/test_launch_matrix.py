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
    assert r.returncode == 64 and "FAMILIA-LAUNCH" in r.stderr and "refusing launch" in r.stderr


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


def test_killer_attribution():
    assert lm.killer(-9, True, "") == "matrix-headroom"
    assert lm.killer(-9, False, "earlyoom[1]: sending SIGKILL to process 42") == "earlyoom"
    assert lm.killer(-9, False, "Out of memory: Killed process 42 (llama-server)") == "kernel-oom"
    assert lm.killer(-9, False, "systemd-oomd[1]: Killed /user.slice/x") == "systemd-oomd"
    assert lm.killer(0, False, "") is None


def test_protocol_codes_distinct_and_mapping():
    import launch_status as ls
    codes = [c for k, (st, c) in ls.CODES.items() if not k.startswith("OK")]
    assert len(codes) == len(set(codes))
    assert ls.from_matrix_class("BAD_PARAMS", False, 1) == "LF_BAD_PARAMS"
    assert ls.from_matrix_class("ENGINE_BUG", True, -6, None, "GGML_ASSERT") == "CR_ASSERT"
    assert ls.from_matrix_class("OOM", True, -9, "earlyoom") == "KL_EARLYOOM"
    r = ls.record("CR_OOM_MEMCG", "llama-server", "m.gguf", rc=-9)
    assert r["v"] == 1 and r["status"] == "CRASHED" and r["phase"] == "run"


def test_admission_budget_composes(tmp_path, monkeypatch):
    import launch_status as ls
    monkeypatch.setattr(ls, "LEDGER", str(tmp_path / "led.json"))
    monkeypatch.setattr(ls, "_rss", lambda pid: 0)  # live, nothing resident yet
    assert ls.admit(3000, 101, avail=6000, total=24000)[0]          # 6000-1536 = 4464 free
    assert not ls.admit(3000, 102, avail=6000, total=24000)[0]      # first launch still owns 3000 outstanding
    ls.release(101)
    assert ls.admit(3000, 102, avail=6000, total=24000)[0]
    monkeypatch.setattr(ls, "_rss", lambda pid: 99999)  # fully resident: only the MemTotal sum binds
    assert ls.admit(17000, 103, avail=99999, total=23000)[0]
    assert not ls.admit(10000, 104, avail=99999, total=23000)[0]    # 17+10 GiB > 23-1.5 GiB


def test_matrix_records_carry_protocol(tmp_path):
    _gguf(str(tmp_path / "m.gguf"))
    b = tmp_path / "bin"; b.mkdir()
    out = tmp_path / "o.jsonl"
    lm.main(["--dry-run", "--no-replay", "--bin-dir", str(b), "--models", str(tmp_path), "--out", str(out), "--host-limit-mib", "100000"])
    import json
    recs = [json.loads(l) for l in out.read_text().splitlines()]
    assert all(r["status"]["v"] == 1 for r in recs)
    assert any(r["status"]["code"] == "LF_MISSING_RUNTIME" for r in recs)
