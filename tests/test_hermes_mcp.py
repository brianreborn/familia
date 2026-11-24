"""agents.<a>.mcp: graph -> HERMES_HOME mcp_servers; secrets as ${VAR} refs; lean keeps declared MCP."""
import copy, os, sys
import pytest, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh
from graph_types import validate_types

GRAPH = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
MCP = {"gh": {"command": "github-mcp-server", "args": ["stdio"], "env_from": ["GITHUB_PERSONAL_ACCESS_TOKEN"]},
       "web": {"url": "https://mcp.example/sse", "headers_from": {"Authorization": "WEB_MCP_TOKEN"}}}

def g_with(mcp, lean=True):
    g = copy.deepcopy(GRAPH); a = g["agents"]["hermes"]; a["mcp"] = mcp
    if lean: a["prompt_profile"] = "lean"
    return g

def test_schema_accepts_and_rejects():
    assert not [e for e in validate_types(g_with(MCP)) if ".mcp" in e]
    bad = {"x": {"command": "c", "env": {"GITHUB_TOKEN": "ghp_literal"}}, "y": {"command": "c", "url": "u"},
           "z": {"command": "c", "env_from": ["not a name"]}}
    errs = [e for e in validate_types(g_with(bad)) if ".mcp" in e]
    assert any("mcp.x" in e and "unknown key 'env'" in e for e in errs)
    assert any("mcp.y" in e and "exactly one" in e for e in errs)
    assert any("mcp.z.env_from" in e for e in errs)

def test_render_mcp_lean_no_secret_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "ghp_SECRETVALUE")
    user = tmp_path / "user.yaml"
    user.write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["terminal", "web", "browser"]},
                                    "mcp_servers": {"gh": {"command": "old", "env": {"GITHUB_TOKEN": "x"}}}}))
    home, *_ = hh.render(g_with(MCP), "hermes", user_cfg_path=str(user))
    raw = open(os.path.join(home, "config.yaml")).read()
    assert "ghp_SECRETVALUE" not in raw
    cfg = yaml.safe_load(raw)
    assert cfg["mcp_servers"]["gh"] == {"command": "github-mcp-server", "args": ["stdio"],
                                        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"}}
    assert cfg["mcp_servers"]["web"]["headers"] == {"Authorization": "Bearer ${WEB_MCP_TOKEN}"}
    cli = cfg["platform_toolsets"]["cli"]
    assert "mcp-gh" in cli and "mcp-web" in cli and "web" not in cli and "terminal" in cli
    assert hh.mcp_env_allowlist(g_with(MCP)["agents"]["hermes"]) == ["GITHUB_PERSONAL_ACCESS_TOKEN", "WEB_MCP_TOKEN"]

def test_no_mcp_declared_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    home, *_ = hh.render(copy.deepcopy(GRAPH), "hermes", user_cfg_path=str(tmp_path / "none.yaml"))
    assert "mcp_servers" not in yaml.safe_load(open(os.path.join(home, "config.yaml")))

PROBE = """import sys, json
sys.path.insert(0, sys.argv[1])
from tools.mcp_tool_config import _load_mcp_config
print("MCP=" + json.dumps(_load_mcp_config()))
"""

def test_hermes_agent_loads_rendered_mcp(tmp_path, monkeypatch):
    """Proof against the real hermes-agent loader (subprocess, its own python). Set
    FAMILIA_HERMES_TEST_PY + FAMILIA_HERMES_SRC to point at a checkout; else HERMES_PY/HERMES_SP."""
    py = os.environ.get("FAMILIA_HERMES_TEST_PY") or hh.HERMES_PY
    src = os.environ.get("FAMILIA_HERMES_SRC") or hh.HERMES_SP
    if not (py and os.path.isfile(py) and src and os.path.isfile(os.path.join(src, "tools", "mcp_tool_config.py"))):
        pytest.skip("hermes-agent not installed (set FAMILIA_HERMES_TEST_PY / FAMILIA_HERMES_SRC)")
    monkeypatch.setenv("HOME", str(tmp_path))
    home, *_ = hh.render(g_with(MCP), "hermes", user_cfg_path=str(tmp_path / "none.yaml"))
    import json, subprocess
    env = hh.hermes_child_env({"HERMES_HOME": home, "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_X", "WEB_MCP_TOKEN": "w1"})
    r = subprocess.run([py, "-c", PROBE, src], env=env, capture_output=True, text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("MCP=")]
    assert line, r.stderr[-2000:]
    servers = json.loads(line[-1][4:])
    assert servers["gh"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_X"
    assert servers["web"]["headers"]["Authorization"] == "Bearer w1"
