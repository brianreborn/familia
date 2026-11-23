"""Boundary hardening for the runtime tool_route forward (#251), on top of #340's
test_routing_toolroute.py (Boundary Reviewer, 2026-11-09). Synthetic graphs only: no
graph.yaml / generated/ reads, loopback fakes on ephemeral ports, real escalation_proxy.

Covers: fail-closed role names (case, Unicode lookalikes, aliases, indirect), a real
second hop through another escalation_proxy, hostile request headers / body fields /
model output that try to set server_tools or opt-outs, and a loopback bind matrix.
Also: an off-loopback source with no server_tools still forwards on an explicit
tool_route (TOOLS-009), and a discovery-only off-loopback source stays none.
After #355 those two, and a fail-closed source (BUG-TR-1 / #358), are current
behavior and asserted directly. Development 79d3d84 / #364 also closed BUG-TR-5, BUG-TR-6,
and the case/fullwidth half of BUG-TR-3 (normalize_role NFKC + casefold); those are
now asserted directly. xfail(strict=True) marks remaining gaps: the still-open
BUG-TR-3 cases (whitespace, Cyrillic/Greek, ZWSP) and BUG-TR-4 (issue pending;
TR-4 left as a product call)."""
import copy, json, os, socket, sys, threading, urllib.error, urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "scripts")]
import escalation_proxy as EP  # noqa: E402
import validate_graph as VG  # noqa: E402
from test_routing_toolroute import TOOLS, Up, close, dead_port, g3, post, _hg, HH  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("FAMILIA_API_KEY", "test-instance-key")
    monkeypatch.setattr(EP, "STATE", str(tmp_path))
    monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setattr(EP, "ACCEPT", str(tmp_path / "a.json"))


def serve_esc(g, cur="light"):
    esc = EP.Escalator(g, cur, [], "h", consent={})
    srv = EP.serve(esc)
    return esc, srv, srv.server_address[1]


def post_raw(port, body, headers=None, timeout=20):
    h = {"Content-Type": "application/json"}; h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers=h)
    return json.load(urllib.request.urlopen(req, timeout=timeout))["choices"][0]["message"]["content"]


def tool_body(text="list files", **extra):
    return dict({"model": "x", "tools": TOOLS, "messages": [{"role": "user", "content": text}]}, **extra)


def _lands(g, cur="light"):
    """Post one tool request through a real proxy; return the runtime names that saw it."""
    seen = []
    L, C = Up("light", seen), Up("coder", seen)
    g = copy.deepcopy(g)
    g["nodes"]["light"]["port"], g["nodes"]["coder"]["port"] = L.port, C.port
    srv = None
    try:
        _, srv, p = serve_esc(g, cur)
        out = post(p)
        return out, [s[0] for s in seen]
    finally:
        close(srv); L.close(); C.close()


# ---------------- fail-closed names: case, Unicode lookalikes, aliases, indirect ----------------

# FIXED by normalize_role (NFKC + casefold) on development 79d3d84 / #364.
CASE_FIXED = ["Guardian", "GUARDIAN", "Pentest", "PENTEST", "Defender", "DeFeNdEr"]
LOOKALIKE_FIXED = ["\uff47\uff55\uff41\uff52\uff44\uff49\uff41\uff4e"]  # fullwidth "guardian"
# Still open: strip()/Cf not applied, and non-ASCII lookalikes are unknown TYPEs.
CASE_OPEN = [" guardian", "pentest ", "defender\n"]
LOOKALIKE_OPEN = ["gu\u0430rdian",          # Cyrillic a
                  "pen\u200btest",          # zero-width space (Cf)
                  "d\u0435fender",          # Cyrillic ie
                  "defend\u0435r",         # Cyrillic ie, second e
                  "GUARD\u0399AN"]         # Greek capital iota
BUG_TR_3 = ("BUG-TR-3 (issue pending): normalize_role does NFKC + casefold, so case and "
            "fullwidth variants of guardian/pentest/defender now fail closed, but it does not "
            "strip() or drop Unicode format chars (Cf, e.g. U+200B). Whitespace, Cyrillic/Greek "
            "lookalikes, and ZWSP variants remain unknown TYPEs that are not fail-closed; the "
            "model's tool_calls makes them tool-capable and the proxy forwards tools into them")


