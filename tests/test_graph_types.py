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

def test_gpu_layers_without_vram():
    x = g(); x["nodes"]["coder"]["gpu_layers"] = 10; has(x, "vram_mib 0")

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
