"""Hermes tool routing (Brian 2026-10-31 / #243): reuses validate_graph.tool_capable,
tool_route, tool_policy. Explicit nodes.<n>.tool_route wins; else same-host then mesh.
Guardian / pentest / defender get none. Live MCP stub against tests/fixtures/mcp_stub."""
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
    # Final fields from #243: nodes.<n>.tool_capable and models.<m>.tool_calls (via vg.tool_capable).
    g = g_main("qodesh-gpu-decision", tool_capable=True)
    assert hh.route_tools(g, "hermes")["mode"] == "direct"
    g = g_main("coder", tool_capable=False)
    assert hh.route_tools(g, "hermes")["mode"] == "nexus"
    g = g_main("qodesh-gpu-decision")
    g["models"][g["nodes"]["qodesh-gpu-decision"]["model"]]["tool_calls"] = True
    assert hh.route_tools(g, "hermes")["mode"] == "direct"


def test_explicit_tool_route_wins_over_discovery(tmp_path, monkeypatch):
    # nodes.<n>.tool_route (one hop, #243) is the nexus target; skip same-host preference.
    g = g_main("qodesh-gpu-decision")
    # Same-host discovery would pick qodesh-resident; explicit route forces coder instead.
    g["nodes"]["qodesh-gpu-decision"]["tool_route"] = "coder"
    assert hh.vg.tool_route(g, "qodesh-gpu-decision") == "coder"
    r = hh.route_tools(g, "hermes")
    assert r["mode"] == "nexus" and r["node"] == "coder" and r.get("reason") == "tool_route"
    g["hosts"]["miryam"]["addr"] = "10.1.1.1"
    cfg = cfg_of(g, tmp_path, monkeypatch)
    assert cfg["model"]["default"] == "coder"
    assert cfg["model"]["base_url"] == f"http://10.1.1.1:{g['nodes']['coder']['port']}/v1"


def test_explicit_tool_route_to_guardian_is_ignored():
    # #243 tool_route() rejects fail-closed targets; Hermes must not use them either.
    g = g_main("qodesh-gpu-decision")
    g["nodes"]["qodesh-gpu-decision"]["tool_route"] = "miryam-pentest"
    g["nodes"]["miryam-pentest"]["status"] = "active"
    assert hh.vg.tool_route(g, "qodesh-gpu-decision") is None
    r = hh.route_tools(g, "hermes")
    assert r["node"] != "miryam-pentest"
    # Falls back to same-host discovery (qodesh-resident), not the invalid route.
    assert r == {"mode": "nexus", "node": "qodesh-resident", "via": None}


def test_discovery_skips_same_host_server_tools_none():
    # Boundary B1: same-host peer with server_tools: none → tool_policy [] → skipped.
    g = g_main("qodesh-gpu-decision")
    # Make resident the only same-host candidate, then opt it out.
    for k, n in g["nodes"].items():
        if n.get("host") == "qodesh" and k not in ("qodesh-gpu-decision", "qodesh-resident"):
            if not hh.tool_free(g, k):
                n["status"] = "planned"
    g["nodes"]["qodesh-resident"]["server_tools"] = "none"
    assert hh.vg.tool_policy(g, "qodesh-resident") == []
    # Plan mesh peers too so the only would-be target is the opted-out resident.
    for k, n in g["nodes"].items():
        if n.get("host") != "qodesh" and k != "qodesh-gpu-decision" and not hh.tool_free(g, k):
            n["status"] = "planned"
    r = hh.route_tools(g, "hermes")
    assert r["mode"] == "none" and r["node"] is None


def test_discovery_skips_off_loopback_mesh_peer_without_server_tools():
    # Boundary B1: off-loopback mesh peer, no server_tools key → vg.tool_policy already
    # returns [] (capable + non-loopback + no key / no route). _discovery_ok requires
    # policy != [], so that peer is skipped. (No extra bind check needed in harness.)
    g = g_main("phone7-decision", status="active")
    for k, n in g["nodes"].items():
        if k != "phone7-decision" and not hh.tool_free(g, k):
            n["status"] = "planned"
    peer = "coder"
    g["nodes"][peer]["status"] = "active"
    g["nodes"][peer]["bind"] = "0.0.0.0"
    g["nodes"][peer].pop("server_tools", None)
    assert hh.vg.tool_capable(g, peer)
    assert hh.vg.tool_policy(g, peer) == []
    r = hh.route_tools(g, "hermes")
    assert r["mode"] == "none" and r["node"] is None


def test_explicit_tool_route_skipped_when_target_policy_empty():
    # Explicit route to a server_tools:none target must not be used (policy []).
    g = g_main("qodesh-gpu-decision")
    g["nodes"]["qodesh-gpu-decision"]["tool_route"] = "coder"
    g["nodes"]["coder"]["server_tools"] = "none"
    assert hh.vg.tool_route(g, "qodesh-gpu-decision") is None  # #243 filters
    assert hh.vg.tool_policy(g, "coder") == []
    r = hh.route_tools(g, "hermes")
    assert r.get("node") != "coder"


