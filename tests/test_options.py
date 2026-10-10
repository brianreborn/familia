import copy, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from graph_types import validate_types  # noqa: E402
import validate_graph  # noqa: E402
BASE = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
def g(): return copy.deepcopy(BASE)
def has(x, frag):
    e = validate_types(x); assert any(frag in m for m in e), e

def test_all_options_unverified_and_unplaced():
    opts = BASE["options"]
    assert opts and all(o["unverified"] is True for o in opts.values())
    assert not set(opts) & set(BASE["models"])

def test_decision_gpu_candidates():
    d = {n: o for n, o in BASE["options"].items() if o["role"] == "decision"}
    assert {"k2-type-0.9b", "drex-1.5", "drex-1.1", "glide", "cloudflare-clef", "gev-26b-decide"} <= set(d)
    assert d["k2-type-0.9b"]["gpu_candidate"] is True and d["gev-26b-decide"]["gpu_candidate"] is False

def test_option_checks():
    x = g(); x["options"]["glide"]["unverified"] = False; has(x, "needs hf_repo")
    x = g(); x["options"]["dolphin3-cyber-8b"]["gpu_candidate"] = True; has(x, "only for role decision")
    x = g(); del x["options"]["glide"]["gpu_host"]; has(x, "needs gpu_host")
    x = g(); x["options"]["glide"]["candidate_hosts"] = ["nowhere"]; has(x, "no such host")
    x = g(); x["options"]["qwen35-2b-q4km"] = copy.deepcopy(x["options"]["glide"]); has(x, "same name as a placed model")
    x = g(); x["options"]["glide"]["role"] = "oracle"; has(x, "not one of")
    x = g(); del x["options"]["glide"]["unverified"]; has(x, "missing required 'unverified'")

def test_options_not_ram_counted():
    x = g(); x["options"]["huge"] = {"role": "coder", "unverified": True, "sources": ["s"], "size_note": "999 GB"}
    assert validate_types(x) == []

def test_speech_and_coder_options():
    o = BASE["options"]
    assert o["whistle-stt"]["role"] == "stt" and o["paradee-tts"]["role"] == "tts"
    assert o["qwen35-9b-coder"]["candidate_hosts"] == ["qodesh"]
