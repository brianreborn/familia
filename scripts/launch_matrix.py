#!/usr/bin/env python3
"""launch_matrix.py: launch every engine x every local model through bench_guard, wait for
health / first token, kill cleanly, and classify each failure. Also replays past crashes with
their original and corrected params, to tell "only bad params" apart from real engine bugs.

  launch_matrix.py --bin-dir DIR --models DIR [--models DIR ...] [--out FILE.jsonl]
                   [--engines llama-server,llama-cli,hermes-single,hermes-graph,harness2,serve]
                   [--host-limit-mib N] [--legacy-gpu] [--dry-run] [--no-replay]

Classes: OK, BAD_PARAMS, OOM, MISSING_RUNTIME, ENGINE_BUG, MODEL_FILE, TIMEOUT.
--dry-run runs every guard / classification step but starts no process. Stdlib only."""
import argparse, glob, json, os, re, signal, socket, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bench_guard as bg  # noqa: E402
import launch_status as ls  # noqa: E402
import oom_adj  # noqa: E402

LIVE = set()  # pgids of launched children, killed if the matrix itself is stopped


def _cleanup(*_):
    for g in list(LIVE):
        try:
            os.killpg(g, signal.SIGKILL)
        except OSError:
            pass
    sys.exit(91)

ENGINES = ["llama-server", "llama-cli", "hermes-single", "hermes-graph", "harness2", "serve"]
# Past launch crashes (familia-private logs, 2026-10-09..19). orig = what ran, fixed = corrected.
HISTORY = [
    {"id": "laya-ub64", "tool": "llama-bench", "model": "Laya", "symptom": "rc -6 GGML_ASSERT (abort)",
     "orig": ["-ngl", "0", "-t", "2", "-p", "1024", "-n", "0", "-ub", "64"],
     "fixed": ["-ngl", "0", "-t", "2", "-p", "1024", "-n", "0", "-b", "2048", "-ub", "1024"]},
    {"id": "laya-kvq8-nofa", "tool": "llama-bench", "model": "Laya", "symptom": "rc 1 quantized V cache needs FA",
     "orig": ["-ngl", "0", "-t", "2", "-p", "512", "-n", "0", "-ub", "512", "-fa", "0", "-ctk", "q8_0", "-ctv", "q8_0"],
     "fixed": ["-ngl", "0", "-t", "2", "-p", "512", "-n", "0", "-ub", "512", "-fa", "1", "-ctk", "q8_0", "-ctv", "q8_0"]},
    {"id": "laya-mmp", "tool": "llama-bench", "model": "Laya", "symptom": "rc 1 invalid parameter -mmp",
     "orig": ["-ngl", "0", "-t", "2", "-p", "512", "-n", "0", "-ub", "512", "-mmp", "1"],
     "fixed": ["-ngl", "0", "-t", "2", "-p", "512", "-n", "0", "-ub", "512", "-lm", "mmap"]},
    {"id": "qwen35-2b-capkill", "tool": "llama-bench", "model": "Qwen3.5-2B", "symptom": "SIGKILL by RSS watchdog (fixed cap < mmap peak)",
     "orig": ["-ngl", "0", "-t", "4", "-p", "1024", "-n", "0", "-b", "2048", "-ub", "1024"], "cap_mib": 1400,
     "fixed": ["-ngl", "0", "-t", "4", "-p", "1024", "-n", "0", "-b", "2048", "-ub", "1024", "-lm", "none"]},
    {"id": "coder-rc127", "tool": "serve", "model": "Qwen3.5-2B", "symptom": "rc 127 runtime path missing (#84)",
     "orig_bin": "/nonexistent/llama-server", "orig": [], "fixed": []},
]

