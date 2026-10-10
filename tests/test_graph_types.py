import copy, os, subprocess, sys
import pytest, yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from graph_types import validate_types, TYPES  # noqa: E402
import validate_graph  # noqa: E402

BASE = validate_graph.load(os.path.join(ROOT, "graph.yaml"))

def g(): return copy.deepcopy(BASE)
def errs(graph): return validate_types(graph)
def has(graph, frag):
    e = errs(graph); assert any(frag in x for x in e), e

def test_baseline_valid():
    assert errs(g()) == []

def test_version_required():
    x = g(); x["version"] = 1; has(x, "version: expected 2")

def test_unknown_section_and_field():
    x = g(); x["nodez"] = {}; has(x, "nodez: unknown section")
    x = g(); x["nodes"]["coder"]["ctx_size"] = 1; has(x, "unknown field 'ctx_size'")

@pytest.mark.parametrize("sec,name,key", [("nodes", "coder", "cache_ram_mib"), ("models", "qwen35-2b-q4km", "role"),
                                          ("runtimes", "llama-b11374", "supported_archs"), ("agents", "hermes", "min_ctx")])
def test_no_defaults(sec, name, key):
    x = g(); del x[sec][name][key]; has(x, f"missing required '{key}'")

def test_enums():
    x = g(); x["hosts"]["miryam"]["kind"] = "server"; has(x, "not one of")
    x = g(); x["models"]["qwen35-2b-q4km"]["role"] = "magic"; has(x, "not one of")
    x = g(); x["transports"]["miryam-local"]["kind"] = "ftp"; has(x, "not one of")

def test_measured_host_needs_facts_and_unmeasured_excluded():
    x = g(); del x["hosts"]["miryam"]["ram_mib"]; has(x, "measured host missing required 'ram_mib'")
    x = g(); x["hosts"]["note9"]["ram_mib"] = 6000; has(x, "measured is false")
    x = g(); x["runtimes"]["llama-b11374"]["hosts"].append("note9"); x["nodes"]["coder"]["host"] = "note9"
    has(x, "not measured; unmeasured hosts are excluded")

def test_transport_rules():
    x = g(); x["transports"]["bad"] = {"kind": "local", "from": "miryam", "to": "godslove"}; has(x, "requires from == to")
    x = g(); x["transports"]["bad"] = {"kind": "ssh", "from": "miryam", "to": "nowhere"}; has(x, "no such hosts entry 'nowhere'")

def test_runtime_commit_must_be_sha():
    x = g(); x["runtimes"]["llama-b11374"]["commit"] = "main"; has(x, "not a git sha")

def test_arch_not_supported_catches_gemma_embedding2():
    x = g()
    x["models"]["egemma2"] = {"gguf": "/x.gguf", "sha256": "unmeasured", "arch": "gemma-embedding2", "trained_ctx": 8192, "role": "embed"}
    x["nodes"]["embed"] = dict(x["nodes"]["coder"], model="egemma2", ctx=8192, port=9942)
    has(x, "arch 'gemma-embedding2' not in runtime 'llama-b11374'")

def test_sha_format():
    x = g(); x["models"]["qwen35-2b-q4km"]["sha256"] = "abc"; has(x, "64 lowercase hex")

def test_runtime_not_on_host_and_port_clash():
    x = g(); x["runtimes"]["llama-b11374"]["hosts"] = ["godslove"]; has(x, "not installed on host 'miryam'")
    x = g(); x["nodes"]["c2"] = dict(x["nodes"]["coder"]); has(x, "port 9941 on host 'miryam' also used")

def test_ctx_rules():
    x = g(); x["nodes"]["coder"]["ctx"] = 524288; x["agents"]["hermes"]["context_length"] = 524288
    has(x, "exceeds model trained_ctx")
    x = g(); x["nodes"]["coder"]["parallel"] = 4; has(x, "per-slot ctx 16384 < agent min_ctx 64000")
    x = g(); x["agents"]["hermes"]["context_length"] = 131072; has(x, "context_length 131072 != alias 'coder' per-slot ctx 65536")
    x = g(); x["nodes"]["coder"]["parallel"] = 3; has(x, "not divisible")

def test_offload_rules():
    x = g(); x["nodes"]["coder"]["gpu_layers"] = 10; has(x, "unknown field 'gpu_layers'")
    x = g(); del x["nodes"]["coder"]["offload"]["split"]; has(x, "offload: missing required 'split'")
    x = g(); x["nodes"]["coder"]["offload"]["ngl"] = 5; has(x, "backend cpu requires ngl 0")
    x = g(); x["nodes"]["coder"]["offload"].update(backend="cuda", ngl=5); has(x, "backend 'cuda' not in runtime")
    x = g(); x["nodes"]["coder"]["offload"].update(backend="vulkan", ngl=5); has(x, "unmeasured/unverified GPU 0")
    x = g(); x["nodes"]["coder"]["offload"].update(backend="vulkan", ngl=5, main_gpu=3); has(x, "declares 1 GPU")
    x = g(); x["nodes"]["coder"]["offload"]["split"] = "diag"; has(x, "not one of")

