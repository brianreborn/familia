#!/usr/bin/env python3
"""Draft-model speculative decoding vs none vs n-gram (#91, contrast #82), one host.

For each config, starts llama-server (args through bench_guard.preflight, cgroup MemoryMax from reservation/headroom, swap allowed (#95)), sends the same greedy (temperature 0, seed 0) requests, and records decode t/s,
draft acceptance and whether the text is byte-identical to the no-speculation baseline
(greedy speculative decoding must be lossless; a mismatch = quality loss, reported).

Workloads: plain (short system prompt), hermes (the SOUL.md hermes.sh renders, if given),
harness2 (coding-v1 task prompts, as Harness² sends them). Every row carries the exact
llama-server args per weight file. A server that dies is reported with rc + log tail.

  spec_bench.py --bin LLAMA_SERVER --target T.gguf --draft D.gguf [--n-max 4,8,16] [--ngram]
                [--threads 4] [--ctx 8192] [--port 18191] [--mem-max 12G] [--hermes-sys FILE] [--out PREFIX]
"""
import argparse, hashlib, json, os, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
import bench_guard as BG  # noqa: E402

DEFAULTS = {"sampling": "temperature 0, seed 0 (greedy, lossless check)", "rope": "GGUF/llama.cpp default", "chat_template": "llama.cpp built-in for arch"}

def workloads(hermes_sys):
    w = [("plain", "You are a helpful assistant.", "Write a Python function that parses an ISO 8601 date string and returns (year, month, day). Include a docstring and two asserts.")]
    if hermes_sys and os.path.isfile(hermes_sys): w.append(("hermes", open(hermes_sys).read(), "Write a Python function that reverses the words of a sentence, with a docstring."))
    ts = json.load(open(os.path.join(ROOT, "registry", "harness2-tasks", "coding-v1.json")))["tasks"][:2]
    w += [(f"harness2:{t['id']}", "You are a careful Python programmer. Reply with one python code block.", t["prompt"]) for t in ts]
    return w

def req(port, sysmsg, user, n):
    b = json.dumps({"messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}], "max_tokens": n,
                    "temperature": 0, "seed": 0, "top_k": 1, "chat_template_kwargs": {"enable_thinking": False}}).encode()
    t = time.time()
    d = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", b, {"Content-Type": "application/json"}), timeout=3600))
    tm = d.get("timings") or {}; txt = d["choices"][0]["message"].get("content") or ""
    return {"wall_s": round(time.time() - t, 2), "tg": round(tm.get("predicted_per_second", 0), 2), "pp": round(tm.get("prompt_per_second", 0), 1),
            "n": tm.get("predicted_n"), "draft_n": tm.get("draft_n"), "draft_ok": tm.get("draft_n_accepted"),
            "sha": hashlib.sha256(txt.encode()).hexdigest()[:12]}

def _mem_max_mib(mem_max):
    """Parse MemoryMax size (12G / 4096M / 4096) to MiB; fall back to headroom (#95)."""
    s = str(mem_max).strip().upper()
    if s.endswith("G"):
        return int(float(s[:-1]) * 1024)
    if s.endswith("M"):
        return int(float(s[:-1]))
    try:
        return int(s)
    except ValueError:
        return BG.headroom_cap_mib() or 4096


