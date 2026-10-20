#!/usr/bin/env python3
"""Harness² review CLI (docs/harness2.md). Reviews; never launches an agent.

usage: harness2.py [--graph FILE] [--state DIR] COMMAND [--target NAME] ...

  status   [--target T]                 settings, versions, pending proposals, endpoint, engine
  set      --agent A --mode off|propose|apply [--dry-run] [--yes]
                                        switch Harness² for one agent in graph.yaml (comments kept;
                                        declares a descriptor for a hermes-agent agent if it has none)
  review   [--target T] [--dry-run]     pending proposals; on a terminal, accept / skip / revert each
  install                               fetch the pinned Harness² source (sha256-checked)
  propose  --target T [--enable] [--k K] [--max-tasks N] [--start-node] [--record] [--dry-run]
                                        one Harness² pass on the evolve tasks -> gated, evaluated proposal
  list     --target T                   proposals and versions
  show     --target T ID                diff + evaluation of one proposal
  accept   --target T ID                apply a pending proposal to the target's files (new version)
  revert   --target T [--to VERSION]    back to the parent version (0000 = original files)
  consent  --target T [--revoke]        allow (or stop) mode apply from accepting by itself
  sync     --target T [--into DIR]      write the current version into the target's files (or a
                                        copy of its layout under DIR); what a launcher calls

--root DIR replaces the target's root (a scratch copy, tests). Works without hermes installed.
Licenses (scripts/licenses.py) are accepted before a node is started (--start-node), before a mode
other than off is written by `set`, and must already be accepted for mode apply. --yes accepts.

example: scripts/harness2.py propose --target hermes-lab --dry-run
"""
import argparse, json, os, signal, subprocess, sys, time
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import self_improve as SI  # noqa: E402
import oom_adj  # noqa: E402

def die(msg, code=1): print(f"harness2: {msg}", file=sys.stderr); sys.exit(code)

def load_graph(path, check_files=False):
    import validate_graph as vg
    g = yaml.safe_load(open(path)); g["_path"] = path
    errs, _ = vg.validate(g, check_files=check_files)
    for e in errs: print(f"graph: ERROR: {e}", file=sys.stderr)
    if errs: die("graph validation failed")
    return g

def setting(g, tname, enable=False):
    sname, s = SI.settings_for(g, tname)
    if s is None: die(f"no self_improve entry lists target {tname!r} in targets")
    s = dict(s)
    if s["mode"] == "off":
        if not enable: die(f"self_improve.{sname}.mode is off; set mode: propose in the graph, or pass --enable for this one run")
        s["mode"] = "propose"
        errs = []; SI.check_self_improve(g, sname, s, errs)
        if errs: die("; ".join(errs))
    return sname, s

def licenses(graph_path, cmd="gate", yes=False):
    lp = os.path.join(ROOT, "scripts", "licenses.py")
    if not os.path.isfile(lp): die("scripts/licenses.py not found; licenses must be accepted first")
    rc = subprocess.run([sys.executable, lp, cmd, "--graph", graph_path] + (["--yes"] if yes and cmd == "gate" else [])).returncode
    if rc != 0:
        die(f"licenses not accepted (scripts/licenses.py {cmd} exit {rc}); nothing was changed or started. "
            "Accept with scripts/licenses.py review, or pass --yes")

def start_node(g, node, yes=False):
    licenses(g["_path"], "gate", yes)
    import validate_graph as vg
    errs, _ = vg.validate(g, check_files=True)
    if errs: die("cannot start node: " + "; ".join(errs[:3]))
    logd = os.path.join(ROOT, ".cache", "familia", "logs"); os.makedirs(logd, exist_ok=True)
    log = open(os.path.join(logd, f"{node}.harness2.log"), "ab")
    args = vg.server_args(g, node)
    try:
        p = subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                             start_new_session=True, env=vg.server_env(g, node), preexec_fn=oom_adj.preexec())
    except FileNotFoundError:
        die(f"runtime binary not found: {args[0]} (run scripts/configure.sh, or start the node yourself)")
    print(f"harness2: started node {node} (pid {p.pid}); it is stopped when propose ends", file=sys.stderr)
    return p

