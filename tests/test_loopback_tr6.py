"""TR-6: one shared literal-loopback check replaces startswith("127.") prefix checks.

Matrix from docs/config/routing-spec.md CFG-SPEC-TOOLS-004 and the Boundary TR-6 spec:
loopback = literal localhost (any case, no DNS), IPv4 127/8, ::1 / [::1], and
IPv4-mapped ::ffff:127.x. Not loopback: wildcard, other DNS names, garbage, host:port.
"""
import os, socket, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import loopback  # noqa: E402
import validate_graph as vg  # noqa: E402
import bind_auth_guard  # noqa: E402
import graph_router  # noqa: E402
import hermes_harness  # noqa: E402
import transport_graph  # noqa: E402

LOOPBACK = [
    "127.0.0.1", "127.0.0.2", "127.0.0.0", "127.255.255.255",
    "localhost", "LOCALHOST", " LocalHost ",
    "::1", "[::1]", "0:0:0:0:0:0:0:1",
    "::ffff:127.0.0.1", "[::ffff:127.0.0.1]", "::ffff:127.0.0.2", "::FFFF:127.0.0.1",
    "::1%lo0", "[::1%lo0]",
]
NOT_LOOPBACK = [
    "0.0.0.0", "::", "[::]", "::ffff:0.0.0.0", "::ffff:8.8.8.8",
    "192.168.1.1", "8.8.8.8", "fe80::1", "fe80::1%eth0",
    "127.example", "127.0.0.1.evil", "127.evil.com", "localhost.evil", "localhost.",
    "127.0.0.01", "127.1", "2130706433", "0x7f.0.0.1",
    "127.0.0.1:8080", "localhost:8080", "[::1]:8080",
    "127.0.0.1%eth0", "::1%", "127.0.0.1#comment", "", "   ", None, 127,
]


@pytest.mark.parametrize("host", LOOPBACK)
def test_is_loopback_true(host):
    assert loopback.is_loopback(host) is True


@pytest.mark.parametrize("host", NOT_LOOPBACK)
def test_is_loopback_false(host):
    assert loopback.is_loopback(host) is False


def test_no_dns(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("is_loopback must never resolve names")
    for fn in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
        monkeypatch.setattr(socket, fn, boom)
    for h in LOOPBACK + NOT_LOOPBACK:
        loopback.is_loopback(h)


@pytest.mark.parametrize("host", LOOPBACK + NOT_LOOPBACK)
def test_existing_helpers_are_the_shared_one(host):
    want = loopback.is_loopback(host)
    assert vg.is_loopback(host) is want
    assert vg._loopback(host) is want
    assert bind_auth_guard._is_loopback_host(host) is want
    assert graph_router._is_loopback(host) is want


def test_no_prefix_checks_left():
    for rel in ("scripts/graph_router.py", "scripts/hermes_harness.py", "scripts/transport_graph.py"):
        src = open(os.path.join(ROOT, rel)).read()
        assert 'startswith("127.")' not in src and "startswith('127.')" not in src, rel


# --- graph_router call sites ------------------------------------------------

@pytest.mark.parametrize("host", ["127.example", "127.0.0.1.evil"])
def test_router_prefix_name_needs_remote_flag(host):
    with pytest.raises(graph_router.ConfigError, match="not loopback"):
        graph_router._node("n", {"url": f"http://{host}:8080"})
    assert graph_router._node("n", {"url": f"http://{host}:8080", "remote": True})["remote"] is True


@pytest.mark.parametrize("url", ["http://127.0.0.2:8080", "http://[::1]:8080",
                                 "http://[::ffff:127.0.0.1]:8080", "http://LOCALHOST:8080"])
def test_router_real_loopback_is_local(url):
    assert graph_router._node("n", {"url": url})["remote"] is False


@pytest.mark.parametrize("host", ["127.example", "127.0.0.1.evil", "0.0.0.0", "::"])
def test_router_listen_refuses_non_loopback(host):
    with pytest.raises(graph_router.ConfigError, match="loopback only"):
        graph_router.make_server({"routes": {}, "nodes": {}}, host=host, port=0)


def _graph(bind, host="a"):
    return {"hosts": {"a": {"addr": "peer-a.invalid"}, "b": {"addr": "peer-b.invalid"}},
            "models": {"m": {"role": "chat"}},
            "nodes": {"n": {"status": "active", "role": "chat", "model": "m", "host": host,
                            "bind": bind, "port": 8080}}}


@pytest.mark.parametrize("bind", ["127.0.0.2", "[::1]", "::ffff:127.0.0.1"])
def test_router_remote_loopback_bind_refused(bind):
    out, refused = graph_router.nodes_from_graph(_graph(bind, host="b"), here="a")
    assert "n" in refused and "binds loopback" in refused["n"]


def test_router_remote_prefix_name_bind_not_treated_as_loopback():
    out, refused = graph_router.nodes_from_graph(_graph("127.example", host="b"), here="a")
    assert "binds loopback" not in refused.get("n", "")


# --- hermes_harness.node_base -----------------------------------------------

def _hg(bind):
    return {"hosts": {"b": {"addr": "peer-b.invalid"}},
            "nodes": {"n": {"host": "b", "bind": bind, "port": 8080}}}


@pytest.mark.parametrize("bind", ["127.0.0.1", "127.0.0.2", "localhost", "LOCALHOST", "::1",
                                  "[::1]", "::ffff:127.0.0.1"])
def test_node_base_rewrites_loopback_bind_for_other_host(bind):
    assert hermes_harness.node_base(_hg(bind), "n", "a") == "http://peer-b.invalid:8080/v1"


@pytest.mark.parametrize("bind", ["127.example", "127.0.0.1.evil"])
def test_node_base_prefix_name_not_rewritten(bind):
    assert hermes_harness.node_base(_hg(bind), "n", "a") == f"http://{bind}:8080/v1"


def test_node_base_same_host_keeps_bind():
    assert hermes_harness.node_base(_hg("127.0.0.2"), "n", "b") == "http://127.0.0.2:8080/v1"


# --- transport_graph.validate_transports ------------------------------------

def _tg(bind):
    return {"hosts": {"t": {"addr": "192.168.1.9", "user": "u", "port": 22, "kind": "pc"}},
            "meshes": {"bt": {"type": "bittorrent", "members": ["t"], "tracker": "t",
                              "bind": bind, "client": "aria2c", "private": True}}}


def _bind_errs(bind):
    return [e for e in transport_graph.validate_transports(_tg(bind)) if "bind" in e]


@pytest.mark.parametrize("bind", ["127.0.0.1", "127.0.0.2", "[::1]", "::1", "::ffff:127.0.0.1", "localhost"])
def test_transport_loopback_bind_ok(bind):
    assert _bind_errs(bind) == []


@pytest.mark.parametrize("bind", ["127.example", "127.0.0.1.evil"])
def test_transport_prefix_name_rejected(bind):
    errs = _bind_errs(bind)
    assert any("must be a loopback or private LAN" in e for e in errs), errs
    assert any("!= tracker host addr" in e for e in errs), errs


def test_transport_lan_mismatch_still_rejected():
    assert any("!= tracker host addr" in e for e in _bind_errs("192.168.1.99"))
