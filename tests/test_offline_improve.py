"""Control-flow tests for scripts/offline_improve.py (no live SSH / llama-bench)."""
import json
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import offline_improve as oi  # noqa: E402


def test_backoff_grows_then_caps():
    assert oi.backoff_seconds(1, base=30, cap=900) == 30
    assert oi.backoff_seconds(2, base=30, cap=900) == 60
    assert oi.backoff_seconds(3, base=30, cap=900) == 120
    assert oi.backoff_seconds(10, base=30, cap=900) == 900


def test_peer_hosts_excludes_self():
    g = {"hosts": {"angel": {}, "miryam": {}, "box": {}}}
    assert oi.peer_hosts(g, "angel") == ["miryam", "box"] or set(oi.peer_hosts(g, "angel")) == {"miryam", "box"}


def test_fleet_reachable_any_peer(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        calls.append(cmd)
        peer = cmd[-2]
        ok = peer == "miryam"
        return types.SimpleNamespace(
            returncode=0 if ok else 255,
            stdout="familia-fleet-ok\n" if ok else "",
            stderr="" if ok else "Connection refused",
        )

    up, rows = oi.fleet_reachable(["qodesh", "miryam"], runner=fake_run, timeout=1)
    assert up is True
    assert any(r["peer"] == "miryam" and r["ok"] for r in rows)
    assert any(r["peer"] == "qodesh" and not r["ok"] for r in rows)


def test_persist_and_pending(tmp_path):
    result = {
        "host": "angel",
        "when": "2026-10-27T12:00:00-07:00",
        "steps": [
            {"kind": "host_ram", "GBps": 12.5},
            {"kind": "llama-bench", "best_avg_ts": 42.0},
        ],
    }
    path = oi.persist(result, tmp_path)
    assert path.is_file()
    pending = oi.load_pending_summary("angel", tmp_path)
    assert pending["steps"][1]["best_avg_ts"] == 42.0
    hist = (tmp_path / "angel" / "history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(hist) == 1
    assert json.loads(hist[0])["best_avg_ts"] == 42.0


def test_improve_cycle_host_ram_only(monkeypatch):
    monkeypatch.setattr(oi, "_find_llama_bench", lambda: None)
    monkeypatch.setattr(oi, "_find_small_gguf", lambda: None)
    r = oi.improve_cycle(host="angel", allow_bench=True)
    assert r["host"] == "angel"
    assert r["steps"][0]["kind"] == "host_ram"
    assert r["steps"][0]["GBps"] is not None
    assert r["steps"][1].get("skipped") == "no llama-bench"


def test_main_offline_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(oi, "improve_cycle", lambda **kw: {
        "host": kw["host"], "when": "t", "steps": [{"kind": "host_ram", "GBps": 1.0}],
    })
    monkeypatch.setattr(oi, "persist", lambda result, state_dir=None: tmp_path / "x.json")
    rc = oi.main(["--offline", "--once", "--host", "angel", "--state-dir", str(tmp_path), "--no-bench"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "improve_cycle" in out


def test_main_check_only_online(monkeypatch, capsys):
    monkeypatch.setattr(oi, "fleet_reachable", lambda peers, **kw: (True, [{"peer": "miryam", "ok": True, "rc": 0, "err": ""}]))
    monkeypatch.setattr(oi, "_load_graph", lambda path: {"hosts": {"angel": {}, "miryam": {}}})
    rc = oi.main(["--check-only", "--host", "angel", "--peers", "miryam"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["online"] is True


def test_private_topology_keeps_pentest_ops_agent():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import familia_yaml
    import node_role as nr
    g = familia_yaml.loads(open(os.path.join(ROOT, "graph.yaml"), encoding="utf-8").read())
    priv = nr.private_topology(g, "angel")
    assert "pentest-ops" in priv["agents"]
    assert priv["pentests"]["angel"]["agent"] == "pentest-ops"
    assert priv["agents"]["pentest-ops"]["aliases"]["main"] == "guardian"