PAT = [  # (class, regex on stderr/log)
    ("BAD_PARAMS", r"invalid parameter for argument|unknown argument|error: invalid argument|quantized V cache .*flash|n_ubatch >= n_tokens|exceeds the trained|failed to parse"),
    ("MODEL_FILE", r"unknown model architecture|invalid magic|failed to read magic|tensor '.*' data is not within|wrong number of tensors|gguf_init_from_file.*failed|unsupported .*architecture"),
    ("OOM", r"failed to allocate|out of memory|cannot allocate memory|std::bad_alloc|ErrorOutOfDeviceMemory"),
    ("MISSING_RUNTIME", r"No such file or directory|not found|cannot open shared object|error while loading shared libraries"),
    ("ENGINE_BUG", r"GGML_ASSERT|Segmentation fault|core dumped|terminate called|SIGSEGV|SIGABRT"),
]


def classify(rc, text, capkill=False, oom_log=""):
    """Class for one launch. rc None = still healthy / killed by us after success."""
    if capkill or re.search(r"(earlyoom|oom-kill|Out of memory: Killed).*llama", oom_log or "", re.I):
        return "OOM"
    if rc in (127, 126):
        return "MISSING_RUNTIME"
    for cls, rx in PAT:
        if re.search(rx, text or "", re.I):
            if cls == "ENGINE_BUG" and re.search(r"n_ubatch|n_tokens <= n_batch|ubatch", text, re.I):
                return "BAD_PARAMS"  # encoder ubatch < prompt aborts inside an assert
            return cls
    if rc in (-9, 137):
        return "OOM"
    if rc in (-6, -11, 134, 139, -4, 132):
        return "ENGINE_BUG"
    return "OK" if rc in (0, None, -15) else "ENGINE_BUG"


def port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def rss_mib(pid):
    try:
        for l in open("/proc/%d/status" % pid):
            if l.startswith("VmRSS:"):
                return int(l.split()[1]) // 1024
    except OSError:
        pass
    return 0


def oom_log(since):
    out = ""
    for cmd in (["journalctl", "-k", "-u", "earlyoom", "--since", "@%d" % int(since), "--no-pager", "-q"], ["dmesg", "-T"]):
        try:
            out += subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout[-4000:]
        except Exception:
            pass
    return out


def mem_avail_mib():
    try:
        return [int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0] // 1024
    except Exception:
        return None


def killer(rc, capkill, log):
    """Which mechanism ended the process: matrix-cap, earlyoom, kernel-oom, systemd-oomd,
    cgroup-memmax, external-sigterm/sigkill, or None (not a kill)."""
    if capkill:
        return "matrix-headroom"
    for name, rx in (("earlyoom", r"earlyoom.*(sending|kill|SIG)"), ("systemd-oomd", r"systemd-oomd.*(Killed|kill)"),
                     ("cgroup-memmax", r"memory cgroup out of memory|oom-kill:.*oom_memcg=/user"),
                     ("kernel-oom", r"Out of memory: Killed process|oom-kill:")):
        if re.search(rx, log or "", re.I):
            return name
    return {-9: "external-sigkill", 137: "external-sigkill", -15: "external-sigterm"}.get(rc)


