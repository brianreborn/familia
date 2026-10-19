"""Self-improving harness settings layer (docs/harness2.md, #65).

Independent of any particular agent. It knows two graph types and a file layout:

  harnesses.<name>     a *target harness descriptor*: where one agent's prompt, guardrails,
                       memory and skills files live (root + relative paths) and which local
                       node serves as the editing/evaluating endpoint. Any agent can have one:
                       hermes, a code-bootstraps agent, a green-roomz agent, or a plain
                       directory with no agent at all.
  self_improve.<name>  an optimizer setting (engine harness2) that points at descriptors:
                       mode off|propose|apply, k, recursion, task set.

This module imports neither hermes nor harness2. scripts/harness2_local.py is the
Harness² engine adapter, scripts/harness2.py the review CLI, and any launcher (hermes.sh
included) may call `harness2.py sync` as a subprocess; nothing requires the others.

Safety (enforced here, not configurable):
  * a target used by a pentest agent, or served by a role:pentest model, cannot be enabled;
  * descriptors name prompt/guardrails/memory/skills only; there is no field for tools,
    toolsets, plugins, scripts or sub-agents, so a proposal cannot reach them;
  * every proposal passes `gate()`: editable files only, no tool/permission widening text,
    no leakage of evaluation task identifiers; anything else rejects the whole proposal.
"""
import datetime, difflib, json, os, re, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.join(ROOT, "harness", "base")
TASKS_DIR = os.path.join(ROOT, "registry", "harness2-tasks")
STATE_ROOT = os.environ.get("FAMILIA_HARNESS2_STATE") or os.path.join(ROOT, ".cache", "familia", "harness2")
CONSENT = os.environ.get("FAMILIA_SELF_IMPROVE_CONSENT") or os.path.join(ROOT, ".cache", "familia", "self-improve-consent.json")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MODES = ("off", "propose", "apply")

# ---- graph types (registered in scripts/graph_types.py) ---------------------
HARNESS_FIELDS = ("kind", "root", "prompt", "guardrails", "memory", "skills", "node", "agent", "notes")
SELF_IMPROVE_FIELDS = ("experimental", "engine", "mode", "targets", "k", "recursion", "tasks", "max_tasks", "notes")

def _relpath_ok(p):
    return isinstance(p, str) and p and not p.startswith("/") and ".." not in p.replace("\\", "/").split("/")

def pentest_agents(g):
    return {p.get("agent") for p in (g.get("pentests") or {}).values() if isinstance(p, dict)}

def check_harness(g, name, h, errs):
    w = f"harnesses.{name}"
    for k in ("prompt", "guardrails", "memory", "skills"):
        if k in h and h[k] is not None and not _relpath_ok(h[k]):
            errs.append(f"{w}.{k}: must be a relative path under root (no '..'), got {h[k]!r}")
    if h.get("prompt") and h.get("prompt") in [h.get(k) for k in ("guardrails", "memory")]:
        errs.append(f"{w}: prompt, guardrails and memory must be different files (omit one to keep it a section of the prompt)")
    n = (g.get("nodes") or {}).get(h.get("node")) if isinstance(h.get("node"), str) else None
    if isinstance(n, dict):
        if str(n.get("bind")) not in LOOPBACK:
            errs.append(f"{w}.node: {h['node']!r} binds {n.get('bind')!r}; the editing endpoint must be loopback (no egress beyond local models)")

def check_self_improve(g, name, s, errs):
    w = f"self_improve.{name}"
    if s.get("mode") is False:
        errs.append(f"{w}.mode: YAML read bare off as false; write mode: \"off\"")
    if isinstance(s.get("k"), int) and s["k"] > 4:
        errs.append(f"{w}.k: {s['k']} > 4 (each candidate costs a full editor+rollout pass on a local model)")
    if s.get("mode") == "off":
        return
    pa = pentest_agents(g)
    for t in s.get("targets") or []:
        h = (g.get("harnesses") or {}).get(t) if isinstance(t, str) else None
        if not isinstance(h, dict): continue
        n = (g.get("nodes") or {}).get(h.get("node")) if isinstance(h.get("node"), str) else None
        if isinstance(n, dict) and ((g.get("models") or {}).get(n.get("model")) or {}).get("role") == "pentest":
            errs.append(f"{w}: target {t!r} node {h['node']!r} serves a role:pentest model; pentest models never self-improve")
        if h.get("agent") in pa:
            errs.append(f"{w}: target {t!r} is agent {h['agent']!r}, which a pentest uses; "
                        "pentest roles never self-improve (declare a separate agent for experiments)")
    if isinstance(s.get("tasks"), str) and not os.path.isfile(os.path.join(TASKS_DIR, s["tasks"] + ".json")):
        errs.append(f"{w}.tasks: no task set registry/harness2-tasks/{s['tasks']}.json")

