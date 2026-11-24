"""Harness² engine adapter for familia: local endpoint, offline task set (docs/harness2.md).

Works on a self_improve.Target only (prompt/guardrails/memory/skills files + an
OpenAI-compatible loopback endpoint). It never imports or launches any agent.

  install()            fetch the pinned upstream source tarball (sha256-checked) into the state dir
  LocalProposer        Harness²'s Proposer with the OpenCode/Vertex session replaced by one
                       chat call to the local endpoint: context files are inlined into the
                       prompt and <file path="harness/...">...</file> blocks in the reply are
                       written back (no bun, no OpenCode, no cloud credentials)
  LocalAdapter         Harness² BenchmarkAdapter over registry/harness2-tasks/<set>.json
  evaluate()           base vs proposal on evolve + holdout tasks, scored by asserts in a
                       throwaway subprocess (ground truth familia keeps; Harness² never sees it)
  propose()            one Harness² run_domain over the evolve split -> gated candidate tree
"""
import hashlib, io, json, os, re, resource, shutil, subprocess, sys, tarfile, tempfile, time, urllib.request
from pathlib import Path

import self_improve as SI
import familia_auth  # noqa: E402  (instance key for every chat()/health call)

H2_REPO = "https://github.com/google-research/harness2"
H2_COMMIT = "1cfe254e8d25b15f37048c3730134686abe60335"
H2_TARBALL = f"https://codeload.github.com/google-research/harness2/tar.gz/{H2_COMMIT}"
H2_SHA256 = "2337f91b71a130e055d8dfb99ead2667a46087c29df939d4d4f0a3c357b5748f"

def src_dir(state_root=None): return os.path.join(state_root or SI.STATE_ROOT, "_src", f"harness2-{H2_COMMIT[:12]}")

def installed(state_root=None):
    return os.path.isfile(os.path.join(src_dir(state_root), "harness2", "core", "schedule.py"))

def install(state_root=None, url=H2_TARBALL):
    """Download + verify + unpack the harness2 package (~0.6 MB of Python) and its LICENSE."""
    d = src_dir(state_root)
    if installed(state_root): return d
    with urllib.request.urlopen(url, timeout=300) as r: data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != H2_SHA256: raise SystemExit(f"harness2: tarball sha256 {got} != pinned {H2_SHA256}; not installing")
    tmp = d + ".tmp"; shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        top = f"harness2-{H2_COMMIT}/"
        for m in tf.getmembers():
            rel = m.name[len(top):] if m.name.startswith(top) else None
            if not rel or not (rel.startswith("harness2/") or rel in ("LICENSE", "pyproject.toml")): continue
            if not (m.isfile() or m.isdir()) or ".." in rel.split("/"): continue
            m.name = rel; tf.extract(m, tmp)
    with open(os.path.join(tmp, "PINNED"), "w") as f: f.write(f"{H2_REPO}@{H2_COMMIT} sha256={H2_SHA256}\n")
    os.makedirs(os.path.dirname(d), exist_ok=True); os.replace(tmp, d)
    return d

def import_h2(state_root=None, src=None):
    d = src or os.environ.get("FAMILIA_HARNESS2_SRC") or src_dir(state_root)
    if not os.path.isfile(os.path.join(d, "harness2", "core", "schedule.py")):
        raise SystemExit(f"harness2: engine not installed at {d}; run: scripts/harness2.py install")
    if d not in sys.path: sys.path.insert(0, d)
    import harness2  # noqa: F401
    return d

# ---- local model --------------------------------------------------------------
THINK = re.compile(r"<think>.*?</think>\s*", re.S)