def run(cmd, cap_mib, timeout, ready, env=None):
    """Start cmd; ready(proc) -> True when healthy. Returns dict(rc, text, capkill, peak, secs)."""
    t0 = time.time()
    log = tempfile.TemporaryFile("w+")
    try:
        p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True,
                             preexec_fn=oom_adj.preexec())
    except FileNotFoundError as e:
        return {"rc": 127, "text": str(e), "capkill": False, "peak": 0, "secs": 0, "ready": False}
    LIVE.add(p.pid)
    if cap_mib:
        okad, why = ls.admit(cap_mib, p.pid, os.path.basename(cmd[0]))
        if not okad:
            os.killpg(p.pid, signal.SIGKILL); p.wait(); LIVE.discard(p.pid)
            return {"rc": "ADMISSION", "text": why, "capkill": False, "peak": 0, "secs": 0, "ready": False}
    peak, capkill, ok, last_rss, last_avail, warned = 0, False, False, 0, None, False
    while time.time() - t0 < timeout:
        if p.poll() is not None:
            ok = p.returncode == 0
            break
        last_rss, last_avail = rss_mib(p.pid), mem_avail_mib()
        peak = max(peak, last_rss)
        if cap_mib and peak > cap_mib and not warned:
            warned = True  # above the measured-peak estimate: warn only (#95)
            print("WARN rss %d MiB > peak cap %d MiB: %s" % (peak, cap_mib, os.path.basename(cmd[0])), file=sys.stderr, flush=True)
        hard = bg.headroom_cap_mib()
        if hard and last_rss and mem_avail_mib() is not None and mem_avail_mib() < 1536 and last_rss > 256:
            capkill = True  # host headroom exhausted (MemAvailable < 1.5 GiB reserve)
            os.killpg(p.pid, signal.SIGKILL)
            break
        if ready(p):
            ok = True
            break
        time.sleep(0.5)
    t_ready = round(time.time() - t0, 1) if ok else None
    rc = p.poll()
    if rc is None:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); p.wait()
        rc = None if ok else "TIMEOUT"
    LIVE.discard(p.pid)
    ls.release(p.pid)
    log.seek(0)
    text = log.read()[-6000:]
    return {"rc": rc, "text": text, "capkill": capkill, "peak": peak, "secs": round(time.time() - t0, 1),
            "oom": oom_log(t0) if rc in (-9, 137, -15) or capkill else "",
            "rss_at_death_mib": last_rss, "memavail_at_death_mib": last_avail, "memavail_after_mib": mem_avail_mib(), "ready": ok, "t_ready_s": t_ready}


def http_ok(url, body=None):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=120)
        return r.status == 200 and (body is None or b"content" in r.read())
    except Exception:
        return False


def chat(p, prompt="Say hi."):
    b = json.dumps({"messages": [{"role": "system", "content": prompt}, {"role": "user", "content": "hi"}],
                    "max_tokens": 4, "temperature": 0}).encode()
    return http_ok("http://127.0.0.1:%d/v1/chat/completions" % p, b)


def render_hermes(mode):
    d = tempfile.mkdtemp()
    a = ["sh", os.path.join(HERE, "hermes.sh"), "--mode", mode] + (["--model", "coder"] if mode == "single" else []) + ["--render-only"]
    try:
        out = subprocess.run(a, capture_output=True, text=True, timeout=120, env=dict(os.environ, HERMES_HOME=d)).stdout
    except Exception:
        out = ""
    f = (glob.glob(d + "/SOUL.md") + glob.glob(d + "/*/SOUL.md") + [None])[0]
    return open(f).read() if f else (out or "You are hermes.")


def cap_for(model, ctx, host_limit):
    mib = os.path.getsize(model) / 2**20
    return bg.mem_cap_mib(mib + 64 + ctx / 1024 * 64, host_limit_mib=host_limit)


