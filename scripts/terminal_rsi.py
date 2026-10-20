#!/usr/bin/env python3
"""Terminal-RSI for familia (#88): recursive self-improvement of a harness on terminal tasks.

Adapted from Tencent's Terminal-RSI recipe (collect trajectories -> the model self-rewrites
its successful ones -> policy refinement) to local models WITHOUT weight updates: the
"policy" is the target harness' editable text (here: the long-term memory section), so a
round produces a Harness² proposal in the same store scripts/harness2.py reviews.

  1. rollout: k samples per evolve task (temperature > 0), each answer = one shell command,
     run in a throwaway sandbox (fixture copy, no network when unshare works, rlimits,
     timeout, minimal env) and checked by exact stdout;
  2. self-rewrite: each successful trajectory is rewritten by the same model into one
     short task-agnostic lesson (never sees holdout tasks);
  3. refine: lessons that pass self_improve.gate() one by one are written into
     LongTermMEMORY.md; the whole tree passes the gate again (no tool/permission text,
     no task-id leakage, editable files only);
  4. evaluate base vs refined on holdout at temperature 0; recurse from the refined tree.

Safety (inherited, not configurable): proposals only (accept/apply stays
`harness2.py accept`, consent-gated); pentest agents/models refused; endpoint loopback
only; nothing here adds tools, toolsets or scope: the evaluator runs the command, the
agent's own tool configuration is never read or written.

  python3 scripts/terminal_rsi.py --target hermes-lab [--endpoint http://127.0.0.1:P/v1]
      [--rounds 2] [--k 2] [--temp 0.7] [--root-override DIR] [--state-root DIR] [--json OUT]
"""
import argparse, json, os, re, resource, shutil, subprocess, sys, tempfile, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import self_improve as SI  # noqa: E402

THINK = re.compile(r"<think>.*?</think>", re.S)
MEM = "LongTermMEMORY.md"
HDR = "## Shell lessons (Terminal-RSI, self-rewritten from successful runs)"
ASK = ("\n\nAnswer with exactly one shell command in a ```sh code block. The current directory "
       "holds the files. Use only standard tools (coreutils, grep, sed, awk, sort, find); no network.")
REWRITE = ("Here is a shell task and a command that solved it.\nTASK: {p}\nCOMMAND: {c}\n\n"
           "Write ONE short, general lesson (max 25 words) that would help with other shell tasks of this "
           "kind. Do not mention file names, words or numbers from this task. Output only the lesson.")

def load_tasks(name):
    d = json.load(open(os.path.join(SI.TASKS_DIR, name + ".json")))
    if d.get("kind") != "terminal": raise SystemExit(f"terminal_rsi: {name} is not a terminal task set")
    return d

def leak_terms(ts):
    terms = {t["id"] for t in ts["tasks"]}
    for f in ts["fixture"]: terms |= {f, os.path.basename(f)}
    for t in ts["tasks"]:
        if t["split"] == "holdout": terms |= {w for w in re.findall(r"[A-Za-z]{4,}", t["expect"])}
    return sorted(terms)

def make_chat(endpoint, timeout=900):
    host = re.sub(r"^https?://", "", endpoint).split("/")[0].rsplit(":", 1)[0].strip("[]")
    if host not in SI.LOOPBACK: raise SystemExit(f"terminal_rsi: endpoint {endpoint} is not loopback")
    def chat(msgs, max_tokens=256, temp=0.0, seed=0):
        b = json.dumps({"messages": msgs, "max_tokens": max_tokens, "temperature": temp, "seed": seed,
                        "chat_template_kwargs": {"enable_thinking": False}}).encode()
        r = urllib.request.urlopen(urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", b,
                                   {"Content-Type": "application/json"}), timeout=timeout)
        return THINK.sub("", json.load(r)["choices"][0]["message"].get("content") or "").strip()
    return chat

def extract_cmd(ans):
    m = re.search(r"```(?:sh|bash|shell)?\s*\n(.*?)```", ans, re.S)
    lines = [l for l in (m.group(1) if m else ans).strip().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    return re.sub(r"^\$\s*", "", lines[0]).strip() if lines else ""

_NONET = None
def _nonet():
    global _NONET
    if _NONET is None:
        u = shutil.which("unshare")
        _NONET = [u, "-rn"] if u and subprocess.run([u, "-rn", "true"], capture_output=True).returncode == 0 else []
    return _NONET

def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5)); resource.setrlimit(resource.RLIMIT_AS, (512 << 20, 512 << 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))

