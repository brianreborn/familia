#!/usr/bin/env python3
"""protograph.py: turn a short recipe into a canonical graph.yaml, check it, and
write it only after a dry run and confirmation (#399, skills/protograph/SKILL.md).

Usage:
  protograph.py RECIPE                      # dry run: print the graph + plan, write nothing
  protograph.py RECIPE --check              # exit 0 only if the emitted graph is valid
  protograph.py RECIPE --out PATH --write   # write PATH (asks first if PATH exists)
  protograph.py RECIPE --out PATH --write --yes   # confirm an overwrite without a prompt

Examples:
  protograph.py skills/protograph/examples/single-chat.recipe.yaml
  protograph.py skills/protograph/examples/from-host.recipe.yaml --check
  protograph.py my.recipe.yaml --out generated/graph-proto.yaml --write

Recipe keys (see skills/protograph/SKILL.md for the full reference):
  protograph: 1                 required version marker
  host: {name, kind, os, cpu, threads, ram_mib, reserve_ram_mib}   or  host: {from_graph: NAME}
  runtime: {name, build, commit, supported_archs, backends}        or  runtime: {from_graph: NAME}
  models: {KEY: {gguf, sha256, arch, trained_ctx, role, db}  or  {from_graph: KEY}}
  nodes: [{role, model, ctx, port, [name, parallel, kv_type, flash_attn, threads, cache_ram_mib,
          status, offload, override_reasons]}]
  gateway: {port}               optional (default 8080); green-roomz gateway + one alias per node
  agent: {kind, main, [auxiliary], min_ctx}   optional (default: hermes-agent on the first node)

Every default the recipe leaves out is written explicitly into the graph
(graph.yaml has no implicit defaults). Nothing is downloaded. graph.yaml
itself is only written with --out graph.yaml --write and a confirmation; an
overwritten file is kept as PATH.bak-YYYYmmdd-HHMMSS. Output is ASCII only.
"""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import yaml  # noqa: E402

NODE_DEFAULTS = {"parallel": 1, "kv_type": "f16", "flash_attn": False, "bind": "127.0.0.1",
                 "cache_ram_mib": 0, "status": "active"}
HOST_KEYS = ("kind", "os", "cpu", "threads", "ram_mib", "reserve_ram_mib")
MIB = 1048576.0


class RecipeError(Exception):
    pass


def _base_graph(recipe_dir, ref_graph=None):
    path = ref_graph or os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(recipe_dir, path)
    import familia_yaml
    return familia_yaml.load(path) or {}