def test_qodesh_gpu_offload_rejected():
    x = g(); x["runtimes"]["llama-b11374"]["hosts"].append("qodesh"); x["runtimes"]["llama-b11374"]["backends"].append("cuda")
    n = x["nodes"]["qodesh-resident"]; n["status"] = "active"; n["offload"].update(backend="cuda", ngl=4)
    has(x, "backend 'cuda' but GPU 0 backend is 'none'")
    has(x, "unmeasured/unverified GPU 0")

def test_gpu_fields():
    x = g(); x["hosts"]["note9"]["gpus"][0]["vram_mib"] = 4096; has(x, "measured is false; leave null")
    x = g(); x["hosts"]["note9"]["gpus"][0]["backend_status"] = "verified"; has(x, "verified requires measured")
    x = g(); x["hosts"]["miryam"]["gpus"][0]["backend"] = "directx"; has(x, "not one of")
    x = g(); del x["hosts"]["shalom"]["gpus"]; has(x, "missing required 'gpus'")
    x = g(); x["hosts"]["miryam"]["gpus"][0]["measured"] = True; has(x, "measured GPU needs vram_mib")
    for h in BASE["hosts"].values(): assert isinstance(h["gpus"], list)

def test_windows_host_block():
    x = g(); del x["hosts"]["qodesh"]["windows"]; has(x, "os windows requires a 'windows' block")
    x = g(); x["hosts"]["qodesh"]["windows"]["startup"] = "magic"; has(x, "windows.startup")
    x = g(); del x["hosts"]["qodesh"]["windows"]["wake"]; has(x, "missing required 'wake'")
    x = g(); x["hosts"]["miryam"]["windows"] = dict(BASE["hosts"]["qodesh"]["windows"]); has(x, "requires os: windows")

def test_reported_only_unmeasured():
    x = g(); x["hosts"]["miryam"]["reported"] = {"source": "x"}; has(x, "only for unmeasured")
    x = g(); x["hosts"]["godslove"]["reported"] = {"ram_mib": 1}; has(x, "with a 'source'")

def test_planned_node_skips_placement():
    assert BASE["nodes"]["qodesh-resident"]["status"] == "planned" and errs(g()) == []
    x = g(); x["nodes"]["qodesh-resident"]["status"] = "active"; has(x, "not installed on host 'qodesh'")

def spec_draft(**kw):
    d = {"experimental": True, "status": "planned", "mode": "draft", "target": "coder", "draft": "egemma2-q8",
         "draft_max": 8, "draft_min": 1, "p_min": 0.75}
    d.update(kw); return d

def test_speculative_draft():
    x = g(); x["speculative"]["d"] = spec_draft(); assert errs(x) == []
    x = g(); x["speculative"]["d"] = spec_draft(draft_min=9); has(x, "draft_min 9 > draft_max 8")
    x = g(); x["speculative"]["d"] = spec_draft(p_min=2); has(x, "expected 0..1")
    x = g(); d = spec_draft(); del d["draft_max"]; x["speculative"]["d"] = d; has(x, "requires 'draft_max'")
    x = g(); x["speculative"]["d"] = spec_draft(draft="qwen35-2b-q4km"); has(x, "draft model is the target")
    x = g(); x["speculative"]["d"] = spec_draft(experimental=False); has(x, "experimental type")
    x = g(); x["runtimes"]["llama-b11374"]["spec_types"] = []; x["speculative"]["d"] = spec_draft(); has(x, "does not list spec_type")

def test_speculative_ngram():
    x = g(); x["speculative"]["coder-ngram"]["spec_type"] = "draft-simple"; has(x, "needs an ngram-* spec_type")
    x = g(); x["speculative"]["coder-ngram"]["draft"] = "egemma2-q8"; has(x, "only applies to mode draft")

def test_speculative_vocab_mismatch_and_ram():
    # egemma2 (gemma4 tokenizer) cannot draft for qwen35 (gpt2 tokenizer): file-level check
    x = g(); x["_path"] = os.path.join(ROOT, "graph.yaml"); x["speculative"]["d"] = spec_draft()
    if not os.path.isfile(os.path.expanduser(BASE["models"]["egemma2-q8"]["gguf"])): pytest.skip("GGUFs not on this machine")
    e, tot = validate_graph.validate(x); assert any("tokenizer/vocab mismatch" in m for m in e), e
    _, base = validate_graph.validate(g()); assert tot["miryam"] > base["miryam"] + 290  # draft weights counted