def cmd_status(a, g):
    import harness2_local as L
    names = [a.target] if a.target else sorted(g.get("harnesses") or {})
    print(f"engine: {'installed' if L.installed(a.state) else 'not installed'} ({L.H2_REPO}@{L.H2_COMMIT[:12]})")
    if not names: print("no harnesses declared"); return
    for n in names:
        t = SI.target(g, n, a.root); sname, s = SI.settings_for(g, n); st = SI.State(t, a.state)
        pend = [p["id"] for p in st.proposals() if p.get("status") == "pending"]
        print(f"{n}: agent={t.agent or '-'} root={t.root} node={t.node} endpoint={t.endpoint} "
              f"({'up' if L.endpoint_up(t.endpoint) else 'down'})")
        print(f"  setting: {('self_improve.' + sname + ' mode=' + s['mode'] + ' k=' + str(s['k']) + ' tasks=' + s['tasks']) if s else 'none (no self_improve entry targets it)'}"
              f"; consent for apply: {'yes' if SI.has_consent(n) else 'no'}")
        print(f"  version: {st.current() or 'none yet'}; versions: {st.versions() or '-'}; pending: {pend or '-'}")

def cmd_install(a, g):
    import harness2_local as L
    print(L.install(a.state))

def cmd_propose(a, g):
    import harness2_local as L
    t = SI.target(g, a.target, a.root); sname, s = setting(g, a.target, a.enable)
    tasks = L.load_tasks(s["tasks"]); cap = a.max_tasks or s.get("max_tasks")
    evolve = [i for i, x in tasks.items() if x["split"] == "evolve"][:cap]
    holdout = [i for i, x in tasks.items() if x["split"] == "holdout"][:cap]
    k = a.k or s["k"]
    plan = (f"target {t.name}: endpoint {t.endpoint} model {t.model}; Harness² {s['recursion']} k={k} on "
            f"{len(evolve)} evolve tasks, then base vs proposal on {len(evolve)}+{len(holdout)} tasks; "
            f"~{len(evolve) * (2 * k + 3) + 2 * (len(evolve) + len(holdout))} model calls")
    if a.dry_run: print("dry-run: " + plan); return
    L.import_h2(a.state)
    proc = None
    if not L.endpoint_up(t.endpoint):
        if not a.start_node: die(f"endpoint {t.endpoint} is down; start it (scripts/serve.sh {t.node}) or pass --start-node")
        proc = start_node(g, t.node, a.yes); t0 = time.time()
        while not L.endpoint_up(t.endpoint):
            if time.time() - t0 > 900 or proc.poll() is not None: die(f"node {t.node} did not come up")
            time.sleep(3)
    try:
        st = SI.State(t, a.state); st.init(); base_v = st.current(); base = st.tree(base_v)
        pid = st.new_proposal_id(); out = st.p("proposals", pid, "work"); os.makedirs(out, exist_ok=True)
        print(plan, file=sys.stderr)
        meter = L.Meter(L.make_chat(t.endpoint, t.model)); t0 = time.time()
        cand, info = L.propose(t, base, tasks, evolve, meter, out, k=k, recursion=s["recursion"], state_root=a.state,
                               log=lambda m: print(m, file=sys.stderr))
        h2cost = meter.as_dict(); meta = {"setting": sname, "mode": s["mode"], "k": k, "tasks": s["tasks"],
                                          "evolve": evolve, "holdout": holdout, "engine": f"{L.H2_REPO}@{L.H2_COMMIT}",
                                          "endpoint": t.endpoint, "model": t.model, "harness2": info.get("chosen"),
                                          "leak_terms": L.leak_terms(tasks)}
        if cand is None:
            meta.update(status="no_change", reason="Harness² kept the base harness"); cand = base
        elif SI.editable(cand) == SI.editable(base):
            meta.update(status="no_change", reason="Harness² picked a candidate with no change to the editable files"); cand = base
        else:
            errs = SI.gate(base, cand, meta["leak_terms"], bool(t.skills))
            if errs: meta.update(status="rejected", reason=errs)
            else:
                ev = L.evaluate(meter, {"base": base, "proposal": cand}, tasks, evolve + holdout, log=lambda m: print(m, file=sys.stderr))
                b, p = ev["base"], ev["proposal"]
                worse = p["holdout"][0] < b["holdout"][0] or p["evolve"][0] < b["evolve"][0]
                meta.update(status="pending", eval={k2: {sp: v[sp] for sp in ("evolve", "holdout")} | {"per_task": v["per_task"]} for k2, v in ev.items()},
                            regresses=worse)
        meta["cost"] = {"harness2": h2cost, "total": meter.as_dict(), "wall_s": round(time.time() - t0, 1)}
        meta = st.save_proposal(pid, base_v, cand, meta)
        if meta["status"] == "pending" and s["mode"] == "apply":
            lic_ok = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "licenses.py"), "check", "--quiet",
                                     "--graph", g["_path"]]).returncode == 0
            if not lic_ok: print("apply mode: licenses not accepted (scripts/licenses.py check); left pending")
            elif not SI.has_consent(t.name): print(f"apply mode: no consent for {t.name} yet (harness2.py consent --target {t.name}); left pending")
            elif meta["regresses"]: print("apply mode: proposal scores lower on evolve or holdout; left pending")
            else: print(f"apply mode: accepted as version {st.accept(pid)}")
        if a.record: record(t, meta)
        report(st, st.proposal(pid))
    finally:
        if proc is not None:
            os.killpg(proc.pid, signal.SIGTERM); print(f"harness2: stopped node {t.node}", file=sys.stderr)

