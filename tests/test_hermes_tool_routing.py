"""Hermes tool routing (Brian 2026-10-31): any node that can use tools gets them, directly or via
graph routing over a nexus mesh; guardian / pentest / defender nodes get none. Plus a live MCP run
of the real hermes-agent loader against tests/fixtures/mcp_stub."""
import copy, json, os, shutil, subprocess, sys
import pytest, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh

GRAPH = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
STUB = os.path.join(ROOT, "tests", "fixtures", "mcp_stub", "server.py")


def g_main(node, **node_over):
    g = copy.deepcopy(GRAPH)
    g["nodes"][node].update(node_over)
    g["agents"]["hermes"]["aliases"] = {"main": node, "auxiliary": node}
    return g


def cfg_of(g, tmp_path, monkeypatch, user=None):
    monkeypatch.setenv("HOME", str(tmp_path))
    up = tmp_path / "user.yaml"
    if user is not None: up.write_text(yaml.safe_dump(user))
    home, *_ = hh.render(g, "hermes", user_cfg_path=str(up))
    return yaml.safe_load(open(os.path.join(home, "config.yaml")))


def test_non_tool_capable_reaches_tool_via_nexus(tmp_path, monkeypatch):
    # phone7-decision: decision model (no tool calls), no tool-capable node on phone7;
    # phone7 shares the lan-nexus ssh mesh with miryam/qodesh, so tools route there.
    g = g_main("phone7-decision", status="active")
    g["agents"]["hermes"]["prompt_profile"] = "full"
    assert not hh.tool_capable(g, "phone7-decision")
    r = hh.route_tools(g, "hermes")
    assert r["mode"] == "nexus" and r["via"] == "lan-nexus"
    assert g["nodes"][r["node"]]["host"] in g["meshes"]["lan-nexus"]["members"]
    assert hh.tool_capable(g, r["node"]) and not hh.tool_free(g, r["node"])
    g["hosts"][g["nodes"][r["node"]]["host"]]["addr"] = "10.9.9.9"
    cfg = cfg_of(g, tmp_path, monkeypatch)
    assert cfg["model"]["default"] == r["node"]
    assert cfg["model"]["base_url"] == f"http://10.9.9.9:{g['nodes'][r['node']]['port']}/v1"
    assert cfg["auxiliary"]["compression"]["model"] == "phone7-decision"  # aux stays on the own node


def test_non_tool_capable_prefers_same_host():
    g = g_main("qodesh-gpu-decision")
    r = hh.route_tools(g, "hermes")
    assert r == {"mode": "nexus", "node": "qodesh-resident", "via": None}


def test_tool_capable_gets_all_tools_by_default(tmp_path, monkeypatch):
    g = copy.deepcopy(GRAPH)
    g["agents"]["hermes"]["prompt_profile"] = "full"
    g["agents"]["hermes"]["mcp"] = {"stub": {"command": sys.executable, "args": [STUB]}}
    assert hh.route_tools(g, "hermes") == {"mode": "direct", "node": "coder", "via": None}
    cfg = cfg_of(g, tmp_path, monkeypatch)
    # no narrowing: hermes' own default = every toolset, plus declared MCP
    assert "platform_toolsets" not in cfg and "stub" in cfg["mcp_servers"]
    assert cfg["model"]["default"] == "coder"


def test_explicit_capability_flags_win():
    g = g_main("qodesh-gpu-decision", tool_capable=True)
    assert hh.route_tools(g, "hermes")["mode"] == "direct"
    g = g_main("coder", tool_capable=False)
    assert hh.route_tools(g, "hermes")["mode"] == "nexus"


@pytest.mark.parametrize("node,over", [("miryam-pentest", {}), ("angel-guardian", {}),
                                       ("coder", {"role": "pentest"}), ("coder", {"role": "guardian"})])
def test_guardian_pentest_get_no_tools(tmp_path, monkeypatch, node, over):
    g = g_main(node, **over)
    g["agents"]["hermes"]["mcp"] = {"stub": {"command": sys.executable, "args": [STUB]}}
    assert hh.route_tools(g, "hermes")["mode"] == "none"
    cfg = cfg_of(g, tmp_path, monkeypatch, user={"platform_toolsets": {"cli": ["terminal", "web"]},
                                                 "mcp_servers": {"u": {"command": "x"}}})
    assert cfg["platform_toolsets"]["cli"] == [] and "mcp_servers" not in cfg


def test_defender_node_gets_no_tools():
    g = copy.deepcopy(GRAPH)
    g["nodes"]["defender"] = dict(g["nodes"]["coder"], port=1)
    g["agents"]["hermes"]["aliases"] = {"main": "defender", "auxiliary": "defender"}
    assert hh.tool_free(g, "defender") and hh.route_tools(g, "hermes")["mode"] == "none"


def test_tool_free_node_is_never_a_nexus_target():
    g = g_main("phone7-decision", status="active")
    for k, n in g["nodes"].items():
        if k != "phone7-decision" and not hh.tool_free(g, k): n["status"] = "planned"
    for k in ("miryam-pentest", "angel-guardian"): g["nodes"][k]["status"] = "active"
    assert hh.route_tools(g, "hermes")["mode"] == "none"


# ---- live MCP: real hermes-agent loader + client against the stdio stub -------------------------
PROBE = """import sys, json
sys.path.insert(0, sys.argv[1])
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.registry import registry
names = discover_mcp_tools()
print("TOOLS=" + json.dumps(sorted(names)))
echo = [n for n in names if n.endswith("__echo")][0]
print("CALL=" + json.dumps(registry.dispatch(echo, {"text": "familia"})))
"""


def _hermes_py():
    src = os.environ.get("FAMILIA_HERMES_SRC") or "/workspace/hermes-agent"
    cands = [os.environ.get("FAMILIA_HERMES_TEST_PY"), hh.HERMES_PY, shutil.which("python3")]
    for py in filter(None, cands):
        if os.path.isdir(os.path.join(src, "tools")) and subprocess.run(
                [py, "-c", "import mcp, yaml"], capture_output=True).returncode == 0:
            return py, src
    return None, None


def test_live_mcp_stub_via_hermes_agent(tmp_path, monkeypatch):
    py, src = _hermes_py()
    if not py: pytest.skip("hermes-agent checkout + a python with the mcp SDK not available")
    g = copy.deepcopy(GRAPH)
    g["agents"]["hermes"]["mcp"] = {"stub": {"command": sys.executable, "args": [STUB]}}
    cfg = cfg_of(g, tmp_path, monkeypatch)
    assert cfg["mcp_servers"]["stub"]["args"] == [STUB]
    home = os.path.join(str(tmp_path), ".cache", "familia", "hermes-hermes")
    probe = tmp_path / "probe.py"; probe.write_text(PROBE)
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_TOKEN", "_API_KEY"))}
    env.update(HERMES_HOME=home, HOME=str(tmp_path), TMPDIR=str(tmp_path))
    p = subprocess.run([py, str(probe), src], capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120)
    out = {l.split("=", 1)[0]: json.loads(l.split("=", 1)[1]) for l in p.stdout.splitlines() if l[:5] in ("TOOLS", "CALL=")}
    assert out.get("TOOLS") == ["mcp__stub__add", "mcp__stub__echo"], p.stdout + p.stderr
    assert "stub-echo:familia" in json.dumps(out["CALL"])
