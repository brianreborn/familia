"""Offline unit tests for #119 task-suite gate (no live models)."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import task_suite_lib as T
import task_suite_promote as P
import task_suite_runner as R

FIX = ROOT / "tests" / "fixtures" / "task_suite"


@pytest.fixture
def suite():
    data, path = T.load_suite()
    assert path.exists()
    return data


def test_suite_loads_and_lists_multi_engine(suite):
    assert suite["suite_id"] == "familia-core-v1"
    me = T.multi_engine_tasks(suite)
    assert len(me) >= 4
    modes = {t.get("mode") for t in me}
    assert {"competing", "tandem", "specialized", "escalate"} <= modes
    plat_ids = {p["id"] for p in suite["platforms"]}
    assert "android-termux-a57" in plat_ids
    assert "note9" not in json.dumps(suite).lower()


def test_radical_triggers_include_multi_engine(suite):
    assert "multi_engine_same_role_topology" in T.radical_triggers(suite)
    assert T.is_radical(["quantization"], suite)
    assert not T.is_radical(["cosmetic-rename"], suite)


def test_score_expect_helpers():
    assert T.score_expect({"type": "exact", "value": "familia-ok"}, "familia-ok")[0]
    assert T.score_expect({"type": "contains", "value": "4"}, "answer 4")[0]
    assert T.score_expect({"type": "contains_all", "values": ["def ", "fizz"]}, "def fizzbuzz")[0]
    assert T.score_expect({"type": "json_keys", "keys": ["ok", "n"]}, '{"ok": true, "n": 1}')[0]
    assert T.score_expect({"type": "non_empty"}, "x")[0]
    assert T.score_expect({"type": "embedding_dim_positive"}, "", embedding=[0.1, 0.2])[0]
    assert not T.score_expect({"type": "exact", "value": "a"}, "b")[0]


def test_evaluate_aggregate_pass_and_fail(suite):
    good = [
        {"id": "route-light-ok", "passed": True, "route_taken": "light", "gold_route": "light"},
        {"id": "route-escalate-hard", "passed": True, "route_taken": "heavy", "gold_route": "heavy"},
        {"id": "coder-smoke-fizz", "passed": True},
        {"id": "coder-smoke-json", "passed": True},
        {"id": "chat-smoke-greeting", "passed": True},
    ]
    agg, gate = T.evaluate_aggregate(good, suite, baseline_pass_rate=0.8)
    assert gate["passed"] and agg["pass_rate"] == 1.0
    assert agg["escalation_precision"] == 1.0 and agg["escalation_recall"] == 1.0

    bad = [{"id": "coder-smoke-fizz", "passed": False} for _ in range(5)]
    agg, gate = T.evaluate_aggregate(bad, suite, baseline_pass_rate=1.0)
    assert not gate["passed"]
    assert any("pass_rate" in r for r in gate["reasons"])


def test_validate_record_pass_fixture(suite):
    rec = json.loads((FIX / "pass.json").read_text(encoding="utf-8"))
    assert T.validate_record(rec, suite) == []
    ok, reasons = T.gate_allows_promotion(rec, suite)
    assert ok, reasons


def test_validate_record_rejects_hash_only_and_failed_gate(suite):
    bad = json.loads((FIX / "hash_only_model.json").read_text(encoding="utf-8"))
    errs = T.validate_record(bad, suite)
    assert any("hash" in e for e in errs)
    fail = json.loads((FIX / "fail.json").read_text(encoding="utf-8"))
    ok, reasons = T.gate_allows_promotion(fail, suite)
    assert not ok
    assert reasons


def test_validate_record_rejects_embedded_ip(suite):
    rec = json.loads((FIX / "pass.json").read_text(encoding="utf-8"))
    rec["notes"] = "talked to " + ".".join(["192", "168", "1", "10"])
    errs = T.validate_record(rec, suite)
    assert any("IPv4" in e for e in errs)


def test_promotion_blocked_without_evidence(suite, tmp_path):
    d = T.promotion_blocked(
        node_id="coder", model_name="Qwen3.5-2B", role="coder",
        triggers=["quantization"], suite=suite, directory=tmp_path,
    )
    assert d["blocked"] is True
    assert d["evidence_path"] is None


def test_promotion_allowed_with_pass_evidence(suite, tmp_path):
    src = FIX / "pass.json"
    dest = tmp_path / "pass.json"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    d = T.promotion_blocked(
        node_id="coder", model_name="Qwen3.5-2B", role="coder",
        triggers=["quantization"], suite=suite, directory=tmp_path,
    )
    assert d["blocked"] is False, d
    assert d["evidence_path"] == str(dest)


def test_promotion_refuses_failed_evidence(suite, tmp_path):
    dest = tmp_path / "fail.json"
    dest.write_text((FIX / "fail.json").read_text(encoding="utf-8"), encoding="utf-8")
    d = T.promotion_blocked(
        node_id="coder", model_name="Qwen3.5-2B", role="coder",
        triggers=["quantization"], suite=suite, directory=tmp_path,
    )
    assert d["blocked"] is True


def test_promote_cli_check_record_pass(capsys):
    rc = P.main(["check-record", str(FIX / "pass.json")])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["blocked"] is False


def test_promote_cli_check_refuses_empty_dir(tmp_path, capsys):
    rc = P.main([
        "check", "--node-id", "coder", "--role", "coder",
        "--model-name", "Qwen3.5-2B", "--radical-trigger", "quantization",
        "--evidence-dir", str(tmp_path),
    ])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["blocked"] is True


def test_runner_dry_run(capsys):
    rc = R.main(["--dry-run", "--role", "coder", "--platform", "ubuntu"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "familia-core-v1" in out
    assert "multi_engine_tasks=" in out
    assert "dry-run OK" in out


def test_runner_rejects_unknown_platform():
    rc = R.main(["--dry-run", "--role", "coder", "--platform", "note9-only"])
    assert rc == 2


def test_tasks_for_role(suite):
    coder = T.tasks_for_role(suite, "coder")
    assert any(t["id"] == "coder-smoke-fizz" for t in coder)
    assert any(t["kind"] == "multi_engine" for t in coder)
    embed = T.tasks_for_role(suite, "embed")
    assert all("embed" in (t.get("roles") or []) for t in embed)