def record(t, meta):
    import registry, socket
    ev = meta.get("eval") or {}
    def frac(lbl, sp): v = (ev.get(lbl) or {}).get(sp); return {"value": f"{v[0]}/{v[1]}", "measured": True} if v else {"value": None, "measured": False}
    r = {"kind": "harness2", "host": socket.gethostname().split(".")[0], "device": {"backend": "cpu", "kind": "cpu"},
         "runtime": {"name": "llama-server", "endpoint": t.endpoint}, "model": {"alias": t.model, "node": t.node},
         "settings": {"target": t.name, "k": meta["k"], "tasks": meta["tasks"], "engine": meta["engine"],
                      "evolve": len(meta["evolve"]), "holdout": len(meta["holdout"])},
         "metrics": {"base_evolve": frac("base", "evolve"), "proposal_evolve": frac("proposal", "evolve"),
                     "base_holdout": frac("base", "holdout"), "proposal_holdout": frac("proposal", "holdout"),
                     "wall_s": {"value": meta["cost"]["wall_s"], "measured": True},
                     "completion_tokens": {"value": meta["cost"]["total"]["completion_tokens"], "measured": True}},
         "timestamp": meta["at"], "source": f"scripts/harness2.py propose --target {t.name} (proposal {meta['id']}, status {meta['status']})",
         "note": "coarse binary search: one Harness² pass, one rollout per task, tiny task set; not a benchmark"}
    registry.append(r); print("recorded in registry/records.jsonl")

def report(st, m):
    print(f"proposal {m['id']} for {st.t.name}: {m['status']}" + (f" ({m.get('reason')})" if m.get("reason") else ""))
    for lbl, v in (m.get("eval") or {}).items():
        print(f"  {lbl:<9} evolve {v['evolve'][0]}/{v['evolve'][1]}  holdout {v['holdout'][0]}/{v['holdout'][1]}")
    if m.get("cost"): print(f"  cost: {m['cost']['total']['calls']} model calls, {m['cost']['total']['completion_tokens']} completion tokens, {m['cost']['wall_s']}s")
    if m["status"] == "pending":
        print(f"  review: harness2.py show --target {st.t.name} {m['id']}   accept: harness2.py accept --target {st.t.name} {m['id']}")

