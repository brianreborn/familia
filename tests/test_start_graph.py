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
