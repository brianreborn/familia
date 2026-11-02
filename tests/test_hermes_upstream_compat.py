"""Rendered HERMES_HOME vs upstream hermes-agent (bleeding v0.22.6 / stable v0.22.5).

Offline part: the keys familia renders. Live part (opt-in): set FAMILIA_HERMES_UPSTREAM_PY to
the python of a real hermes-agent install (e.g. a `uv sync --frozen` venv of the pinned tag);
the rendered config is then loaded and validated by that hermes itself (config schema incl.
mcp_servers and approvals, toolsets, MCP ${VAR} interpolation, aux tasks, skills discovery,
the symbols scripts/hermes_harness.py imports in its child processes).
"""
import copy, json, os, subprocess, sys
import pytest, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh

GRAPH = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
MCP = {"gh": {"command": "github-mcp-server", "args": ["stdio"], "env_from": ["GITHUB_PERSONAL_ACCESS_TOKEN"]},
       "web": {"url": "https://mcp.example/sse", "headers_from": {"Authorization": "WEB_MCP_TOKEN"}}}
UPSTREAM_PY = os.environ.get("FAMILIA_HERMES_UPSTREAM_PY")


def _render(tmp_path, monkeypatch, profile):
    monkeypatch.setenv("HOME", str(tmp_path))
    g = copy.deepcopy(GRAPH)
    a = g["agents"]["hermes"]; a["prompt_profile"] = profile; a["mcp"] = MCP
    home, *_ = hh.render(g, "hermes", user_cfg_path=str(tmp_path / "none.yaml"))
    path = os.path.join(home, "config.yaml")
    cfg = yaml.safe_load(open(path))
    cfg["approvals"] = {"mode": "manual"}  # what tool routing (route_tools) renders for gated nodes
    yaml.safe_dump(cfg, open(path, "w"), sort_keys=False)
    return home, cfg


def test_review_aux_tasks_stay_on_the_local_node(tmp_path, monkeypatch):
    home, cfg = _render(tmp_path, monkeypatch, "full")
    for t in ("review", "background_review", "compression", "approval", "mcp"):
        assert cfg["auxiliary"][t]["provider"] == "custom"
        assert cfg["auxiliary"][t]["base_url"] == cfg["model"]["base_url"]
    _, lean = _render(tmp_path, monkeypatch, "lean")
    assert "background_review" in lean["auxiliary"] and "review" in lean["auxiliary"]


PROBE = r'''
import json, os, sys
from hermes_cli import config as C
from hermes_cli.config_defaults import DEFAULT_CONFIG
from hermes_cli.approval_mode import VALID_APPROVAL_MODES
from hermes_cli.tools_config import _get_platform_tools
from tools.mcp_tool_config import _load_mcp_config
from tools.skills_tool import find_all_skills
from agent.model_metadata import MINIMUM_CONTEXT_LENGTH
import tools.env_probe as E
from hermes_cli.prompt_size import _build_inspection_agent
from agent.system_prompt import build_system_prompt, build_system_prompt_parts
from agent.context_compressor import ContextCompressor
import inspect
cfg = C.load_config()
cc = inspect.signature(ContextCompressor.__init__).parameters
print(json.dumps({
  "issues": [[i.severity, i.message] for i in C.validate_config_structure(cfg)],
  "approvals": cfg.get("approvals", {}).get("mode") in VALID_APPROVAL_MODES,
  "tools": sorted(_get_platform_tools(cfg, "cli")),
  "mcp": _load_mcp_config(),
  "aux": {k: (cfg["auxiliary"][k] or {}).get("base_url") for k in ("compression", "review", "background_review")},
  "ctx": [cfg["model"]["context_length"], MINIMUM_CONTEXT_LENGTH],
  "skills": [s.get("name") for s in find_all_skills()],
  "env_probe": callable(getattr(E, "_build_probe_line", None)),
  "cc": all(k in cc for k in ("model", "threshold_percent", "protect_first_n", "protect_last_n",
                               "summary_target_ratio", "quiet_mode", "base_url", "api_key",
                               "config_context_length", "provider")),
}))
'''


@pytest.mark.skipif(not UPSTREAM_PY, reason="set FAMILIA_HERMES_UPSTREAM_PY to a real hermes-agent python")
@pytest.mark.parametrize("profile", ["full", "lean"])
def test_upstream_hermes_accepts_rendered_home(tmp_path, monkeypatch, profile):
    home, cfg = _render(tmp_path, monkeypatch, profile)
    skill = tmp_path / "skillsrc" / "fam-demo"; skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: fam-demo\ndescription: linked by familia\n---\n# demo\n")
    os.makedirs(os.path.join(home, "skills"), exist_ok=True)
    os.symlink(skill, os.path.join(home, "skills", "fam-demo"))  # how scripts/skills.py links skills
    env = dict(os.environ, HOME=str(tmp_path), HERMES_HOME=home,
               GITHUB_PERSONAL_ACCESS_TOKEN="ghp_test", WEB_MCP_TOKEN="w_test")
    env.pop("PYTHONPATH", None)
    before = open(os.path.join(home, "config.yaml"), "rb").read()
    r = subprocess.run([UPSTREAM_PY, "-c", PROBE], capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["issues"] == []
    assert out["approvals"] is True
    assert out["env_probe"] and out["cc"]
    assert out["ctx"][0] >= out["ctx"][1]
    assert set(out["mcp"]) == {"gh", "web"}
    assert out["mcp"]["gh"]["env"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"}
    assert "gh" in out["tools"] and "web" in out["tools"] or profile == "full"
    if profile == "lean":
        assert set(out["tools"]) <= set(hh.LEAN_TOOLSETS) | {"gh", "web"}
    assert set(out["aux"].values()) == {cfg["model"]["base_url"]}
    assert "fam-demo" in out["skills"]
    assert open(os.path.join(home, "config.yaml"), "rb").read() == before  # hermes did not rewrite it