# ---- resolution --------------------------------------------------------------
class Target:
    """Adapter boundary: everything an optimizer needs to know about one harness."""
    def __init__(self, name, root, prompt, guardrails=None, memory=None, skills=None,
                 endpoint=None, model=None, node=None, agent=None):
        self.name, self.root = name, os.path.expanduser(root)
        self.prompt, self.guardrails, self.memory, self.skills = prompt, guardrails, memory, skills
        self.endpoint, self.model, self.node, self.agent = endpoint, model, node, agent

    def path(self, rel): return os.path.join(self.root, rel) if rel else None
    def as_dict(self): return dict(vars(self))

def target(g, name, root_override=None):
    h = (g.get("harnesses") or {}).get(name)
    if not isinstance(h, dict):
        raise SystemExit(f"harness2: no harnesses.{name} in the graph (declared: {sorted(g.get('harnesses') or {})})")
    n = g["nodes"][h["node"]]
    alias = next((a for a, al in (g.get("aliases") or {}).items() if al.get("node") == h["node"]), h["node"])
    return Target(name, root_override or h["root"], h["prompt"], h.get("guardrails"), h.get("memory"), h.get("skills"),
                  endpoint=f"http://{n['bind']}:{n['port']}/v1", model=alias, node=h["node"], agent=h.get("agent"))

def settings_for(g, tname):
    """(setting name, setting) of the self_improve entry targeting tname, or (None, None)."""
    for sname, s in (g.get("self_improve") or {}).items():
        if tname in (s.get("targets") or []): return sname, s
    return None, None

def targets_for_agent(g, agent):
    return [t for t, h in (g.get("harnesses") or {}).items() if h.get("agent") == agent]

# ---- trees: rel path -> text (Harness² c1..c8 layout, editable subset) -------
ALWAYS_ON = ("systemprompt.md", "guardrails.md", "LongTermMEMORY.md")
FROZEN = ("tool_descriptions/tool_guidance.md",)
SKILL_RE = re.compile(r"skills/([a-z0-9][a-z0-9_\-]*)/SKILL\.md")
STUB_RE = re.compile(r"(skills|sub_agents|scripts|plugin)/README\.md")
DENY = [re.compile(p, re.I) for p in (
    r"\b(enable|unlock|grant|allow|add|turn on|widen)\b[^.\n]{0,40}\b(tools?|toolsets?|terminal|shell|network|internet|sudo|root|permissions?|exec)\b",
    r"\b(ignore|bypass|disable|override|skip)\b[^.\n]{0,40}\b(guardrails?|safety|approvals?|confirm(ation)?s?|restrictions?|sandbox)\b",
    r"\b(curl|wget|nc|netcat|nmap|ssh|scp)\s+\S", r"\bsudo\b", r"\brm\s+-rf\b",
    r"\bdisabled_toolsets\b", r"\bapproval(s)?\s*:\s*(off|false|never)\b",
)]

def read_dir_tree(d):
    out = {}
    for dp, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(dp, f); rel = os.path.relpath(p, d).replace(os.sep, "/")
            if "__pycache__" in rel: continue
            with open(p, encoding="utf-8", errors="replace") as fh: out[rel] = fh.read()
    return out

def write_dir_tree(tree, d):
    if os.path.isdir(d): shutil.rmtree(d)
    for rel, txt in tree.items():
        p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh: fh.write(txt)

def editable(tree):
    return {r: t for r, t in tree.items() if r in ALWAYS_ON or SKILL_RE.fullmatch(r)}

def base_tree(t):
    """The target's current files as a tree (first use), base templates filling gaps."""
    base = read_dir_tree(BASE_DIR)
    tree = {r: base.get(r, "") for r in ALWAYS_ON + FROZEN}
    for key, rel in (("prompt", "systemprompt.md"), ("guardrails", "guardrails.md"), ("memory", "LongTermMEMORY.md")):
        p = t.path(getattr(t, key))
        if p and os.path.isfile(p):
            tree[rel] = open(p, encoding="utf-8", errors="replace").read()
    return tree

