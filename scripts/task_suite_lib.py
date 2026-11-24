#!/usr/bin/env python3
"""Task-suite acceptance library for #119 (promote gate + record validation).

No network I/O here. Runner uses this for scoring/gates; CI tests import it offline.
Never store addresses, logins, ports, or keys in records.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE = ROOT / "docs" / "testing" / "suites" / "familia-core-v1.yaml"
DEFAULT_SCHEMA = ROOT / "docs" / "testing" / "suites" / "result-record.schema.json"
EVIDENCE_ENV = "FAMILIA_TASK_SUITE_EVIDENCE_DIR"


def evidence_dir(override=None):
    path = override or os.environ.get(EVIDENCE_ENV)
    if path:
        return Path(path).expanduser()
    if os.name == "nt":
        state = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state).expanduser() / "familia" / "task-suite-evidence"


def load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_suite(path=None):
    p = Path(path) if path else DEFAULT_SUITE
    data = load_yaml(p)
    if not isinstance(data, dict) or data.get("suite_id") is None:
        raise ValueError(f"suite missing suite_id: {p}")
    if not data.get("tasks"):
        raise ValueError(f"suite has no tasks: {p}")
    return data, p


def tasks_for_role(suite, role):
    role = (role or "").strip()
    out = []
    for t in suite.get("tasks") or []:
        roles = t.get("roles") or []
        if role in roles or not roles:
            out.append(t)
    return out


def radical_triggers(suite):
    return list(suite.get("radical_change_triggers") or [])


def is_radical(triggers, suite=None):
    allowed = set(radical_triggers(suite) if suite else [])
    if not triggers:
        return False
    if allowed:
        return any(t in allowed for t in triggers)
    return bool(triggers)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "content" in value:
        return _text(value["content"])
    if isinstance(value, list):
        return "".join(_text(x) for x in value)
    return str(value)


def score_expect(expect, output, embedding=None):
    """Return (passed: bool, detail: str)."""
    if not expect:
        return True, "no-expect"
    kind = expect.get("type")
    text = _text(output).strip()
    if kind == "exact":
        ok = text == str(expect.get("value", ""))
        return ok, "exact"
    if kind == "contains":
        ok = str(expect.get("value", "")) in text
        return ok, "contains"
    if kind == "contains_all":
        vals = list(expect.get("values") or [])
        missing = [v for v in vals if v not in text]
        return (not missing), ("contains_all" if not missing else f"missing:{missing}")
    if kind == "json_keys":
        try:
            # Allow fenced or leading junk: take first {...}
            m = re.search(r"\{.*\}", text, re.S)
            obj = json.loads(m.group(0) if m else text)
            keys = list(expect.get("keys") or [])
            ok = isinstance(obj, dict) and all(k in obj for k in keys)
            return ok, "json_keys"
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            return False, f"json_error:{e}"
    if kind == "non_empty":
        return bool(text), "non_empty"
    if kind == "embedding_dim_positive":
        if embedding is None:
            return False, "no-embedding"
        try:
            n = len(embedding)
        except TypeError:
            return False, "bad-embedding"
        return n > 0, f"dim={n}"
    return False, f"unknown-expect:{kind}"


def escalation_prf(task_results, suite_tasks_by_id):
    """Precision/recall for tasks that declare gold_route light/heavy."""
    tp = fp = fn = 0
    for r in task_results:
        meta = suite_tasks_by_id.get(r.get("id")) or {}
        gold = r.get("gold_route") or meta.get("gold_route")
        if gold not in ("light", "heavy"):
            continue
        taken = r.get("route_taken")
        if taken is None:
            continue
        want_heavy = gold == "heavy"
        got_heavy = taken == "heavy"
        if want_heavy and got_heavy:
            tp += 1
        elif (not want_heavy) and got_heavy:
            fp += 1
        elif want_heavy and (not got_heavy):
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return precision, recall


def evaluate_aggregate(task_results, suite, baseline_pass_rate=None):
    n = len(task_results)
    n_passed = sum(1 for r in task_results if r.get("passed"))
    pass_rate = (n_passed / n) if n else 0.0
    by_id = {t["id"]: t for t in (suite.get("tasks") or [])}
    precision, recall = escalation_prf(task_results, by_id)
    gate_cfg = suite.get("aggregate_gate") or {}
    reasons = []
    ok = True
    min_pr = float(gate_cfg.get("min_pass_rate", 0.8))
    if pass_rate + 1e-12 < min_pr:
        ok = False
        reasons.append(f"pass_rate {pass_rate:.3f} < min_pass_rate {min_pr}")
    if baseline_pass_rate is not None:
        max_reg = float(gate_cfg.get("max_pass_rate_regression", 0.05))
        if baseline_pass_rate - pass_rate > max_reg + 1e-12:
            ok = False
            reasons.append(
                f"pass_rate regression {baseline_pass_rate - pass_rate:.3f} "
                f"> max {max_reg} (baseline {baseline_pass_rate:.3f})"
            )
    min_p = gate_cfg.get("min_escalation_precision")
    min_r = gate_cfg.get("min_escalation_recall")
    if precision is not None and min_p is not None and precision + 1e-12 < float(min_p):
        ok = False
        reasons.append(f"escalation_precision {precision:.3f} < {min_p}")
    if recall is not None and min_r is not None and recall + 1e-12 < float(min_r):
        ok = False
        reasons.append(f"escalation_recall {recall:.3f} < {min_r}")
    if ok and not reasons:
        reasons.append("aggregate thresholds met")
    aggregate = {
        "n_tasks": n,
        "n_passed": n_passed,
        "pass_rate": pass_rate,
        "escalation_precision": precision,
        "escalation_recall": recall,
        "baseline_pass_rate": baseline_pass_rate,
    }
    return aggregate, {"passed": ok, "reasons": reasons}


def required_record_fields():
    return [
        "schema", "suite_id", "suite_revision", "seed", "platform_class",
        "candidate", "baseline_id", "harness", "tasks", "aggregate", "gate",
        "recorded_at",
    ]


def validate_record(record, suite=None):
    """Structural validation (no external jsonschema dependency required)."""
    errs = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    for k in required_record_fields():
        if k not in record:
            errs.append(f"missing field {k}")
    if record.get("schema") != 1:
        errs.append("schema must be 1")
    cand = record.get("candidate") or {}
    for k in ("model_name", "model_version", "role", "runtime_name", "runtime_commit", "status_before"):
        if not cand.get(k):
            errs.append(f"candidate.{k} required")
    # Reject hash-only model labels
    name = str(cand.get("model_name") or "")
    if name and re.fullmatch(r"[0-9a-fA-F]{7,64}", name):
        errs.append("candidate.model_name must be a name, not a bare hash")
    tasks = record.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errs.append("tasks must be a non-empty list")
    else:
        for i, t in enumerate(tasks):
            if not isinstance(t, dict) or "id" not in t or "passed" not in t:
                errs.append(f"tasks[{i}] needs id and passed")
    agg = record.get("aggregate") or {}
    for k in ("n_tasks", "n_passed", "pass_rate"):
        if k not in agg:
            errs.append(f"aggregate.{k} required")
    gate = record.get("gate") or {}
    if "passed" not in gate or "reasons" not in gate:
        errs.append("gate.passed and gate.reasons required")
    if suite is not None:
        if record.get("suite_id") != suite.get("suite_id"):
            errs.append("suite_id mismatch")
        plats = {p.get("id") for p in (suite.get("platforms") or [])}
        if plats and record.get("platform_class") not in plats:
            errs.append(f"platform_class {record.get('platform_class')!r} not in suite platforms")
    # Privacy: refuse records that look like they embed endpoints
    blob = json.dumps(record, ensure_ascii=True)
    if re.search(r"(?i)\b\d{1,3}(?:\.\d{1,3}){3}\b", blob):
        errs.append("record must not contain IPv4 addresses")
    if re.search(r"(?i)(api[_-]?key|secret|password)\s*[:=]", blob):
        errs.append("record must not contain credential-looking fields")
    return errs


def gate_allows_promotion(record, suite=None, require_gate_pass=True):
    """Return (ok, reasons)."""
    errs = validate_record(record, suite)
    if errs:
        return False, errs
    if require_gate_pass and not (record.get("gate") or {}).get("passed"):
        return False, list((record.get("gate") or {}).get("reasons") or ["gate.passed is false"])
    status = (record.get("candidate") or {}).get("status_before")
    if status == "active":
        return False, ["candidate already active; gate is for planned/experimental promotion"]
    return True, ["evidence sufficient for promotion"]


def find_evidence(node_id=None, model_name=None, role=None, directory=None):
    """Load JSON evidence files; filter by node/model/role when given."""
    d = evidence_dir(directory)
    if not d.is_dir():
        return []
    found = []
    for path in sorted(d.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cand = rec.get("candidate") or {}
        if node_id and cand.get("node_id") != node_id:
            continue
        if model_name and cand.get("model_name") != model_name:
            continue
        if role and cand.get("role") != role:
            continue
        found.append((path, rec))
    return found


def promotion_blocked(node_id=None, model_name=None, role=None, triggers=None,
                      suite=None, directory=None, force_radical=False):
    """Decide whether promoting to active/default must be refused.

    Returns dict: blocked (bool), reasons (list), evidence_path (str|None)
    """
    suite = suite or load_suite()[0]
    triggers = list(triggers or [])
    needs = force_radical or is_radical(triggers, suite) or bool(triggers) or True
    # Always require evidence for active/default per #119 hard requirement.
    if not needs:
        return {"blocked": False, "reasons": ["no radical triggers"], "evidence_path": None}
    matches = find_evidence(node_id=node_id, model_name=model_name, role=role, directory=directory)
    if not matches:
        return {
            "blocked": True,
            "reasons": [
                "no task-suite evidence record found; run scripts/task_suite_runner.py "
                "and keep the JSON under FAMILIA_TASK_SUITE_EVIDENCE_DIR"
            ],
            "evidence_path": None,
        }
    # Prefer a passing gate record
    for path, rec in reversed(matches):
        ok, reasons = gate_allows_promotion(rec, suite=suite)
        if ok:
            return {"blocked": False, "reasons": reasons, "evidence_path": str(path)}
    path, rec = matches[-1]
    ok, reasons = gate_allows_promotion(rec, suite=suite)
    return {"blocked": True, "reasons": reasons, "evidence_path": str(path)}


def multi_engine_tasks(suite):
    return [t for t in (suite.get("tasks") or []) if "issue-150" in (t.get("tags") or [])
            or t.get("kind") == "multi_engine"]