def run(a, name, extra, log):
    import oom_adj  # noqa: E402
    args = [a.bin, "-m", a.target, "-c", str(a.ctx), "-t", str(a.threads), "-ngl", "0", "-np", "1", "--port", str(a.port),
            "--host", "127.0.0.1", "-lm", "none", "--jinja", "-fa", "on"] + extra
    if hasattr(BG, "preflight"): probs, args = BG.preflight(args, BG.summarize(BG.read_gguf(a.target)))
    else:
        try: probs, args = [], BG.modern_args(args)
        except ValueError as e: probs = [f"BAD_PARAMS: {e}"]
    if probs: return {"config": name, "args": args, "error": "; ".join(probs)}
    lf = f"{a.out}-{name}.log"
    # #95: hard MemoryMax = reservation; swap allowed (MemorySwapMax not set). Cap from --mem-max or headroom.
    hard = _mem_max_mib(a.mem_max)
    # fleet admission (#95); MemoryMax = reservation; swap allowed. Big sweeps: wrap with with-host-lock.
    ar = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "launch_status.py"),
                         "admit", "--mib", str(hard), "--pid", str(os.getpid()), "--tag", f"spec-{name}"],
                        capture_output=True, text=True)
    if ar.returncode != 0:
        return {"config": name, "args": args, "error": "LF_OOM_CAP: " + (ar.stderr or ar.stdout or "admission refused")[-200:]}
    p = subprocess.Popen(
        ["systemd-run", "--user", "--scope", "-q",
         "-p", f"MemoryHigh={max(256, hard - 256)}M", "-p", f"MemoryMax={hard}M",
         os.path.join(ROOT, "scripts", "oom-adj"), "900"] + args,
        stdout=open(lf, "w"), stderr=subprocess.STDOUT, preexec_fn=oom_adj.preexec())
    up = False
    for _ in range(300):
        if p.poll() is not None: break
        try: urllib.request.urlopen(f"http://127.0.0.1:{a.port}/health", timeout=2); up = True; break
        except Exception: time.sleep(1)
    r = {"config": name, "args": args[1:], "rows": {}}
    if not up:
        r["error"] = f"server died rc={p.poll()} during load: " + " | ".join(open(lf).read().strip().splitlines()[-3:])[-300:]
        p.kill()
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "launch_status.py"),
                        "release", "--pid", str(os.getpid())], capture_output=True)
        return r
    try:
        for wn, s, u in workloads(a.hermes_sys):
            r["rows"][wn] = req(a.port, s, u, a.max_tokens); log(f"  {name:<12} {wn:<24} {r['rows'][wn]}")
    except Exception as e:
        r["error"] = f"request failed ({e}); server rc={p.poll()}: " + " | ".join(open(lf).read().strip().splitlines()[-3:])[-300:]
    p.terminate(); p.wait(30)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "launch_status.py"),
                    "release", "--pid", str(os.getpid())], capture_output=True)
    return r

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--bin", required=True); ap.add_argument("--target", required=True); ap.add_argument("--draft", required=True)
    ap.add_argument("--n-max", default="4,8,16"); ap.add_argument("--ngram", action="store_true"); ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--ctx", type=int, default=8192); ap.add_argument("--port", type=int, default=18191); ap.add_argument("--mem-max", default="12G")
    ap.add_argument("--max-tokens", type=int, default=192); ap.add_argument("--hermes-sys"); ap.add_argument("--out", default=os.path.expanduser("~/perf/spec"))
    a = ap.parse_args(argv); os.makedirs(os.path.dirname(a.out), exist_ok=True)
    meta = {}
    for role, f in (("target", a.target), ("draft", a.draft)):
        m = BG.summarize(BG.read_gguf(f)); probs, notes = BG.validate(m, DEFAULTS)
        meta[role] = {"file": os.path.basename(f), "size_mib": round(os.path.getsize(f) / 2**20), "problems": probs, "notes": notes}
        if probs: print(f"GUARD-FAIL {role} {f}: {probs}"); return 3
    cfgs = [("none", [])] + [(f"draft-n{n}", ["-md", a.draft, "--spec-type", "draft-simple", "--spec-draft-n-max", n, "--spec-draft-n-min", "0",
                                            "--spec-draft-p-min", "0.75", "-ngld", "0", "-td", str(a.threads), "-cd", str(a.ctx)]) for n in a.n_max.split(",")]
    if a.ngram: cfgs.append(("ngram-simple", ["--spec-type", "ngram-simple"]))
    res = [run(a, n, x, print) for n, x in cfgs]
    base = (res[0].get("rows") or {})
    for r in res[1:]:
        for wn, row in (r.get("rows") or {}).items():
            b = base.get(wn) or {}; row["lossless"] = row["sha"] == b.get("sha"); row["speedup"] = round(row["tg"] / b["tg"], 2) if b.get("tg") else None
    json.dump({"meta": meta, "results": res, "host": os.uname().nodename, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, open(a.out + ".json", "w"), indent=1)
    with open(a.out + ".md", "w") as f:
        f.write(f"target {meta['target']['file']} ({meta['target']['size_mib']} MiB), draft {meta['draft']['file']} ({meta['draft']['size_mib']} MiB); notes {meta['target']['notes'] + meta['draft']['notes']}\n\n")
        f.write("| config | workload | tg t/s | speedup | accepted/drafted | lossless |\n|---|---|---|---|---|---|\n")
        for r in res:
            if r.get("error"): f.write(f"| {r['config']} | ERROR | {r['error'][:200]} | | | |\n")
            for wn, row in (r.get("rows") or {}).items():
                f.write(f"| {r['config']} | {wn} | {row['tg']} | {row.get('speedup', '-')} | {row['draft_ok']}/{row['draft_n']} | {row.get('lossless', 'base')} |\n")
        f.write("\nexact args per config:\n" + "".join(f"- {r['config']}: `{' '.join(map(str, r['args']))}`\n" for r in res))
    print(open(a.out + ".md").read()[:3000]); return 0

if __name__ == "__main__": sys.exit(main())
