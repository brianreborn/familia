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
  "modal": {k: [(cfg["auxiliary"].get(k) or {}).get("provider"), (cfg["auxiliary"].get(k) or {}).get("base_url")]
            for k in ("vision", "voice_chat", "moa_reference", "moa_aggregator")},
  "moa": (lambda p: {"enabled": p.get("enabled"), "providers": sorted({s["provider"] for s in p.get("reference_models", [])}
          | {(p.get("aggregator") or {}).get("provider")}), "presets": sorted(cfg["moa"]["presets"])})(
          __import__("hermes_cli.moa_config", fromlist=["x"]).resolve_moa_preset(cfg.get("moa"))),
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
    for k, (prov, url) in out["modal"].items():   # fix-forward (f): no upstream auto for these
        assert prov == "custom" and url == cfg["model"]["base_url"], k
    assert out["moa"] == {"enabled": False, "providers": ["custom"], "presets": ["default"]}
    assert "fam-demo" in out["skills"]
    assert open(os.path.join(home, "config.yaml"), "rb").read() == before  # hermes did not rewrite it


# --- Boundary fix-forward (f): modality / MoA aux tasks local-or-disabled; cloud keys scrubbed ----

MODAL = ("vision", "voice_chat", "moa_reference", "moa_aggregator")


def test_modal_aux_tasks_local_and_moa_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv(hh.ALLOW_CLOUD_ENV, raising=False)
    user = tmp_path / "user.yaml"
    user.write_text(yaml.safe_dump({"moa": {"presets": {"cloud": {"reference_models": [
        {"provider": "openrouter", "model": "x/y"}], "aggregator": {"provider": "openrouter", "model": "x/z"}}}}}))
    monkeypatch.setenv("HOME", str(tmp_path))
    home, *_ = hh.render(copy.deepcopy(GRAPH), "hermes", user_cfg_path=str(user))
    cfg = yaml.safe_load(open(os.path.join(home, "config.yaml")))
    for t in MODAL:
        assert cfg["auxiliary"][t]["provider"] == "custom"
        assert cfg["auxiliary"][t]["base_url"] == cfg["model"]["base_url"]
    assert list(cfg["moa"]["presets"]) == ["default"]                    # user's cloud preset not inherited
    p = cfg["moa"]["presets"]["default"]
    assert p["enabled"] is False
    assert {s["provider"] for s in p["reference_models"]} | {p["aggregator"]["provider"]} == {"custom"}