def test_server_tools_opt_out_on_direct_node():
    # Boundary B2: capable node with server_tools key and policy [] → none, not direct.
    g = g_main("coder", server_tools="none")
    assert hh.vg.tool_capable(g, "coder") and "server_tools" in g["nodes"]["coder"]
    assert hh.vg.tool_policy(g, "coder") == []
    r = hh.route_tools(g, "hermes")
    assert r == {"mode": "none", "node": None, "via": None, "reason": "server_tools opt-out"}
    # Missing key stays direct (even though an off-loopback bind would make policy []).
    g2 = g_main("coder", bind="0.0.0.0")
    assert "server_tools" not in g2["nodes"]["coder"]
    assert hh.vg.tool_policy(g2, "coder") == []
    assert hh.route_tools(g2, "hermes") == {"mode": "direct", "node": "coder", "via": None}


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
    # Mesh case: only tool-capable candidates left are guardian/pentest → none, not into them.
    g = g_main("phone7-decision", status="active")
    for k, n in g["nodes"].items():
        if k != "phone7-decision" and not hh.tool_free(g, k): n["status"] = "planned"
    for k in ("miryam-pentest", "angel-guardian"): g["nodes"][k]["status"] = "active"
    r = hh.route_tools(g, "hermes")
    assert r["mode"] == "none" and r["node"] is None
    assert r.get("reason")


def test_nexus_never_routes_into_guardian_pentest_or_defender_same_host():
    # Only remaining "active" peers are defender/guardian (same host + mesh). Must still be none.
    g = g_main("qodesh-gpu-decision")
    for k, n in list(g["nodes"].items()):
        if k != "qodesh-gpu-decision" and not hh.tool_free(g, k):
            n["status"] = "planned"
    # Inject a same-host defender that *looks* tool-capable by model type but is tool_free by role.
    g["nodes"]["qodesh-defender"] = dict(g["nodes"]["coder"], host="qodesh", port=1, status="active")
    # And a same-host guardian.
    g["nodes"]["qodesh-guardian"] = dict(g["nodes"]["miryam-pentest"], host="qodesh", port=2, status="active",
                                         role="guardian")
    # Mesh peers that are guardian/pentest also flipped active — still must not be chosen.
    for k in ("miryam-pentest", "angel-guardian"):
        g["nodes"][k]["status"] = "active"
    r = hh.route_tools(g, "hermes")
    assert r["mode"] == "none" and r["node"] is None, r
    assert hh.tool_free(g, "qodesh-defender") and hh.tool_free(g, "qodesh-guardian")


def test_nexus_never_routes_into_pentest_even_when_flagged_tool_capable():
    # Even an explicit tool_capable=True on a pentest/guardian must not make it a nexus target
    # (CFG-PENT-POL-004: never an auto-route target in any mode).
    g = g_main("phone7-decision", status="active")
    for k, n in g["nodes"].items():
        if k != "phone7-decision" and not hh.tool_free(g, k): n["status"] = "planned"
    g["nodes"]["miryam-pentest"]["status"] = "active"
    g["nodes"]["miryam-pentest"]["tool_capable"] = True
    r = hh.route_tools(g, "hermes")
    assert r["mode"] == "none" and r["node"] is None


def test_pentest_stays_closed_even_with_tools_confirm_policy_today():
    # Plain seatbelt (non-xfail): a graph with pentests.<p>.policy.mode=tools-confirm still
    # gives tool_free == True and route mode none. CFG-PENT-MODE-004: tools-confirm must not
    # open until every tool call (MCP and all toolsets) goes through per-action confirmation;
    # setting approvals.mode=manual alone is not enough.
    g = g_main("miryam-pentest")
    g["pentests"] = {"fleet": {"node": "miryam-pentest",
                               "policy": {"enabled": True, "mode": "tools-confirm",
                                          "tools": "all", "autonomy": "confirm-each-action",
                                          "audit": "on"}}}
    assert hh.pentest_policy_mode(g, "miryam-pentest") == "tools-confirm"
    assert hh.pentest_tools_allowed(g, "miryam-pentest") is False
    assert hh.tool_free(g, "miryam-pentest") is True
    assert hh.route_tools(g, "hermes")["mode"] == "none"


@pytest.mark.xfail(strict=True, reason="TODO(pentest-policy): tools-confirm must not open until "
                   "every tool call (MCP and all toolsets) goes through per-action confirmation; "
                   "setting approvals.mode=manual alone is not enough. Also needs graph_types "
                   "pentests.*.policy. See docs/config/pentest-policy.md CFG-PENT-MODE-004.")
def test_tools_confirm_grants_full_tools_with_per_action_confirm(tmp_path, monkeypatch):
    # Expected once the TODO lands: mode tools-confirm → direct + full tools + approvals.mode=manual.
    g = g_main("miryam-pentest")
    g["agents"]["hermes"]["prompt_profile"] = "full"
    g["agents"]["hermes"]["mcp"] = {"stub": {"command": sys.executable, "args": [STUB]}}
    g["pentests"] = {"fleet": {"node": "miryam-pentest",
                               "policy": {"enabled": True, "mode": "tools-confirm",
                                          "tools": "all", "autonomy": "confirm-each-action",
                                          "audit": "on"},
                               "scope": {"allow": ["miryam"], "deny": []}}}
    assert hh.pentest_tools_allowed(g, "miryam-pentest") is True
    assert not hh.tool_free(g, "miryam-pentest")
    r = hh.route_tools(g, "hermes")
    assert r == {"mode": "direct", "node": "miryam-pentest", "via": None}
    cfg = cfg_of(g, tmp_path, monkeypatch)
    assert "stub" in (cfg.get("mcp_servers") or {})
    assert (cfg.get("approvals") or {}).get("mode") == "manual"
    # Must not be opened without confirm: yolo / mode=off forbidden.
    assert (cfg.get("approvals") or {}).get("mode") != "off"


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
        if not os.path.isdir(os.path.join(src, "tools")):
            continue
        try:
            ok = subprocess.run([py, "-c", "import mcp, yaml"], capture_output=True).returncode == 0
        except (FileNotFoundError, OSError):
            continue
        if ok:
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