def make_chat(endpoint, model, timeout=3600):
    """-> chat(messages, max_tokens) -> (text, usage). Loopback OpenAI-compatible endpoint only."""
    host = re.sub(r"^https?://", "", endpoint).split("/")[0].rsplit(":", 1)[0].strip("[]")
    if host not in SI.LOOPBACK: raise SystemExit(f"harness2: endpoint {endpoint} is not loopback")
    def chat(messages, max_tokens=2048):
        body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens,
                           "chat_template_kwargs": {"enable_thinking": False}}).encode()
        # every (recursive) Harness² chat() call carries the instance key; fail closed if none
        url = endpoint.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(url, body, familia_auth.auth_headers(
            {"Content-Type": "application/json"}, key=familia_auth.key_for_url(url), required=True))
        with urllib.request.urlopen(req, timeout=timeout) as r: d = json.load(r)
        return THINK.sub("", d["choices"][0]["message"].get("content") or ""), d.get("usage") or {}
    return chat

def endpoint_up(endpoint):
    try:
        with familia_auth.open_url(endpoint.rstrip("/").rsplit("/v1", 1)[0] + "/health", timeout=5) as r: return r.status == 200
    except Exception: return False

class Meter:
    def __init__(self, chat): self.chat, self.calls, self.prompt_tokens, self.completion_tokens, self.wall = chat, 0, 0, 0, 0.0
    def __call__(self, messages, max_tokens=2048):
        t0 = time.time(); text, u = self.chat(messages, max_tokens)
        self.wall += time.time() - t0; self.calls += 1
        self.prompt_tokens += int(u.get("prompt_tokens") or 0); self.completion_tokens += int(u.get("completion_tokens") or 0)
        return text, u
    def as_dict(self): return {"calls": self.calls, "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens, "wall_s": round(self.wall, 1)}

# ---- tasks and checking ---------------------------------------------------------
def load_tasks(name):
    d = json.load(open(os.path.join(SI.TASKS_DIR, name + ".json")))
    return {t["id"]: t for t in d["tasks"]}

def leak_terms(tasks): return sorted({t["id"] for t in tasks.values()} | {t["entry"] for t in tasks.values()})

CODE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)

def extract_code(answer):
    blocks = CODE.findall(answer or "")
    return blocks[-1] if blocks else (answer or "")

def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5)); resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))

