#!/usr/bin/env python3
"""Offline RouterBench scorer: cost and quality of a routing policy from cached responses.

RouterBench (withmartian/routerbench) ships each prompt with every model's cached
response, a correctness/performance score and the cost of that call. Scoring a
router therefore needs no model and no network: pick one model per prompt, then
look up that model's cached score and cost.

No RouterBench data is committed to this repo (the dataset has no license on its
card). Point the loader at a local copy with --data PATH or ROUTERBENCH_DATA.

Supported layouts (the RouterBench "wide" table, one row per prompt):
  columns sample_id, eval_name, [prompt], and per model M: M (score),
  "M|total_cost", optional "M|model_response".
Formats: .jsonl / .json / .csv (stdlib), .parquet and .pkl (need pandas;
.pkl is a pickle, so only load a copy you downloaded yourself from the HF repo).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path

DATA_ENV = "ROUTERBENCH_DATA"
COST_SUFFIX = "|total_cost"
RESP_SUFFIX = "|model_response"
META_COLS = {"sample_id", "eval_name", "prompt", "oracle_model_to_route_to"}


def resolve_path(path=None):
    p = path or os.environ.get(DATA_ENV)
    if not p:
        raise SystemExit(f"RouterBench data path required: --data PATH or {DATA_ENV}=PATH")
    p = Path(p).expanduser()
    if not p.exists():
        raise SystemExit(f"RouterBench data not found: {p}")
    return p


def _num(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN -> None


def _read_rows(p):
    suf = p.suffix.lower()
    if suf == ".jsonl":
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if suf == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data["rows"]
    if suf == ".csv":
        with open(p, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    if suf in (".pkl", ".pickle", ".parquet"):
        import pandas as pd
        df = pd.read_parquet(p) if suf == ".parquet" else pd.read_pickle(p)
        return df.to_dict(orient="records")
    raise SystemExit(f"unsupported RouterBench file type: {p.suffix}")


def models_in(rows):
    cols = set()
    for r in rows[:50]:
        cols |= set(r)
    return sorted(c[: -len(COST_SUFFIX)] for c in cols
                  if c.endswith(COST_SUFFIX) and c[: -len(COST_SUFFIX)] in cols)


def load(path=None, evals=None, models=None, limit=None):
    """Return (records, models). Each record: {sample_id, eval_name, scores{m}, costs{m}}."""
    rows = _read_rows(resolve_path(path))
    all_models = models_in(rows)
    if models:
        unknown = set(models) - set(all_models)
        if unknown:
            raise SystemExit(f"unknown models: {sorted(unknown)}; have {all_models}")
        all_models = [m for m in all_models if m in set(models)]
    if not all_models:
        raise SystemExit("no model columns found (expected 'M' and 'M|total_cost')")
    recs = []
    for i, r in enumerate(rows):
        ev = r.get("eval_name") or ""
        if evals and not any(ev == e or ev.startswith(e) for e in evals):
            continue
        scores, costs = {}, {}
        for m in all_models:
            s, c = _num(r.get(m)), _num(r.get(m + COST_SUFFIX))
            if s is not None and c is not None:
                scores[m], costs[m] = s, c
        if not scores:
            continue
        recs.append({"sample_id": str(r.get("sample_id", i)), "eval_name": ev,
                     "prompt": r.get("prompt"), "scores": scores, "costs": costs})
        if limit and len(recs) >= limit:
            break
    return recs, all_models


# ------------------------------------------------------------------ policies
def oracle_choice(rec):
    """Best score; ties broken by lowest cost (RouterBench's oracle)."""
    return min(rec["scores"], key=lambda m: (-rec["scores"][m], rec["costs"][m], m))


def evaluate(records, choose):
    """choose(rec) -> model name. Returns quality/cost summary plus per-eval breakdown."""
    n = 0
    q = c = 0.0
    picks = {}
    by_eval = {}
    missing = 0
    for rec in records:
        m = choose(rec)
        if m not in rec["scores"]:
            missing += 1
            continue
        n += 1
        q += rec["scores"][m]
        c += rec["costs"][m]
        picks[m] = picks.get(m, 0) + 1
        e = by_eval.setdefault(rec["eval_name"], [0, 0.0, 0.0])
        e[0] += 1
        e[1] += rec["scores"][m]
        e[2] += rec["costs"][m]
    return {
        "n": n,
        "skipped_no_cached_response": missing,
        "quality": q / n if n else 0.0,
        "total_cost": c,
        "cost_per_query": c / n if n else 0.0,
        "picks": dict(sorted(picks.items())),
        "by_eval": {k: {"n": v[0], "quality": v[1] / v[0], "total_cost": v[2]}
                    for k, v in sorted(by_eval.items())},
    }


def single_model_table(records, models):
    return {m: evaluate(records, lambda r, m=m: m) for m in models}


def best_single(table):
    """Highest quality; ties -> cheaper."""
    return min(table, key=lambda m: (-table[m]["quality"], table[m]["total_cost"], m))


def make_policy(spec, models, seed=0):
    """Policy spec: oracle | single:MODEL | random | routes:FILE.jsonl ({sample_id, model})."""
    if spec == "oracle":
        return oracle_choice
    if spec.startswith("single:"):
        m = spec.split(":", 1)[1]
        if m not in models:
            raise SystemExit(f"unknown model {m!r}")
        return lambda r: m
    if spec == "random":
        rng = random.Random(seed)
        return lambda r: rng.choice(sorted(r["scores"]))
    if spec.startswith("routes:"):
        routes = {}
        for l in Path(spec.split(":", 1)[1]).read_text(encoding="utf-8").splitlines():
            if l.strip():
                o = json.loads(l)
                routes[str(o["sample_id"])] = o["model"]
        return lambda r: routes.get(r["sample_id"])
    raise SystemExit(f"unknown policy {spec!r}")


def report(records, models, policy_spec, seed=0):
    table = single_model_table(records, models)
    best = best_single(table)
    pol = evaluate(records, make_policy(policy_spec, models, seed))
    orc = evaluate(records, oracle_choice)
    bs = table[best]

    def rel(x, base):
        return x / base if base else None

    return {
        "n_prompts": len(records),
        "models": models,
        "policy": {"spec": policy_spec, **pol},
        "oracle": orc,
        "best_single": {"model": best, **bs},
        "single_models": {m: {k: v[k] for k in ("quality", "total_cost", "cost_per_query")}
                          for m, v in table.items()},
        "vs_best_single": {"quality_delta": pol["quality"] - bs["quality"],
                           "cost_ratio": rel(pol["total_cost"], bs["total_cost"])},
        "vs_oracle": {"quality_gap": orc["quality"] - pol["quality"],
                      "cost_ratio": rel(pol["total_cost"], orc["total_cost"])},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score a routing policy on cached RouterBench responses (offline).")
    ap.add_argument("--data", help=f"local RouterBench file (or set {DATA_ENV})")
    ap.add_argument("--policy", default="oracle",
                    help="oracle | single:MODEL | random | routes:FILE.jsonl")
    ap.add_argument("--eval", action="append", dest="evals", help="filter eval_name prefix (repeatable)")
    ap.add_argument("--model", action="append", dest="models", help="restrict model pool (repeatable)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--seed", type=int, default=167)
    ap.add_argument("--brief", action="store_true", help="omit per-eval breakdown")
    a = ap.parse_args(argv)
    recs, models = load(a.data, a.evals, a.models, a.limit)
    out = report(recs, models, a.policy, a.seed)
    if a.brief:
        for k in ("policy", "oracle", "best_single"):
            out[k].pop("by_eval", None)
    json.dump(out, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
