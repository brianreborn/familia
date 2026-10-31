"""Offline tests for the BFCL v4 -> task-suite adapter (exact AST match, no judge)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bfcl_adapter as B
import task_suite_lib as T

FIX = ROOT / "tests" / "fixtures" / "bfcl"


def _first(v):
    if isinstance(v, dict):
        return {k: _first(x[0] if isinstance(x, list) else x) for k, x in v.items() if x not in ([""], "")}
    return v


def render(gt, style="python"):
    calls = []
    for c in gt:
        (name, args), = c.items()
        kw = {}
        for k, allowed in args.items():
            if allowed[0] == "":
                continue
            kw[k] = _first(allowed[0])
        calls.append((name, kw))
    if style == "json":
        return json.dumps([{"name": n, "arguments": a} for n, a in calls])
    return "[" + ", ".join(f"{n}(" + ", ".join(f"{k}={v!r}" for k, v in a.items()) + ")"
                           for n, a in calls) + "]"


@pytest.fixture(scope="module")
def cases():
    return B.load_cases()


@pytest.fixture(scope="module")
def suite(cases):
    return B.build_suite(cases)


def test_fixture_size_categories_and_license(cases):
    assert len(cases) == 200
    cats = {B._category(c) for c in cases}
    assert cats == set(B.NON_LIVE)
    assert "Apache License" in (FIX / "LICENSE.gorilla-apache-2.0").read_text()
    assert "Apache-2.0" in (FIX / "README.md").read_text()


def test_suite_shape_matches_task_suite_format(suite):
    assert suite["suite_id"] == "bfcl-v4-subset" and len(suite["tasks"]) == 200
    ids = [t["id"] for t in suite["tasks"]]
    assert len(set(ids)) == len(ids)
    for t in suite["tasks"]:
        assert t["roles"] and t["prompt"] and t["expect"]["type"] == "bfcl_ast"
        assert T.tasks_for_role(suite, "decision")


def test_suite_roundtrips_through_load_suite(suite, tmp_path):
    p = tmp_path / "bfcl.yaml"
    assert B.main(["--out", str(p)]) == 0
    data, _ = T.load_suite(p)
    assert data["suite_id"] == suite["suite_id"] and len(data["tasks"]) == 200


@pytest.mark.parametrize("style", ["python", "json"])
def test_gold_answers_score_100pct(cases, suite, style):
    fails = [c["id"] for c, t in zip(cases, suite["tasks"])
             if not T.score_expect(t["expect"], render(c["ground_truth"], style))[0]]
    assert fails == []


def test_wrong_answers_fail(cases, suite):
    c, t = cases[0], suite["tasks"][0]
    assert not T.score_expect(t["expect"], "")[0]
    assert not T.score_expect(t["expect"], "I think the area is 25.")[0]
    assert not T.score_expect(t["expect"], "[calculate_triangle_area(base=11, height=5)]")[0]
    assert not T.score_expect(t["expect"], "[calculate_triangle_area(base=10)]")[0]
    assert not T.score_expect(t["expect"], "[calculate_triangle_area(base=10, height=5, color='red')]")[0]
    assert not T.score_expect(t["expect"], "[other_fn(base=10, height=5)]")[0]
    assert T.score_expect(t["expect"], "```python\n[calculate_triangle_area(base=10, height=5)]\n```")[0]


def test_parallel_order_insensitive_and_count_strict(cases, suite):
    i = next(i for i, c in enumerate(cases) if B._category(c) == "parallel")
    gt, t = cases[i]["ground_truth"], suite["tasks"][i]
    assert T.score_expect(t["expect"], render(list(reversed(gt))))[0]
    assert not T.score_expect(t["expect"], render(gt[:1]))[0]
    assert not T.score_expect(t["expect"], render(gt + gt[:1]))[0]


def test_value_rules():
    assert B._value_ok(5, [5.0])            # int ok where float expected
    assert not B._value_ok(5.5, [5])        # float not ok where int expected
    assert not B._value_ok(True, [1])
    assert B._value_ok("San Francisco, CA", ["san francisco ca"])
    assert B._value_ok([1, 2], [[1, 2]]) and not B._value_ok([2, 1], [[1, 2]])


def test_live_categories_rejected():
    with pytest.raises(ValueError):
        B.case_to_task({"id": "live_simple_0", "question": [[]], "function": [], "ground_truth": []})


def test_cli_score(tmp_path, cases, capsys):
    out = tmp_path / "out.jsonl"
    rows = [{"id": c["id"], "output": render(c["ground_truth"])} for c in cases[:10]]
    rows.append({"id": cases[10]["id"], "output": "nope"})
    out.write_text("\n".join(json.dumps(r) for r in rows))
    assert B.main(["--score", str(out)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res == {"n": 11, "passed": 10, "accuracy": 10 / 11}