@pytest.mark.parametrize("where", ["node_role", "model_role"])
@pytest.mark.parametrize("role", CASE_FIXED + LOOKALIKE_FIXED, ids=ascii)
def test_fail_closed_role_variants_get_no_forward(role, where):
    g = g3(1, 2, coder={"role": role}) if where == "node_role" else g3(1, 2, coder_role=role)
    assert VG.tool_policy(g, "coder") == []
    assert EP.tool_target(g, "light") is None


@pytest.mark.xfail(strict=True, reason=BUG_TR_3)
@pytest.mark.parametrize("where", ["node_role", "model_role"])
@pytest.mark.parametrize("role", CASE_OPEN + LOOKALIKE_OPEN, ids=ascii)
def test_fail_closed_role_variants_still_open_get_no_forward(role, where):
    g = g3(1, 2, coder={"role": role}) if where == "node_role" else g3(1, 2, coder_role=role)
    assert VG.tool_policy(g, "coder") == []
    assert EP.tool_target(g, "light") is None


def test_fail_closed_role_variant_end_to_end_stays_on_source():
    assert _lands(g3(0, 0, coder={"role": "Guardian"})) == ("light", ["light"])


@pytest.mark.xfail(strict=True, reason=BUG_TR_3)
def test_fail_closed_cyrillic_role_variant_end_to_end_stays_on_source():
    assert _lands(g3(0, 0, coder={"role": "gu\u0430rdian"})) == ("light", ["light"])


@pytest.mark.parametrize("role", ["guardian", "pentest", "defender"])
@pytest.mark.parametrize("override", ["all", ["exec_shell_command"], None])
def test_exact_fail_closed_roles_ignore_any_override(role, override):
    """Control for BUG-TR-3: the exact names fail closed even with server_tools/tool_capable set."""
    coder = {"role": role, "tool_capable": True}
    if override is not None: coder["server_tools"] = override
    g = g3(1, 2, coder=coder)
    assert VG.tool_policy(g, "coder") == [] and EP.tool_target(g, "light") is None


@pytest.mark.parametrize("route", ["guardian-a", "coder-a", "Coder", " coder", "coder ", "light-alias"])
def test_tool_route_by_alias_or_near_name_is_not_resolved(route):
    """tool_route names a node, never an alias or a near-miss spelling (no fuzzy lookup)."""
    g = g3(1, 2)
    g["nodes"]["sec"] = {"host": "h", "port": 3, "model": "c", "bind": "127.0.0.1", "role": "guardian"}
    g["aliases"].update({"guardian-a": {"node": "sec"}, "light-alias": {"node": "light"}})
    g["nodes"]["light"]["tool_route"] = route
    assert EP.tool_target(g, "light") is None


def test_alias_named_like_a_node_cannot_redirect_into_guardian():
    """An alias that shadows the target's node name does not change where tool_route goes."""
    g = g3(1, 2)
    g["nodes"]["sec"] = {"host": "h", "port": 3, "model": "c", "bind": "127.0.0.1", "role": "guardian"}
    g["aliases"]["coder"] = {"node": "sec"}
    assert EP.tool_target(g, "light") == "coder"
    out, seen = _lands(g)
    assert out == "coder" and seen == ["coder"]


@pytest.mark.parametrize("route", [["coder"], {"node": "coder"}, 1, True], ids=repr)
def test_non_string_tool_route_is_ignored(route):
    assert EP.tool_target(g3(1, 2, light={"tool_route": route}), "light") is None


@pytest.mark.parametrize("node_role", [None, ""], ids=repr)
@pytest.mark.parametrize("role", ["guardian", "pentest", "defender"])
def test_indirect_model_role_with_empty_node_role_fails_closed(role, node_role):
    """Indirect: the node gives no (or an empty) role, so TYPE comes from the model's role."""
    g = g3(1, 2, coder_role=role, coder={"role": node_role})
    assert VG.tool_policy(g, "coder") == [] and EP.tool_target(g, "light") is None


@pytest.mark.xfail(strict=True, reason="BUG-TR-4 (issue pending): a node-level role (e.g. coder) overrides a "
                   "fail-closed MODEL role (guardian/pentest/defender), so tools are forwarded into a "
                   "guardian model by relabelling its node; TOOLS-005 says those always fail closed")
