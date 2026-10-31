import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import start_graph  # noqa: E402
import validate_graph  # noqa: E402

GRAPH = validate_graph.load(os.path.join(ROOT, "graph.yaml"))


def graph():
    return copy.deepcopy(GRAPH)


def test_host_selection_requires_an_exact_declared_graph_host(tmp_path):
    g = graph()
    env = {"XDG_STATE_HOME": str(tmp_path)}  # isolate from this machine's hostname pin
    assert start_graph.select_host(g, environ=dict(env), hostname="miryam.example") == "miryam"
    assert start_graph.select_host(g, requested="angel", environ={**env, "FAMILIA_HOST": "miryam"}) == "angel"
    with pytest.raises(start_graph.StartupError, match="not declared"):
        start_graph.select_host(g, environ=dict(env), hostname="codespace")
    # OS hostname can differ from the graph key via hosts.*.local_names
    assert start_graph.select_host(g, environ=dict(env), hostname="grok-bot-vm-414232872") == "box"


def test_local_topology_starts_only_local_active_nodes_and_routes():
    nodes, remote, gateways, omitted, remote_gateways = start_graph.local_topology(graph(), "miryam")
    assert nodes == ["coder", "embed"]
    assert {name for name, _ in remote} >= {"qodesh-gpu-decision", "qodesh-resident"}
    assert len(gateways) == 1
    name, gateway, aliases = gateways[0]
    assert name == "roomz"
    assert gateway["port"] == 9931
    assert aliases == {
        "coder": {"kind": "chat", "url": "http://127.0.0.1:9941"},
        "general": {"kind": "chat", "url": "http://127.0.0.1:9941"},
        "embed": {"kind": "embedding", "url": "http://127.0.0.1:9951"},
    }
    # planned/unbuilt roles on miryam are listed, not started (graph.yaml)
    assert {role for role, _node, host in omitted} == {"defender", "guardian", "pentest", "safe-build"}
    assert all(host == "miryam" for _r, _n, host in omitted)
    assert remote_gateways == []


def test_freebsd_host_runs_its_nodes_without_starting_a_gateway():
    # angel-coder is active on angel since the Nanbeige prize; the gateway stays on miryam
    nodes, remote, gateways, omitted, remote_gateways = start_graph.local_topology(graph(), "angel")
    assert nodes == ["angel-coder"]
    assert remote
    assert gateways == []
    assert omitted == []
    assert remote_gateways == [("roomz", "miryam")]


def test_local_active_node_with_unimplemented_runtime_fails_closed():
    g = graph()
    g["nodes"]["qodesh-gpu-decision"]["host"] = "miryam"
    with pytest.raises(start_graph.StartupError, match="unsupported runtime kind"):
        start_graph.validate_local_nodes(g, "miryam", ["qodesh-gpu-decision"], check_files=False)


def test_graph_proxy_manifest_preserves_graph_routes_without_remote_aliases():
    g = graph()
    _, _, gateways, _, _ = start_graph.local_topology(g, "miryam")
    name, gateway, aliases = gateways[0]
    manifest = start_graph.graph_proxy_manifest("miryam", gateway, aliases)
    assert manifest == {
        "schema_version": 1,
        "graph_host": "miryam",
        "gateway": {"host": "127.0.0.1", "port": 9931},
        "aliases": aliases,
    }


def _two_host():
    return validate_graph.load(os.path.join(ROOT, "examples", "graphs", "two-host.yaml"))


def test_single_node_aliases_keep_graph_proxy_shape():
    _n, _r, gws, omitted, _rg = start_graph.local_topology(_two_host(), "h1")
    (_name, _gw, aliases), = gws
    assert aliases == {"chat": {"kind": "chat", "url": "http://127.0.0.1:9001"}}
    assert ("far", "far", "h2") in omitted and not start_graph.needs_router(aliases)


def test_fallback_list_alias_launches_graph_router(tmp_path, monkeypatch):
    g = _two_host()
    g["nodes"]["chat2"] = dict(g["nodes"]["chat"], port=9003)
    g["aliases"]["chat"]["node"] = ["chat", "chat2"]
    assert validate_graph.validate(g, check_files=False)[0] == []
    _n, _r, gws, _o, _rg = start_graph.local_topology(g, "h1")
    (name, gw, aliases), = gws
    assert [m["url"] for m in aliases["chat"]["members"]] == ["http://127.0.0.1:9001", "http://127.0.0.1:9003"]
    assert start_graph.needs_router(aliases)
    cfg = start_graph.router_routes(aliases)
    assert cfg["routes"] == {"chat": ["chat-node", "chat2"]}
    monkeypatch.setattr(start_graph, "CACHE", tmp_path)
    argv = start_graph.gateway_command("h1", name, gw, aliases, "/gr")
    assert argv[1].endswith("graph_router.py") and argv[-2:] == ["--port", "8080"]
    import json, graph_router
    compiled = graph_router.compile_config(json.loads(open(argv[2]).read()))
    assert compiled["routes"]["chat"]


def test_remote_member_needs_explicit_opt_in_and_reachable_bind():
    g = _two_host()
    g["aliases"]["far"]["remote"] = True                    # node bound to loopback: still omitted
    assert "far" not in start_graph.local_topology(g, "h1")[2][0][2]
    g["nodes"]["far"]["bind"] = "0.0.0.0"; g["hosts"]["h2"]["addr"] = "10.0.0.2"
    aliases = start_graph.local_topology(g, "h1")[2][0][2]
    assert aliases["far"]["members"][0]["url"] == "http://10.0.0.2:9002" and start_graph.needs_router(aliases)
    del g["aliases"]["far"]["remote"]                       # no consent: omitted again
    assert "far" not in start_graph.local_topology(g, "h1")[2][0][2]


def test_gateway_router_opt_in_bounds_down_node_stall(tmp_path, monkeypatch):
    g = _two_host(); g["gateways"]["gw"]["router"] = True
    assert validate_graph.validate(g, check_files=False)[0] == []
    (name, gw, aliases), = start_graph.local_topology(g, "h1")[2]
    assert start_graph.needs_router(aliases, gw) and not start_graph.needs_router(aliases)
    monkeypatch.setattr(start_graph, "CACHE", tmp_path)
    assert start_graph.gateway_command("h1", name, gw, aliases, "/gr")[1].endswith("graph_router.py")
    g["gateways"]["gw"]["router"] = "yes"
    assert validate_graph.validate(g, check_files=False)[0]
