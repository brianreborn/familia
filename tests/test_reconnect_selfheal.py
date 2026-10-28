"""Unit/smoke tests for scripts/reconnect_selfheal.py (no live SSH / no models)."""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import reconnect_selfheal as rs  # noqa: E402
import offline_improve as oi  # noqa: E402


def test_backoff_matches_offline_improve_and_docs():
    assert rs.documented_backoff_schedule()[:6] == [30, 60, 120, 240, 480, 900]
    for fails in range(1, 12):
        assert rs.backoff_seconds(fails) == oi.backoff_seconds(fails, base=30, cap=900)
    # Cap documented
    assert rs.backoff_seconds(100) == 900


def test_backoff_jitter_never_exceeds_cap():
    class R:
        def uniform(self, a, b):
            return b  # max positive jitter

    for fails in range(1, 10):
        v = rs.backoff_with_jitter(fails, base=30, cap=900, jitter=0.5, rng=R())
        assert v <= 900


def test_decide_state_matrix():
    assert rs.decide_state(
        local_net_ok=False, fleet_any_up=False, health_ok_any=False,
        health_ok_all=False, health_configured=False,
    ) == rs.ProbeState.OFFLINE
    assert rs.decide_state(
        local_net_ok=True, fleet_any_up=False, health_ok_any=False,
        health_ok_all=False, health_configured=False,
    ) == rs.ProbeState.LOCAL_OK_FLEET_DOWN
    assert rs.decide_state(
        local_net_ok=True, fleet_any_up=False, health_ok_any=True,
        health_ok_all=False, health_configured=True,
    ) == rs.ProbeState.ONLINE_ISH
    assert rs.decide_state(
        local_net_ok=True, fleet_any_up=True, health_ok_any=True,
        health_ok_all=True, health_configured=True,
    ) == rs.ProbeState.HEALTHY
    assert rs.decide_state(
        local_net_ok=True, fleet_any_up=True, health_ok_any=False,
        health_ok_all=False, health_configured=True,
    ) == rs.ProbeState.ONLINE_ISH  # fleet up, health not green
    assert rs.decide_state(
        local_net_ok=True, fleet_any_up=True, health_ok_any=False,
        health_ok_all=False, health_configured=False,
    ) == rs.ProbeState.HEALTHY  # no health configured + fleet up


def test_probe_dns_ok_and_fail():
    def ok_res(host, _port):
        return [(0, 0, 0, "", ("1.1.1.1", 0))]

    r = rs.probe_dns("1.1.1.1", timeout=1, resolver=ok_res)
    assert r["ok"] is True
    assert r["kind"] == "dns"

    def bad_res(host, _port):
        raise OSError("Name or service not known")

    r2 = rs.probe_dns("no.such", timeout=1, resolver=bad_res)
    assert r2["ok"] is False
    assert "error" in r2


def test_probe_local_health_soft_fail():
    class Boom:
        def __call__(self, req, timeout=None):
            raise OSError("connection refused")

    rows = rs.probe_local_health(
        ["http://127.0.0.1:9/health"], timeout=0.5, opener=Boom()
    )
    assert len(rows) == 1
    assert rows[0]["ok"] is False


def test_probe_local_health_200():
    class Resp:
        status = 200

    class OK:
        def __call__(self, req, timeout=None):
            return Resp()

    rows = rs.probe_local_health(
        ["http://127.0.0.1:18100/health"], timeout=0.5, opener=OK()
    )
    assert rows[0]["ok"] is True
    assert rows[0]["status"] == 200


def test_health_urls_from_graph_filters_host():
    g = {
        "nodes": {
            "coder": {"host": "angel", "port": 18200, "bind": "127.0.0.1"},
            "other": {"host": "miryam", "port": 18100},
            "sshish": {"host": "angel", "port": 22},
        }
    }
    urls = rs.health_urls_from_env_and_graph(g, "angel")
    assert urls == ["http://127.0.0.1:18200/health"]


def test_run_probe_no_llm_compose_fleet(monkeypatch):
    """Probe must not call llama-bench / improve_cycle; fleet uses offline_improve."""
    called = {"bench": 0}

    def boom_bench(*a, **k):
        called["bench"] += 1
        raise AssertionError("llama-bench must not run on probe path")

    monkeypatch.setattr(oi, "run_llama_bench_bounded", boom_bench)
    monkeypatch.setattr(oi, "improve_cycle", boom_bench)

    def fake_fleet(peers, **kw):
        return True, [{"peer": peers[0], "ok": True, "rc": 0, "err": ""}]

    monkeypatch.setattr(oi, "fleet_reachable", fake_fleet)

    probe = rs.run_probe(
        host="angel",
        peers=["miryam"],
        health_urls=[],
        dns_resolver=lambda h, p: [(0, 0, 0, "", ("1.1.1.1", 0))],
        route_runner=lambda *a, **k: types.SimpleNamespace(
            returncode=0, stdout="default via 10.0.0.1\n", stderr=""
        ),
    )
    assert probe.state == rs.ProbeState.HEALTHY.value
    assert probe.fleet_any_up is True
    assert called["bench"] == 0