def check(ts, task, cmd, timeout=10):
    """-> (passed, detail). Runs one command in a fresh copy of the fixture."""
    if not cmd: return False, "no command"
    with tempfile.TemporaryDirectory(prefix="familia-trsi-") as d:
        for rel, txt in ts["fixture"].items():
            p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(txt)
        try:
            p = subprocess.run(_nonet() + ["/bin/sh", "-c", cmd], cwd=d, capture_output=True, text=True, timeout=timeout,
                               env={"PATH": "/usr/bin:/bin", "HOME": d, "LC_ALL": "C"}, preexec_fn=_limits, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired: return False, "timeout"
        out = "\n".join(l.rstrip() for l in p.stdout.strip().splitlines())
        return out == task["expect"], ("ok" if out == task["expect"] else f"rc={p.returncode} out={out[:60]!r}")

def solve(chat, tree, task, temp=0.0, seed=0):
    return extract_cmd(chat([{"role": "system", "content": SI.compose(tree)},
                             {"role": "user", "content": task["prompt"] + ASK}], 200, temp, seed))

def score(chat, ts, tree, split):
    r = {}
    for t in ts["tasks"]:
        if t["split"] == split: c = solve(chat, tree, t); r[t["id"]] = [check(ts, t, c)[0], c]
    return r

def with_lessons(tree, lessons):
    new = dict(tree); mem = new.get(MEM, "").split(HDR)[0].rstrip()
    new[MEM] = (mem + "\n\n" if mem else "") + HDR + "\n" + "".join(f"- {l}\n" for l in lessons)
    return new

def round_(chat, ts, tree, k, temp, leaks, log):
    traj, lessons, rejected = [], [], []
    for t in [t for t in ts["tasks"] if t["split"] == "evolve"]:
        for s in range(k):
            c = solve(chat, tree, t, temp, seed=1 + s); ok, why = check(ts, t, c)
            traj.append({"id": t["id"], "seed": 1 + s, "cmd": c, "ok": ok, "why": why})
            if ok:
                l = chat([{"role": "user", "content": REWRITE.format(p=t["prompt"], c=c)}], 80, 0.0)
                l = " ".join(l.replace("\n", " ").strip(" -*\"'").split())[:200]
                errs = SI.gate(tree, with_lessons(tree, [l]), leaks) if l else ["empty"]
                (rejected if errs else lessons).append(l if not errs else {"lesson": l, "why": errs[0][:120]})
                break  # one successful trajectory per task is enough to rewrite
    old = [x[2:].strip() for x in tree.get(MEM, "").split(HDR)[-1].splitlines() if x.startswith("- ")] if HDR in tree.get(MEM, "") else []
    keep = list(dict.fromkeys(old + lessons))[-8:]
    log(f"  rollouts {sum(x['ok'] for x in traj)}/{len(traj)} ok, lessons +{len(lessons)} (rejected {len(rejected)}), memory {len(keep)}")
    return with_lessons(tree, keep), {"trajectories": traj, "lessons": lessons, "rejected": rejected}

def refuse_pentest(g, tname):
    h = (g.get("harnesses") or {}).get(tname) or {}
    n = (g.get("nodes") or {}).get(h.get("node")) or {}
    if h.get("agent") in SI.pentest_agents(g) or ((g.get("models") or {}).get(n.get("model")) or {}).get("role") == "pentest":
        raise SystemExit(f"terminal_rsi: target {tname} is a pentest agent/model; pentest roles never self-improve")

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--graph", default=os.path.join(SI.ROOT, "graph.yaml")); ap.add_argument("--target", required=True)
    ap.add_argument("--tasks", default="terminal-v1"); ap.add_argument("--endpoint")
    ap.add_argument("--rounds", type=int, default=2); ap.add_argument("--k", type=int, default=2); ap.add_argument("--temp", type=float, default=0.7)
    ap.add_argument("--root-override"); ap.add_argument("--state-root"); ap.add_argument("--json")
    a = ap.parse_args(argv)
    import yaml
    g = yaml.safe_load(open(a.graph)); refuse_pentest(g, a.target)
    if a.k > 4: raise SystemExit("terminal_rsi: k > 4")
    t = SI.target(g, a.target, a.root_override); st = SI.State(t, a.state_root); st.init()
    ts = load_tasks(a.tasks); leaks = leak_terms(ts); chat = make_chat(a.endpoint or t.endpoint)
    base_v = st.current(); base = st.tree(base_v); tree = base; rounds = []
    b = score(chat, ts, base, "holdout"); bs = sum(v[0] for v in b.values())
    print(f"terminal_rsi: {t.name} base {base_v} holdout {bs}/{len(b)}")
    for r in range(1, a.rounds + 1):
        tree, info = round_(chat, ts, tree, a.k, a.temp, leaks, print)
        s = score(chat, ts, tree, "holdout"); info["holdout"] = s; rounds.append(info)
        print(f"  round {r}: holdout {sum(v[0] for v in s.values())}/{len(s)}")
    errs = SI.gate(base, tree, leaks)
    best = max(range(len(rounds)), key=lambda i: sum(v[0] for v in rounds[i]["holdout"].values())) if rounds else None
    fs = sum(v[0] for v in rounds[-1]["holdout"].values()) if rounds else bs
    status = "rejected" if errs else ("pending" if fs > bs else "no-gain")
    meta = st.save_proposal(st.new_proposal_id(), base_v, tree, {"status": status, "engine": "terminal-rsi", "tasks": a.tasks,
                            "k": a.k, "rounds": a.rounds, "temp": a.temp, "holdout": {"base": bs, "refined": fs, "n": len(b)},
                            "gate": errs, "leak_terms": leaks})
    out = {"target": t.name, "proposal": meta["id"], "status": status, "base": b, "rounds": rounds, "gate": errs, "best_round": best}
    if a.json: json.dump(out, open(a.json, "w"), indent=1)
    print(f"terminal_rsi: proposal {meta['id']} {status}: holdout {bs} -> {fs} of {len(b)} (review: harness2.py show --target {t.name} {meta['id']})")
    return 0

if __name__ == "__main__": sys.exit(main())
