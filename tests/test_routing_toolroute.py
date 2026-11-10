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
        st = self; self.inflight = self.peak = 0; self.headers = []; mu = threading.Lock()
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with mu:
                    seen.append((name, b)); st.headers.append(dict(self.headers))
                    st.inflight += 1; st.peak = max(st.peak, st.inflight)
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
        gate.set()
        outs = [f.result(timeout=30) for f in futs]
        peak = C.peak  # after drain, so a leak during drain shows up (R7 / Race #362 nit)
    finally:
        gate.set(); ex.shutdown(wait=True); close(srv); L.close(); C.close()
    assert outs == ["coder"] * N
    assert 0 < peak <= EP.UPSTREAM_CAP, peak
    assert {s[0] for s in seen} == {"coder"} and len(seen) == N


# ---------------- #345 loopback bind matrix (policy, not just _loopback) ----------------

@pytest.mark.parametrize("bind,loop", [
    ("::1", True), ("[::1]", True), ("127.0.0.2", True), ("127.255.255.255", True),
    ("::ffff:127.0.0.1", True), ("[::ffff:127.0.0.1]", True), ("localhost", True), ("LOCALHOST", True),
    ("::", False), ("0.0.0.0", False), ("lan.example", False), ("localhost.example", False),
])
def test_loopback_bind_matrix_controls_default_grant(bind, loop):
    """Default read-only grant only on loopback binds; no DNS (lan.example is off)."""
    g = g3(1, 2, coder={"bind": bind})
    pol = VG.tool_policy(g, "coder")
    if loop:
        assert pol == VG.READ_ONLY_TOOLS
        assert EP.tool_target(g, "light") == "coder"
        hg = _hg({"a": {"model": "cod", "bind": bind}})
        assert HH.route_tools(hg, "hermes")["mode"] == "direct"
    else:
        assert pol == []
        assert EP.tool_target(g, "light") is None
        hg = _hg({"a": {"model": "cod", "bind": bind}})
        r = HH.route_tools(hg, "hermes")
        assert r["mode"] == "none" and r.get("reason") == "off-loopback without server_tools"


# ---------------- #340 role-name normalization ----------------

@pytest.mark.parametrize("role", ["Guardian", "GUARDIAN", "Pentest", "DEFENDER", "ｇｕａｒｄｉａｎ"])
@pytest.mark.parametrize("where", ["node", "model"])
def test_fail_closed_roles_normalized_across_hermes_policy_and_proxy(role, where):
    """Casefold/NFKC: Guardian / fullwidth guardian fail closed like guardian."""
    import unicodedata
    if role == "ｇｕａｒｄｉａｎ":
        assert unicodedata.normalize("NFKC", role).casefold() == "guardian"
    light = {}
    coder = {}
    coder_role = "coder"
    if where == "node":
        coder["role"] = role
    else:
        coder_role = role
    g = g3(1, 2, light=light, coder=coder, coder_role=coder_role)
    assert VG.normalize_role(role) in VG.FAIL_CLOSED_TYPES
    assert VG.node_type(g, "coder") in VG.FAIL_CLOSED_TYPES
    assert VG.tool_policy(g, "coder") == []
    assert EP.tool_target(g, "light") is None
    hg = _hg({"a": {"model": "cod", "role": role, "tool_capable": True, "server_tools": "all",
                    "tool_route": "t"}, "t": {"model": "cod"}})
    r = HH.route_tools(hg, "hermes")
    assert r["mode"] == "none" and HH.tool_free(hg, "a")


# ---------------- #340 proxy re-entry (hop / loop guard) ----------------

def _post(port, tools=True, headers=None, timeout=8):
    body = {"model": "x", "messages": [{"role": "user", "content": "list files"}]}
    if tools:
        body["tools"] = TOOLS
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(body).encode(), headers=hdrs), timeout=timeout)
        return r.status, json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_forward_sets_hop_header_and_incoming_hop_refuses_reentry():
    """A forwarded request carries X-Familia-Tool-Hop: 1; a request arriving with that
    hop is refused (502) and does not loop or land on the source with tools."""
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    try:
        srv, p = serve(g3(L.port, C.port))
        try:
            assert post(p) == "coder"
            hops = [h.get("X-Familia-Tool-Hop") or h.get("x-familia-tool-hop") for h in C.headers]
            assert hops == ["1"]
            status, body = _post(p, headers={"X-Familia-Tool-Hop": "1"})
            assert status == 502 and "re-entry refused" in body
            # source (light) must not have received the re-entered tool request
            assert all(s[0] != "light" for s in seen)
        finally:
            srv.shutdown()
    finally:
        L.close(); C.close()


def test_self_forward_reentry_does_not_deadlock():
    """If the tool target URL is this same proxy, the hop guard must 502 before
    taking the session lock (otherwise urlopen-under-lock deadlocks)."""
    seen = []; L = Up("light", seen)
    try:
        # placeholder coder port; we re-point after serve()
        g = g3(L.port, 1)
        srv, p = serve(g)
        try:
            g["nodes"]["coder"]["port"] = p
            status, body = _post(p, timeout=5)
            # First request forwards to this same proxy; the re-entered hop is 502'd
            # ("re-entry refused") and the outer request therefore also 502s
            # ("tool_route coder failed"). Either text proves the guard fired;
            # the timeout proves it did not deadlock on the session lock.
            assert status == 502
            assert ("re-entry refused" in body) or ("tool_route coder failed" in body)
            assert all(s[0] != "light" for s in seen)
        finally:
            srv.shutdown()
    finally:
        L.close()


# ---------------- #340 hostile headers must never widen tool access ----------------

