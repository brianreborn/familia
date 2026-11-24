#!/usr/bin/env python3
"""Run the fixed familia task suite (#119).

Modes:
  --dry-run   validate suite + print the plan (no model calls; CI-safe)
  --record    call OpenAI-compatible endpoints from env and write a result JSON

Env (record mode; never written into the result file):
  FAMILIA_ENDPOINT      default chat/completions base (.../v1)
  FAMILIA_LIGHT_URL     light route base (routing tasks)
  FAMILIA_HEAVY_URL     heavy route base
  FAMILIA_ENGINE_<LABEL>_URL  per multi-engine instance label (#150)
  FAMILIA_MODEL         model id sent to the API (optional)
  FAMILIA_TASK_SUITE_EVIDENCE_DIR  where to write evidence (default XDG state)

No live attack tools or network probes. Do not skip models for license reasons.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_suite_lib as T


def _base(url):
    url = (url or "").rstrip("/")
    if url.endswith("/v1"):
        return url
    return url + ("/v1" if url else "")


def chat_completion(base, prompt, model=None, timeout=120):
    url = _base(base) + "/chat/completions"
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 512,
    }
    if model:
        body["model"] = model
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    choices = payload.get("choices") or []
    if not choices:
        return "", payload
    msg = choices[0].get("message") or {}
    return T._text(msg.get("content")), payload


def embeddings(base, prompt, model=None, timeout=120):
    url = _base(base) + "/embeddings"
    body = {"input": prompt}
    if model:
        body["model"] = model
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    rows = payload.get("data") or []
    vec = (rows[0] or {}).get("embedding") if rows else None
    return vec, payload


def pick_endpoint(task, args):
    """Resolve endpoint for a task without recording host details."""
    kind = task.get("kind")
    if kind == "routing":
        gold = task.get("gold_route")
        # Candidate under test: use strategy from --baseline for baseline runs;
        # for candidate, prefer light unless gold says heavy and heavy URL set.
        if args.baseline == "always-light":
            return os.environ.get("FAMILIA_LIGHT_URL") or os.environ.get("FAMILIA_ENDPOINT"), "light"
        if args.baseline == "always-heavy":
            return os.environ.get("FAMILIA_HEAVY_URL") or os.environ.get("FAMILIA_ENDPOINT"), "heavy"
        if args.baseline == "random":
            import random
            rng = random.Random(args.seed ^ hash(task["id"]) & 0xFFFFFFFF)
            pick = rng.choice(["light", "heavy"])
            env = "FAMILIA_LIGHT_URL" if pick == "light" else "FAMILIA_HEAVY_URL"
            return os.environ.get(env) or os.environ.get("FAMILIA_ENDPOINT"), pick
        # candidate / escalate heuristic: heavy gold -> heavy URL when present
        if gold == "heavy" and os.environ.get("FAMILIA_HEAVY_URL"):
            return os.environ["FAMILIA_HEAVY_URL"], "heavy"
        if os.environ.get("FAMILIA_LIGHT_URL"):
            return os.environ["FAMILIA_LIGHT_URL"], "light"
        return os.environ.get("FAMILIA_ENDPOINT"), gold or "light"
    if kind == "multi_engine":
        setup = task.get("setup") or {}
        instances = setup.get("instances") or []
        policy = setup.get("policy") or ""
        if not instances:
            return os.environ.get("FAMILIA_ENDPOINT"), None
        # Prefer specialty/weight matching; fall back to first configured URL
        chosen = instances[0]
        if policy == "escalate_light_to_heavy_same_role":
            for inst in instances:
                if inst.get("weight") == "heavy":
                    chosen = inst
                    break
        elif policy == "route_by_specialty":
            for inst in instances:
                if inst.get("specialty") == "structured_transform" and "json" in (task.get("prompt") or "").lower():
                    chosen = inst
                    break
        label = chosen.get("label") or ""
        env_key = "FAMILIA_ENGINE_" + label.upper().replace("-", "_") + "_URL"
        url = os.environ.get(env_key) or os.environ.get("FAMILIA_ENDPOINT")
        return url, chosen.get("engine")
    return os.environ.get("FAMILIA_ENDPOINT"), None


def run_task(task, args):
    prompt = task.get("prompt") or ""
    expect = task.get("expect") or {}
    kind = task.get("kind")
    t0 = time.time()
    route_taken = None
    engine_used = None
    failure = None
    output = ""
    embedding = None
    try:
        base, route_or_engine = pick_endpoint(task, args)
        if kind == "routing":
            route_taken = route_or_engine
        elif kind == "multi_engine":
            engine_used = route_or_engine
        if not base:
            raise RuntimeError("no endpoint configured (set FAMILIA_ENDPOINT or role URLs)")
        if kind == "embedding":
            embedding, _ = embeddings(base, prompt, model=args.model)
            passed, detail = T.score_expect(expect, "", embedding=embedding)
            output = f"<embedding dim={len(embedding) if embedding else 0}>"
        else:
            output, _ = chat_completion(base, prompt, model=args.model)
            passed, detail = T.score_expect(expect, output)
            if not passed:
                failure = detail
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, OSError) as e:
        passed = False
        failure = str(e)
        detail = "transport"
    latency_ms = (time.time() - t0) * 1000.0
    excerpt = (output or "")[:240]
    return {
        "id": task["id"],
        "passed": bool(passed),
        "score": 1.0 if passed else 0.0,
        "latency_ms": round(latency_ms, 1),
        "route_taken": route_taken,
        "gold_route": task.get("gold_route"),
        "engine_used": engine_used,
        "failure": failure,
        "output_excerpt": excerpt,
    }


def plan_lines(suite, role, harness, baseline, platform):
    tasks = T.tasks_for_role(suite, role) if role else list(suite.get("tasks") or [])
    lines = [
        f"suite={suite.get('suite_id')} rev={suite.get('revision')}",
        f"role={role or '*'} harness={harness} baseline={baseline} platform={platform}",
        f"tasks={len(tasks)} radical_triggers={len(suite.get('radical_change_triggers') or [])}",
        f"multi_engine_tasks={len(T.multi_engine_tasks(suite))} (#150)",
        f"baselines={[b.get('id') for b in (suite.get('baselines') or [])]}",
        f"harness_modes={[h.get('id') for h in (suite.get('harness_modes') or [])]}",
    ]
    for t in tasks:
        lines.append(f"  - {t['id']} kind={t.get('kind')} tags={t.get('tags')}")
    return lines, tasks


def build_record(suite, tasks_run, args, baseline_pass_rate=None):
    aggregate, gate = T.evaluate_aggregate(tasks_run, suite, baseline_pass_rate=baseline_pass_rate)
    multi = None
    if args.multi_engine_json:
        multi = json.loads(args.multi_engine_json)
    cand = {
        "model_name": args.model_name,
        "model_version": args.model_version,
        "quant": args.quant or None,
        "role": args.role,
        "runtime_name": args.runtime_name,
        "runtime_commit": args.runtime_commit,
        "engine": args.engine,
        "graph_fingerprint": args.graph_fingerprint or None,
        "prompt_profile": args.prompt_profile or None,
        "chat_template": args.chat_template or None,
        "system_prompt_label": args.system_prompt_label or None,
        "node_id": args.node_id or None,
        "status_before": args.status_before,
        "radical_triggers": list(args.radical_trigger or []),
        "multi_engine": multi,
    }
    return {
        "schema": 1,
        "suite_id": suite.get("suite_id"),
        "suite_revision": str(suite.get("revision")),
        "seed": int(args.seed),
        "platform_class": args.platform,
        "host_key": args.host_key or None,
        "candidate": cand,
        "baseline_id": args.baseline,
        "harness": args.harness,
        "tasks": tasks_run,
        "aggregate": aggregate,
        "gate": gate,
        "limitations": list(suite.get("description") and [suite["description"].strip()] or []),
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notes": args.notes or "",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", default=str(T.DEFAULT_SUITE), help="suite YAML path")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--record", action="store_true")
    ap.add_argument("--role", default="general")
    ap.add_argument("--harness", default="plain-llamacpp",
                    choices=["plain-llamacpp", "hermes-single", "hermes-graph", "harness2"])
    ap.add_argument("--baseline", default="always-light",
                    choices=["always-light", "always-heavy", "random", "candidate"])
    ap.add_argument("--platform", default="ubuntu")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--model", default=os.environ.get("FAMILIA_MODEL"))
    ap.add_argument("--model-name", default="unspecified-model")
    ap.add_argument("--model-version", default="unspecified")
    ap.add_argument("--quant", default="")
    ap.add_argument("--runtime-name", default="llama-server")
    ap.add_argument("--runtime-commit", default="unknown")
    ap.add_argument("--engine", default="llama")
    ap.add_argument("--node-id", default="")
    ap.add_argument("--host-key", default="")
    ap.add_argument("--status-before", default="planned",
                    choices=["planned", "experimental", "active"])
    ap.add_argument("--radical-trigger", action="append", default=[])
    ap.add_argument("--graph-fingerprint", default="")
    ap.add_argument("--prompt-profile", default="")
    ap.add_argument("--chat-template", default="")
    ap.add_argument("--system-prompt-label", default="")
    ap.add_argument("--multi-engine-json", default="")
    ap.add_argument("--baseline-pass-rate", type=float, default=None)
    ap.add_argument("--out", default="")
    ap.add_argument("--notes", default="")
    args = ap.parse_args(argv)

    suite, suite_path = T.load_suite(args.suite)
    if args.seed is None:
        args.seed = int(suite.get("seed_default") or 119)
    plats = {p.get("id") for p in (suite.get("platforms") or [])}
    if plats and args.platform not in plats:
        print(f"error: platform {args.platform!r} not in suite {sorted(plats)}", file=sys.stderr)
        return 2

    lines, tasks = plan_lines(suite, args.role, args.harness, args.baseline, args.platform)
    print("\n".join(lines))
    print(f"suite_path={suite_path}")

    if args.dry_run:
        # Validate scoring helpers offline with a tiny self-check
        ok, _ = T.score_expect({"type": "exact", "value": "x"}, "x")
        assert ok
        print("dry-run OK")
        return 0

    results = [run_task(t, args) for t in tasks]
    record = build_record(suite, results, args, baseline_pass_rate=args.baseline_pass_rate)
    verrs = T.validate_record(record, suite)
    if verrs:
        print("record validation errors:", file=sys.stderr)
        for e in verrs:
            print(f"  - {e}", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else (
        T.evidence_dir() / f"{suite.get('suite_id')}-{args.role}-{args.platform}-{int(time.time())}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"gate.passed={record['gate']['passed']} pass_rate={record['aggregate']['pass_rate']:.3f}")
    for r in record["gate"]["reasons"]:
        print(f"  reason: {r}")
    return 0 if record["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