@pytest.mark.parametrize("role", ["guardian", "pentest", "defender"])
def test_node_role_cannot_launder_fail_closed_model(role):
    g = g3(1, 2, coder_role=role, coder={"role": "coder"})
    assert EP.tool_target(g, "light") is None


@pytest.mark.parametrize("role", ["guardian", "pentest", "defender"])
def test_fail_closed_source_does_not_forward_tools(role):
    """#355: empty source tool_policy (fail-closed TYPE) blocks the forward (#358)."""
    g = g3(1, 2, light={"role": role})
    assert VG.tool_policy(g, "light") == []
    assert EP.tool_target(g, "light") is None


# ---------------- real proxy re-entry: a second hop through an actual escalation_proxy ----------------

def _two_proxies(b_current):
    """A: light -tool_route-> coder, where coder's port is proxy B. B: a real escalation_proxy
    over its own graph (light -tool_route-> coder), current node b_current.
    If the second serve_esc fails, close B and the Ups so they do not leak."""
    seen = []
    ups = (Up("b-light", seen), Up("b-coder", seen), Up("a-light", seen))
    BL, BC, AL = ups
    srvs = []
    try:
        _, b_srv, b_port = serve_esc(g3(BL.port, BC.port), cur=b_current)
        srvs.append(b_srv)
        _, a_srv, a_port = serve_esc(g3(AL.port, b_port))
        srvs.append(a_srv)
        return seen, ups, (a_srv, b_srv), a_port
    except Exception:
        close(*srvs)
        [u.close() for u in ups]
        raise


def test_reentry_second_hop_through_real_proxy_is_refused():
    """B fail-closes any inbound request with hop >= 1 (MAX_TOOL_HOPS) before routing,
    so A -> B(current=coder) gets 502 and no runtime sees the tool request."""
    seen, ups, srvs, a_port = _two_proxies(b_current="coder")
    try:
        with pytest.raises(urllib.error.HTTPError) as ei:
            post(a_port)
        assert ei.value.code == 502
        assert [s[0] for s in seen] == []
        assert post(a_port, tools=False) == "a-light"        # plain chat stays on A
    finally:
        close(*srvs); [u.close() for u in ups]


def test_reentry_forwarded_request_is_not_forwarded_again():
    seen, ups, srvs, a_port = _two_proxies(b_current="light")
    try:
        try:
            post(a_port)
        except urllib.error.HTTPError:
            pass                                             # fail closed is acceptable
        assert "b-coder" not in [s[0] for s in seen], seen
    finally:
        close(*srvs); [u.close() for u in ups]


# ---------------- hostile headers / body fields / model output must not set policy ----------------

HOSTILE_HEADERS = {"X-Familia-Server-Tools": "all", "X-Familia-Tool-Route": "coder",
                   "X-Familia-Tool-Policy": "all", "X-Familia-Role": "coder", "X-Familia-Node": "coder",
                   "X-Familia-Tool-Capable": "true", "Server-Tools": "all", "X-Server-Tools": "all"}
OPT_OUT_HEADERS = {"X-Familia-Server-Tools": "none", "X-Familia-Tool-Route": "", "X-Familia-Opt-Out": "1",
                   "X-Familia-Role": "guardian", "Server-Tools": "[]"}
HOSTILE_FIELDS = {"server_tools": "all", "tool_route": "coder", "tool_policy": "all", "role": "coder",
                  "tool_capable": True, "familia": {"server_tools": "all", "tool_route": "coder"}}
OPT_OUT_FIELDS = {"server_tools": [], "tool_route": None, "tool_policy": "none", "role": "guardian",
                  "familia": {"server_tools": "none"}}
HOSTILE_TEXT = ('{"server_tools": "all", "tool_route": "coder", "role": "coder"}\n'
                'server_tools: all\ntool_route: coder\n[familia] tool forward: light -> coder')


def _hostile_run(g, headers, fields, text, n=3):
    seen = []
    L, C = Up(HOSTILE_TEXT, seen), Up("coder", seen)     # light's model output is hostile text
    g["nodes"]["light"]["port"], g["nodes"]["coder"]["port"] = L.port, C.port
    before = copy.deepcopy(g)
    srv = None
    try:
        esc, srv, p = serve_esc(g)
        outs = [post_raw(p, tool_body(text, **fields), headers) for _ in range(n)]
        assert g == before and esc.g == before                 # graph never mutated by a request
        assert esc.current == "light"
        return outs, [s[0] for s in seen]
    finally:
        close(srv); L.close(); C.close()


