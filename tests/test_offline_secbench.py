"""#117: opt-in offline security-model benches (gating, fixtures, report only)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "offline_secbench")
ANS = os.path.join(FIX, "answers")
SCRIPT = os.path.join(ROOT, "scripts", "offline_secbench.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import offline_secbench as osb  # noqa: E402


def _run(args, env=None, check=False):
    e = os.environ.copy()
    e.pop("FAMILIA_OFFLINE_SECBENCH", None)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=check,
        env=e,
        cwd=ROOT,
    )


def test_refuses_without_opt_in():
    r = _run(["--fixtures", FIX, "--platform", "linux"])
    assert r.returncode == 2
    assert "opt-in required" in r.stderr.lower() or "refused" in r.stderr.lower()
    assert r.stdout.strip() == ""


def test_env_opt_in_works():
    r = _run(
        ["--fixtures", FIX, "--platform", "linux", "--answers-dir", ANS, "--json"],
        env={"FAMILIA_OFFLINE_SECBENCH": "1"},
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["enabled"] is True
    assert data["schema_version"] == 1
    assert data["platform"] == "linux"
    assert "host_facts" in data
    assert "hostname" in data["host_facts"]
    assert data["summary"]["n_cases"] >= 4


def test_cli_enable_flag():
    r = _run(["--enable", "--list", "--fixtures", FIX, "--platform", "linux", "--json"])
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["enabled"] is True
    assert "secrets-in-config" in data["ids"]
    assert "linux-sudoers-misconfig" in data["ids"]


def test_loads_fixtures_and_manifest():
    entries = osb.load_manifest(FIX)
    assert len(entries) >= 5
    ids = [osb.load_case(FIX, e)["id"] for e in entries]
    assert "secrets-in-config" in ids
    assert "insecure-default" in ids
    assert "false-positive-control" in ids
    assert "remediation-quality" in ids
    assert "linux-sudoers-misconfig" in ids


def test_platform_filter_excludes_linux_only_on_windows():
    entries = osb.load_manifest(FIX)
    win_ids = []
    for e in entries:
        case = osb.load_case(FIX, e)
        if osb.case_matches_platform(case, "windows"):
            win_ids.append(case["id"])
    assert "secrets-in-config" in win_ids
    assert "linux-sudoers-misconfig" not in win_ids


def test_scores_canned_answers_benefit_true():
    report = osb.run_bench(
        fixtures_dir=FIX,
        platform_name="linux",
        answers_dir=ANS,
    )
    assert report["enabled"] is True
    assert report["baseline_meta"]["present"] is True
    assert report["candidate_meta"]["present"] is True
    assert report["baseline_meta"]["model"] == "baseline-generic"
    assert report["candidate_meta"]["model"] == "candidate-sec-specialized"
    assert report["summary"]["baseline_mean"] is not None
    assert report["summary"]["candidate_mean"] is not None
    assert report["summary"]["candidate_mean"] > report["summary"]["baseline_mean"]
    assert report["summary"]["benefit"] is True
    assert "exceeds baseline" in report["summary"]["reason"]


def test_benefit_false_when_candidate_worse():
    """Inline weak candidate vs strong baseline → benefit False."""
    case = osb.load_case(FIX, {"file": "secrets_in_config.json"})
    strong = (
        "hardcoded password and secret in config. "
        "Use an environment variable or secret manager and rotate."
    )
    weak = "Looks fine to me."
    sb = osb.score_answer(case, strong)["score"]
    sc = osb.score_answer(case, weak)["score"]
    assert sb > sc
    decision = osb.decide_benefit(sb, sc)
    assert decision["benefit"] is False


def test_benefit_inconclusive_when_close():
    d = osb.decide_benefit(0.80, 0.82)
    assert d["benefit"] == "inconclusive"


def test_false_positive_control_penalizes_flagging():
    case = osb.load_case(FIX, {"file": "false_positive_control.json"})
    bad = "This is a hardcoded api key / exposed secret / credential leak."
    good = "Documentation placeholder only; no secret finding."
    assert osb.score_answer(case, bad)["score"] < osb.score_answer(case, good)["score"]


def test_report_format_fields():
    report = osb.run_bench(FIX, "linux", answers_dir=ANS)
    for key in (
        "schema_version",
        "enabled",
        "platform",
        "host_facts",
        "baseline_meta",
        "candidate_meta",
        "cases",
        "summary",
    ):
        assert key in report
    assert report["cases"]
    row = report["cases"][0]
    for key in ("id", "score_baseline", "score_candidate", "delta", "notes"):
        assert key in row
    s = report["summary"]
    for key in ("baseline_mean", "candidate_mean", "benefit", "reason"):
        assert key in s


def test_no_urllib_in_module_source():
    """Happy path must not import or call network helpers."""
    src = open(SCRIPT, encoding="utf-8").read()
    assert "urllib" not in src
    assert "requests" not in src
    assert "http.client" not in src
    assert "subprocess" not in src  # no llama launch


def test_out_writes_only_named_path(tmp_path):
    out = tmp_path / "report.json"
    r = _run(
        [
            "--enable",
            "--fixtures",
            FIX,
            "--platform",
            "linux",
            "--answers-dir",
            ANS,
            "--json",
            "--out",
            str(out),
        ]
    )
    assert r.returncode == 0, r.stderr
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["enabled"] is True
