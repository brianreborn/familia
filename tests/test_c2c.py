import copy, os, shutil, subprocess, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, os.path.join(ROOT, "scripts", "c2c"))
from graph_types import validate_types  # noqa: E402
import validate_graph, kv_ship  # noqa: E402
BASE = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
SHA = "a" * 64

def active_pair():
    g = copy.deepcopy(BASE)
    g["models"]["qwen35-2b-q4km"]["sha256"] = SHA
    n2 = copy.deepcopy(g["nodes"]["coder"]); n2["port"] = 9942; g["nodes"]["coder2"] = n2
    g["kv_channels"] = {"c": {"experimental": True, "status": "experimental", "from": "coder", "to": "coder2", "via": "local"}}
    return g

def errs(g): return [e for e in validate_types(g) if e.startswith("kv_channels")]

def test_baseline_planned_ok():
    assert validate_types(copy.deepcopy(BASE)) == []

def test_active_pair_ok():
    assert errs(active_pair()) == []

@pytest.mark.parametrize("mut,frag", [
    (lambda g: g["nodes"]["coder2"].update(kv_type="f16"), "kv_type differs"),
    (lambda g: g["nodes"]["coder2"].update(ctx=32768), "per-slot ctx differs"),
    (lambda g: g["nodes"]["coder2"].update(runtime="llama-b11539"), "runtime build differs"),
    (lambda g: g["nodes"]["coder2"].update(model="egemma2-q8"), "model sha256 differs"),
    (lambda g: g["models"]["qwen35-2b-q4km"].update(sha256="unmeasured"), "sha256 unmeasured"),
    (lambda g: g["kv_channels"]["c"].update(to="coder"), "same node"),
    (lambda g: g["kv_channels"]["c"].update(experimental=False), "experimental type"),
])
def test_mismatch_refused(mut, frag):
    g = active_pair(); mut(g)
    assert any(frag in e for e in errs(g)), errs(g)

def test_runtime_compare():
    fp = {"build_info": "b1", "n_ctx_slot": 128, "model_sha256": SHA}
    assert kv_ship.compare(fp, dict(fp), "f16/f16", "f16/f16") == []
    assert kv_ship.compare(fp, dict(fp, build_info="b2"), "f16/f16", "f16/f16")
    assert kv_ship.compare(fp, dict(fp, model_sha256="b" * 64), "f16/f16", "f16/f16")
    assert kv_ship.compare(fp, dict(fp, n_ctx_slot=None), "f16/f16", "f16/f16")
    assert kv_ship.compare(fp, dict(fp), "f16/f16", "q8_0/q8_0")

BIN = os.environ.get("C2C_LLAMA_SERVER"); GGUF = os.environ.get("C2C_GGUF")
@pytest.mark.skipif(not (BIN and GGUF), reason="set C2C_LLAMA_SERVER and C2C_GGUF (stories15M) to run loopback")
def test_loopback(tmp_path):
    p = subprocess.run(["sh", os.path.join(ROOT, "scripts/c2c/loopback_test.sh"), BIN, GGUF, str(tmp_path)],
                       capture_output=True, text=True, timeout=180)
    assert "LOOPBACK OK" in p.stdout, p.stdout + p.stderr
