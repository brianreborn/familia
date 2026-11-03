"""examples/graphs/*.yaml stay valid and route the way their comments say (releng routing UX)."""
import copy, os, subprocess, sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import start_graph  # noqa: E402
import validate_graph as vg  # noqa: E402

EX = ROOT / "examples" / "graphs"
EXAMPLES = sorted(EX.glob("*.yaml"))


def load(name):
    return yaml.safe_load((EX / name).read_text())


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_validates(path):
    errs, _ = vg.validate(yaml.safe_load(path.read_text()), check_files=False)
    assert errs == []


def aliases_on(g, host="h1"):
    _, _, gws, omitted, _ = start_graph.local_topology(g, host)
    return {a: v["url"] for _, _, al in gws for a, v in al.items()}, omitted


def test_fanout_one_alias_per_specialist():
    routes, omitted = aliases_on(load("fanout-specialists.yaml"))
    assert routes == {"chat": "http://127.0.0.1:9001", "coder": "http://127.0.0.1:9002",
                      "emb": "http://127.0.0.1:9003"} and omitted == []


def test_two_host_omits_remote_alias_instead_of_routing_it():
    routes, omitted = aliases_on(load("two-host.yaml"))
    assert routes == {"chat": "http://127.0.0.1:9001"}
    assert omitted == [("far", "far", "h2")]


def test_explicit_tools_route_executes_on_target_only():
    g = load("explicit-tools.yaml")
    assert vg.tools_argv(g, "chat") == ["--tools", "read_file,grep_search"]
    assert vg.tools_argv(g, "r") == []
    assert vg.tool_policy(g, "r") == vg.tool_policy(g, "coder")


def test_tool_route_on_capable_node_warns():
    g = load("explicit-tools.yaml")
    del g["nodes"]["r"]["tool_capable"]
    assert vg.validate(g, check_files=False)[0] == []
    assert any("nodes.r.tool_route: ignored" in w for w in vg.WARNINGS)


@pytest.mark.parametrize("model_role,node_role", [("reasoning", None), ("chat", "general")])
def test_reasoning_and_general_nodes_route_as_chat(model_role, node_role):
    g = load("single-node.yaml")
    g["models"]["mchat"]["role"] = model_role
    if node_role: g["nodes"]["chat"]["role"] = node_role
    assert vg.validate(g, check_files=False)[0] == []
    assert not any(w.startswith("aliases.") for w in vg.WARNINGS)
    routes, _ = aliases_on(g)
    assert routes == {"chat": "http://127.0.0.1:9001"}


def test_alias_to_unroutable_role_warns_before_start_refuses():
    g = load("single-node.yaml")
    g["models"]["mchat"]["role"] = "vision"
    assert vg.validate(g, check_files=False)[0] == []
    assert any(w.startswith("aliases.chat:") and "vision" in w for w in vg.WARNINGS)
    with pytest.raises(start_graph.StartupError, match="node role 'vision'"):
        start_graph.local_topology(g, "h1")


@pytest.mark.parametrize("mutate,expect", [
    (lambda g: g["aliases"].__setitem__("x", {"node": "nope", "gateway": "gw"}), "no such nodes entry 'nope'"),
    (lambda g: g["aliases"]["chat"].__setitem__("node", ["chat"]), "expected a nodes name"),
])
def test_start_dry_run_reports_validation_not_traceback(tmp_path, mutate, expect):
    g = load("single-node.yaml"); mutate(g)
    f = tmp_path / "g.yaml"; f.write_text(yaml.safe_dump(g))
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "start_graph.py"), "--graph", str(f),
                        "--host", "h1", "--dry-run", "--fleet"], capture_output=True, text=True, cwd=ROOT,
                       env={**os.environ, "FAMILIA_HOST": ""})
    assert p.returncode == 1
    assert "graph validation failed" in p.stderr + p.stdout and expect in p.stderr + p.stdout
    assert "Traceback" not in p.stderr
