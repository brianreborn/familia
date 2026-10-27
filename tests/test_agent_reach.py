"""Agent-Reach graph + HERMES_HOME link (#27 follow-up / tool-provider wire)."""
import copy, json, os, sys, textwrap
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import familia_agent_reach as ar
import graph_types as gt
import yaml


def _minimal_graph():
    return {
        "hosts": {"h": {"kind": "desktop", "ram_mib": 16384}},
        "runtimes": {},
        "nodes": {},
        "aliases": {},
        "agents": {"hermes": {"kind": "hermes-agent", "aliases": {"main": "x", "auxiliary": "x"},
                              "min_ctx": 1024, "context_length": 4096}},
        "reaches": {
            "agent-reach": {
                "experimental": True,
                "repo": "Panniantong/Agent-Reach",
                "agents": ["hermes"],
            }
        },
    }


def test_validate_reach_entry_ok():
    g = _minimal_graph()
    assert ar.validate_reach_entry(g, "agent-reach", g["reaches"]["agent-reach"]) == []


def test_validate_reach_entry_bad_repo():
    g = _minimal_graph()
    g["reaches"]["agent-reach"]["repo"] = "not-a-repo"
    errs = ar.validate_reach_entry(g, "agent-reach", g["reaches"]["agent-reach"])
    assert any("repo" in e for e in errs)


def test_validate_reach_unknown_agent():
    g = _minimal_graph()
    g["reaches"]["agent-reach"]["agents"] = ["nope"]
    errs = ar.validate_reach_entry(g, "agent-reach", g["reaches"]["agent-reach"])
    assert any("nope" in e for e in errs)


def test_graph_types_accepts_reaches():
    """Experimental reaches stub still accepted by graph_types (existing contract)."""
    # Use the real graph.yaml shape via a deep copy of the experimental stub test style
    g = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    g = copy.deepcopy(g)
    g["reaches"] = {
        "agent-reach": {
            "experimental": True,
            "repo": "Panniantong/Agent-Reach",
            "agents": ["hermes"],
        }
    }
    errs = [e for e in gt.validate_types(g) if "reach" in e.lower()]
    assert not errs, errs


def test_reaches_for_filters_agent():
    g = _minimal_graph()
    assert [n for n, _ in ar.reaches_for(g, "hermes")] == ["agent-reach"]
    assert ar.reaches_for(g, "other") == []


def test_link_reach_into_home(tmp_path, monkeypatch):
    # Point pin checkout at the real (or symlinked) agent-reach under ROOT
    checkout = ar.pin_checkout(ROOT)
    if not checkout:
        pytest.skip("agent-reach pin checkout not present")
    home = tmp_path / "hermes-home"
    home.mkdir()
    actions = ar.link_reach_into_home(str(home), checkout=checkout)
    skill = home / "skills" / "agent-reach"
    assert skill.is_symlink()
    assert (skill / "SKILL.md").is_file()
    wrapper = home / "bin" / "agent-reach"
    assert wrapper.is_file() and os.access(wrapper, os.X_OK)
    body = wrapper.read_text()
    assert "agent_reach.cli" in body and checkout in body
    tip = home / "agent-reach.mcp.example.json"
    assert tip.is_file()
    mcp = json.loads(tip.read_text())
    assert "agent-reach" in mcp["mcpServers"]
    # idempotent
    actions2 = ar.link_reach_into_home(str(home), checkout=checkout)
    assert any(a.startswith("ok ") for a in actions2)


def test_set_agents_list_creates_section():
    text = "agents:\n  hermes:\n    kind: hermes-agent\n"
    out = ar.set_agents_list(text, "agent-reach", ["hermes"])
    assert "reaches:" in out
    assert "experimental: true" in out
    assert "repo: Panniantong/Agent-Reach" in out
    assert "agents: [hermes]" in out
    g = yaml.safe_load(out)
    assert g["reaches"]["agent-reach"]["agents"] == ["hermes"]


def test_hermes_link_reaches_hook(tmp_path, monkeypatch):
    import hermes_harness as hh
    checkout = ar.pin_checkout(ROOT)
    if not checkout:
        pytest.skip("agent-reach pin checkout not present")
    g = _minimal_graph()
    home = tmp_path / "h"
    home.mkdir()
    linked = hh.link_reaches(g, "hermes", str(home))
    assert linked
    assert (home / "skills" / "agent-reach").is_symlink()
    # agent not opted in → no-op
    assert hh.link_reaches(g, "nobody", str(home)) == []


def test_hermes_child_env_prepends_bin(tmp_path, monkeypatch):
    import hermes_harness as hh
    home = tmp_path / "h"
    (home / "bin").mkdir(parents=True)
    env = hh.hermes_child_env({"HERMES_HOME": str(home)}, environ={"PATH": "/usr/bin"})
    assert env["PATH"].startswith(str(home / "bin"))