def cmd_list(a, g):
    st = SI.State(SI.target(g, a.target, a.root), a.state)
    print(f"current version: {st.current() or 'none'}  versions: {st.versions() or '-'}")
    for m in st.proposals():
        ev = m.get("eval") or {}
        sc = " ".join(f"{l}:{v['evolve'][0]}/{v['evolve'][1]}+{v['holdout'][0]}/{v['holdout'][1]}" for l, v in ev.items())
        print(f"  {m['id']}  {m['status']:<10} base={m.get('base')} {sc}")

def cmd_show(a, g):
    st = SI.State(SI.target(g, a.target, a.root), a.state); m = st.proposal(a.id)
    report(st, m)
    if m.get("harness2"): print("  harness2 pick: " + json.dumps(m["harness2"], ensure_ascii=False)[:1500])
    print(open(st.p("proposals", a.id, "diff.patch")).read() or "(no textual change)")

def cmd_accept(a, g):
    st = SI.State(SI.target(g, a.target, a.root), a.state); v = st.accept(a.id)
    print(f"{a.target}: accepted {a.id} as version {v}; files written under {st.t.root}. Undo: harness2.py revert --target {a.target}")

def cmd_revert(a, g):
    st = SI.State(SI.target(g, a.target, a.root), a.state)
    if not st.current(): die(f"{a.target}: nothing recorded yet")
    print(f"{a.target}: now at version {st.revert(a.to)}" + (" (original files restored)" if st.current() == "0000" else ""))

def cmd_consent(a, g):
    SI.target(g, a.target, a.root); SI.record_consent(a.target, a.revoke)
    print(f"{a.target}: apply-mode consent {'revoked' if a.revoke else 'recorded'} in {SI.CONSENT}")

def cmd_sync(a, g):
    t = SI.target(g, a.target, a.root); st = SI.State(t, a.state)
    sname, s = SI.settings_for(g, a.target)
    if not st.current(): print(f"{a.target}: no versions yet; nothing to sync"); return
    if st.current() == "0000" and a.into: print(f"{a.target}: at original version; nothing to sync"); return
    root = st.export(a.into); print(f"{a.target}: version {st.current()} written to {root}")

# ---- graph.yaml text edits (comments kept; same approach as familia_yaml.set_node_list) ----
import re

