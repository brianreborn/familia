"""#355 follow-up: off-loopback without server_tools honours only an explicit tool_route.

Discovery / resident-peer nexus must not implicit-forward when a capable node is
rebound off loopback. Separate file so it does not collide with Routing Test
Designer's additions in tests/test_routing_toolroute.py (#362).
"""
import os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import escalation_proxy as EP  # noqa: E402
import hermes_harness as HH  # noqa: E402
import validate_graph as VG  # noqa: E402


def _g(src=None, peer=None, src_model="c", peer_host="h"):
    """Tool-capable source `a` plus a same-host (or given-host) tool-capable peer `p`."""
    g = {"hosts": {"h": {}, "r": {"addr": "r.example"}},
         "models": {"c": {"role": "coder", "tool_calls": True},
                    "d": {"role": "decision", "tool_calls": False}},
         "aliases": {},
         "agents": {"hermes": {"aliases": {"main": "a", "auxiliary": "a"}}},
         "nodes": {
             "a": dict({"host": "h", "port": 9000, "model": src_model, "bind": "0.0.0.0"}, **(src or {})),
             "p": dict({"host": peer_host, "port": 9001, "model": "c", "bind": "127.0.0.1"}, **(peer or {})),
         }}
    return g


def test_offloopback_capable_source_explicit_tool_route_is_nexus():
    """TOOLS-009 opt-in: off-loopback, no server_tools, explicit tool_route still forwards."""
    g = _g(src={"tool_route": "p"})
    assert "server_tools" not in g["nodes"]["a"]
    assert not VG._loopback(g["nodes"]["a"]["bind"])
    assert VG.tool_capable(g, "a")
    assert VG.tool_policy(g, "a") == VG.READ_ONLY_TOOLS  # routed grant
    r = HH.route_tools(g, "hermes")
    assert r == {"mode": "nexus", "node": "p", "via": None, "reason": "tool_route"}
    assert EP.tool_target(g, "a") == "p"


def test_offloopback_capable_source_discovery_only_stays_none():
    """A same-host tool-capable peer is not enough; without tool_route, mode is none."""
    g = _g()
    assert "tool_route" not in g["nodes"]["a"]
    assert "server_tools" not in g["nodes"]["a"]
    assert VG.tool_capable(g, "p") and VG.tool_policy(g, "p") != []
    r = HH.route_tools(g, "hermes")
    assert r == {"mode": "none", "node": None, "via": None, "reason": "off-loopback without server_tools"}
    assert EP.tool_target(g, "a") is None
    # Mesh-discoverable peer also must not be used.
    g["nodes"]["p"]["host"] = "r"
    g["meshes"] = {"lan": {"type": "ssh", "members": ["h", "r"]}}
    r = HH.route_tools(g, "hermes")
    assert r["mode"] == "none" and r.get("reason") == "off-loopback without server_tools"


def test_proxy_refuses_empty_tool_policy_source_without_server_tools():
    """tool_target fails closed when source tool_policy is [] even if server_tools is absent.

    Off-loopback capable source with a tool_route key pointing at an empty-policy
    target: the key is present (so the old 'server_tools' in node gate would not
    apply) but policy is [], so the proxy must not forward.
    """
    g = _g(src={"tool_route": "p"}, peer={"server_tools": []})
    assert "server_tools" not in g["nodes"]["a"]
    assert VG.tool_policy(g, "a") == []
    assert VG.tool_route(g, "a") is None
    assert EP.tool_target(g, "a") is None
    # Same if the source has no route at all (policy [] from the missing grant).
    g2 = _g()
    assert VG.tool_policy(g2, "a") == []
    assert EP.tool_target(g2, "a") is None
