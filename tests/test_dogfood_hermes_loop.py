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


def test_hermes_agent_cmd_oneshot_limited_tools(tmp_path, monkeypatch):
    monkeypatch.delenv("FAMILIA_HERMES_DOGFOOD_YOLO", raising=False)
    fake = str(tmp_path / "fake-hermes-agent")
    cmd = HL.build_agent_cmd("fix the bug", hermes_bin=fake)
    assert cmd[0] == fake
    assert "-z" in cmd and cmd[cmd.index("-z") + 1] == "fix the bug"
    tools = cmd[cmd.index("-t") + 1]
    assert "file" in tools and "terminal" in tools
    assert "web" not in tools and "search" not in tools and "browser" not in tools
    assert "--yolo" not in cmd   # Boundary N1b: off unless opted in
    # opt-in still refuses an untrusted absolute hermes_bin
    try:
        HL.build_agent_cmd("x", hermes_bin=fake, yolo=True)
        raise AssertionError("expected ValueError for untrusted yolo bin")
    except ValueError as e:
        assert "trust_exec" in str(e)


def test_yolo_from_env_and_resolve_path_require_trust_exec(tmp_path, monkeypatch):
    """Boundary N1b: YOLO via env or resolve_agent_bin also goes through trust_exec."""
    fake = str(tmp_path / "fake-hermes-agent")
    monkeypatch.setenv("FAMILIA_HERMES_DOGFOOD_YOLO", "1")
    # explicit bin + env yolo
    try:
        HL.build_agent_cmd("x", hermes_bin=fake)
        raise AssertionError("expected ValueError for env-yolo untrusted bin")
    except ValueError as e:
        assert "trust_exec" in str(e)
    # resolve_agent_bin path + yolo=True
    monkeypatch.delenv("FAMILIA_HERMES_DOGFOOD_YOLO", raising=False)
    monkeypatch.setattr(HL, "resolve_agent_bin",
                        lambda missing="defaults", require_trust=False: (
                            (_ for _ in ()).throw(ValueError(f"hermes_bin {fake!r} failed trust_exec (nope)"))
                            if require_trust else fake))
    try:
        HL.build_agent_cmd("x", yolo=True)
        raise AssertionError("expected ValueError for resolve-path yolo")
    except ValueError as e:
        assert "trust_exec" in str(e)


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
    monkeypatch.setattr(HL, "_require_trusted_bin", lambda p, reason="": p)  # N1b gate stubbed for unit test
    home = tmp_path / "home"
    fake = str(tmp_path / "fake-hermes")
    rc, out, cmd, env = HL.run_oneshot(
        str(tmp_path / "wt"), "do it", home, sh=fake_sh,
        lock_prefix=["flock", str(tmp_path / "x.lock")], hermes_bin=fake,
    )
    assert rc == 0
    assert calls[0]["cwd"] == str(tmp_path / "wt")
    assert calls[0]["cmd"][:2] == ["flock", str(tmp_path / "x.lock")]
    assert calls[0]["cmd"][2] == fake
    assert env["HERMES_HOME"] == str(home)
    assert env["FAMILIA_SYNC"] == "0"


def test_run_oneshot_refuses_untrusted_bin(tmp_path, monkeypatch):
    """Boundary N1b: live exec path always trust_execs the hermes binary."""
    monkeypatch.delenv("FAMILIA_HERMES_DOGFOOD_YOLO", raising=False)
    monkeypatch.setattr(HL, "agent_env", lambda home, extra=None: {"HERMES_HOME": str(home)})
    try:
        HL.run_oneshot(str(tmp_path / "wt"), "x", tmp_path / "h",
                       sh=lambda *a, **k: (0, ""), hermes_bin=str(tmp_path / "nope"))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "trust_exec" in str(e)


def test_no_legacy_chat_in_adapters():
    for rel in ("scripts/dogfood/hermes_loop.py", "scripts/dogfood/harness2_loop.py"):
        src = open(os.path.join(ROOT, rel)).read()
        assert "/v1/chat/completions" not in src
        assert "<file path=" not in src
        assert "FILE_RE" not in src
