"""Routing tests for the runtime tool_route forward in escalation_proxy (#251), with the
Hermes route_tools view (#243) where the rule lives there. Synthetic graphs only: no
graph.yaml / generated/ reads, no embed nodes, loopback fakes on ephemeral ports.
Covers #345 (off-loopback needs explicit server_tools), #340 (proxy agrees with Hermes/tool_policy)."""
import json, os, socket, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import escalation_proxy as EP  # noqa: E402
import hermes_harness as HH  # noqa: E402
import validate_graph as VG  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "ls", "parameters": {"type": "object"}}}]
OPT_OUTS = [[], "none", False, None, ""]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("FAMILIA_API_KEY", "test-instance-key")
    monkeypatch.setattr(EP, "STATE", str(tmp_path))
    monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))


class Up:
    """Fake upstream: records (name, body); optional delay; tracks peak in-flight."""
    def __init__(self, name, seen, delay=0.0, gate=None):
        st = self; self.inflight = self.peak = 0; mu = threading.Lock()
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with mu:
                    seen.append((name, b)); st.inflight += 1; st.peak = max(st.peak, st.inflight)
                try:
                    if gate is not None: gate.wait(10)
                    if delay: time.sleep(delay)
                    out = json.dumps({"choices": [{"message": {"role": "assistant", "content": name}}]}).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.end_headers(); self.wfile.write(out)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    with mu: st.inflight -= 1
        cls = type("_S", (ThreadingHTTPServer,), {"request_queue_size": 128, "daemon_threads": True})
        self.srv = cls(("127.0.0.1", 0), H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown(); self.srv.server_close()


def dead_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def g3(pl, pc, pg=None, light=None, coder=None, coder_role="coder"):
    """light (chat, routed-only) -tool_route-> coder; optional third node g."""
    g = {"hosts": {"h": {}}, "aliases": {"coder-a": {"node": "coder"}},
         "models": {"m": {"role": "chat", "tool_calls": False}, "c": {"role": coder_role, "tool_calls": True}},
         "nodes": {"light": dict({"host": "h", "port": pl, "model": "m", "bind": "127.0.0.1", "tool_route": "coder"}, **(light or {})),
                   "coder": dict({"host": "h", "port": pc, "model": "c", "bind": "127.0.0.1"}, **(coder or {}))}}
    if pg is not None:
        g["models"]["c2"] = {"role": "coder", "tool_calls": True}
        g["nodes"]["g"] = {"host": "h", "port": pg, "model": "c2", "bind": "127.0.0.1"}
    return g


def serve(g, cur="light"):
    srv = EP.serve(EP.Escalator(g, cur, [], "h", consent={})); return srv, srv.server_address[1]


def close(*srvs):
    """Shut down and server_close() each proxy (None = never started); for finally blocks."""
    for srv in srvs:
        if srv is not None:
            srv.shutdown(); srv.server_close()


def post(port, tools=True, timeout=20):
    body = {"model": "x", "messages": [{"role": "user", "content": "list files"}]}
    if tools: body["tools"] = TOOLS
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=timeout)
    return json.load(r)["choices"][0]["message"]["content"]


# ---------------- one hop only ----------------

def test_one_hop_forward_lands_on_target_runtime_not_its_proxy():
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    srv = None
    try:
        srv, p = serve(g3(L.port, C.port))
        assert post(p) == "coder"
        assert [s[0] for s in seen] == ["coder"] and seen[0][1]["model"] == "coder-a"
    finally:
        close(srv); L.close(); C.close()


def test_chained_tool_route_is_not_followed():
    """light -> coder -> g: coder is itself routed, so light gets no target (no 2nd hop)."""
    seen = []; L, C, G = Up("light", seen), Up("coder", seen), Up("g", seen)
    srv = None
    try:
        g = g3(L.port, C.port, G.port, coder={"tool_route": "g"})
        assert VG.tool_route(g, "light") is None and EP.tool_target(g, "light") is None
        srv, p = serve(g)
        assert post(p) == "light" and [s[0] for s in seen] == ["light"]
    finally:
        close(srv); L.close(); C.close(); G.close()


def test_self_route_is_not_a_target():
    g = g3(1, 2, light={"tool_route": "light"})
    assert EP.tool_target(g, "light") is None


# ---------------- never into guardian / pentest / defender ----------------

