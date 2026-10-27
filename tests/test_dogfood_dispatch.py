"""#110: dogfood dispatch must drive real hermes / Harness² CLIs, not single chat calls."""
import os
import sys
import importlib.util

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "dogfood_dispatch", os.path.join(ROOT, "scripts", "dogfood", "dispatch.py")
)
dd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dd)


def test_hermes_render_cmd_single_and_graph():
    single = dd.build_hermes_render_cmd("single", "coder")
    assert "hermes.sh" in single[1]
    assert single[single.index("--mode") + 1] == "single"
    assert single[single.index("--model") + 1] == "coder"
    assert "--render-only" in single

    graph = dd.build_hermes_render_cmd("graph", "coder")
    assert graph[graph.index("--mode") + 1] == "graph"
    assert "--model" not in graph
    assert "--render-only" in graph


def test_hermes_agent_cmd_oneshot_limited_tools():
    cmd = dd.build_hermes_agent_cmd("fix the bug")
    assert "-z" in cmd
    assert cmd[cmd.index("-z") + 1] == "fix the bug"
    assert "-t" in cmd
    tools = cmd[cmd.index("-t") + 1]
    assert "file" in tools and "terminal" in tools
    assert "web" not in tools and "search" not in tools and "browser" not in tools
    assert "--yolo" in cmd


def test_harness2_cmd_smoke_uses_real_propose_dry_run():
    cmd = dd.build_harness2_cmd("hermes-lab", smoke=True, max_tasks=1)
    assert cmd[1].endswith("harness2.py")
    assert "propose" in cmd
    assert "--target" in cmd and cmd[cmd.index("--target") + 1] == "hermes-lab"
    assert "--dry-run" in cmd
    assert "--enable" in cmd


def test_harness2_cmd_live_omits_dry_run():
    cmd = dd.build_harness2_cmd("hermes-lab", smoke=False)
    assert "propose" in cmd
    assert "--dry-run" not in cmd


def test_no_legacy_single_chat_file_blocks():
    src = open(os.path.join(ROOT, "scripts", "dogfood", "dispatch.py")).read()
    assert "FILE_RE" not in src
    assert "<file path=" not in src
    assert "/v1/chat/completions" not in src
    assert "PROMPTS" not in src
    assert "hermes.sh" in src and "harness2.py" in src


def test_worktree_sets_familia_sync_zero(tmp_path, monkeypatch):
    calls = []

    def fake_sh(cmd, cwd=None, timeout=900, env=None):
        calls.append({"cmd": cmd, "env": env})
        return 0, ""

    monkeypatch.setattr(dd, "sh", fake_sh)
    dd.worktree_add(str(tmp_path), str(tmp_path / "wt"))
    assert calls, "expected git worktree calls"
    for c in calls:
        assert c["env"] and c["env"].get("FAMILIA_SYNC") == "0"


def test_default_harnesses_include_both_hermes_modes_and_h2():
    assert "hermes" in dd.DEFAULT_HARNESSES
    assert "hermes-graph" in dd.DEFAULT_HARNESSES
    assert "harness2" in dd.DEFAULT_HARNESSES
    assert dd.HERMES_MODES["hermes"] == "single"
    assert dd.HERMES_MODES["hermes-graph"] == "graph"