def one(engine, model, a, host_limit, legacy, dry):
    rec = {"engine": engine, "model": os.path.basename(model)}
    try:
        meta = bg.summarize(bg.read_gguf(model))
    except Exception as e:
        return dict(rec, cls="MODEL_FILE", why=str(e)[:120], args=[])
    ctx = min(4096, int(meta.get("context_length") or 4096))
    args = ["-m", model, "-c", str(ctx), "-t", str(a.threads), "-ngl", "0", "-lm", "none"]
    if bg.is_encoder(meta):
        args += ["--embeddings", "--pooling", "last", "-ub", "2048", "-b", "2048"]
    probs, args = bg.preflight(args, meta, legacy_gpu=legacy)
    docd = {k: "llama.cpp defaults (launch smoke test, 4 tokens)" for k in bg.DOCUMENTABLE}
    _, notes = bg.validate(meta, docd)
    rec.update(args=args[2:], notes=notes)
    binname = "llama-cli" if engine == "llama-cli" else "llama-server"
    b = os.path.join(a.bin_dir, binname)
    if probs:
        return dict(rec, cls=probs[0].split(":")[0], why=probs[0])
    if not os.access(b, os.X_OK):
        return dict(rec, cls="MISSING_RUNTIME", why=b)
    cap = cap_for(model, ctx, host_limit)
    if cap is None:
        return dict(rec, cls="OOM", why="does not fit host limit %s MiB (refused before launch)" % host_limit)
    rec["cap_mib"] = cap
    if dry:
        return dict(rec, cls="OK", why="dry-run")
    env = dict(os.environ, GGML_VK_VISIBLE_DEVICES="")
    if engine == "harness2":
        r = run([sys.executable, os.path.join(HERE, "harness2.py"), "status"], None, 60, lambda p: False, env)
    elif engine == "llama-cli":
        if bg.is_encoder(meta):
            return dict(rec, cls="SKIP", why="encoder: llama-cli has no embedding mode (served by llama-server)")
        cmd = [b] + args + ["-p", "hi", "-n", "4", "-st", "--temp", "0"]  # b11374: -no-cnv removed, -st single turn
        r = run(cmd, cap, a.timeout, lambda p: False, env)
    else:
        P = port()
        sysmsg = render_hermes(engine.split("-")[1]) if engine.startswith("hermes") else "Say hi."
        if bg.is_encoder(meta):
            ready = lambda p: http_ok("http://127.0.0.1:%d/health" % P)
        else:
            ready = lambda p: http_ok("http://127.0.0.1:%d/health" % P) and chat(P, sysmsg)
        r = run([b] + args + ["--host", "127.0.0.1", "--port", str(P), "--jinja"], cap, a.timeout, ready, env)
    rec.update(rc=r["rc"], peak_mib=r["peak"], secs=r["secs"])
    k = killer(r["rc"], r["capkill"], r.get("oom"))
    if k:
        rec.update(killer=k, rss_at_death_mib=r["rss_at_death_mib"], memavail_at_death_mib=r["memavail_at_death_mib"],
                   memavail_after_mib=r["memavail_after_mib"], premature=bool(r["memavail_at_death_mib"] and
                   r["memavail_at_death_mib"] > 1024))  # killed while >1 GiB was still available
    if r["rc"] == "ADMISSION":
        return dict(rec, cls="OOM", why="admission refused: " + r["text"], status=ls.record("LF_OOM_CAP", engine, rec["model"], {"args": args}, evidence=r["text"]))
    rec["cls"] = "TIMEOUT" if r["rc"] == "TIMEOUT" else classify(r["rc"], r["text"], r["capkill"], r.get("oom"))
    if rec["cls"] != "OK":
        rec["why"] = (r["text"].strip().splitlines() or [""])[-1][:160]
    code = ls.from_matrix_class(rec["cls"], r.get("ready"), r["rc"] if isinstance(r["rc"], int) else None, k, r["text"])
    rec["status"] = ls.record(code, engine, rec["model"], {"args": args, "cap_mib": cap}, r["rc"] if isinstance(r["rc"], int) else None,
                              -r["rc"] if isinstance(r["rc"], int) and r["rc"] < 0 else None, r["text"][-400:] if code[:2] != "OK" else "", r.get("t_ready_s"))
    return rec