@pytest.mark.parametrize("role", ["guardian", "pentest", "defender"])
@pytest.mark.parametrize("how", ["model_role", "node_role", "node_role+server_tools_all+tool_capable"])
def test_never_forwards_into_fail_closed_nodes(role, how):
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    srv = None
    try:
        if how == "model_role":
            g = g3(L.port, C.port, coder_role=role)
        elif how == "node_role":
            g = g3(L.port, C.port, coder={"role": role})
        else:
            g = g3(L.port, C.port, coder={"role": role, "server_tools": "all", "tool_capable": True})
        assert EP.tool_target(g, "light") is None
        assert VG.tool_policy(g, "coder") == []
        srv, p = serve(g)
        assert post(p) == "light" and all(s[0] != "coder" for s in seen)
    finally:
        close(srv); L.close(); C.close()


@pytest.mark.parametrize("role", ["guardian", "pentest", "defender"])
def test_hermes_never_routes_into_fail_closed_nodes(role):
    g = _hg({"a": {"model": "dec"}, "t": {"model": "cod", "role": role, "server_tools": "all"}})
    g["nodes"]["a"]["tool_route"] = "t"
    assert HH.route_tools(g, "hermes")["mode"] == "none"


# ---------------- tool_free / not tool-capable targets ----------------

@pytest.mark.parametrize("role", ["decision", "vision"])
def test_not_tool_capable_target_gets_no_forward(role):
    g = g3(1, 2, coder_role=role)
    g["models"]["c"]["tool_calls"] = False
    assert EP.tool_target(g, "light") is None


def test_hermes_tool_free_node_gets_no_tools_even_with_route():
    g = _hg({"a": {"model": "cod", "role": "guardian", "tool_route": "t"}, "t": {"model": "cod"}})
    r = HH.route_tools(g, "hermes")
    assert r["mode"] == "none" and r["node"] is None


# ---------------- explicit server_tools opt-out ----------------

@pytest.mark.parametrize("opt", OPT_OUTS, ids=repr)
def test_target_server_tools_opt_out_gets_no_forward(opt):
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    srv = None
    try:
        g = g3(L.port, C.port, coder={"server_tools": opt})
        assert VG.tool_policy(g, "coder") == [] and EP.tool_target(g, "light") is None
        srv, p = serve(g)
        assert post(p) == "light"
    finally:
        close(srv); L.close(); C.close()


@pytest.mark.parametrize("opt", [[], "none", False], ids=repr)
def test_source_server_tools_opt_out_blocks_forward(opt):
    g = g3(1, 2, light={"server_tools": opt})
    assert VG.tool_policy(g, "light") == []
    assert EP.tool_target(g, "light") is None


def test_hermes_source_opt_out_is_none():
    g = _hg({"a": {"model": "cod", "server_tools": "none"}, "t": {"model": "cod"}})
    r = HH.route_tools(g, "hermes")
    assert r == {"mode": "none", "node": None, "via": None, "reason": "server_tools opt-out"}


# ---------------- tool_capable goes direct ----------------

def test_hermes_tool_capable_goes_direct_even_with_route():
    g = _hg({"a": {"model": "cod", "tool_route": "t"}, "t": {"model": "cod"}})
    assert HH.route_tools(g, "hermes") == {"mode": "direct", "node": "a", "via": None}


def test_proxy_tool_capable_source_stays_direct():
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    try:
        g = g3(L.port, C.port); g["models"]["m"]["tool_calls"] = True
        assert VG.tool_capable(g, "light") and VG.tools_argv(g, "light") != []
        srv, p = serve(g)
        try:
            assert post(p) == "light"
        finally:
            close(srv)
    finally:
        L.close(); C.close()


# ---------------- same-host discovery before mesh (Hermes; proxy has no discovery) ----------------

def _hg(nodes, hosts=("h", "p"), meshes=None):
    g = {"hosts": {h: {"addr": f"{h}.example"} for i, h in enumerate(hosts)},
         "models": {"dec": {"role": "decision", "tool_calls": False}, "cod": {"role": "coder", "tool_calls": True}},
         "aliases": {}, "meshes": meshes or {}, "agents": {"hermes": {"aliases": {"main": "a", "auxiliary": "a"}}},
         "nodes": {}}
    for i, (k, v) in enumerate(nodes.items()):
        g["nodes"][k] = dict({"host": "h", "port": 9000 + i, "bind": "127.0.0.1"}, **v)
    return g


