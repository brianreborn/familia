"""Consumer-conformance tests (config-usage duplication audit).

For each requirement ID / duplication cluster, every code path that reads the same
config must interpret it identically. We load one fixture graph through each path and
compare resolved values. A divergence is a strict xfail citing the cluster + CFG ID.
Offline: no servers, no network, no launches.
"""
import os, pathlib, sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
FIX = ROOT / "tests/fixtures/config/conformance-graph.yaml"


def _strip(g):
    return {k: v for k, v in (g or {}).items() if k != "_path"}


# --- DUP-01: graph.yaml loader (CFG-FILE-007, CFG-GRAPH-*) ---
def _loaders():
    import familia_yaml, offline_improve, monitor, guardian_ready, hosts_overlay
    return {
        "familia_yaml.load": lambda: familia_yaml.load(str(FIX)),
        "offline_improve._load_graph": lambda: offline_improve._load_graph(FIX),
        "monitor.load_graph": lambda: monitor.load_graph(str(FIX)),
        "guardian_ready._load_graph": lambda: guardian_ready._load_graph(str(FIX)),
        "hosts_overlay.load_graph_with_overlay": lambda: hosts_overlay.load_graph_with_overlay(str(FIX), apply_overlay=False),
    }


@pytest.mark.parametrize("name", list(_loaders()))
def test_dup01_loaders_agree(name):
    """CFG-FILE-007 / DUP-01: every ad-hoc loader yields the same parsed graph."""
    got = _strip(_loaders()[name]())
    ref = _strip(_loaders()["familia_yaml.load"]())
    assert got == ref, f"{name} diverges from familia_yaml.load (DUP-01)"


# --- DUP-02: graph path + FAMILIA_GRAPH resolution (CFG-FILE-007) ---
def _graph_path_resolvers(monkeypatch, custom):
    monkeypatch.setenv("FAMILIA_GRAPH", custom)
    import importlib
    import familia_agent_reach, skills, guardian_ready
    importlib.reload(guardian_ready)  # module-level DEFAULT_GRAPH
    return {
        "familia_agent_reach.graph_path": familia_agent_reach.graph_path(),
        "skills.graph_path": skills.graph_path(),
        "guardian_ready.DEFAULT_GRAPH": guardian_ready.DEFAULT_GRAPH,
    }


def test_dup02_graph_path_honours_env(monkeypatch):
    custom = "/custom/elsewhere/graph.yaml"
    res = _graph_path_resolvers(monkeypatch, custom)
    assert all(v == custom for v in res.values()), res


# --- DUP-03: active/planned node filtering (CFG-GRAPH-NODES-102, CFG-SPEC-PLAN-002) ---
def test_dup03_active_node_filter_agrees():
    """Every path that picks auto-routable nodes must select active-only, per host."""
    import familia_yaml, start_graph
    g = familia_yaml.load(str(FIX))
    sg = start_graph.local_topology(g, "h1")
    names = sg[0] if isinstance(sg, tuple) else sg
    start_active = {n[0] if isinstance(n, (tuple, list)) else n for n in names}
    naive = {n for n, nd in g["nodes"].items() if nd.get("status") == "active" and nd.get("host") == "h1"}
    assert naive == {"coder-a"}
    assert start_active >= naive, (start_active, naive)


# --- DUP-04: launch argv builder incl. --tools (CFG-GRAPH-NODES-108, CFG-SPEC-TOOLS-001) ---
def test_dup04_server_args_is_single_owner():
    """validate_graph.server_args is the one argv builder; it enforces the model-db
    contract (DUP-04). A node without a model-db entry fails here, not in start_graph."""
    import familia_yaml, validate_graph
    g = familia_yaml.load(str(FIX)); g["_path"] = str(FIX)
    with pytest.raises(SystemExit) as ei:
        validate_graph.server_args(g, "coder-a")
    assert "model database" in str(ei.value)


def test_dup04_every_launch_has_explicit_tools():
    """CFG-SPEC-TOOLS-001/002: the single argv owner decides --tools per TYPE on every
    launch. coder=all; chat/general=read set; embed/decision/reasoning/guardian/pentest=none
    (no --tools: llama.cpp is tools-disabled by default). node.server_tools overrides."""
    import familia_yaml, validate_graph as v
    g = familia_yaml.load(str(FIX))
    assert v.tools_argv(g, "coder-a") == ["--tools", "all"]
    g["nodes"]["coder-a"]["role"] = "chat"
    assert v.tools_argv(g, "coder-a") == ["--tools", "read_file,file_glob_search,grep_search,get_info"]
    for t in ("embed", "decision", "reasoning", "guardian", "pentest"):
        g["nodes"]["coder-a"]["role"] = t
        assert v.tools_argv(g, "coder-a") == [], t
    g["nodes"]["coder-a"]["server_tools"] = ["read_file"]
    assert v.tools_argv(g, "coder-a") == ["--tools", "read_file"]


# --- DUP-05: alias -> node resolution (CFG-GRAPH-ALIASES-*) ---
def test_dup05_alias_resolves_to_node():
    import familia_yaml, graph_types
    g = familia_yaml.load(str(FIX))
    assert graph_types.lookup(g, "aliases", "coder") == g["aliases"]["coder"]