def test_allow_cloud_restores_upstream_routing(tmp_path, monkeypatch):
    monkeypatch.setenv(hh.ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    user = tmp_path / "user.yaml"; user.write_text(yaml.safe_dump({"moa": {"default_preset": "mine"}}))
    home, *_ = hh.render(copy.deepcopy(GRAPH), "hermes", user_cfg_path=str(user))
    cfg = yaml.safe_load(open(os.path.join(home, "config.yaml")))
    assert not any(t in cfg["auxiliary"] for t in MODAL)
    assert cfg["moa"] == {"default_preset": "mine"}
    assert hh.hermes_child_env(environ={"OPENAI_API_KEY": "sk", hh.ALLOW_CLOUD_ENV: "1"})["OPENAI_API_KEY"] == "sk"


def test_child_env_scrubs_cloud_keys_keeps_mcp_and_familia(tmp_path, monkeypatch):
    monkeypatch.delenv(hh.ALLOW_CLOUD_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    g = copy.deepcopy(GRAPH)
    g["agents"]["hermes"]["mcp"] = dict(MCP, brave={"command": "brave-mcp", "env_from": ["BRAVE_SEARCH_API_KEY"]})
    hh.render(g, "hermes", user_cfg_path=str(tmp_path / "none.yaml"))
    src = {"OPENAI_API_KEY": "sk", "OPENROUTER_API_KEY": "or", "ANTHROPIC_API_KEY": "a", "XAI_API_KEY": "x",
           "AWS_SECRET_ACCESS_KEY": "aws", "HF_TOKEN": "hf", "SOME_API_TOKEN": "t",
           "FAMILIA_API_KEY": "fam", "BRAVE_SEARCH_API_KEY": "brave", "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp",
           "PATH": "/usr/bin", "HOME": str(tmp_path)}
    env = hh.hermes_child_env({"HERMES_HOME": "/h"}, environ=src)
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY",
              "AWS_SECRET_ACCESS_KEY", "HF_TOKEN", "SOME_API_TOKEN"):
        assert k not in env, k
    assert env["FAMILIA_API_KEY"] == "fam" and env["BRAVE_SEARCH_API_KEY"] == "brave"
    assert env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp" and env["HERMES_HOME"] == "/h"
    assert src["OPENAI_API_KEY"] == "sk"                                  # caller's dict untouched
    assert hh.hermes_child_env({"OPENAI_API_KEY": "explicit"}, environ={})["OPENAI_API_KEY"] == "explicit"


# --- Boundary B3: scrub set built from upstream's provider registry + static superset; file creds -----

def test_ast_parser_reads_registry_rows_and_plugin_env_vars(tmp_path):
    root = tmp_path / "src"; (root / "hermes_cli").mkdir(parents=True)
    (root / "hermes_cli" / "auth.py").write_text(
        "_REGISTRY_ROWS = (\n"
        "    ProviderConfig('x', 'X', 'oauth', api_key_env_vars=('XO_TOKEN',)),\n"
        "    ('a', 'A', 'https://a', ('AAA_KEY', 'AAA_SECRET_THING'), 'AAA_URL'),\n"
        ")\n")
    pl = root / "plugins" / "model-providers" / "p"; pl.mkdir(parents=True)
    (pl / "__init__.py").write_text("register(name='p', env_vars=('PEE_TOKEN', 'PEE_BASE_URL'))\n")
    names = hh.upstream_provider_env_names([str(root)])
    assert {"XO_TOKEN", "AAA_KEY", "AAA_SECRET_THING", "AAA_URL", "PEE_TOKEN", "PEE_BASE_URL"} <= names
    assert hh.upstream_provider_env_names([str(tmp_path / "absent")]) == frozenset()


def test_scrub_static_superset_and_file_creds(tmp_path, monkeypatch):
    monkeypatch.delenv(hh.ALLOW_CLOUD_ENV, raising=False)
    monkeypatch.setattr(hh, "upstream_provider_env_names", lambda roots=None: frozenset())
    hh.MCP_ENV_KEEP.clear()
    home = tmp_path / "hh"; home.mkdir(mode=0o700)
    src = {k: "v" for k in ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "AWS_PROFILE", "AWS_REGION",
                            "AWS_ACCESS_KEY_ID", "AWS_WEB_IDENTITY_TOKEN_FILE", "HF_TOKEN", "OPENAI_API_KEY",
                            "GOOGLE_APPLICATION_CREDENTIALS", "CODEX_HOME", "PATH")}
    env = hh.hermes_child_env({"HERMES_HOME": str(home)}, environ=src)
    for k in ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "AWS_PROFILE", "AWS_REGION", "AWS_ACCESS_KEY_ID",
              "AWS_WEB_IDENTITY_TOKEN_FILE", "HF_TOKEN", "OPENAI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"):
        assert k not in env, k
    assert env["AWS_SHARED_CREDENTIALS_FILE"] == env["AWS_CONFIG_FILE"] == os.devnull
    assert env["AWS_EC2_METADATA_DISABLED"] == "true"
    for k, sub in (("CODEX_HOME", "codex"), ("CLOUDSDK_CONFIG", "gcloud")):
        assert env[k] == str(home / ".no-cloud-creds" / sub) and os.listdir(env[k]) == []
        assert (os.stat(env[k]).st_mode & 0o777) == 0o700
    assert hh.hermes_child_env(environ={"PATH": "/bin"})["CODEX_HOME"] == os.devnull   # no HERMES_HOME
    cloud = hh.hermes_child_env({"HERMES_HOME": str(home)}, environ=dict(src, **{hh.ALLOW_CLOUD_ENV: "1"}))
    assert cloud["AWS_PROFILE"] == "v" and cloud["CODEX_HOME"] == "v" and "AWS_CONFIG_FILE" not in cloud


