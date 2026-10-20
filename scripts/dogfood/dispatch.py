#!/usr/bin/env python3
"""Dogfood dispatcher: run small familia dev tasks through a local familia node.

usage: dispatch.py QUEUE.yaml [--out DIR] [--model GGUF] [--threads N] [--harness hermes,harness2]

QUEUE.yaml: list of {id, issue, goal, files: [...], accept: "shell cmd"}.
Per task: scratch git worktree off origin/main, one model call through the harness
adapter (alternating hermes / harness2 prompt styles), full-file <file path=...> blocks
applied only to in-scope files, acceptance command run, patch + transcript + timing
saved, one summary line appended to OUT/results.jsonl. Nothing is committed or pushed.

Memory: launches llama-server directly with no per-launch hard cap (LESSONS-LEARNED:
no MemoryMax/MemorySwapMax=0 wrappers). Host lock: the server runs under flock ~/.local/state/familia/big.lock
(scripts/with-host-lock when present). Threads: waits until sum(-t) + N <= cores.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE / "scripts"))
FILE_RE = re.compile(r'<file path="([^"]+)">\n?(.*?)</file>', re.S)
SAMPLING = {"temperature": 0.2, "top_p": 0.95, "max_tokens": 6144}  # documented defaults (not from GGUF)
PROMPTS = {
 "hermes": "You are Hermes, a careful software engineer working in the familia repo. "
           "Make the smallest correct change for the task. Reply ONLY with complete new file "
           'contents as <file path="REL/PATH">...</file> blocks, one per changed file, then one line "SUMMARY: ...".',
 "harness2": "Harness2 task executor. Read the inlined context, plan briefly in <plan></plan>, then emit "
             'each changed file in full as <file path="REL/PATH">...</file>. Files you do not emit stay unchanged. '
             'Only files listed under SCOPE may change. End with "SUMMARY: ...".',
}

def sh(cmd, cwd=None, timeout=900):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)[-4000:]

def threads_in_use():
    from bench_guard import threads_in_use as t
    return t()

def wait_budget(n, cores, max_wait):
    t0 = time.time()
    while threads_in_use() + n > cores:
        if time.time() - t0 > max_wait: return False
        time.sleep(15)
    return True

def start_server(binary, model, threads, port, ctx, log):
    args = [binary, "-m", model, "-t", str(threads), "-c", str(ctx), "-ngl", "0",
            "--host", "127.0.0.1", "--port", str(port), "--jinja", "-np", "1"]
    lock = os.path.expanduser("~/.local/state/familia/big.lock"); os.makedirs(os.path.dirname(lock), exist_ok=True)
    hl = HERE / "scripts" / "with-host-lock"   # per-host big-job mutex: never two big things at once
    pre = [str(hl)] if hl.exists() else ["flock", lock]
    p = subprocess.Popen(pre + args, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    for _ in range(14400):  # includes time queued on the host lock
        if p.poll() is not None: raise SystemExit(f"server died rc={p.returncode}, see {log}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read(); return p, args
        except Exception: time.sleep(1)
    p.kill(); raise SystemExit("server not healthy in 600s")

def chat(port, system, user):
    body = dict(SAMPLING, model="coder", messages=[{"role": "system", "content": system},
                {"role": "user", "content": user}], chat_template_kwargs={"enable_thinking": False})
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r: d = json.load(r)
    return d["choices"][0]["message"].get("content") or "", d.get("usage", {}), d.get("timings", {})

def run_task(t, harness, port, out, repo):
    tid = t["id"]; wt = Path(f"/tmp/dogfood-wt-{tid}"); d = out / tid; d.mkdir(parents=True, exist_ok=True)
    sh(f"git worktree remove --force {wt}", repo); sh(f"git worktree add -q --detach {wt} origin/main", repo)
    ctx = []
    for f in t["files"]:
        p = wt / f
        ctx.append(f"# FILE {f}\n" + (p.read_text() if p.exists() else "(new file)\n"))
    user = (f"TASK {tid} ({t.get('issue','')}): {t['goal']}\nSCOPE: {', '.join(t['files'])}\n"
            f"ACCEPTANCE: `{t['accept']}` must pass.\n\n" + "\n\n".join(ctx))
    t0 = time.time(); text, usage, tim = chat(port, PROMPTS[harness], user); gen_s = time.time() - t0
    touched = []
    for path, body in FILE_RE.findall(text):
        rel = path.strip().lstrip("./")
        if rel in t["files"]:
            (wt / rel).parent.mkdir(parents=True, exist_ok=True); (wt / rel).write_text(body); touched.append(rel)
    sh("git add -A", wt); _, patch = sh("git diff --cached", wt, 60)
    patch = subprocess.run("git diff --cached", shell=True, cwd=wt, capture_output=True, text=True).stdout
    (d / "patch.diff").write_text(patch)
    (d / "transcript.json").write_text(json.dumps({"system": PROMPTS[harness], "user": user, "reply": text}, indent=1))
    rc, acc_out = (1, "no files changed") if not touched else sh(t["accept"], wt)
    (d / "accept.log").write_text(acc_out)
    return {"id": tid, "issue": t.get("issue"), "harness": harness, "touched": touched, "accept_rc": rc,
            "gen_s": round(gen_s, 1), "usage": usage, "tg_tps": tim.get("predicted_per_second"),
            "worktree": str(wt), "patch_lines": patch.count("\n")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queue"); ap.add_argument("--out", default=os.path.expanduser("~/.cache/familia/dogfood"))
    ap.add_argument("--model", default=os.path.expanduser("~/models/Qwen3.5-9B-Q4_K_M.gguf"))
    ap.add_argument("--bin", default=os.path.expanduser("~/.local/share/familia/runtime/b11539/llama-b11539/llama-server"))
    ap.add_argument("--threads", type=int, default=2); ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--port", type=int, default=18977); ap.add_argument("--harness", default="hermes,harness2")
    ap.add_argument("--max-wait", type=int, default=3600)
    a = ap.parse_args()
    tasks = yaml.safe_load(open(a.queue)); hs = a.harness.split(",")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); res = out / "results.jsonl"
    repo = str(HERE); sh("git fetch -q origin", repo)
    cores = os.cpu_count() or 1
    if not wait_budget(a.threads, cores, a.max_wait):
        print(json.dumps({"error": "thread budget never freed", "in_use": threads_in_use()})); sys.exit(2)
    srv, args = start_server(a.bin, a.model, a.threads, a.port, a.ctx, out / "server.log")
    params = {"model": os.path.basename(a.model), "server_args": args[1:], "sampling": SAMPLING,
              "sampling_note": "GGUF has no sampling metadata; dispatcher defaults used"}
    try:
        for i, t in enumerate(tasks):
            h = hs[i % len(hs)]
            try: r = run_task(t, h, a.port, out, repo)
            except Exception as e: r = {"id": t["id"], "harness": h, "error": repr(e)[:300]}
            if srv.poll() is not None: r["server_died_rc"] = srv.returncode
            r["model"] = params["model"]; r["params"] = params
            with open(res, "a") as f: f.write(json.dumps(r) + "\n")
            print(t["id"], h, r.get("accept_rc", r.get("error")), flush=True)
            if srv.poll() is not None: break
    finally:
        srv.terminate()

if __name__ == "__main__": main()