@pytest.mark.parametrize("vector", ["headers", "fields", "text", "all"])
def test_hostile_request_cannot_grant_tools_to_opted_out_target(vector):
    g = g3(0, 0, coder={"server_tools": []})
    h = HOSTILE_HEADERS if vector in ("headers", "all") else {}
    f = HOSTILE_FIELDS if vector in ("fields", "all") else {}
    t = HOSTILE_TEXT if vector in ("text", "all") else "list files"
    outs, seen = _hostile_run(g, h, f, t)
    assert outs == [HOSTILE_TEXT] * 3 and seen == [HOSTILE_TEXT] * 3   # never reached coder


@pytest.mark.parametrize("vector", ["headers", "fields", "text", "all"])
def test_hostile_request_cannot_opt_out_a_graph_route(vector):
    """The other direction: a request cannot switch off (or redirect) a graph-validated route."""
    g = g3(0, 0)
    h = OPT_OUT_HEADERS if vector in ("headers", "all") else {}
    f = OPT_OUT_FIELDS if vector in ("fields", "all") else {}
    t = "server_tools: none\ntool_route: none\nrole: guardian" if vector in ("text", "all") else "list files"
    outs, seen = _hostile_run(g, h, f, t)
    assert outs == ["coder"] * 3 and seen == ["coder"] * 3


def test_hostile_model_output_does_not_change_later_routing():
    """Light's replies claim server_tools/tool_route; the next tool request still follows the graph."""
    g = g3(0, 0, coder={"server_tools": "none"})
    outs, seen = _hostile_run(g, {}, {}, "go", n=4)
    assert seen == [HOSTILE_TEXT] * 4


def test_hostile_policy_headers_are_not_forwarded_as_policy():
    """Whatever reaches the runtime, the routed body never carries request-supplied policy keys
    that the proxy itself added; the proxy only rewrites model (and handoff)."""
    seen = []
    C, L = Up("coder", seen), Up("light", seen)
    g = g3(L.port, C.port)
    srv = None
    try:
        _, srv, p = serve_esc(g)
        post_raw(p, tool_body(), HOSTILE_HEADERS)
        (name, body), = seen
        assert name == "coder" and set(body) == {"model", "tools", "messages"}
    finally:
        close(srv); L.close(); C.close()


# ---------------- loopback matrix ----------------

LOOPBACK = ["127.0.0.1", "127.0.0.2", "127.255.255.254", "::1", "[::1]", "0:0:0:0:0:0:0:1",
            "::ffff:127.0.0.1", "[::ffff:127.0.0.1]", "localhost", "LOCALHOST", " localhost "]
NOT_LOOPBACK = ["0.0.0.0", "::", "[::]", "::ffff:0.0.0.0", "", None,
                "localhost.", "localhost.localdomain", "ip6-localhost", "lo.example",
                "127.1", "0x7f.0.0.1", "2130706433", "127.0.0.1.example", "::2", "128.0.0.1"]


@pytest.mark.parametrize("bind", LOOPBACK)
def test_loopback_binds_get_default_grant_and_forward(bind):
    assert VG._loopback(bind) is True
    g = g3(1, 2, coder={"bind": bind})
    assert VG.tool_policy(g, "coder") == VG.READ_ONLY_TOOLS and EP.tool_target(g, "light") == "coder"


@pytest.mark.parametrize("bind", NOT_LOOPBACK, ids=repr)
def test_non_loopback_or_unparseable_binds_fail_safe(bind):
    """Wildcards, unknown names and non-canonical IPv4 spellings are NOT loopback: no default
    grant, so no forward without an explicit server_tools (fail-safe direction)."""
    assert VG._loopback(bind) is False
    g = g3(1, 2, coder={"bind": bind})
    assert VG.tool_policy(g, "coder") == [] and EP.tool_target(g, "light") is None