def test_hermes_same_host_discovery_preferred_over_mesh():
    mesh = {"lan": {"type": "ssh", "members": ["h", "p"]}}
    # "a-peer" sorts before "z-local": order must come from same-host-first, not names.
    g = _hg({"a": {"model": "dec"}, "a-peer": {"model": "cod", "host": "p", "server_tools": "all", "bind": "0.0.0.0"},
             "z-local": {"model": "cod"}}, meshes=mesh)
    assert HH.route_tools(g, "hermes") == {"mode": "nexus", "node": "z-local", "via": None}
    g["nodes"]["z-local"]["status"] = "planned"
    assert HH.route_tools(g, "hermes") == {"mode": "nexus", "node": "a-peer", "via": "lan"}


def test_proxy_does_not_discover_without_explicit_route():
    g = g3(1, 2, light={"tool_route": None})
    assert EP.tool_target(g, "light") is None


# ---------------- off-loopback without server_tools ----------------

@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "lan.example", "LOCALHOST.example"])
def test_off_loopback_target_without_server_tools_gets_no_forward(bind):
    g = g3(1, 2, coder={"bind": bind})
    assert VG.tool_policy(g, "coder") == [] and EP.tool_target(g, "light") is None
    g["nodes"]["coder"]["server_tools"] = ["read_file"]
    assert EP.tool_target(g, "light") == "coder"     # explicit grant re-opens it


def test_hermes_off_loopback_direct_without_server_tools_gets_none():
    g = _hg({"a": {"model": "cod", "bind": "0.0.0.0"}})
    assert VG.tool_policy(g, "a") == []
    r = HH.route_tools(g, "hermes")
    assert r["mode"] == "none" and r.get("reason") == "off-loopback without server_tools"
    # loopback without server_tools stays the default direct grant
    g["nodes"]["a"]["bind"] = "127.0.0.1"
    assert HH.route_tools(g, "hermes") == {"mode": "direct", "node": "a", "via": None}
    # explicit opt-in re-opens off-loopback
    g["nodes"]["a"]["bind"] = "0.0.0.0"
    g["nodes"]["a"]["server_tools"] = ["read_file"]
    assert HH.route_tools(g, "hermes") == {"mode": "direct", "node": "a", "via": None}


# ---------------- target down or slow ----------------

def test_target_down_is_502_and_never_redialed_with_tools():
    seen = []; L = Up("light", seen)
    srv = None
    try:
        srv, p = serve(g3(L.port, dead_port()))
        with pytest.raises(urllib.error.HTTPError) as ei:
            post(p)
        assert ei.value.code == 502 and seen == []
        assert post(p, tools=False) == "light"            # plain chat still served
    finally:
        close(srv); L.close()


def test_target_slow_past_timeout_is_502_and_not_retried(monkeypatch):
    monkeypatch.setattr(EP, "UPSTREAM_TIMEOUT_S", 0.5)
    seen = []; L, C = Up("light", seen), Up("coder", seen, delay=2.0)
    srv = None
    try:
        srv, p = serve(g3(L.port, C.port))
        t0 = time.monotonic()
        with pytest.raises(urllib.error.HTTPError) as ei:
            post(p)
        assert ei.value.code == 502 and time.monotonic() - t0 < 5
        assert [s[0] for s in seen] == ["coder"]          # one attempt, never light
    finally:
        close(srv); L.close(); C.close()


def test_target_slow_within_timeout_is_served():
    seen = []; L, C = Up("light", seen), Up("coder", seen, delay=0.3)
    srv = None
    try:
        srv, p = serve(g3(L.port, C.port))
        assert post(p) == "coder"
    finally:
        close(srv); L.close(); C.close()


# ---------------- concurrent forwards ----------------

def test_concurrent_tool_forwards_capped_and_none_leak_to_source():
    N, gate = 16, threading.Event()
    seen = []; L, C = Up("light", seen), Up("coder", seen, gate=gate)
    srv, p = serve(g3(L.port, C.port))
    ex = ThreadPoolExecutor(N)
    try:
        futs = [ex.submit(post, p, True, 30) for _ in range(N)]
        end = time.monotonic() + 5
        while time.monotonic() < end and C.peak < EP.UPSTREAM_CAP:
            time.sleep(0.05)
        time.sleep(0.3)
        peak = C.peak
        gate.set()
        outs = [f.result(timeout=30) for f in futs]
    finally:
        gate.set(); ex.shutdown(wait=True); close(srv); L.close(); C.close()
    assert outs == ["coder"] * N
    assert 0 < peak <= EP.UPSTREAM_CAP, peak
    assert {s[0] for s in seen} == {"coder"} and len(seen) == N