def replay(h, a, models, host_limit, dry):
    m = next((x for x in models if h["model"].lower() in os.path.basename(x).lower()), None)
    out = {"id": h["id"], "symptom": h["symptom"]}
    if not m:
        return dict(out, verdict="NO_MODEL_LOCALLY")
    meta = bg.summarize(bg.read_gguf(m))
    res = {}
    for k in ("orig", "fixed"):
        args = ["-m", m] + h[k]
        probs, fixed_args = bg.preflight(h[k], meta)
        if h["tool"] == "serve":
            b = h.get("orig_bin") if k == "orig" else os.path.join(a.bin_dir, "llama-server")
            res[k] = "MISSING_RUNTIME" if not os.access(b, os.X_OK) else "OK"
            continue
        res[k + "_guard"] = probs[0].split(":")[0] if probs else "BAD_PARAMS(rewritten)" if fixed_args != h[k] else "OK"
        b = os.path.join(a.bin_dir, "llama-bench")
        if dry or not os.access(b, os.X_OK):
            res[k] = ("OK" if res[k + "_guard"].startswith("BAD_PARAMS(") else res[k + "_guard"]) if dry else "MISSING_RUNTIME(llama-bench)"
            continue
        if k == "orig":  # never re-run crash params: no intentional crashes or OOM kills (user rule)
            res[k] = res[k + "_guard"] if res[k + "_guard"] != "OK" else ("OOM(recorded)" if h.get("cap_mib") else "OK")
            continue
        cap = cap_for(m, 8192, host_limit)
        r = run([b, "-m", m] + fixed_args, cap, a.timeout * 3, lambda p: False,
                dict(os.environ, GGML_VK_VISIBLE_DEVICES=""))
        res[k] = classify(r["rc"], r["text"], r["capkill"], r.get("oom"))
        if killer(r["rc"], r["capkill"], r.get("oom")):
            res[k + "_kill"] = "%s rss=%s avail=%s" % (killer(r["rc"], r["capkill"], r.get("oom")), r["rss_at_death_mib"], r["memavail_at_death_mib"])
    bad = res.get("orig") != "OK" or res.get("orig_guard", "OK") != "OK" or h.get("cap_mib")
    verdict = ("ONLY_BAD_PARAMS" if bad and res.get("fixed") == "OK" else
               "NOT_REPRODUCED" if not bad else "STILL_FAILS:" + str(res.get("fixed")))
    return dict(out, verdict=verdict, **res)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bin-dir", required=True)
    ap.add_argument("--models", action="append", required=True)
    ap.add_argument("--engines", default=",".join(ENGINES))
    ap.add_argument("--out", default="launch_matrix.jsonl")
    ap.add_argument("--host-limit-mib", type=int)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--legacy-gpu", action="store_true", default=os.environ.get("FAMILIA_LEGACY_GPU") == "1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-replay", action="store_true")
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    if a.host_limit_mib is None:
        try:
            avail = [int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0] // 1024
            a.host_limit_mib = max(512, avail - 1536)
        except Exception:
            a.host_limit_mib = None
    models = sorted({m for d in a.models for m in glob.glob(os.path.join(d, "**", "*.gguf"), recursive=True)
                     if os.path.getsize(m) > 50 * 2**20 and "vocab" not in os.path.basename(m)})
    recs, counts = [], {}
    with open(a.out, "w") as f:
        for e in a.engines.split(","):
            for m in models:
                r = one(e, m, a, a.host_limit_mib, a.legacy_gpu, a.dry_run)
                r.setdefault("status", ls.record(ls.from_matrix_class(r["cls"], r["cls"] == "OK", None), e, r["model"], {"args": r.get("args", [])}, evidence=r.get("why", "")))
                recs.append(r); f.write(json.dumps(r) + "\n"); f.flush()
                counts[r["cls"]] = counts.get(r["cls"], 0) + 1
                if r["cls"] not in ("OK", "SKIP"):
                    print("FAIL %s %s %s: %s%s" % (e, r["model"], r["cls"], r.get("why", ""), " [killer=%s rss=%s avail=%s premature=%s]" % (
                        r["killer"], r["rss_at_death_mib"], r["memavail_at_death_mib"], r["premature"]) if r.get("killer") else ""), flush=True)
        reps = [] if a.no_replay else [replay(h, a, models, a.host_limit_mib, a.dry_run) for h in HISTORY]
        for r in reps:
            f.write(json.dumps(dict(r, kind="replay")) + "\n")
            print("REPLAY %(id)s: %(verdict)s" % r, flush=True)
    print("MATRIX %d launches: %s" % (len(recs), " ".join("%s=%d" % kv for kv in sorted(counts.items()))))
    return 0 if set(counts) <= {"OK", "SKIP"} else 1


if __name__ == "__main__":
    sys.exit(main())