def build(recipe, recipe_dir=".", ref_graph=None):
    """recipe dict -> (graph dict, plan lines). Raises RecipeError on an incomplete or unsafe recipe."""
    if not isinstance(recipe, dict) or recipe.get("protograph") != 1:
        raise RecipeError("recipe must start with 'protograph: 1'")
    unknown = set(recipe) - {"protograph", "host", "runtime", "models", "nodes", "gateway", "agent", "graph", "notes"}
    if unknown:
        raise RecipeError(f"unknown recipe key(s): {', '.join(sorted(unknown))}")
    plan, base = [], None

    def ref():
        nonlocal base
        if base is None:
            base = _base_graph(recipe_dir, recipe.get("graph") or ref_graph)
        return base

    h = recipe.get("host") or {}
    if "from_graph" in h:
        name = h["from_graph"]
        src = (ref().get("hosts") or {}).get(name)
        if not src:
            raise RecipeError(f"host.from_graph: no host {name!r} in the reference graph")
        host = {k: v for k, v in copy.deepcopy(src).items()}
        host["addr"], host["user"] = "REPLACE_ME", "REPLACE_ME"   # privacy (#104): never copy real addr/user
        plan.append(f"host {name}: copied from the reference graph (addr/user left as REPLACE_ME)")
    else:
        name = h.get("name")
        missing = [k for k in ("name",) + HOST_KEYS if h.get(k) is None]
        if missing:
            raise RecipeError(f"host: missing {', '.join(missing)} (or use host: {{from_graph: NAME}})")
        host = {"kind": h["kind"], "measured": bool(h.get("measured", False)), "os": h["os"], "cpu": h["cpu"],
                "threads": h["threads"], "ram_mib": h["ram_mib"], "reserve_ram_mib": h["reserve_ram_mib"],
                "gpus": h.get("gpus", [])}
        plan.append(f"host {name}: from the recipe (measured: {host['measured']})")
    r = recipe.get("runtime") or {}
    if "from_graph" in r:
        rname = r["from_graph"]
        rt = copy.deepcopy((ref().get("runtimes") or {}).get(rname))
        if not rt:
            raise RecipeError(f"runtime.from_graph: no runtime {rname!r} in the reference graph")
        rt["hosts"] = [name]
        plan.append(f"runtime {rname}: copied from the reference graph")
    else:
        missing = [k for k in ("name", "build", "commit", "supported_archs", "backends") if r.get(k) in (None, [])]
        if missing:
            raise RecipeError(f"runtime: missing {', '.join(missing)} (or use runtime: {{from_graph: NAME}})")
        rname = r["name"]
        rt = {"kind": r.get("kind", "llama-server"), "build": r["build"], "commit": r["commit"], "hosts": [name],
              "supported_archs": list(r["supported_archs"]), "backends": list(r["backends"]),
              "spec_types": list(r.get("spec_types", []))}
        # bin and url are not accepted from recipe-authored runtimes (must come from from_graph or pins)
        if "sha256" in r:
            rt["sha256"] = r["sha256"]
    models = {}
    for key, m in (recipe.get("models") or {}).items():
        if isinstance(m, dict) and "from_graph" in m:
            src = (ref().get("models") or {}).get(m["from_graph"])
            if not src:
                raise RecipeError(f"models.{key}.from_graph: no model {m['from_graph']!r} in the reference graph")
            models[key] = copy.deepcopy(src)
            plan.append(f"model {key}: copied from reference models.{m['from_graph']}")
        else:
            missing = [k for k in ("gguf", "sha256", "arch", "trained_ctx", "role", "db") if not (m or {}).get(k)]
            if missing:
                raise RecipeError(f"models.{key}: missing {', '.join(missing)}")
            models[key] = dict(m)
    if not models:
        raise RecipeError("models: at least one model is required")
    nodes_in = recipe.get("nodes") or []
    if not nodes_in:
        raise RecipeError("nodes: at least one node is required")
    nodes, ports = {}, set()
    for i, n in enumerate(nodes_in):
        missing = [k for k in ("role", "model", "ctx", "port") if n.get(k) is None]
        if missing:
            raise RecipeError(f"nodes[{i}]: missing {', '.join(missing)}")
        key = n.get("name") or n["role"]
        if key in nodes:
            raise RecipeError(f"nodes[{i}]: duplicate node {key!r} (one node per role per host; give 'name')")
        if n["model"] not in models:
            raise RecipeError(f"nodes[{i}]: model {n['model']!r} is not in models:")
        if n["port"] in ports:
            raise RecipeError(f"nodes[{i}]: port {n['port']} used twice")
        ports.add(n["port"])
        bind = n.get("bind", NODE_DEFAULTS["bind"])
        if bind not in ("127.0.0.1", "::1", "localhost"):
            raise RecipeError(f"nodes[{i}]: bind {bind!r} is not loopback; protograph only emits loopback nodes "
                              f"(edit graph.yaml by hand for LAN exposure)")
        node = {"model": n["model"], "host": name, "runtime": rname, "ctx": n["ctx"]}
        model_role = (models[n["model"]].get("role") or "").strip().lower()
        node_role = (n.get("role") or "").strip().lower()
        fail_closed = ("guardian", "pentest", "defender")
        if node_role != model_role:
            if node_role in fail_closed or model_role in fail_closed:
                raise RecipeError(
                    f"nodes[{i}]: role override {node_role!r} over {model_role!r} model refused; "
                    f"fail-closed models cannot be overridden to routable roles"
                )
            node["role"] = n["role"]
        for k, d in NODE_DEFAULTS.items():
            node[k] = n.get(k, d)
            if k not in n:
                plan.append(f"node {key}: {k} = {d!r} (recipe default)")
        if "threads" in n:
            node["threads"] = n["threads"]
        if n.get("override_reasons"):
            node["override_reasons"] = dict(n["override_reasons"])   # model-card deviations (#51)
        node["offload"] = n.get("offload", {"backend": "cpu", "ngl": 0, "split": "none", "main_gpu": 0})
        node["port"] = n["port"]
        nodes[key] = node
    g = {"version": 2, "hosts": {name: host}, "runtimes": {rname: rt}, "models": models, "nodes": nodes}
    gw = recipe.get("gateway")
    if not gw:
        gw = {"port": 8080}
        plan.append("gateway: green-roomz on port 8080 (recipe default; the graph needs one)")
    if gw.get("port") in ports:
        raise RecipeError(f"gateway port {gw['port']} conflicts with node port")
    if True:
        g["gateways"] = {"gw": {"kind": "green-roomz", "host": name, "port": gw["port"]}}
        g["aliases"] = {k: {"node": k, "gateway": "gw"} for k in nodes}
    ag = recipe.get("agent")
    if not ag:
        ag = {"main": next(iter(nodes))}
        plan.append(f"agent ag: hermes-agent on alias {ag['main']} (recipe default; the graph needs one)")
    if True:
        main = ag.get("main")
        if main not in nodes:
            raise RecipeError(f"agent.main: {main!r} is not a node")
        aux = ag.get("auxiliary", main)
        ctx = nodes[main]["ctx"] // nodes[main]["parallel"]
        g["agents"] = {ag.get("name", "ag"): {"kind": ag.get("kind", "hermes-agent"), "host": name,
                                              "min_ctx": ag.get("min_ctx", ctx), "context_length": ctx,
                                              "aliases": {"main": main, "auxiliary": aux}}}
    return g, plan