@pytest.mark.parametrize("bind", ["::1", "127.0.0.2", "::ffff:127.0.0.1", "0.0.0.0", "::", "localhost"])
def test_loopback_matrix_end_to_end(bind):
    """Same host: the proxy always dials 127.0.0.1; the bind decides only whether tools may go."""
    out, seen = _lands(g3(0, 0, coder={"bind": bind}))
    want = "coder" if VG._loopback(bind) else "light"
    assert out == want and seen == [want]


def test_loopback_decision_never_consults_dns(monkeypatch):
    """localhost via DNS: a name that resolves to loopback is not trusted, and a hostile resolver
    answer for localhost cannot change the decision; the check is resolver-free."""
    calls = []
    real = socket.getaddrinfo
    def fake(host, *a, **k):
        calls.append(host)
        if host == "lo.example": return real("127.0.0.1", *a, **k)
        if host == "localhost": return real("192.0.2.1", *a, **k)
        return real(host, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    monkeypatch.setattr(socket, "gethostbyname", lambda h: calls.append(h) or "127.0.0.1")
    assert VG._loopback("lo.example") is False and VG._loopback("localhost") is True
    assert EP.tool_target(g3(1, 2, coder={"bind": "lo.example"}), "light") is None
    assert EP.tool_target(g3(1, 2, coder={"bind": "localhost"}), "light") == "coder"
    assert calls == []


def _remote(bind):
    g = g3(1, 2, coder={"host": "p", "bind": bind})
    g["hosts"]["p"] = {"addr": "peer.example"}
    return g


@pytest.mark.parametrize("bind", ["127.0.0.1", "127.0.0.2"])
def test_remote_ipv4_loopback_bind_needs_tunnel(bind):
    assert EP.node_url(_remote(bind), "coder", "h") is None


@pytest.mark.parametrize("bind", ["0.0.0.0", "::"])
def test_remote_wildcard_bind_is_dialed_at_host_addr(bind):
    assert EP.node_url(_remote(bind), "coder", "h") == "http://peer.example:2/v1"


@pytest.mark.parametrize("bind", ["::1", "[::1]", "::ffff:127.0.0.1", "localhost", "LOCALHOST"])
def test_remote_non_ipv4_loopback_bind_needs_tunnel(bind):
    assert EP.node_url(_remote(bind), "coder", "h") is None


# ---------------- off-loopback source: explicit tool_route vs discovery (TOOLS-009 / #345) ----------------

def test_off_loopback_explicit_tool_route_still_forwards():
    """TOOLS-009: an explicit graph tool_route is a deliberate opt-in and still
    forwards when the source is off-loopback with no server_tools (#355)."""
    g = _hg({"a": {"model": "cod", "bind": "0.0.0.0", "tool_route": "t"}, "t": {"model": "cod"}})
    assert "server_tools" not in g["nodes"]["a"]
    assert not VG._loopback(g["nodes"]["a"]["bind"]) and VG.tool_capable(g, "a")
    assert VG.tool_route(g, "a") == "t"
    r = HH.route_tools(g, "hermes")
    assert r == {"mode": "nexus", "node": "t", "via": None, "reason": "tool_route"}
    assert EP.tool_target(g, "a") == "t"


def test_off_loopback_discovery_only_gets_none():
    """Off-loopback, no server_tools, no tool_route: none. #355 does not consult
    same-host or mesh discovery, so rebinding cannot implicitly forward."""
    g = _hg({"a": {"model": "cod", "bind": "0.0.0.0"}, "z-local": {"model": "cod"}})
    assert "server_tools" not in g["nodes"]["a"] and "tool_route" not in g["nodes"]["a"]
    assert VG.tool_policy(g, "a") == []
    assert VG.tool_capable(g, "z-local") and VG.tool_policy(g, "z-local") != []
    r = HH.route_tools(g, "hermes")
    assert r == {"mode": "none", "node": None, "via": None, "reason": "off-loopback without server_tools"}
    assert EP.tool_target(g, "a") is None
    g = _hg({"a": {"model": "cod", "bind": "0.0.0.0"},
             "a-peer": {"model": "cod", "host": "p", "server_tools": "all", "bind": "0.0.0.0"}},
            meshes={"lan": {"type": "ssh", "members": ["h", "p"]}})
    r = HH.route_tools(g, "hermes")
    assert r == {"mode": "none", "node": None, "via": None, "reason": "off-loopback without server_tools"}