@pytest.mark.parametrize("headers", [
    {"X-Familia-Role": "coder"},
    {"X-Familia-Server-Tools": "all"},
    {"X-Familia-Tool-Policy": "all"},
    {"X-Familia-Tool-Route": "coder"},
    {"X-Familia-Node": "coder"},
    {"X-Familia-Tools": "all"},
    {"X-Familia-Bind": "127.0.0.1"},
])
def test_hostile_headers_cannot_widen_tool_access(headers):
    """Opt-out source stays unforwarded; fail-closed target stays unforwarded."""
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    try:
        # (a) source opt-out
        g = g3(L.port, C.port, light={"server_tools": []})
        assert EP.tool_target(g, "light") is None
        srv, p = serve(g)
        try:
            status, body = _post(p, headers=headers)
            assert status == 200 and body == "light"
            assert all(s[0] != "coder" for s in seen)
        finally:
            srv.shutdown()
        # (b) fail-closed target
        seen.clear(); C.headers.clear()
        g = g3(L.port, C.port, coder={"role": "guardian"})
        assert EP.tool_target(g, "light") is None
        srv, p = serve(g)
        try:
            status, body = _post(p, headers=headers)
            assert status == 200 and body == "light"
            assert all(s[0] != "coder" for s in seen)
        finally:
            srv.shutdown()
    finally:
        L.close(); C.close()


def _familia(headers):
    return {k.lower(): v for k, v in headers.items() if k.lower().startswith("x-familia-")}


def test_outbound_headers_strip_untrusted_x_familia_then_set_owned(monkeypatch):
    """A named denylist is not enough: every X-Familia-* on the outbound dict is
    dropped, then only Request-Id and (on a forward) Tool-Hop are set."""
    real = EP.familia_auth.auth_headers

    def with_hostile(headers=None, **kw):
        h = real(headers, **kw)
        h["X-Familia-Role"] = "coder"
        h["X-Familia-Tool-Capable"] = "true"
        h["X-Familia-Opt-Out"] = "1"
        h["X-Familia-Tool-Hop"] = "0"
        return h

    monkeypatch.setattr(EP.familia_auth, "auth_headers", with_hostile)
    incoming = {"Authorization": "Bearer caller-key", "X-Familia-Request-Id": "caller-1"}
    hdrs = EP.outbound_headers(incoming, request_id="caller-1", hop=1)
    familia = _familia(hdrs)
    assert set(familia) == {"x-familia-request-id", "x-familia-tool-hop"}
    assert familia["x-familia-tool-hop"] == "1"
    assert familia["x-familia-request-id"] == "caller-1"
    plain = _familia(EP.outbound_headers(incoming, request_id="caller-1"))
    assert set(plain) == {"x-familia-request-id"}


def test_forward_strips_inbound_x_familia_headers():
    """End to end: client X-Familia-* do not reach the runtime, except the proxy's
    own request id and hop. The hop URL is cleartext HTTP."""
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    try:
        srv, p = serve(g3(L.port, C.port))
        try:
            status, body = _post(p, headers={
                "X-Familia-Role": "coder",
                "X-Familia-Tool-Capable": "true",
                "X-Familia-Opt-Out": "1",
                "X-Familia-Request-Id": "caller-1",
            })
            assert status == 200 and body == "coder"
            familia = _familia(C.headers[-1])
            assert set(familia) == {"x-familia-request-id", "x-familia-tool-hop"}
            assert familia["x-familia-tool-hop"] == "1"
            assert familia["x-familia-request-id"] == "caller-1"
        finally:
            srv.shutdown()
    finally:
        L.close(); C.close()


def _remote(bind, port=2):
    g = g3(1, port, coder={"host": "p", "bind": bind})
    g["hosts"]["p"] = {"addr": "peer.example"}
    return g


@pytest.mark.parametrize("bind", ["::1", "[::1]", "::ffff:127.0.0.1", "[::ffff:127.0.0.1]",
                                   "localhost", "LOCALHOST", " localhost ", "127.0.0.1", "127.0.0.2"])
def test_remote_loopback_bind_needs_tunnel(bind):
    """node_url agrees with validate_graph._loopback, including non-IPv4 loopback."""
    assert VG._loopback(bind) is True
    assert EP.node_url(_remote(bind), "coder", "h") is None


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "lan.example", "127.evil.example"])
def test_remote_non_loopback_bind_is_cleartext_http(bind):
    """Not loopback (including a 127-prefixed name) is dialed at the host, over HTTP."""
    assert VG._loopback(bind) is False
    url = EP.node_url(_remote(bind), "coder", "h")
    assert url == "http://peer.example:2/v1"


def test_local_node_url_is_cleartext_http_and_missing_bind_needs_tunnel():
    g = g3(9, 8)
    assert EP.node_url(g, "coder", "h") == "http://127.0.0.1:8/v1"
    remote = _remote("0.0.0.0")
    del remote["nodes"]["coder"]["bind"]
    assert EP.node_url(remote, "coder", "h") is None


def test_hostile_hop_zero_cannot_reset_and_widen():
    """A client hop of 0 is a first hop (allowed); hop of 1 still refuses. Neither
    grants tools a graph opt-out would deny."""
    seen = []; L, C = Up("light", seen), Up("coder", seen)
    try:
        g = g3(L.port, C.port, light={"server_tools": []})
        srv, p = serve(g)
        try:
            status, body = _post(p, headers={"X-Familia-Tool-Hop": "0"})
            assert status == 200 and body == "light"
            assert all(s[0] != "coder" for s in seen)
            status, body = _post(p, headers={"X-Familia-Tool-Hop": "1"})
            assert status == 502 and "re-entry refused" in body
        finally:
            srv.shutdown()
    finally:
        L.close(); C.close()

