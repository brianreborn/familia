#!/usr/bin/env python3
"""Dogfood dispatcher: REAL hermes (single + graph) and Harness² loops (#110).

usage: dispatch.py QUEUE.yaml [--out DIR] [--harness hermes,hermes-graph,harness2]
                              [--model-node NODE] [--h2-target TARGET] [--threads N]
                              [--smoke] [--max-wait N]

QUEUE.yaml: list of {id, issue, goal, files: [...], accept: "shell cmd"}.

Per task:
  - scratch git worktree off origin/main with FAMILIA_SYNC=0 (avoids pin-sync polluting
    the worktree; #111)
  - invoke a REAL harness (not a single chat completion returning <file> blocks):
      hermes         -> scripts/hermes.sh --mode single --model NODE  (+ hermes-agent -z)
      hermes-graph   -> scripts/hermes.sh --mode graph               (+ hermes-agent -z)
      harness2       -> scripts/harness2.py propose --target TARGET
  - tools limited to the task worktree (cwd=worktree; hermes -t file,terminal,todo)
  - acceptance command run in the worktree (hermes paths); H2 path accepts on propose OK
  - host lock / thread admission when a live node is required (not in --smoke)
  - accept rates appended to OUT/dogfood-daily.md (and mirrored under docs/ when --record-docs)

--smoke: prove the real CLIs are invoked via hermes --render-only and harness2 --dry-run.
  No llama-server, no weights. Use when free RAM cannot host the coder node.

Nothing is committed or pushed by dispatch itself (loop.sh does that).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE / "scripts"))

# Lean coding surface only — no web/search/browser (tools stay inside the worktree cwd).
HERMES_TOOLSETS = "file,terminal,todo"
DEFAULT_HARNESSES = ("hermes", "hermes-graph", "harness2")
HERMES_MODES = {"hermes": "single", "hermes-graph": "graph"}


def sh(cmd, cwd=None, timeout=900, env=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    p = subprocess.run(
        cmd, shell=isinstance(cmd, str), cwd=cwd, capture_output=True, text=True,
        timeout=timeout, env=e,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def threads_in_use():
    from bench_guard import threads_in_use as t
    return t()


def wait_budget(n, cores, max_wait):
    t0 = time.time()
    while threads_in_use() + n > cores:
        if time.time() - t0 > max_wait:
            return False
        time.sleep(15)
    return True


def endpoint_up(host, port, timeout=2):
    try:
        urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout).read()
        return True
    except Exception:
        return False


def worktree_add(repo, wt, ref="origin/main"):
    """Create a detached worktree without running pin-sync into it (#111)."""
    env = {"FAMILIA_SYNC": "0"}
    sh(f"git worktree remove --force {wt}", cwd=repo, env=env)
    rc, out = sh(f"git worktree add -q --detach {wt} {ref}", cwd=repo, env=env)
    if rc != 0:
        raise RuntimeError(f"worktree add failed: {out[-500:]}")
    return wt


def worktree_remove(repo, wt):
    sh(f"git worktree remove --force {wt}", cwd=repo, env={"FAMILIA_SYNC": "0"})


def task_prompt(t):
    files = ", ".join(t.get("files") or [])
    return (
        f"TASK {t['id']} ({t.get('issue', '')}): {t['goal']}\n"
        f"SCOPE (only these paths may change): {files}\n"
        f"Working directory is a git worktree of familia. Use file/terminal tools only "
        f"inside this directory. Do not touch pentest/security/ssh/keys/sudo paths.\n"
        f"ACCEPTANCE: `{t['accept']}` must pass in the worktree when you are done.\n"
        f"Make the smallest correct change. Prefer editing existing files over rewriting."
    )


def hermes_home_for(mode, agent, node):
    if mode == "single":
        return Path(os.path.expanduser(f"~/.cache/familia/hermes-{agent}@{node}"))
    return Path(os.path.expanduser(f"~/.cache/familia/hermes-{agent}"))


def build_hermes_render_cmd(mode, node, agent="hermes"):
    cmd = [
        "bash", str(HERE / "scripts" / "hermes.sh"),
        "--mode", mode, "--agent", agent, "--yes", "--render-only",
    ]
    if mode == "single":
        cmd += ["--model", node]
    return cmd


def build_hermes_agent_cmd(prompt, toolsets=HERMES_TOOLSETS):
    """Argv for hermes-agent oneshot inside the task worktree (after render)."""
    return [
        os.environ.get("HERMES_BIN") or "/snap/bin/hermes-agent",
        "-z", prompt,
        "-t", toolsets,
        "--yolo",
        "--accept-hooks",
        "--source", "tool",
    ]


def build_harness2_cmd(target, *, smoke, max_tasks=1, enable=True):
    cmd = [
        sys.executable, str(HERE / "scripts" / "harness2.py"),
        "propose", "--target", target, "--max-tasks", str(max_tasks), "--yes",
    ]
    if enable:
        cmd.append("--enable")
    if smoke:
        cmd.append("--dry-run")
    return cmd


def with_host_lock_prefix():
    hl = HERE / "scripts" / "with-host-lock"
    if hl.exists():
        return [str(hl), "--big", "--tag", "dogfood", "--"]
    lock = os.path.expanduser("~/.local/state/familia/big.lock")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    return ["flock", lock]


def collect_patch(wt, scope_files):
    """Stage in-scope changes (and untracked in-scope paths) and return the cached diff."""
    scope = set(scope_files or [])
    for rel in scope:
        p = Path(wt) / rel
        if p.exists() or p.is_symlink():
            sh(["git", "add", "-A", "--", rel], cwd=wt)
    # Also pick up new files created under scoped dirs / exact paths via status
    rc, st = sh(["git", "status", "--porcelain", "-uall"], cwd=wt)
    for line in (st or "").splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().split(" -> ")[-1]
        if path in scope or any(path.startswith(s.rstrip("/") + "/") for s in scope if s.endswith("/")):
            sh(["git", "add", "-A", "--", path], cwd=wt)
    rc, patch = sh(["git", "diff", "--cached"], cwd=wt, timeout=60)
    return patch or ""


def run_hermes_task(t, harness, args, out_dir, repo):
    mode = HERMES_MODES[harness]
    tid = t["id"]
    wt = Path(f"/tmp/dogfood-wt-{tid}")
    d = out_dir / tid
    d.mkdir(parents=True, exist_ok=True)
    worktree_add(repo, str(wt))
    prompt = task_prompt(t)
    render_cmd = build_hermes_render_cmd(mode, args.model_node)
    agent_cmd = build_hermes_agent_cmd(prompt)
    home = hermes_home_for(mode, "hermes", args.model_node)
    transcript = {
        "harness": harness, "mode": mode, "smoke": args.smoke,
        "render_cmd": render_cmd, "agent_cmd": agent_cmd,
        "hermes_home": str(home), "prompt": prompt, "worktree": str(wt),
    }
    t0 = time.time()

    # Always render first (proves hermes.sh single/graph path; cheap; no server).
    rc_r, out_r = sh(render_cmd, cwd=str(HERE), timeout=600)
    transcript["render_rc"] = rc_r
    transcript["render_out"] = out_r[-4000:]
    if rc_r != 0:
        (d / "transcript.json").write_text(json.dumps(transcript, indent=1))
        return {
            "id": tid, "issue": t.get("issue"), "harness": harness, "mode": mode,
            "touched": [], "accept_rc": rc_r, "error": f"hermes render failed rc={rc_r}",
            "gen_s": round(time.time() - t0, 1), "smoke": args.smoke,
            "invoked": ["hermes.sh --render-only"], "worktree": str(wt),
            "model": args.model_node,
        }

    if args.smoke:
        # Prove agent argv construction + hermes binary exists; do not call the model.
        bin_path = agent_cmd[0]
        bin_ok = os.path.isfile(bin_path) or os.path.islink(bin_path)
        transcript["agent_bin_exists"] = bin_ok
        transcript["smoke_note"] = (
            "render-only OK; live oneshot skipped (--smoke). "
            "Live land needs coder node up (DETACH_MODE=screen-attached serve.sh) "
            "and enough MemAvailable above hosts.miryam.reserve_ram_mib."
        )
        (d / "transcript.json").write_text(json.dumps(transcript, indent=1))
        (d / "patch.diff").write_text("")
        (d / "accept.log").write_text("smoke: hermes render-only invoked; oneshot not run\n")
        return {
            "id": tid, "issue": t.get("issue"), "harness": harness, "mode": mode,
            "touched": [], "accept_rc": 0 if bin_ok else 1,
            "gen_s": round(time.time() - t0, 1), "smoke": True,
            "invoked": ["hermes.sh --mode %s --render-only" % mode, "hermes-agent -z (argv only)"],
            "worktree": str(wt), "model": args.model_node, "patch_lines": 0,
        }

    # Live: require node; optionally start under with-host-lock via serve.sh.
    g = yaml.safe_load(open(HERE / "graph.yaml"))
    node = (g.get("nodes") or {}).get(args.model_node) or {}
    host, port = node.get("bind", "127.0.0.1"), int(node.get("port", 9941))
    if not endpoint_up(host, port):
        if args.start_node:
            if not wait_budget(args.threads, os.cpu_count() or 1, args.max_wait):
                raise RuntimeError("thread budget never freed")
            serve = with_host_lock_prefix() + [
                "env", f"DETACH_MODE=screen-attached",
                "bash", str(HERE / "scripts" / "serve.sh"), args.model_node,
            ]
            # serve.sh under screen returns after spawn; wait for health
            sh(serve, cwd=str(HERE), timeout=120)
            t_wait = time.time()
            while not endpoint_up(host, port):
                if time.time() - t_wait > 900:
                    raise RuntimeError(f"node {args.model_node} did not come up on {host}:{port}")
                time.sleep(3)
        else:
            raise RuntimeError(
                f"node {args.model_node} not up on {host}:{port}; "
                f"start with DETACH_MODE=screen-attached sh scripts/serve.sh {args.model_node} "
                f"or pass --start-node"
            )

    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    env["FAMILIA_SYNC"] = "0"
    # Hold big.lock for the duration of the agent loop (one big job).
    locked = with_host_lock_prefix() + agent_cmd
    rc_a, out_a = sh(locked, cwd=str(wt), timeout=args.task_timeout, env=env)
    transcript["agent_rc"] = rc_a
    transcript["agent_out"] = out_a[-8000:]
    gen_s = round(time.time() - t0, 1)

    patch = collect_patch(str(wt), t.get("files") or [])
    (d / "patch.diff").write_text(patch)
    touched = []
    rc_st, st = sh(["git", "diff", "--cached", "--name-only"], cwd=str(wt))
    touched = [x for x in (st or "").splitlines() if x.strip()]
    if not touched:
        rc_acc, acc_out = 1, "no files changed"
    else:
        rc_acc, acc_out = sh(t["accept"], cwd=str(wt), timeout=args.task_timeout)
    (d / "accept.log").write_text(acc_out[-8000:])
    (d / "transcript.json").write_text(json.dumps(transcript, indent=1))
    return {
        "id": tid, "issue": t.get("issue"), "harness": harness, "mode": mode,
        "touched": touched, "accept_rc": rc_acc, "agent_rc": rc_a,
        "gen_s": gen_s, "smoke": False,
        "invoked": [
            "hermes.sh --mode %s --render-only" % mode,
            "hermes-agent -z (oneshot, cwd=worktree, tools=%s)" % HERMES_TOOLSETS,
        ],
        "worktree": str(wt), "model": args.model_node,
        "patch_lines": patch.count("\n"),
    }


def run_harness2_task(t, args, out_dir, repo):
    tid = t["id"]
    wt = Path(f"/tmp/dogfood-wt-{tid}")
    d = out_dir / tid
    d.mkdir(parents=True, exist_ok=True)
    # Worktree still created so loop.sh paths stay stable; H2 edits harness state, not the issue tree.
    worktree_add(repo, str(wt))
    cmd = build_harness2_cmd(args.h2_target, smoke=args.smoke, max_tasks=args.h2_max_tasks)
    transcript = {
        "harness": "harness2", "smoke": args.smoke, "cmd": cmd,
        "worktree": str(wt), "note": (
            "Harness² propose improves the target harness (prompt/skills), not the GitHub "
            "issue files. Real engine loop via scripts/harness2.py."
        ),
    }
    t0 = time.time()
    if args.smoke:
        rc, out = sh(cmd, cwd=str(HERE), timeout=120)
    else:
        if not wait_budget(args.threads, os.cpu_count() or 1, args.max_wait):
            raise RuntimeError("thread budget never freed")
        locked = with_host_lock_prefix() + cmd
        rc, out = sh(locked, cwd=str(HERE), timeout=args.task_timeout)
    transcript["rc"] = rc
    transcript["out"] = out[-8000:]
    gen_s = round(time.time() - t0, 1)
    (d / "transcript.json").write_text(json.dumps(transcript, indent=1))
    (d / "patch.diff").write_text("")
    ok = rc == 0 and (
        ("dry-run:" in out) if args.smoke else ("proposal" in out.lower() or rc == 0)
    )
    # For live propose, exit 0 is success even if candidate == base (still a real loop).
    if not args.smoke:
        ok = rc == 0
    (d / "accept.log").write_text(out[-4000:] if out else ("rc=%s" % rc))
    return {
        "id": tid, "issue": t.get("issue"), "harness": "harness2",
        "touched": [], "accept_rc": 0 if ok else (rc or 1),
        "gen_s": gen_s, "smoke": args.smoke,
        "invoked": [" ".join(cmd)],
        "worktree": str(wt), "model": args.h2_target,
        "patch_lines": 0,
    }


def run_task(t, harness, args, out_dir, repo):
    if harness in HERMES_MODES:
        return run_hermes_task(t, harness, args, out_dir, repo)
    if harness == "harness2":
        return run_harness2_task(t, args, out_dir, repo)
    raise ValueError(f"unknown harness {harness!r}; expected one of {list(HERMES_MODES)+['harness2']}")


def update_daily(out_dir, results, model_label):
    """Append/refresh accept-rate table in OUT/dogfood-daily.md."""
    path = out_dir / "dogfood-daily.md"
    # Aggregate from results.jsonl (already includes this run's lines).
    stats = defaultdict(lambda: {"ok": 0, "n": 0, "smoke": 0})
    jl = out_dir / "results.jsonl"
    rows = []
    if jl.exists():
        for line in jl.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    elif results:
        rows = list(results)
    for r in rows:
        key = f"{r.get('harness','?')}/{r.get('model') or model_label}"
        stats[key]["n"] += 1
        if r.get("accept_rc") == 0:
            stats[key]["ok"] += 1
        if r.get("smoke"):
            stats[key]["smoke"] += 1
    lines = [
        "# dogfood-daily",
        "",
        f"Updated: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "Accept rate per harness/model (accept_rc==0). Smoke rows prove real CLI invocation "
        "without a live model loop.",
        "",
        "| harness/model | ok | n | rate | smoke |",
        "|---|---:|---:|---:|---:|",
    ]
    for k in sorted(stats):
        s = stats[k]
        rate = (100.0 * s["ok"] / s["n"]) if s["n"] else 0.0
        lines.append(f"| {k} | {s['ok']} | {s['n']} | {rate:.0f}% | {s['smoke']} |")
    lines.append("")
    path.write_text("\n".join(lines) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("queue")
    ap.add_argument("--out", default=os.path.expanduser("~/.cache/familia/dogfood"))
    ap.add_argument("--harness", default=",".join(DEFAULT_HARNESSES),
                    help="comma list: hermes,hermes-graph,harness2 (alias: harness2 keeps old name)")
    ap.add_argument("--model-node", default="coder", help="graph node for hermes single mode")
    ap.add_argument("--h2-target", default="hermes-lab", help="harnesses.* target for propose")
    ap.add_argument("--h2-max-tasks", type=int, default=1)
    ap.add_argument("--threads", type=int, default=3, help="thread budget reservation for live runs")
    ap.add_argument("--port", type=int, default=0, help="unused; node port comes from graph.yaml")
    ap.add_argument("--max-wait", type=int, default=3600)
    ap.add_argument("--task-timeout", type=int, default=7200)
    ap.add_argument("--smoke", action="store_true",
                    help="invoke real CLIs in dry/render-only mode (no model weights)")
    ap.add_argument("--start-node", action="store_true",
                    help="if coder endpoint down, start via with-host-lock + serve.sh")
    ap.add_argument("--record-docs", action="store_true",
                    help="also write docs/dogfood-daily.md in the repo")
    # Legacy flags kept so old loop.sh invocations do not crash:
    ap.add_argument("--model", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--bin", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--ctx", type=int, default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    # Normalize legacy "hermes,harness2" and map bare hermes -> single.
    raw = [x.strip() for x in a.harness.split(",") if x.strip()]
    hs = []
    for h in raw:
        if h == "hermes-single":
            h = "hermes"
        hs.append(h)
    for h in hs:
        if h not in HERMES_MODES and h != "harness2":
            print(json.dumps({"error": f"unknown harness {h}"}), file=sys.stderr)
            sys.exit(2)

    tasks = yaml.safe_load(open(a.queue)) or []
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res_path = out / "results.jsonl"
    repo = str(HERE)
    sh("git fetch -q origin", cwd=repo, env={"FAMILIA_SYNC": "0"})

    run_results = []
    for i, t in enumerate(tasks):
        h = hs[i % len(hs)]
        try:
            r = run_task(t, h, a, out, repo)
        except Exception as e:
            r = {"id": t.get("id"), "harness": h, "error": repr(e)[:400], "accept_rc": 1,
                 "smoke": a.smoke, "model": a.model_node if h != "harness2" else a.h2_target}
        r.setdefault("model", a.model_node if h != "harness2" else a.h2_target)
        r["params"] = {
            "smoke": a.smoke, "model_node": a.model_node, "h2_target": a.h2_target,
            "toolsets": HERMES_TOOLSETS, "issue": "#110 real loops",
        }
        with open(res_path, "a") as f:
            f.write(json.dumps(r) + "\n")
        run_results.append(r)
        print(t.get("id"), h, r.get("accept_rc", r.get("error")), flush=True)

    daily = update_daily(out, run_results, a.model_node)
    if a.record_docs:
        docs = HERE / "docs" / "dogfood-daily.md"
        docs.write_text(daily.read_text())
        print("wrote", docs, flush=True)
    print("daily", daily, flush=True)
    # Non-zero if any task failed (smoke expects all 0).
    if any(r.get("accept_rc", 1) != 0 for r in run_results):
        sys.exit(1)


if __name__ == "__main__":
    main()
