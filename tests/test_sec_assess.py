"""Fixture-only tests for scripts/sec_assess.py (#116).

No live scans, sockets to targets, attack tools, or exploit reproduction.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sec_assess.py"
FIXTURE_GRAPH = ROOT / "tests" / "fixtures" / "sec-assess" / "inventory.yaml"
FIXTURE_POLICY = ROOT / "tests" / "fixtures" / "sec-assess" / "policy.json"
START_SH = ROOT / "start.sh"
START_GRAPH = ROOT / "scripts" / "start_graph.py"
RUN_TESTS = ROOT / "scripts" / "run-tests.sh"


@pytest.fixture
def assess_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    audit = tmp_path / "audit.jsonl"
    state.mkdir()
    monkeypatch.setenv("FAMILIA_SEC_ASSESS_STATE", str(state))
    monkeypatch.setenv("FAMILIA_SEC_ASSESS_AUDIT", str(audit))
    monkeypatch.delenv("FAMILIA_SEC_ASSESS_CONFIRM", raising=False)
    monkeypatch.delenv("FAMILIA_SEC_ASSESS_APPLY", raising=False)
    return {"state": state, "audit": audit}


def run_cli(args, env_extra=None, check=False):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=check,
    )


def auth_args(allowlist="fixture-alpha,fixture-beta", mode="low", window=30):
    return [
        "--i-authorize-assessment",
        "--allowlist",
        allowlist,
        "--mode",
        mode,
        f"--window-minutes={window}",
        "--graph",
        str(FIXTURE_GRAPH),
        "--policy",
        str(FIXTURE_POLICY),
    ]


def test_missing_confirm_refuses(assess_env):
    r = run_cli(["run", *auth_args()], env_extra={"FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
                                                    "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"])})
    assert r.returncode == 2
    assert "REFUSED" in r.stderr
    assert "FAMILIA_SEC_ASSESS_CONFIRM" in r.stderr


def test_missing_authorize_flag_refuses(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r = run_cli(
        [
            "run",
            "--allowlist",
            "fixture-alpha",
            "--mode",
            "low",
            "--window-minutes",
            "10",
            "--graph",
            str(FIXTURE_GRAPH),
        ],
        env_extra=env,
    )
    assert r.returncode == 2
    assert "--i-authorize-assessment" in r.stderr


def test_empty_allowlist_refuses(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r = run_cli(
        [
            "run",
            "--i-authorize-assessment",
            "--allowlist",
            "",
            "--mode",
            "low",
            "--window-minutes",
            "10",
            "--graph",
            str(FIXTURE_GRAPH),
        ],
        env_extra=env,
    )
    assert r.returncode == 2
    assert "allowlist" in r.stderr.lower()


def test_expired_window_refuses(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r = run_cli(
        [
            "run",
            "--i-authorize-assessment",
            "--allowlist",
            "fixture-alpha",
            "--mode",
            "low",
            "--until",
            "2000-01-01T00:00:00Z",
            "--graph",
            str(FIXTURE_GRAPH),
        ],
        env_extra=env,
    )
    assert r.returncode == 2
    assert "expired" in r.stderr.lower() or "window" in r.stderr.lower()


def test_detail_without_confirm_refuses(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    # No CONFIRM env — must abort, never fall back to low.
    r = run_cli(["run", *auth_args(mode="detail")], env_extra=env)
    assert r.returncode == 2
    assert "REFUSED" in r.stderr
    assert "FAMILIA_SEC_ASSESS_CONFIRM" in r.stderr


def test_low_mode_runs_on_fixtures_without_network(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r = run_cli(["run", *auth_args(mode="low")], env_extra=env)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["mode"] == "low"
    assert doc["status"] == "completed"
    assert doc.get("network") == "none"
    assert any(f.get("check") == "network_boundary" and f.get("result") == "no_sockets" for f in doc["findings"])
    assert any(f.get("check") == "inventory_measured" and f.get("host") == "fixture-alpha" for f in doc["findings"])
    assert assess_env["audit"].is_file()
    audit_lines = assess_env["audit"].read_text(encoding="utf-8").strip().splitlines()
    assert any('"run_start"' in line or '"event": "run_start"' in line for line in audit_lines)


def test_detail_mode_emits_plan_refuses_network(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r = run_cli(["run", *auth_args(mode="detail")], env_extra=env)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["mode"] == "detail"
    assert doc["status"] == "completed_plan_only"
    assert doc.get("network") == "refused"
    assert doc.get("plan", {}).get("status") == "refused_network"
    assert "autonomous exploitation" in " ".join(doc["plan"]["forbidden"])


def test_stop_works(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r_stop = run_cli(["stop"], env_extra=env)
    assert r_stop.returncode == 0
    assert (assess_env["state"] / "STOP").is_file()
    r_run = run_cli(["run", *auth_args()], env_extra=env)
    assert r_run.returncode == 2
    assert "STOP" in r_run.stderr
    r_stat = run_cli(["status"], env_extra=env)
    assert r_stat.returncode == 0
    status = json.loads(r_stat.stdout)
    assert status["stop_flag"] is True
    r_clear = run_cli(["status", "--clear-stop"], env_extra=env)
    assert json.loads(r_clear.stdout)["stop_flag"] is False


def test_remediation_propose_writes_plan_without_applying(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    assert run_cli(["run", *auth_args()], env_extra=env).returncode == 0
    r = run_cli(
        [
            "propose-remediation",
            "--i-authorize-assessment",
            "--allowlist",
            "fixture-alpha,fixture-beta",
            "--note",
            "review seatbelts offline",
        ],
        env_extra=env,
    )
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert plan["apply_status"] == "refused_until_approved"
    assert any(p.get("check") == "operator_note" for p in plan["proposals"])
    # Apply without token refuses
    r2 = run_cli(
        [
            "propose-remediation",
            "--i-authorize-assessment",
            "--allowlist",
            "fixture-alpha",
            "--apply",
        ],
        env_extra=env,
    )
    assert r2.returncode == 2
    assert "REFUSED" in r2.stderr
    # Apply with token still does not mutate (stub)
    env_ok = dict(env, FAMILIA_SEC_ASSESS_APPLY="I-APPROVE-REMEDIATION")
    r3 = run_cli(
        [
            "propose-remediation",
            "--i-authorize-assessment",
            "--allowlist",
            "fixture-alpha",
            "--apply",
        ],
        env_extra=env_ok,
    )
    assert r3.returncode == 0, r3.stderr
    plan3 = json.loads(r3.stdout)
    assert plan3["apply_status"] == "approved_but_apply_not_implemented"
    # Fixture graph unchanged
    assert "fixture-alpha" in FIXTURE_GRAPH.read_text(encoding="utf-8")


def test_start_sh_and_ci_do_not_call_sec_assess():
    """Import/grep guard: normal startup and CI never invoke assessment."""
    start_txt = START_SH.read_text(encoding="utf-8")
    assert "sec_assess" not in start_txt
    sg = START_GRAPH.read_text(encoding="utf-8")
    assert "sec_assess" not in sg
    rt = RUN_TESTS.read_text(encoding="utf-8")
    assert "sec_assess" not in rt
    # CI workflow(s)
    gh = ROOT / ".github"
    if gh.is_dir():
        for path in gh.rglob("*"):
            if path.is_file() and path.suffix in {".yml", ".yaml", ".sh"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                assert "sec_assess" not in text, path
    # Menu tables: CLI-only — no one-click assess item
    for name in ("menu-items.txt", "cli-commands.txt", "menu-internal.txt"):
        p = ROOT / "scripts" / name
        if p.is_file():
            assert "sec_assess" not in p.read_text(encoding="utf-8"), name


def test_seatbelts_untouched_by_module():
    """Dual-disable seatbelt stubs remain empty + launch_test_only."""
    for name in ("guardian-role.json", "pentest-role.json"):
        data = json.loads((ROOT / "scripts" / name).read_text(encoding="utf-8"))
        assert data.get("tools", {}).get("allow") == []
        assert data.get("launch_test_only") is True


def test_preflight_ok(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r = run_cli(["preflight", *auth_args()], env_extra=env)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["status"] == "preflight_ok"
    assert doc["network"] == "disabled"


def test_wildcard_allowlist_refuses(assess_env):
    env = {
        "FAMILIA_SEC_ASSESS_CONFIRM": "yes",
        "FAMILIA_SEC_ASSESS_STATE": str(assess_env["state"]),
        "FAMILIA_SEC_ASSESS_AUDIT": str(assess_env["audit"]),
    }
    r = run_cli(["run", *auth_args(allowlist="fixture-*")], env_extra=env)
    assert r.returncode == 2
    assert "wildcard" in r.stderr.lower()