def _block(lines, section, name=None):
    """(start, end) line range of section (or section.name), end exclusive; None if absent."""
    si = next((i for i, l in enumerate(lines) if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", l)), None)
    if si is None: return None
    se = next((i for i in range(si + 1, len(lines)) if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")), len(lines))
    if name is None: return si, se
    ni = next((i for i in range(si + 1, se) if re.match(rf"^(\s+){re.escape(name)}:\s*(#.*)?$", lines[i])), None)
    if ni is None: return None
    ind = len(lines[ni]) - len(lines[ni].lstrip(" "))
    ne = next((i for i in range(ni + 1, se) if lines[i].strip() and not lines[i].lstrip().startswith("#")
               and len(lines[i]) - len(lines[i].lstrip(" ")) <= ind), se)
    return ni, ne

def set_key(text, section, name, key, rendered):
    lines = text.split("\n"); b = _block(lines, section, name)
    if b is None: raise KeyError(f"{section}.{name}")
    for i in range(b[0] + 1, b[1]):
        m = re.match(rf"^(\s+){re.escape(key)}:(\s*)([^#]*?)(\s*)(#.*)?$", lines[i])
        if m:
            old_w = len(m.group(3)) + len(m.group(4))
            pad = " " * max(2, old_w - len(rendered)) if m.group(5) else ""
            lines[i] = f"{m.group(1)}{key}:{m.group(2) or ' '}{rendered}{pad}{m.group(5) or ''}"; return "\n".join(lines)
    ind = len(lines[b[0]]) - len(lines[b[0]].lstrip(" ")) + 2
    last = b[1]
    while last > b[0] + 1 and not lines[last - 1].strip(): last -= 1
    lines.insert(last, " " * ind + f"{key}: {rendered}"); return "\n".join(lines)

def add_entry(text, section, name, body_lines, comment=None):
    lines = text.split("\n"); b = _block(lines, section)
    entry = [f"  {name}:"] + [f"    {l}" for l in body_lines]
    if b is None:
        while lines and not lines[-1].strip(): lines.pop()
        lines += ["", f"{section}:"] + ([f"  # {comment}"] if comment else []) + entry + [""]
    else:
        last = b[1]
        while last > b[0] + 1 and not lines[last - 1].strip(): last -= 1
        lines[last:last] = entry
    return "\n".join(lines)

def cmd_set(a, g):
    agent, mode = a.agent, a.mode
    agents = g.get("agents") or {}
    if agent not in agents: die(f"no agents.{agent} in the graph (agents: {sorted(agents)})", 2)
    text = open(a.graph, encoding="utf-8").read(); changes = []
    tnames = SI.targets_for_agent(g, agent)
    if not tnames:
        if mode == "off": print(f"{agent}: no Harness² target declared; nothing to switch off"); return 0
        if agents[agent].get("kind") != "hermes-agent":
            die(f"{agent} has no harnesses.* descriptor; declare one (docs/harness2.md) naming its prompt file", 2)
        main_alias = (agents[agent].get("aliases") or {}).get("main")
        node = ((g.get("aliases") or {}).get(main_alias) or {}).get("node", main_alias)
        t = agent if agent not in (g.get("harnesses") or {}) else f"{agent}-harness"
        text = add_entry(text, "harnesses", t, ["kind: files", f"agent: {agent}", f"root: ~/.cache/familia/hermes-{agent}",
                                                 "prompt: SOUL.md", "skills: skills", f"node: {node}"],
                         "target harness descriptors (docs/harness2.md)")
        changes.append(f"harnesses.{t}: new descriptor (hermes-agent layout, node {node})"); tnames = [t]
    q = lambda m: '"off"' if m == "off" else m
    for t in tnames:
        sname, s = SI.settings_for(g, t)
        if s is not None and s.get("mode") == mode: changes.append(f"self_improve.{sname}: {t} already {mode}"); continue
        if s is not None and list(s.get("targets")) == [t]:
            text = set_key(text, "self_improve", sname, "mode", q(mode)); changes.append(f"self_improve.{sname}.mode: {s['mode']} -> {mode}")
            continue
        if s is not None:
            rest = [x for x in s["targets"] if x != t]
            text = set_key(text, "self_improve", sname, "targets", "[" + ", ".join(rest) + "]")
            changes.append(f"self_improve.{sname}.targets: {s['targets']} -> {rest}")
        elif mode == "off": continue
        base = s or {"k": 1, "recursion": "parallel", "tasks": "coding-v1", "max_tasks": 3}
        new = f"harness2-{t}"
        text = add_entry(text, "self_improve", new, ["experimental: true", "engine: harness2", f"mode: {q(mode)}", f"targets: [{t}]",
                                                     f"k: {base['k']}", f"recursion: {base['recursion']}", f"tasks: {base['tasks']}"]
                         + ([f"max_tasks: {base['max_tasks']}"] if base.get("max_tasks") else []),
                         "Harness² settings (docs/harness2.md)")
        changes.append(f"self_improve.{new}: new, mode {mode}, targets [{t}]")
    g2 = yaml.safe_load(text); g2["_path"] = a.graph
    import validate_graph as vg
    errs, _ = vg.validate(g2, check_files=False)
    if errs: die("refusing to write graph.yaml:\n  " + "\n  ".join(errs))
    got = {t: (SI.settings_for(g2, t)[1] or {}).get("mode", "off") for t in tnames}
    if any(v != mode for v in got.values()): die(f"internal: edit did not produce mode {mode}: {got}")
    for c in changes: print(("[dry-run] would set " if a.dry_run else "set ") + c)
    if a.dry_run: print("[dry-run] graph.yaml not written"); return 0
    if mode != "off":
        tmp = a.graph + ".harness2.tmp"
        with open(tmp, "w", encoding="utf-8") as f: f.write(text)
        try: licenses(tmp, "gate", a.yes)
        finally: os.path.exists(tmp) and os.remove(tmp)
    with open(a.graph + ".tmp", "w", encoding="utf-8") as f: f.write(text)
    os.replace(a.graph + ".tmp", a.graph)
    if mode == "apply" and not all(SI.has_consent(t) for t in tnames):
        print(f"note: apply accepts by itself only after: scripts/harness2.py consent --target {tnames[0]}")
    if mode != "off": print(f"next: scripts/harness2.py propose --target {tnames[0]} --dry-run")
    return 0

def cmd_review(a, g):
    names = [a.target] if a.target else sorted(g.get("harnesses") or {})
    tty = sys.stdin.isatty() and not os.environ.get("FAMILIA_NO_TTY") and not a.dry_run
    found = 0
    for n in names:
        st = SI.State(SI.target(g, n, a.root), a.state)
        pend = [m for m in st.proposals() if m.get("status") == "pending"]
        print(f"{n}: version {st.current() or 'none yet'}, {len(pend)} pending")
        for m in pend:
            found += 1; report(st, m)
            if not tty: continue
            print(open(st.p("proposals", m["id"], "diff.patch")).read() or "(no textual change)")
            ans = input(f"  accept {m['id']}? [a]ccept / [s]kip / [q]uit: ").strip().lower()
            if ans.startswith("q"): return 0
            if ans.startswith("a"): print(f"  accepted as version {st.accept(m['id'])}")
        if tty and st.current() not in (None, "0000"):
            if input(f"  revert {n} from {st.current()} to its parent? [y/N]: ").strip().lower().startswith("y"):
                print(f"  now at {st.revert()}")
    if not tty:
        print("(no terminal: listed only. Accept with: scripts/harness2.py accept --target T ID; undo with: scripts/harness2.py revert --target T)"
              if found else "(nothing pending; make one with: scripts/harness2.py propose --target T)")
    return 0

def main(argv=None):
    ap = argparse.ArgumentParser(prog="harness2.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default=os.path.join(ROOT, "graph.yaml"))
    ap.add_argument("--state", default=None, help="state dir (default .cache/familia/harness2; env FAMILIA_HARNESS2_STATE)")
    ap.add_argument("--root", default=None, help="replace the target's root directory")
    sp = ap.add_subparsers(dest="cmd", required=True)
    def add(name, need_target=True):
        p = sp.add_parser(name); p.add_argument("--target", required=need_target); return p
    add("status", False); add("install", False)
    p = sp.add_parser("set"); p.add_argument("--agent", required=True); p.add_argument("--mode", required=True, choices=SI.MODES)
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--yes", "--accept-licenses", action="store_true")
    p = add("review", False); p.add_argument("--dry-run", action="store_true")
    p = add("propose"); p.add_argument("--enable", action="store_true"); p.add_argument("--k", type=int)
    p.add_argument("--max-tasks", type=int); p.add_argument("--start-node", action="store_true")
    p.add_argument("--record", action="store_true"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", "--accept-licenses", action="store_true")
    add("list"); add("show").add_argument("id"); add("accept").add_argument("id")
    add("revert").add_argument("--to"); add("consent").add_argument("--revoke", action="store_true")
    add("sync").add_argument("--into")
    a = ap.parse_args(argv)
    if a.state: SI.STATE_ROOT = a.state
    g = load_graph(a.graph)
    if getattr(a, "target", None) and a.target not in (g.get("harnesses") or {}):
        die(f"no harnesses.{a.target} in {a.graph} (declared: {sorted(g.get('harnesses') or {})})", 2)
    return globals()["cmd_" + a.cmd](a, g)

if __name__ == "__main__":
    sys.exit(main() or 0)