def gate(base, tree, leak_terms=(), allow_skills=True):
    """familia's own safety gate on a proposed tree; returns a list of errors (empty = ok)."""
    errs = []
    for rel in sorted(tree):
        if rel in ALWAYS_ON or rel in FROZEN or STUB_RE.fullmatch(rel): continue
        if SKILL_RE.fullmatch(rel):
            if not allow_skills: errs.append(f"{rel}: this target declares no skills directory")
            continue
        errs.append(f"{rel}: not on familia's editable surface (only prompt, guardrails, memory, skills/<n>/SKILL.md); "
                    "scripts, plugins, sub-agents and tool files are never applied")
    for rel in FROZEN:
        if tree.get(rel, "") != base.get(rel, ""): errs.append(f"{rel}: tool descriptions are frozen in familia")
    if not tree.get("systemprompt.md", "").strip(): errs.append("systemprompt.md: empty prompt")
    for rel, txt in sorted(editable(tree).items()):
        old = set(base.get(rel, "").splitlines())
        added = [l for l in txt.splitlines() if l not in old]
        for l in added:
            for rx in DENY:
                if rx.search(l): errs.append(f"{rel}: tool/permission-widening text rejected: {l.strip()[:120]!r}"); break
            for term in leak_terms:
                if term and re.search(rf"\b{re.escape(term)}\b", l):
                    errs.append(f"{rel}: names evaluation task item {term!r} (leakage; harness must stay task-agnostic)"); break
    return errs

def compose(tree):
    """One always-on text, as a target with prompt-only layout would see it."""
    parts = [tree.get("systemprompt.md", "").strip()]
    for rel, title in (("guardrails.md", "Guardrails"), ("LongTermMEMORY.md", "Long-term memory")):
        if tree.get(rel, "").strip(): parts.append(f"## {title}\n\n{tree[rel].strip()}")
    for rel in sorted(r for r in tree if SKILL_RE.fullmatch(r)):
        parts.append(f"## Skill: {SKILL_RE.fullmatch(rel).group(1)}\n\n{tree[rel].strip()}")
    return "\n\n".join(p for p in parts if p) + "\n"

def diff(a, b):
    out = []
    for rel in sorted(set(editable(a)) | set(editable(b))):
        out += difflib.unified_diff(a.get(rel, "").splitlines(True), b.get(rel, "").splitlines(True), f"a/{rel}", f"b/{rel}")
    return "".join(out)