def ram_report(g):
    """Rough RAM check: model file (or model-db bytes) + cache_ram per active node vs host budget."""
    lines, bad = [], False
    for hn, h in g["hosts"].items():
        budget = (h.get("ram_mib") or 0) - (h.get("reserve_ram_mib") or 0)
        tot, unknown = 0.0, []
        for nn, n in g["nodes"].items():
            if n["host"] != hn or n.get("status") == "planned":
                continue
            m = g["models"][n["model"]]
            p = os.path.expanduser(str(m.get("gguf", "")))
            size = os.path.getsize(p) if os.path.isfile(p) else None
            if size is None:
                try:
                    import model_db
                    size = (model_db.load(m.get("db")) or {}).get("bytes")
                except Exception:
                    size = None
            if size is None:
                unknown.append(nn)
                continue
            tot += size / MIB + (n.get("cache_ram_mib") or 0)
        ok = tot <= budget
        bad |= not ok
        lines.append(f"RAM {hn}: est. {tot:.0f} MiB of {budget} MiB budget (ram_mib - reserve_ram_mib)"
                     f"{' OK' if ok else ' OVER BUDGET'}" + (f"; size unknown: {', '.join(unknown)}" if unknown else ""))
    return lines, bad


def check(g):
    import validate_graph
    errs, _ = validate_graph.validate(copy.deepcopy(g), check_files=False)
    ram, over = ram_report(g)
    if over:
        errs = list(errs) + [l for l in ram if "OVER" in l]
    return errs, ram, list(validate_graph.WARNINGS)


def dump(g, recipe_path):
    head = (f"# Generated by scripts/protograph.py from {recipe_path} (#399).\n"
            "# Every value is explicit; edit the recipe and regenerate rather than hand-editing.\n")
    return head + yaml.safe_dump(g, sort_keys=False, allow_unicode=False, default_flow_style=False)


def confirm(path, yes):
    if yes:
        return True
    if not (sys.stdin.isatty() and os.environ.get("FAMILIA_NO_TTY") != "1"):
        return False
    return input(f"{path} exists. Overwrite (a backup is kept)? [y/N] ").strip().lower() in ("y", "yes")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="protograph.py", description=__doc__.split("\n")[0],
                                 epilog="Example: protograph.py skills/protograph/examples/single-chat.recipe.yaml",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe")
    ap.add_argument("--out")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--yes", action="store_true", help="confirm an overwrite without asking")
    ap.add_argument("--check", action="store_true", help="validate only; print errors, exit 1 if any")
    ap.add_argument("--graph", help="reference graph for from_graph (default FAMILIA_GRAPH or graph.yaml)")
    ap.add_argument("--force", action="store_true", help="write even when validation fails (never for graph.yaml)")
    a = ap.parse_args(argv)
    try:
        with open(a.recipe, encoding="utf-8") as f:
            recipe = yaml.safe_load(f)
        g, plan = build(recipe, os.path.dirname(os.path.abspath(a.recipe)), a.graph)
    except (OSError, yaml.YAMLError, RecipeError) as e:
        print(f"protograph: ERROR: {e}", file=sys.stderr)
        return 1
    errs, ram, warns = check(g)
    for w in warns:
        print(f"protograph: WARNING: {w}", file=sys.stderr)
    for e in errs:
        print(f"protograph: ERROR: {e}", file=sys.stderr)
    if a.check:
        print("protograph: OK" if not errs else f"protograph: {len(errs)} error(s)")
        return 1 if errs else 0
    text = dump(g, a.recipe)
    if not a.write:
        print("# plan:")
        for l in plan + ram:
            print(f"#   {l}")
        print(f"# validate_graph (no file checks): {'OK' if not errs else 'ERRORS (see stderr)'}")
        print(f"# dry run: nothing written{' (would write ' + a.out + ')' if a.out else ''}; add --out PATH --write")
        print(text, end="")
        return 1 if errs else 0
    if not a.out:
        print("protograph: ERROR: --write needs --out PATH", file=sys.stderr)
        return 2
    is_main = os.path.abspath(a.out) == os.path.abspath(os.path.join(ROOT, "graph.yaml"))
    if errs and (not a.force or is_main):
        print("protograph: not written: validation failed" + (" (graph.yaml is never force-written)" if is_main else
              " (--force writes anyway)"), file=sys.stderr)
        return 1
    if os.path.exists(a.out):
        if not confirm(a.out, a.yes):
            print(f"protograph: not written: {a.out} exists; rerun with --yes to confirm the overwrite", file=sys.stderr)
            return 1
        bak = a.out + time.strftime(".bak-%Y%m%d-%H%M%S")
        shutil.copy2(a.out, bak)
        print(f"protograph: kept the old file as {bak}")
    d = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(d, exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="ascii", errors="strict") as f:
        f.write(text)
    os.replace(tmp, a.out)
    print(f"protograph: wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