def test_run_probe_offline(monkeypatch):
    monkeypatch.setattr(
        oi, "fleet_reachable",
        lambda peers, **kw: (False, [{"peer": "miryam", "ok": False, "rc": 255, "err": "down"}]),
    )
    probe = rs.run_probe(
        host="angel",
        peers=["miryam"],
        health_urls=[],
        dns_resolver=lambda h, p: (_ for _ in ()).throw(OSError("fail")),
        route_runner=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert probe.state == rs.ProbeState.OFFLINE.value


def test_repair_refuses_without_screen_attached(monkeypatch):
    monkeypatch.setenv("DETACH_MODE", "nohup")
    monkeypatch.delenv("FAMILIA_DETACH_MODE", raising=False)
    r = rs.repair_restart_screen_attached(dry_run=False)
    assert r.ok is False
    assert "refused" in r.detail
    assert "screen-attached" in r.reason


def test_repair_dry_run_when_screen_attached(monkeypatch):
    monkeypatch.setenv("DETACH_MODE", "screen-attached")
    r = rs.repair_restart_screen_attached(dry_run=True)
    assert r.ok is True
    assert r.dry_run is True
    assert "would_run" in r.detail


def test_repair_live_needs_allow_start(monkeypatch):
    monkeypatch.setenv("DETACH_MODE", "screen-attached")
    monkeypatch.delenv("FAMILIA_RECONNECT_ALLOW_START", raising=False)
    r = rs.repair_restart_screen_attached(dry_run=False)
    assert r.ok is False
    assert r.detail == "seatbelt"
    assert "FAMILIA_RECONNECT_ALLOW_START" in r.reason


def test_hook_stub_and_dry_run(monkeypatch):
    monkeypatch.delenv("FAMILIA_RECONNECT_HOOK", raising=False)
    r = rs.repair_reapply_hook(dry_run=True)
    assert r.ok is True
    assert r.detail == "noop"

    monkeypatch.setenv("FAMILIA_RECONNECT_HOOK", "echo rejoin")
    r2 = rs.repair_reapply_hook(dry_run=True)
    assert r2.dry_run is True
    assert r2.reason == "echo rejoin"


def test_git_fetch_not_blocked_by_local_edits(monkeypatch, tmp_path):
    """familia #181 U10: a local edit never blocks the fetch (fetch does not touch the tree)."""
    monkeypatch.setenv("FAMILIA_RECONNECT_PULL", "1")

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        if "status" in cmd:
            assert "--ignore-submodules=all" in cmd
            return types.SimpleNamespace(returncode=0, stdout=" M dirty.txt\n", stderr="")
        raise AssertionError(f"unexpected cmd {cmd}")

    r = rs.repair_git_fetch_tip(dry_run=True, repo=tmp_path, runner=fake_run)
    assert r.ok is True
    assert r.detail == "would_run"


def test_git_fetch_skipped_without_env(monkeypatch):
    monkeypatch.delenv("FAMILIA_RECONNECT_PULL", raising=False)
    r = rs.repair_git_fetch_tip(dry_run=True)
    assert r.ok is True
    assert r.detail == "skipped"


def test_list_repair_actions_stable():
    acts = rs.list_repair_actions()
    assert acts == [
        "check_screen",
        "restart_screen_attached",
        "reapply_hook",
        "git_fetch_tip",
    ]


def test_persist_probe(tmp_path):
    pr = rs.ProbeResult(
        state="offline",
        host="angel",
        when="2026-10-27T12:00:00-07:00",
        fleet_any_up=False,
    )
    path = rs.persist_probe(pr, tmp_path)
    assert path.is_file()
    latest = json.loads((tmp_path / "angel" / "latest.json").read_text(encoding="utf-8"))
    assert latest["state"] == "offline"


def test_main_probe_only_online(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        rs, "run_probe",
        lambda **kw: rs.ProbeResult(
            state=rs.ProbeState.HEALTHY.value,
            host="angel",
            when="t",
            fleet_any_up=True,
        ),
    )
    monkeypatch.setattr(rs, "persist_probe", lambda result, state_dir=None: tmp_path / "p.json")
    monkeypatch.setattr(oi, "_load_graph", lambda path: {"hosts": {"angel": {}, "miryam": {}}, "nodes": {}})
    rc = rs.main(["--probe-only", "--host", "angel", "--peers", "miryam", "--state-dir", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["probe"]["state"] == "healthy"


def test_main_show_backoff(capsys):
    rc = rs.main(["--show-backoff"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schedule_seconds"][0] == 30
    assert data["schedule_seconds"][5] == 900


def test_main_repair_refuses_non_screen(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DETACH_MODE", "foreground")
    monkeypatch.delenv("FAMILIA_DETACH_MODE", raising=False)
    monkeypatch.setattr(
        rs, "run_probe",
        lambda **kw: rs.ProbeResult(
            state=rs.ProbeState.LOCAL_OK_FLEET_DOWN.value,
            host="angel",
            when="t",
            fleet_any_up=False,
            local_net={"ok": True},
        ),
    )
    monkeypatch.setattr(rs, "persist_probe", lambda result, state_dir=None: tmp_path / "p.json")
    monkeypatch.setattr(oi, "_load_graph", lambda path: {"hosts": {"angel": {}, "miryam": {}}, "nodes": {}})
    # Avoid real screen -ls
    monkeypatch.setattr(
        rs, "check_screen_sessions",
        lambda **kw: rs.RepairResult("check_screen", True, False, detail="mocked"),
    )
    rc = rs.main([
        "--once", "--repair", "--host", "angel", "--peers", "miryam",
        "--state-dir", str(tmp_path),
    ])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    restart = next(r for r in out["repairs"] if r["action"] == "restart_screen_attached")
    assert restart["ok"] is False
    assert "screen-attached" in restart["reason"]


def test_screen_attached_ok_helper(monkeypatch):
    monkeypatch.setenv("DETACH_MODE", "screen-attached")
    assert rs.screen_attached_ok() is True
    monkeypatch.setenv("FAMILIA_DETACH_MODE", "tmux")
    assert rs.screen_attached_ok() is False
