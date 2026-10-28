"""#110: hermes_loop + harness2_loop adapters (real CLIs, not single chat)."""
import os
import sys
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "dogfood"))


def _load(name, rel):
    path = os.path.join(ROOT, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HL = _load("hermes_loop", "scripts/dogfood/hermes_loop.py")
H2 = _load("harness2_loop", "scripts/dogfood/harness2_loop.py")


def test_hermes_render_cmd_single_and_graph():
    single = HL.build_render_cmd("single", "coder", repo_root=ROOT)
    assert "hermes.sh" in single[1]
    assert single[single.index("--mode") + 1] == "single"
    assert single[single.index("--model") + 1] == "coder"
    assert "--render-only" in single

    graph = HL.build_render_cmd("graph", "coder", repo_root=ROOT)
    assert graph[graph.index("--mode") + 1] == "graph"
    assert "--model" not in graph
    assert "--render-only" in graph


def test_hermes_agent_cmd_oneshot_limited_tools():
    cmd = HL.build_agent_cmd("fix the bug", hermes_bin="/tmp/fake-hermes-agent")
    assert cmd[0] == "/tmp/fake-hermes-agent"
    assert "-z" in cmd and cmd[cmd.index("-z") + 1] == "fix the bug"
    tools = cmd[cmd.index("-t") + 1]
    assert "file" in tools and "terminal" in tools
    assert "web" not in tools and "search" not in tools and "browser" not in tools
    assert "--yolo" in cmd


def test_hermes_home_single_vs_graph():
    s = HL.home_for("single", "hermes", "coder")
    g = HL.home_for("graph", "hermes", "coder")
    assert "hermes-hermes@coder" in str(s)
    assert "hermes-hermes" in str(g)
    assert "@" not in str(g)


def test_harness_to_mode_map():
    assert HL.HARNESS_TO_MODE["hermes"] == "single"
    assert HL.HARNESS_TO_MODE["hermes-graph"] == "graph"


def test_harness2_propose_smoke_and_live():
    smoke = H2.build_propose_cmd("hermes-lab", smoke=True, max_tasks=1, repo_root=ROOT)
    assert smoke[1].endswith("harness2.py")
    assert "propose" in smoke
    assert smoke[smoke.index("--target") + 1] == "hermes-lab"
    assert "--dry-run" in smoke
    assert "--enable" in smoke

    live = H2.build_propose_cmd("hermes-lab", smoke=False, repo_root=ROOT)
    assert "propose" in live
    assert "--dry-run" not in live


def test_propose_accepted_semantics():
    assert H2.propose_accepted(0, "dry-run: plan", smoke=True)
    assert not H2.propose_accepted(0, "no marker", smoke=True)
    assert H2.propose_accepted(0, "anything", smoke=False)
    assert not H2.propose_accepted(1, "fail", smoke=False)


def test_run_render_invokes_sh():
    calls = []

    def fake_sh(cmd, cwd=None, timeout=900, env=None):
        calls.append({"cmd": cmd, "cwd": cwd})
        return 0, "ok"

    rc, out, cmd = HL.run_render("single", "coder", sh=fake_sh, repo_root=ROOT)
    assert rc == 0 and out == "ok"
    assert calls and "--render-only" in calls[0]["cmd"]
    assert cmd == calls[0]["cmd"]


def test_run_oneshot_uses_lock_prefix_and_worktree_cwd(tmp_path, monkeypatch):
    calls = []

    def fake_sh(cmd, cwd=None, timeout=900, env=None):
        calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        return 0, "done"

    monkeypatch.setattr(HL, "agent_env", lambda home, extra=None: {"HERMES_HOME": str(home), "FAMILIA_SYNC": "0"})
    home = tmp_path / "home"
    rc, out, cmd, env = HL.run_oneshot(
        str(tmp_path / "wt"), "do it", home, sh=fake_sh,
        lock_prefix=["flock", "/tmp/x"], hermes_bin="/tmp/fake-hermes",
    )
    assert rc == 0
    assert calls[0]["cwd"] == str(tmp_path / "wt")
    assert calls[0]["cmd"][:2] == ["flock", "/tmp/x"]
    assert calls[0]["cmd"][2] == "/tmp/fake-hermes"
    assert env["HERMES_HOME"] == str(home)
    assert env["FAMILIA_SYNC"] == "0"


def test_no_legacy_chat_in_adapters():
    for rel in ("scripts/dogfood/hermes_loop.py", "scripts/dogfood/harness2_loop.py"):
        src = open(os.path.join(ROOT, rel)).read()
        assert "/v1/chat/completions" not in src
        assert "<file path=" not in src
        assert "FILE_RE" not in src