def check(task, answer, timeout=20):
    """Run the task's asserts against the answer's code in a scratch dir. -> (passed, detail)."""
    with tempfile.TemporaryDirectory(prefix="familia-h2-check-") as d:
        Path(d, "solution.py").write_text(extract_code(answer))
        Path(d, "check.py").write_text("from solution import *\n" + task["tests"])
        try:
            p = subprocess.run([sys.executable, "-E", "-s", "check.py"], cwd=d, capture_output=True, text=True, timeout=timeout,
                               env={"PATH": "/usr/bin:/bin", "HOME": d}, preexec_fn=_limits, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired: return False, "timeout"
        last = (p.stderr.strip().splitlines() or [""])[-1]
        return p.returncode == 0, ("ok" if p.returncode == 0 else (last[:200] or f"rc={p.returncode} (killed: cpu/memory limit)"))

def self_check(task, answer):
    """What the agent itself could see (no hidden asserts): compiles, defines the entry."""
    code = extract_code(answer)
    try: compile(code, "solution.py", "exec"); ok = "ok"
    except SyntaxError as e: ok = f"SyntaxError: {e.msg} (line {e.lineno})"
    defines = bool(re.search(rf"^def {re.escape(task['entry'])}\s*\(", code, re.M))
    return f"python compile: {ok}; defines `{task['entry']}`: {'yes' if defines else 'no'}"

def run_task(chat, tree, task, max_tokens=1024):
    text, u = chat([{"role": "system", "content": SI.compose(tree)}, {"role": "user", "content": task["prompt"]}], max_tokens)
    return text

def evaluate(chat, trees, tasks, ids, log=print):
    """{label: {split: [passed, n], per_task: {id: bool}}} for each tree in `trees`."""
    out = {}
    for label, tree in trees.items():
        r = {"per_task": {}, "evolve": [0, 0], "holdout": [0, 0]}
        for tid in ids:
            t = tasks[tid]; ok, why = check(t, run_task(chat, tree, t))
            r["per_task"][tid] = ok; r[t["split"]][1] += 1; r[t["split"]][0] += int(ok)
            log(f"  eval {label:<8} {t['split']:<7} {tid:<20} {'PASS' if ok else 'fail: ' + why}")
        out[label] = r
    return out

# ---- Harness² integration ----------------------------------------------------------
FILE_RE = re.compile(r'<file\s+path="([^"]+)"\s*>\n?(.*?)</file>', re.S)
DEL_RE = re.compile(r'<delete\s+path="([^"]+)"\s*/>')
INLINE_MAX, INLINE_TOTAL = 16_000, 90_000
ORDER = ("task", "harness", "rollout", "deliverable", "decision", "pool", "library")

PROTOCOL = """
---
# How to deliver (familia local editor)
You cannot run tools or read files: every file of the working directory is inlined above
under "# FILE <path>". To create or replace a harness file, emit it complete:
<file path="harness/systemprompt.md">
...entire new content...
</file>
To delete one: <delete path="harness/skills/old/SKILL.md"/>
Files you do not emit stay unchanged. Only harness/systemprompt.md, harness/guardrails.md,
harness/LongTermMEMORY.md and harness/skills/<name>/SKILL.md can change in familia; scripts,
plugins, sub-agents and tool descriptions are rejected. Then give the rest of the requested
output (tags, blocks) as plain text.
"""

def inline_context(ctx):
    files = sorted((p for p in Path(ctx).rglob("*") if p.is_file()),
                   key=lambda p: (next((i for i, k in enumerate(ORDER) if k in str(p.relative_to(ctx)).lower()), len(ORDER)), str(p)))
    parts, total, skipped = [], 0, []
    for p in files:
        rel = str(p.relative_to(ctx))
        try: txt = p.read_text(encoding="utf-8")
        except UnicodeDecodeError: skipped.append(rel + " (binary)"); continue
        if len(txt) > INLINE_MAX: txt = txt[:INLINE_MAX] + f"\n[... truncated, {len(txt)} chars total]"
        if total + len(txt) > INLINE_TOTAL: skipped.append(rel + " (budget)"); continue
        parts.append(f"# FILE {rel}\n{txt}"); total += len(txt)
    if skipped: parts.append("# NOT INLINED\n" + "\n".join(skipped))
    return "\n\n".join(parts)

def apply_reply(ctx, text):
    """Write <file>/<delete> blocks under ctx/harness; return the reply with them removed."""
    h = Path(ctx) / "harness"
    for path, body in FILE_RE.findall(text):
        rel = re.sub(r"^(\./)?(context/)?", "", path.strip())
        if not rel.startswith("harness/") or ".." in rel.split("/") or rel.startswith("/"): continue
        p = Path(ctx) / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
    for path in DEL_RE.findall(text):
        rel = re.sub(r"^(\./)?(context/)?", "", path.strip())
        if rel.startswith("harness/") and ".." not in rel.split("/") and (Path(ctx) / rel).is_file(): (Path(ctx) / rel).unlink()
    h.mkdir(parents=True, exist_ok=True)
    return DEL_RE.sub("", FILE_RE.sub("", text)).strip()

def make_classes():
    """Built lazily so importing this module never needs the harness2 package."""
    from harness2.core.proposer import Proposer
    from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
    from harness2.core import tree as HT
    from harness2.substrate.opencode import OpencodeSubstrate

    class LocalProposer(Proposer):
        chat = None; max_tokens = 3072
        def _opencode(self, cwd, mission, system, wall):
            ctx = Path(cwd) / "context"; ctx.mkdir(exist_ok=True)
            user = mission + "\n\n---\n# WORKING DIRECTORY (context/)\n" + inline_context(ctx) + PROTOCOL
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
            try: text, _ = self.chat(msgs, self.max_tokens)
            except Exception as e: return "", 0.0, f"local endpoint: {type(e).__name__}: {e}"
            rest = apply_reply(ctx, text)
            return (rest or "(edits written)"), 0.0, ""

    class LocalAdapter:
        def __init__(self, root, tasks, evolve, base_tree, chat, leak, allow_skills):
            self.root, self.tasks_, self.evolve, self.chat = Path(root), tasks, evolve, chat
            self.base, self.leak, self.allow_skills = base_tree, leak, allow_skills
            self.substrate = OpencodeSubstrate()
            ch = ChannelSpec("opencode", "familia/local")
            self.spec = BenchSpec(name="familia", runs_root=self.root / "runs", install_mode="workspace_config",
                                  prompts=BenchPrompts(work="write small, correct Python functions from a short specification"),
                                  channels={"proposer": ch, "selector": ch})
            HT.write_tree(self.substrate.surface(), base_tree, self.base_harness(), stubs=False)
        def tasks(self, split="all"): return list(self.evolve)
        def domain_of(self, task_id): return "coding"
        def task_prompt(self, task_id): return self.tasks_[task_id]["prompt"]
        def task_files(self, task_id): return None
        def base_harness(self): return self.root / "base"
        def validate_tree(self, harness):
            errs = SI.gate(self.base, dict(harness), self.leak, self.allow_skills)
            if errs: raise ValueError(" | ".join(errs))
        def execute(self, task_id, harness_dir, run_id, *, timeout=None):
            run_dir = self.root / "executions" / run_id; run_dir.mkdir(parents=True, exist_ok=True)
            tree = HT.read_tree(self.substrate.surface(), harness_dir or self.base_harness())
            t = self.tasks_[task_id]
            ans = run_task(self.chat, tree, t)
            (run_dir / "answer.md").write_text(ans)
            (run_dir / "trajectory.md").write_text(
                f"[SYSTEM] harness composed ({len(SI.compose(tree))} chars)\n[USER]\n{t['prompt']}\n"
                f"[ASSISTANT]\n{ans}\n[OBSERVATION] {self_check(t, ans)}\n")
            return run_dir
        def delivered(self, run_dir): return bool((Path(run_dir) / "answer.md").is_file() and (Path(run_dir) / "answer.md").read_text().strip())
        def trajectory(self, run_dir, *, obs_trunc): return (Path(run_dir) / "trajectory.md").read_text()
        def deliverable_text(self, run_dir): return (Path(run_dir) / "answer.md").read_text()
        def deliverable_files(self, run_dir): return {"answer.md": self.deliverable_text(run_dir)}

    return LocalProposer, LocalAdapter, ChannelSpec, HT

def propose(t, tree, tasks, evolve, chat, out_dir, k=1, recursion="parallel", state_root=None, log=print):
    """One Harness² pass over the evolve split; -> (candidate tree or None, info)."""
    import_h2(state_root)
    import harness2.core.proposer as P
    from harness2.core.schedule import run_domain
    P._SEM = __import__("threading").BoundedSemaphore(1)  # one model session at a time on a small box
    LocalProposer, LocalAdapter, ChannelSpec, HT = make_classes()
    out = Path(out_dir)
    ad = LocalAdapter(out / "h2", tasks, evolve, tree, chat, leak_terms(tasks), bool(t.skills))
    prop = LocalProposer(ChannelSpec("opencode", f"familia/{t.node}", timeout=7200), audit_dir=out / "audit", attempts=2)
    prop.chat = chat
    mode = {"parallel": "agg", "sequential": "seq"}[recursion]
    res = run_domain("coding", list(evolve), k, adapter=ad, prop=prop, runs_root=ad.spec.runs_root,
                     library_root=out / "h2" / "library", modes=(mode,))
    info = {"run_domain": res, "mode": mode}
    for tid in reversed(list(evolve)):
        for sp in sorted((out / "h2" / "runs").glob(f"*/{tid}/summary.json")):
            sel = (json.load(open(sp)).get("selections") or {}).get(mode) or {}
            if not sel.get("ok"): continue
            info["chosen"] = {"task": tid, "label": sel.get("chosen_label"), "is_base": bool(sel.get("chosen_is_base")),
                              "why": sel.get("why"), "experience": sel.get("experience")}
            if sel.get("chosen_is_base"): return None, info
            cand = HT.read_tree(ad.substrate.surface(), sp.parent / "harnesses" / sel["chosen_label"])
            return dict(cand), info
    return None, info
