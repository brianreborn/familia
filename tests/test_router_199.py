"""Routing test suite for #199 (router no-op catalogue). Offline only.

Fake loopback OpenAI-style servers stand in for llama-server nodes; a fake
gateway serves the exact manifest that scripts/start_graph.py builds for
green-roomz graph-proxy. Each test asserts the EXPECTED route per node TYPE
(host is placement only). Known no-op cases are xfail(strict=True) with the
issue ref, so a fix flips them to XPASS and forces the marker to be removed.
No product code is changed by this file. See docs/testing/router-199-findings.md.
"""
import copy
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import escalation as E  # noqa: E402
import hermes_harness as HH  # noqa: E402
import start_graph as SG  # noqa: E402

GRAPH = yaml.safe_load((ROOT / "graph.yaml").read_text(encoding="utf-8"))
NOOP = "#199 routing no-op"

# Expected routing per TYPE (docs/testing/router-199-findings.md, table 1).
# Request for model/alias == TYPE must land on an active node whose role is TYPE
# (general may fall back to chat). Never on a node of another type.
EXPECTED_TYPE = {
    "chat": {"chat"},
    "coder": {"coder"},
    "general": {"general", "chat"},
    "decision": {"decision"},
    "embed": {"embed"},
}


# ---------------------------------------------------------------- fakes
class _Node(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        out = {"served_by": self.server.node_name, "model": body.get("model"),
               "choices": [{"message": {"content": "ok"}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


class _Gateway(BaseHTTPRequestHandler):
    """Mimics graph-proxy: route by request `model` to manifest alias URL; else 404."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) or b"{}"
        model = json.loads(raw).get("model")
        al = self.server.aliases.get(model)
        if not al:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"unknown model"}')
            return
        req = urllib.request.Request(al["url"] + self.path, data=raw,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(data)


def _serve(handler, **attrs):
    s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    for k, v in attrs.items():
        setattr(s, k, v)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


@pytest.fixture
def fleet():
    """Start fake nodes for a graph host; return (route(model)->node|None, closer)."""
    servers = []

    def boot(graph, host):
        g = copy.deepcopy(graph)
        port_to_node = {}
        for name, n in g["nodes"].items():
            if n.get("host") == host and n.get("status") == "active":
                s = _serve(_Node, node_name=name)
                servers.append(s)
                n["port"] = s.server_address[1]
                port_to_node[n["port"]] = name
        _, _, gws, omitted, _ = SG.local_topology(g, host)
        aliases = {}
        for gname, gw, al in gws:
            aliases.update(SG.graph_proxy_manifest(host, gw, al)["aliases"])
        gw = _serve(_Gateway, aliases=aliases)
        servers.append(gw)
        base = f"http://127.0.0.1:{gw.server_address[1]}"

        def route(model):
            body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}]}).encode()
            req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return json.loads(r.read())["served_by"]
            except urllib.error.HTTPError:
                return None
        return g, route, omitted

    yield boot
    for s in servers:
        s.shutdown()


def node_type(g, name):
    n = g["nodes"][name]
    return n.get("role") or g["models"][n["model"]]["role"]


def _synthetic(roles, host="h1"):
    """Minimal graph: one active loopback llama-server node + alias per role."""
    g = {"hosts": {host: {}}, "runtimes": {"rt": {"kind": "llama-server"}},
         "gateways": {"gw": {"kind": "green-roomz", "host": host, "port": 1}},
         "models": {}, "nodes": {}, "aliases": {}}
    for r in roles:
        g["models"][f"m-{r}"] = {"role": "chat" if r == "general" else r}
        g["nodes"][r] = {"host": host, "status": "active", "runtime": "rt", "bind": "127.0.0.1",
                         "port": 1, "model": f"m-{r}", "role": r, "embeddings": r == "embed"}
        g["aliases"][r] = {"node": r, "gateway": "gw"}
    return g


# ------------------------------------------------- 1. real graph, gateway host
@pytest.mark.parametrize("typ", [
    "coder",
    "embed",
    pytest.param("general", marks=pytest.mark.xfail(strict=True, reason=f"{NOOP}: alias general -> coder node (graph.yaml aliases.general)")),
    pytest.param("chat", marks=pytest.mark.xfail(strict=True, reason=f"{NOOP}: no chat alias/active chat node on gateway host")),
    pytest.param("decision", marks=pytest.mark.xfail(strict=True, reason=f"{NOOP}: decision has no routable alias (start_graph.py:168)")),
])
def test_gateway_host_routes_type_to_matching_node(fleet, typ):
    g, route, _ = fleet(GRAPH, "miryam")
    served = route(typ)
    assert served is not None, f"{typ}: gateway has no route"
    assert node_type(g, served) in EXPECTED_TYPE[typ], f"{typ} landed on {served} ({node_type(g, served)})"


def test_coder_and_general_must_not_collapse(fleet):
    """Documents the current collapse: both names land on one node (no-op routing)."""
    _, route, _ = fleet(GRAPH, "miryam")
    assert route("coder") == route("general") == "coder"


@pytest.mark.xfail(strict=True, reason=f"{NOOP}: aliases to planned/inactive nodes are silently omitted (start_graph.py:147)")
def test_declared_aliases_are_all_routable_or_refused_loudly(fleet):
    _, _, omitted = fleet(GRAPH, "miryam")
    assert omitted == [], f"silently omitted aliases: {[a for a, _, _ in omitted]}"


# ----------------------------------- 2. hosts with active nodes but no gateway
@pytest.mark.parametrize("host", [
    pytest.param("box", marks=pytest.mark.xfail(strict=True, reason=f"{NOOP}: active nodes, no local gateway")),
    pytest.param("angel", marks=pytest.mark.xfail(strict=True, reason=f"{NOOP}: active nodes, no local gateway")),
])
def test_host_with_active_nodes_has_router(host):
    nodes, _, gws, _, _ = SG.local_topology(GRAPH, host)
    assert nodes
    assert gws, f"{host}: {nodes} reachable only by port; requests cannot be routed by type"


# ------------------------------------------- 3. synthetic per-type graphs
def test_synthetic_chat_coder_embed_route_by_type(fleet):
    g, route, _ = fleet(_synthetic(["chat", "coder", "embed"]), "h1")
    for t in ("chat", "coder", "embed"):
        assert node_type(g, route(t)) == t


def test_unknown_type_is_refused_not_defaulted(fleet):
    _, route, _ = fleet(_synthetic(["chat", "coder"]), "h1")
    assert route("reasoning") is None


@pytest.mark.xfail(strict=True, raises=SG.StartupError, reason=f"{NOOP}: graph-proxy refuses decision role (start_graph.py:168-172)")
def test_synthetic_decision_is_routable(fleet):
    g, route, _ = fleet(_synthetic(["chat", "decision"]), "h1")
    assert node_type(g, route("decision")) == "decision"


@pytest.mark.xfail(strict=True, reason=f"{NOOP} / #150: one alias -> one node; no same-role multi-engine routing")
def test_150_two_coder_engines_both_reachable_by_role(fleet):
    g = _synthetic(["coder"])
    g["runtimes"]["rt2"] = {"kind": "llama-server"}
    g["nodes"]["coder-b"] = dict(g["nodes"]["coder"], runtime="rt2")
    g, route, _ = fleet(g, "h1")
    seen = {route("coder") for _ in range(6)}
    assert seen == {"coder", "coder-b"}, f"role coder reached only {seen}"


# ------------------------------------------------- 4. hermes graph/single
def test_hermes_agents_resolve_main_node():
    for agent in ("hermes", "hermes-lab"):
        _, name, _, _ = HH.node_for(GRAPH, agent)
        assert name == "coder"


@pytest.mark.xfail(strict=True, reason=f"{NOOP}: harness owns smart_model_routing and pins main+aux to one alias (hermes_harness.py:230,488-500)")
def test_hermes_graph_mode_can_reach_more_than_one_type():
    a = GRAPH["agents"]["hermes"]["aliases"]
    nodes = {GRAPH["aliases"][x]["node"] for x in a.values()}
    assert len({node_type(GRAPH, n) for n in nodes}) > 1


# ----------------------------------------------------- 5. escalation proxy
def test_escalation_decide_suggests_on_stuck_signal():
    g = {"nodes": {"light": {"host": "a", "model": "m", "escalates_to": ["heavy"], "escalation": {"mode": "suggest"}},
                   "heavy": {"host": "a", "model": "m"}}}
    assert E.decide(g, "light", {"failures": 5}, [], {})["decision"] in ("suggest", "auto")


@pytest.mark.xfail(strict=True, reason=f"{NOOP}: hermes main node has no escalates_to; proxy never auto-enabled (hermes_modes.py:218-221)")
def test_hermes_main_node_has_escalation_path():
    _, name, node, _ = HH.node_for(GRAPH, "hermes")
    assert node.get("escalates_to"), f"{name} cannot escalate"


@pytest.mark.xfail(strict=True, reason=f"{NOOP}: every escalating node is planned, so escalation is unreachable")
def test_some_active_node_escalates():
    assert any(n.get("escalates_to") and n.get("status") == "active" for n in GRAPH["nodes"].values())


# ---------------------------------------------------------- 6. --tools
ACTIVE_LS = sorted(k for k, n in GRAPH["nodes"].items()
                   if n.get("status") == "active" and GRAPH["runtimes"][n["runtime"]]["kind"] == "llama-server")


@pytest.mark.parametrize("node", [
    n if GRAPH["nodes"][n].get("server_tools") else
    pytest.param(n, marks=pytest.mark.xfail(strict=True, reason="#199: no server_tools -> validate_graph.py:419-423 emits no --tools"))
    for n in ACTIVE_LS
])
def test_graph_node_launch_has_explicit_tools(node):
    st = GRAPH["nodes"][node].get("server_tools")
    assert st == "all" or (isinstance(st, list) and st)


@pytest.mark.parametrize("path", [
    pytest.param("install/linux/install.sh", marks=pytest.mark.xfail(strict=True, reason="#199: familia-start exec has no --tools")),
    pytest.param("install/termux/install.sh", marks=pytest.mark.xfail(strict=True, reason="#199: termux launcher exec has no --tools")),
])
def test_installer_launchers_pass_explicit_tools(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if re.search(r"exec .*(llama-server|\\\$B)", l)]
    assert lines
    assert all("--tools" in l for l in lines), lines
