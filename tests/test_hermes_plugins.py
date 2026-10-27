"""#92: official / portable Hermes plugins bridge into rendered HERMES_HOME."""
import os, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh

def test_link_plugins_none(tmp_path, monkeypatch):
    monkeypatch.setattr(hh, "USER_HOME", str(tmp_path / "uh"))
    home = tmp_path / "home"; home.mkdir()
    assert hh.link_plugins({}, str(home)) == []
    assert not (home / "plugins").exists()

def test_link_plugins_named(tmp_path, monkeypatch):
    uh = tmp_path / "uh"; (uh / "plugins" / "rea").mkdir(parents=True)
    (uh / "plugins" / "rea" / "plugin.json").write_text("{}")
    monkeypatch.setattr(hh, "USER_HOME", str(uh))
    home = tmp_path / "home"; home.mkdir()
    assert hh.link_plugins({"plugins": ["rea"]}, str(home)) == ["rea"]
    dst = home / "plugins" / "rea"
    assert dst.is_symlink() and dst.resolve() == (uh / "plugins" / "rea").resolve()
    # idempotent
    assert hh.link_plugins({"plugins": ["rea"]}, str(home)) == ["rea"]

def test_link_plugins_star(tmp_path, monkeypatch):
    uh = tmp_path / "uh"
    for n in ("rea", "other"): (uh / "plugins" / n).mkdir(parents=True)
    monkeypatch.setattr(hh, "USER_HOME", str(uh))
    home = tmp_path / "home"; home.mkdir()
    assert hh.link_plugins({"plugins": ["*"]}, str(home)) == ["other", "rea"]

def test_link_plugins_missing_dies(tmp_path, monkeypatch):
    uh = tmp_path / "uh"; (uh / "plugins").mkdir(parents=True)
    monkeypatch.setattr(hh, "USER_HOME", str(uh))
    home = tmp_path / "home"; home.mkdir()
    with pytest.raises(SystemExit):
        hh.link_plugins({"plugins": ["rea"]}, str(home))

def test_lean_keeps_mcp_aux():
    """REA's MCP server is reached through hermes' mcp aux path; lean must keep it."""
    assert "mcp" in hh.AUX_TASKS
    assert "mcp" not in hh.LEAN_AUX_DROP

def test_graph_accepts_plugins_field():
    """agents.*.plugins is a known field; ignore unrelated graph validation noise."""
    import copy, yaml
    g = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    g = copy.deepcopy(g)
    g["agents"]["hermes-lab"]["plugins"] = ["rea"]
    import graph_types as gt
    # Only plugin-related complaints matter here. Broader "unknown field" matches would
    # fail this test whenever unrelated catalog fields (e.g. options.*.db) drift.
    errs = [e for e in gt.validate_types(g) if "plugins" in e.lower()]
    assert not errs, errs
    assert "plugins" in (gt.TYPES["agents"].fields or {})