# ---- state: versions, proposals, export --------------------------------------
def now(): return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class State:
    def __init__(self, t, root=None):
        self.t, self.dir = t, os.path.join(root or STATE_ROOT, t.name)

    def p(self, *a): return os.path.join(self.dir, *a)
    def _json(self, rel, default=None):
        p = self.p(rel)
        return json.load(open(p)) if os.path.isfile(p) else default
    def _wjson(self, rel, obj):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), "w") as f: json.dump(obj, f, indent=1)
    def log(self, **ev):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.p("history.jsonl"), "a") as f: f.write(json.dumps(dict(ev, at=now())) + "\n")

    def init(self):
        """Version 0000 = the target's own files as first seen; originals backed up."""
        if os.path.isdir(self.p("versions", "0000")): return
        t = self.t; orig = {}
        for key in ("prompt", "guardrails", "memory"):
            rel = getattr(t, key); p = t.path(rel)
            orig[key] = {"rel": rel, "existed": bool(p and os.path.isfile(p))}
            if orig[key]["existed"]:
                os.makedirs(self.p("original"), exist_ok=True); shutil.copy2(p, self.p("original", key))
        write_dir_tree(base_tree(t), self.p("versions", "0000", "tree"))
        self._wjson("original.json", orig)
        self._wjson("versions/0000/meta.json", {"version": "0000", "from": "target files", "at": now()})
        self.set_current("0000")
        self.log(event="init", version="0000")

    def current(self):
        p = self.p("CURRENT")
        return open(p).read().strip() if os.path.isfile(p) else None
    def set_current(self, v):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.p("CURRENT"), "w") as f: f.write(v + "\n")
    def versions(self):
        d = self.p("versions")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []
    def tree(self, v=None):
        return read_dir_tree(self.p("versions", v or self.current(), "tree"))
    def proposals(self):
        d = self.p("proposals")
        out = []
        for pid in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            out.append(self._json(f"proposals/{pid}/meta.json", {"id": pid, "status": "broken"}))
        return out
    def proposal(self, pid):
        m = self._json(f"proposals/{pid}/meta.json")
        if m is None: raise SystemExit(f"harness2: no proposal {pid!r} for target {self.t.name} (see: harness2.py list --target {self.t.name})")
        return m
    def new_proposal_id(self):
        return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    def save_proposal(self, pid, base_version, tree, meta):
        write_dir_tree(tree, self.p("proposals", pid, "tree"))
        with open(self.p("proposals", pid, "diff.patch"), "w") as f: f.write(diff(self.tree(base_version), tree))
        meta = dict(meta, id=pid, base=base_version, at=meta.get("at") or now())
        self._wjson(f"proposals/{pid}/meta.json", meta); self.log(event="propose", id=pid, status=meta["status"])
        return meta

    def accept(self, pid):
        m = self.proposal(pid)
        if m["status"] != "pending":
            raise SystemExit(f"harness2: proposal {pid} is {m['status']}, only pending proposals can be accepted")
        if m["base"] != self.current():
            raise SystemExit(f"harness2: proposal {pid} was made against version {m['base']}, current is {self.current()}; "
                             "propose again (or revert to its base first)")
        tree = read_dir_tree(self.p("proposals", pid, "tree"))
        errs = gate(self.tree(m["base"]), tree, m.get("leak_terms", ()), allow_skills=bool(self.t.skills))
        if errs: raise SystemExit("harness2: proposal fails the gate now:\n  " + "\n  ".join(errs))
        v = f"{len(self.versions()):04d}"
        write_dir_tree(tree, self.p("versions", v, "tree"))
        self._wjson(f"versions/{v}/meta.json", {"version": v, "from": f"proposal {pid}", "parent": m["base"], "at": now()})
        m["status"], m["version"] = "accepted", v
        self._wjson(f"proposals/{pid}/meta.json", m)
        self.set_current(v); self.export(); self.log(event="accept", id=pid, version=v)
        return v

    def revert(self, to=None):
        """Back to the current version's parent (or --to VERSION; 0000 restores the original files)."""
        vs = self.versions(); cur = self.current()
        if to is None:
            to = self._json(f"versions/{cur}/meta.json", {}).get("parent")
            if to is None: raise SystemExit(f"harness2: {self.t.name} is at {cur}, nothing to revert to")
        if to not in vs: raise SystemExit(f"harness2: no version {to!r} (have {vs})")
        self.set_current(to); self.export(); self.log(event="revert", **{"from": cur, "to": to})
        return to

    def export(self, into=None):
        """Write the current version into the target's files (or a copy of its layout at `into`)."""
        t = self.t; root = os.path.expanduser(into) if into else t.root
        cur = self.current() or "0000"
        orig = self._json("original.json", {})
        manifest_rel = "exported.json" if into is None else f"exported-{re.sub(r'[^A-Za-z0-9]+', '_', root)}.json"
        man = self._json(manifest_rel, {"skills": []})
        if cur == "0000" and into is None:  # restore originals exactly
            for key, o in orig.items():
                p = os.path.join(root, o["rel"]) if o.get("rel") else None
                if not p: continue
                if o["existed"]: shutil.copy2(self.p("original", key), p)
                elif os.path.isfile(p): os.remove(p)
            tree = {}
        else:
            tree = self.tree(cur)
            sec = {"systemprompt.md": tree.get("systemprompt.md", "").rstrip() + "\n"}
            body = [f"<!-- managed by familia harness2 (target {t.name}, version {cur}); review with scripts/harness2.py -->\n",
                    sec["systemprompt.md"]]
            for key, rel, title in (("guardrails", "guardrails.md", "Guardrails"), ("memory", "LongTermMEMORY.md", "Long-term memory")):
                txt = tree.get(rel, "").strip()
                if getattr(t, key):
                    p = os.path.join(root, getattr(t, key)); os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                    with open(p, "w") as f: f.write(txt + "\n" if txt else "")
                elif txt:
                    body.append(f"\n## {title}\n\n{txt}\n")
            p = os.path.join(root, t.prompt); os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w") as f: f.write("".join(body))
        names = sorted(SKILL_RE.fullmatch(r).group(1) for r in tree if SKILL_RE.fullmatch(r))
        if names and not t.skills: raise SystemExit(f"harness2: version {cur} has skills but target {t.name} declares no skills dir")
        sk = os.path.join(root, t.skills) if t.skills else None
        for n in man["skills"]:
            if n not in names and sk and os.path.isdir(os.path.join(sk, n)): shutil.rmtree(os.path.join(sk, n))
        for n in names:
            d = os.path.join(sk, n)
            if os.path.exists(d) and n not in man["skills"]:
                raise SystemExit(f"harness2: {d} exists and is not managed by harness2; rename the skill or move that directory")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "SKILL.md"), "w") as f: f.write(tree[f"skills/{n}/SKILL.md"])
        self._wjson(manifest_rel, {"skills": names, "version": cur, "root": root})
        return root

# ---- consent (apply mode) ------------------------------------------------------
def load_consent(path=None):
    p = path or CONSENT
    return json.load(open(p)) if os.path.isfile(p) else {}

def has_consent(tname, path=None): return tname in load_consent(path)

def record_consent(tname, revoke=False, path=None):
    p = path or CONSENT; c = load_consent(p)
    if revoke: c.pop(tname, None)
    else: c[tname] = now()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: json.dump(c, f, indent=1)
