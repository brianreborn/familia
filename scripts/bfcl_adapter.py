#!/usr/bin/env python3
"""BFCL v4 -> #167 task-suite adapter, plus an exact AST-match scorer.

No judge model, no network. Converts Berkeley Function Calling Leaderboard
(Apache-2.0, ShishirPatil/gorilla) non-live cases into task-suite tasks with
expect {type: bfcl_ast, ...}, which task_suite_lib.score_expect scores through
score_bfcl_ast() here.

Model output may be either BFCL prompt style, a Python list of calls such as
``[get_weather(city="Paris"), f(x=1)]``, or JSON
``[{"name": "f", "arguments": {...}}]`` / ``[{"f": {...}}]``.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "bfcl" / "bfcl_v4_subset.jsonl"
NON_LIVE = ("simple_python", "multiple", "parallel", "parallel_multiple")


# ---------------------------------------------------------------- parsing
def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _value(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return ast.unparse(node)  # e.g. a bare name; never evaluated


def _strip_fence(text):
    m = re.search(r"```(?:\w+)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


MAX_OUTPUT_BYTES = 64 * 1024


def parse_calls(output):
    """Return a list of {name: {arg: value}} or raise ValueError."""
    if isinstance(output, list):
        data = output
    else:
        raw = str(output or "")
        if len(raw.encode("utf-8", "surrogatepass")) > MAX_OUTPUT_BYTES:
            raise ValueError(f"output exceeds {MAX_OUTPUT_BYTES} bytes")
        text = _strip_fence(raw)
        if not text:
            raise ValueError("empty output")
        data = None
        if text[0] in "[{":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
        if data is None:
            if not text.startswith("["):
                text = f"[{text}]"
            try:
                tree = ast.parse(text, mode="eval")
            except (SyntaxError, RecursionError, MemoryError) as e:
                raise ValueError(f"unparseable: {type(e).__name__}") from None
            elts = tree.body.elts if isinstance(tree.body, (ast.List, ast.Tuple)) else [tree.body]
            calls = []
            for el in elts:
                if not isinstance(el, ast.Call) or el.args:
                    raise ValueError("expected keyword-only function calls")
                name = _dotted(el.func)
                if not name:
                    raise ValueError("bad function name")
                calls.append({name: {k.arg: _value(k.value) for k in el.keywords}})
            return calls
    if isinstance(data, dict):
        data = [data]
    calls = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("call is not an object")
        if "name" in item:
            args = item.get("arguments", item.get("parameters", {}))
            if isinstance(args, str):
                args = json.loads(args)
            calls.append({item["name"]: dict(args or {})})
        elif len(item) == 1:
            (name, args), = item.items()
            calls.append({name: dict(args or {})})
        else:
            raise ValueError("ambiguous call object")
    return calls


# ---------------------------------------------------------------- matching
def _norm_str(s):
    # BFCL's checker: case-insensitive, ignore whitespace and common punctuation.
    return re.sub(r"[ ,./\-_*^]", "", s).lower()


def _value_ok(got, allowed):
    for want in allowed:
        if want == "":
            continue
        if isinstance(want, bool) or isinstance(got, bool):
            if got is want:
                return True
            continue
        if isinstance(want, float) and isinstance(got, int):
            if float(got) == want:
                return True
            continue
        if isinstance(want, str) and isinstance(got, str):
            if _norm_str(got) == _norm_str(want):
                return True
            continue
        if isinstance(want, list) and isinstance(got, (list, tuple)):
            if len(want) == len(got) and all(_value_ok(g, [w]) for g, w in zip(got, want)):
                return True
            continue
        if isinstance(want, dict) and isinstance(got, dict):
            if set(got) <= set(want) and all(
                k in got or "" in (want[k] if isinstance(want[k], list) else [want[k]])
                for k in want
            ) and all(_value_ok(got[k], want[k] if isinstance(want[k], list) else [want[k]]) for k in got):
                return True
            continue
        if type(got) is type(want) and got == want:
            return True
    return False


def _call_ok(call, gold, funcs):
    (name, args), = call.items()
    (gname, gargs), = gold.items()
    if name != gname:
        return False, f"name {name!r} != {gname!r}"
    if name not in funcs and funcs:
        return False, f"{name!r} not among offered functions"
    for k in args:
        if k not in gargs:
            return False, f"{name}: unexpected arg {k!r}"
    for k, allowed in gargs.items():
        if k not in args:
            # BFCL's possible_answer marks omittable args with "" (it wins over schema "required").
            if "" in allowed:
                continue
            return False, f"{name}: missing arg {k!r}"
        if not _value_ok(args[k], allowed):
            return False, f"{name}: bad value for {k!r}: {args[k]!r}"
    return True, "ok"


def ast_match(calls, ground_truth, functions=()):
    """Exact AST match, order-insensitive across parallel calls."""
    funcs = {f["name"]: f for f in functions or []}
    if len(calls) != len(ground_truth):
        return False, f"call count {len(calls)} != {len(ground_truth)}"
    unused = list(range(len(ground_truth)))
    for call in calls:
        reason = "no matching gold call"
        for i in unused:
            ok, why = _call_ok(call, ground_truth[i], funcs)
            if ok:
                unused.remove(i)
                break
            reason = why
        else:
            return False, reason
    return True, "ast-match"


def score_bfcl_ast(expect, output):
    try:
        calls = parse_calls(output)
    except (ValueError, json.JSONDecodeError, RecursionError, MemoryError, TypeError) as e:
        return False, f"parse_error:{type(e).__name__}:{str(e)[:200]}"
    return ast_match(calls, expect.get("ground_truth") or [], expect.get("functions") or [])


# ---------------------------------------------------------------- conversion
def load_cases(path=DEFAULT_FIXTURE, answers=None):
    """Read merged fixture JSONL, or a raw BFCL question file plus possible_answer file."""
    cases = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    if answers:
        gt = {}
        for l in Path(answers).read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                gt[r["id"]] = r["ground_truth"]
        cases = [dict(c, ground_truth=gt[c["id"]]) for c in cases if c["id"] in gt]
    return cases


def _category(case):
    if case.get("category"):
        return case["category"]
    return re.sub(r"_\d+$", "", case["id"])


SYSTEM = (
    "You are a function-calling assistant. Reply ONLY with the call(s) in Python syntax, "
    "e.g. [func_a(x=1), func_b(y=\"s\")]. No prose."
)


def case_to_task(case):
    cat = _category(case)
    if cat.startswith("live") or cat.startswith("multi_turn"):
        raise ValueError(f"unsupported category {cat!r}: only non-live single-turn cases")
    turns = case["question"]
    messages = [m for turn in turns for m in turn]
    user = "\n".join(m["content"] for m in messages if m.get("role") == "user")
    tools = json.dumps(case["function"], ensure_ascii=False)
    return {
        "id": f"bfcl-{case['id'].replace('_', '-')}",
        "roles": ["decision", "general", "coder"],
        "kind": "tool_call",
        "prompt": f"{SYSTEM}\n\nAvailable functions (JSON schema):\n{tools}\n\nRequest: {user}",
        "messages": [{"role": "system", "content": SYSTEM}] + messages,
        "tools": case["function"],
        "expect": {"type": "bfcl_ast", "ground_truth": case["ground_truth"],
                   "functions": case["function"]},
        "tags": ["bfcl-v4", cat, "tool-call"],
        "source": {"benchmark": "BFCL v4", "case_id": case["id"], "license": "Apache-2.0"},
    }


def build_suite(cases, suite_id="bfcl-v4-subset", min_pass_rate=0.0):
    return {
        "schema": 1,
        "suite_id": suite_id,
        "revision": "1",
        "title": "BFCL v4 non-live tool-call subset (AST match)",
        "description": "Adapted from the Berkeley Function Calling Leaderboard v4 "
                       "(Apache-2.0). Scored by exact AST match; no judge model.",
        "platforms": [{"id": p, "class": c} for p, c in (
            ("ubuntu", "linux-desktop"), ("windows", "windows-desktop"),
            ("freebsd", "bsd-desktop"), ("android-termux-a57", "android-termux"))],
        "roles": ["decision", "general", "coder"],
        "radical_change_triggers": ["unusual_sampling_or_tool_configuration"],
        "aggregate_gate": {"min_pass_rate": min_pass_rate, "max_pass_rate_regression": 0.05},
        "tasks": [case_to_task(c) for c in cases],
        "seed_default": 167,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", default=str(DEFAULT_FIXTURE),
                    help="merged JSONL fixture, or a raw BFCL_v4_<cat>.json question file")
    ap.add_argument("--answers", help="raw BFCL possible_answer file (with a raw --cases file)")
    ap.add_argument("--suite-id", default="bfcl-v4-subset")
    ap.add_argument("--out", help="write suite YAML here (default stdout)")
    ap.add_argument("--score", help="JSONL of {id, output} to score against the cases")
    a = ap.parse_args(argv)
    cases = load_cases(a.cases, a.answers)
    suite = build_suite(cases, a.suite_id)
    if a.score:
        by_id = {t["id"]: t for t in suite["tasks"]}
        n = ok = 0
        for l in Path(a.score).read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            tid = r["id"] if r["id"] in by_id else f"bfcl-{r['id'].replace('_', '-')}"
            passed, _ = score_bfcl_ast(by_id[tid]["expect"], r["output"])
            n += 1
            ok += passed
        print(json.dumps({"n": n, "passed": ok, "accuracy": ok / n if n else 0.0}))
        return 0
    import yaml
    text = yaml.safe_dump(suite, sort_keys=False, allow_unicode=True)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
