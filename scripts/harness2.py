#!/usr/bin/env python3
"""Harness² review CLI (docs/harness2.md). Reviews; never launches an agent.

usage: harness2.py [--graph FILE] [--state DIR] COMMAND [--target NAME] ...

  status   [--target T]                 settings, versions, pending proposals, endpoint, engine
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
"""
import argparse, json, os, signal, subprocess, sys, time
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import self_improve as SI  # noqa: E402

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

def start_node(g, node):
    import validate_graph as vg
    errs, _ = vg.validate(g, check_files=True)
    if errs: die("cannot start node: " + "; ".join(errs[:3]))
    logd = os.path.join(ROOT, ".cache", "familia", "logs"); os.makedirs(logd, exist_ok=True)
    log = open(os.path.join(logd, f"{node}.harness2.log"), "ab")
    args = vg.server_args(g, node)
    try:
        p = subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                             start_new_session=True, env=vg.server_env(g, node))
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
        proc = start_node(g, t.node); t0 = time.time()
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
            if not SI.has_consent(t.name): print(f"apply mode: no consent for {t.name} yet (harness2.py consent --target {t.name}); left pending")
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

def main(argv=None):
    ap = argparse.ArgumentParser(prog="harness2.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--graph", default=os.path.join(ROOT, "graph.yaml"))
    ap.add_argument("--state", default=None, help="state dir (default .cache/familia/harness2; env FAMILIA_HARNESS2_STATE)")
    ap.add_argument("--root", default=None, help="replace the target's root directory")
    sp = ap.add_subparsers(dest="cmd", required=True)
    def add(name, need_target=True):
        p = sp.add_parser(name); p.add_argument("--target", required=need_target); return p
    add("status", False); add("install", False)
    p = add("propose"); p.add_argument("--enable", action="store_true"); p.add_argument("--k", type=int)
    p.add_argument("--max-tasks", type=int); p.add_argument("--start-node", action="store_true")
    p.add_argument("--record", action="store_true"); p.add_argument("--dry-run", action="store_true")
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