def test_server_args_spec_flags():
    x = g(); x["speculative"]["d"] = spec_draft(status="experimental"); x["speculative"]["coder-ngram"]["status"] = "planned"
    a = validate_graph.server_args(x, "coder")
    for f in ("-md", "--spec-draft-n-max", "--spec-draft-n-min", "--spec-draft-p-min"): assert f in a
    assert "--draft-max" not in a  # removed upstream
    assert "--embeddings" in validate_graph.server_args(g(), "embed")

def test_alias_exactly_one_node():
    x = g(); x["aliases"]["coder"]["node"] = ["coder"]; has(x, "expected a nodes name")
    x = g(); x["aliases"]["coder"]["node"] = "auto"; has(x, "no such nodes entry 'auto'")

def test_duplicate_yaml_keys_rejected(tmp_path):
    p = tmp_path / "g.yaml"; p.write_text("version: 2\naliases:\n  coder: {node: a}\n  coder: {node: b}\n")
    with pytest.raises(yaml.YAMLError): validate_graph.load(str(p))

def test_alias_gateway_needs_transport():
    x = g(); x["hosts"]["box2"] = dict(x["hosts"]["miryam"]); x["gateways"]["roomz"]["host"] = "box2"
    has(x, "has no transport to node host")
    x["transports"]["l"] = {"kind": "ssh", "from": "box2", "to": "miryam"}; assert errs(x) == []

def test_agent_roles():
    x = g(); del x["agents"]["hermes"]["aliases"]["auxiliary"]; has(x, "missing required role 'auxiliary'")
    x = g(); x["agents"]["hermes"]["aliases"]["vision"] = "coder"; has(x, "unknown role 'vision'")
    x = g(); x["agents"]["hermes"]["aliases"]["main"] = ["coder", "coder"]; has(x, "exactly one alias per role")
    x = g(); x["agents"]["hermes"]["aliases"]["main"] = "nope"; has(x, "no such alias 'nope'")

def test_fleet_and_agency():
    x = g(); x["fleets"]["green-agentz"]["agents"] = ["ghost"]; has(x, "no such agents entry 'ghost'")
    x = g(); x["agencies"]["familia-issues"]["assignments"]["wontfix"] = "hermes"; has(x, "label 'wontfix' not in labels")
    x = g(); x["agencies"]["familia-issues"]["assignments"]["bug"] = "ghost"; has(x, "no such agent 'ghost'")
    x = g(); x["agencies"]["familia-issues"]["repo"] = "familia"; has(x, "expected owner/name")

def test_experimental_stubs():
    x = g()
    x["rooms"] = {"r": {"experimental": True, "gateway": "roomz", "agents": ["hermes"]}}
    x["swarms"] = {"s": {"experimental": True, "rooms": ["r"]}}
    x["stores"] = {"st": {"experimental": True, "kind": "fs", "host": "miryam", "path": "~/.familia"}}
    x["reaches"] = {"re": {"experimental": True, "repo": "brianreborn/agent-reach", "agents": ["hermes"]}}
    x["councils"] = {"q": {"experimental": True, "mode": "quorum", "quorum": 1, "agents": ["hermes"]},
                     "c": {"experimental": True, "mode": "cascade", "agents": ["hermes"]}}
    assert errs(x) == []
    y = copy.deepcopy(x); y["rooms"]["r"]["experimental"] = False; has(y, "experimental type")
    y = copy.deepcopy(x); y["councils"]["q"]["quorum"] = 2; has(y, "quorum 2 must be between 1 and 1")
    y = copy.deepcopy(x); del y["councils"]["q"]["quorum"]; has(y, "requires integer 'quorum'")
    y = copy.deepcopy(x); y["councils"]["c"]["quorum"] = 1; has(y, "only applies to mode quorum")

def test_registry_extension():
    TYPES["probes"] = type(TYPES["fleets"])({"target": TYPES["aliases"].fields["node"]}, experimental=False)
    try:
        x = g(); x["probes"] = {"p": {"target": "coder"}}; assert errs(x) == []
        x["probes"]["p"]["target"] = "zzz"; has(x, "probes.p.target: no such nodes entry")
    finally:
        del TYPES["probes"]

def test_cli_baseline_schema_only():
    r = subprocess.run([sys.executable, "scripts/validate_graph.py", "--no-files"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_cli_fails_loud(tmp_path):
    x = g(); x["agents"]["hermes"]["context_length"] = 16384
    p = tmp_path / "g.yaml"; p.write_text(yaml.safe_dump(x))
    r = subprocess.run([sys.executable, "scripts/validate_graph.py", "--no-files", "--graph", str(p)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 1 and "graph: ERROR: agents.hermes: context_length 16384" in r.stderr