REGISTRY_PROBE = r'''
import json
from hermes_cli.auth import PROVIDER_REGISTRY
import hermes_cli, os
names = set()
for p in PROVIDER_REGISTRY.values():
    names.update(p.api_key_env_vars)
    if p.base_url_env_var: names.add(p.base_url_env_var)
print(json.dumps({"root": os.path.dirname(os.path.dirname(hermes_cli.__file__)), "names": sorted(names)}))
'''


@pytest.mark.skipif(not UPSTREAM_PY, reason="set FAMILIA_HERMES_UPSTREAM_PY to a real hermes-agent python")
def test_every_upstream_registry_env_name_is_scrubbed(tmp_path, monkeypatch):
    """Fails when upstream's provider registry (api_key_env_vars / base_url_env_var, plugin providers
    included) names an env var familia's child env would still carry."""
    env = dict(os.environ, HOME=str(tmp_path)); env.pop("PYTHONPATH", None)
    r = subprocess.run([UPSTREAM_PY, "-c", REGISTRY_PROBE], capture_output=True, text=True, env=env,
                       cwd=str(tmp_path), timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["names"], "upstream registry is empty?"
    monkeypatch.delenv(hh.ALLOW_CLOUD_ENV, raising=False)
    monkeypatch.setattr(hh, "HERMES_SP", out["root"])
    hh.MCP_ENV_KEEP.clear()
    left = hh.hermes_child_env(environ={n: "secret" for n in out["names"]})
    assert sorted(n for n in out["names"] if left.get(n) == "secret") == []
    # and the source parser alone (no regex / static help) sees every registry name
    parsed = hh.upstream_provider_env_names([out["root"]])
    assert sorted(set(out["names"]) - parsed) == []


def test_ambient_secrets_not_carried_unless_opted_in(tmp_path, monkeypatch):
    """Boundary N2: GH_TOKEN / *_SECRET / *_PASSWORD / SSH_AUTH_SOCK never reach hermes' terminal env."""
    monkeypatch.setenv("HOME", str(tmp_path))
    g = copy.deepcopy(GRAPH)
    g["agents"]["hermes"]["mcp"] = {"gh": {"command": "github-mcp-server", "env_from": ["GITHUB_TOKEN"]}}
    hh.render(g, "hermes", user_cfg_path=str(tmp_path / "none.yaml"))
    src = {"GH_TOKEN": "g", "GITHUB_TOKEN": "gt", "DB_PASSWORD": "p", "CLIENT_SECRET": "s", "AWS_X": "a",
           "MY_SECRET_KEY": "k", "SSH_AUTH_SOCK": "/run/ssh", "FAMILIA_ADMIN_PASSWORD": "f", "TERM": "xterm"}
    env = hh.hermes_child_env(environ=src)
    for k in ("GH_TOKEN", "DB_PASSWORD", "CLIENT_SECRET", "MY_SECRET_KEY", "SSH_AUTH_SOCK"):
        assert k not in env, k
    assert env["GITHUB_TOKEN"] == "gt"                    # declared by the gh MCP server
    assert env["FAMILIA_ADMIN_PASSWORD"] == "f" and env["TERM"] == "xterm"
    opted = hh.hermes_child_env(environ=dict(src, **{hh.PASS_SECRETS_ENV: "1"}))
    assert opted["GH_TOKEN"] == "g" and opted["SSH_AUTH_SOCK"] == "/run/ssh"
