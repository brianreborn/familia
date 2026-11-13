#!/usr/bin/env python3
"""model_pick.py: pick a model for one graph host from the full catalog (#398).

Catalog = every graph.yaml models: entry plus loose .gguf files found in the
usual model folders on this machine. Each entry is scored for the host:
fits RAM (ram_mib - reserve_ram_mib, docs/ram-safety.md), file present here,
role match, measured registry evidence, then size (bigger that fits wins).

Usage:
  model_pick.py list   --host HOST [--role ROLE] [--query WORDS] [--json]
  model_pick.py default --host HOST [--role ROLE]
  model_pick.py pick   --host HOST [--role ROLE] [--query WORDS] [--choice KEY]
  model_pick.py export --host HOST --model KEY [--role ROLE] [--out PATH] [--write]
  model_pick.py menu   --host HOST [--role ROLE]

Examples:
  model_pick.py list --host miryam --role coder
  model_pick.py pick --host angel --choice ''      # empty choice = host default
  model_pick.py export --host miryam --model qwen35-2b-q4km --role coder
  model_pick.py export --host miryam --model qwen35-2b-q4km --role coder --write

export prints a host graph (private topology, docs/graph-types.md) with the
role node switched to the chosen model and validates it. Nothing is written
without --write; with --write it goes to generated/graph-pick-HOST.yaml and
graph.yaml itself is never touched. Loose .gguf files must be registered
first (Models: Add a model) before they can be exported.

On a terminal, menu uses gum filter when gum is installed (arrows, page
up/down, live search; the header line or Esc = host default), else a numbered
prompt with /search. Headless: no TTY (or FAMILIA_NO_TTY=1) never prompts; pick reads --choice.
Colors only on a TTY with NO_COLOR unset. Output is ASCII only.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import familia_yaml  # noqa: E402

GGUF_DIRS = ("~/.local/share/gguf/models", "~/models", "~/familia/models")
OVERHEAD_MIB = 256          # runtime + small KV; conservative, not measured
MIB = 1048576.0


def graph_path():
    return os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")


def load_graph(path=None):
    return familia_yaml.load(path or graph_path()) or {}


def gguf_dirs():
    extra = [d for d in (os.environ.get("FAMILIA_MODEL_DIRS") or "").split(os.pathsep) if d]
    return extra + ([] if os.environ.get("FAMILIA_MODEL_DIRS_ONLY") == "1" else list(GGUF_DIRS))


def host_budget_mib(host):
    ram, res = host.get("ram_mib"), host.get("reserve_ram_mib")
    if not isinstance(ram, (int, float)):
        return None
    return ram - (res if isinstance(res, (int, float)) else 2048)


def _db_bytes(dbid):
    if not dbid:
        return None
    try:
        import model_db
        e = model_db.load(dbid)
        return (e or {}).get("bytes")
    except Exception:
        return None


def _registry_best(host, role):
    """Best measured tg t/s per lowercase model name for host+role (empty when none)."""
    try:
        import registry
        recs = registry.load()
        out = {}
        for c in registry.suggest(host, role, recs) if role in registry.ROLE_MODELS else []:
            name = json.dumps(c.get("model")).lower()
            out[name] = max(out.get(name, 0), c["tg_tps"][0] or 0)
        return out
    except Exception:
        return {}


def local_host():
    """This machine's graph host: FAMILIA_HOST, then the hostname pin, then the short hostname."""
    h = (os.environ.get("FAMILIA_HOST") or "").strip()
    if h:
        return h
    try:
        import hostname_pin
        h = hostname_pin.read_pin()
    except Exception:
        h = None
    if h:
        return h
    import socket
    return socket.gethostname().split(".", 1)[0].lower()


def catalog(graph, host_name, role=None):
    hosts = graph.get("hosts") or {}
    if host_name not in hosts:
        raise SystemExit(f"model_pick: no host {host_name!r} in graph (hosts: {', '.join(hosts)})")
    host = hosts[host_name] or {}
    budget = host_budget_mib(host)
    on_host = {d.get("model"): n for n, d in (graph.get("nodes") or {}).items()
               if isinstance(d, dict) and d.get("host") == host_name}
    reg = _registry_best(host_name, role) if role else {}
    archs = set()
    for d in (graph.get("nodes") or {}).values():
        if isinstance(d, dict) and d.get("host") == host_name:
            archs |= set(((graph.get("runtimes") or {}).get(d.get("runtime")) or {}).get("supported_archs") or [])
    here = local_host() == host_name   # file presence only means something on that host
    rows, seen = [], set()
    for key, m in (graph.get("models") or {}).items():
        if not isinstance(m, dict):
            continue
        path = os.path.expanduser(str(m.get("gguf", "")))
        exists = os.path.isfile(path)
        present = exists if here else None
        size = os.path.getsize(path) if exists else _db_bytes(m.get("db"))
        seen.add(os.path.abspath(path))
        rows.append({"key": key, "source": "graph", "role": m.get("role"), "arch": m.get("arch"),
                     "gguf": m.get("gguf"), "present": present, "bytes": size,
                     "on_host_node": on_host.get(key)})
    for d in (gguf_dirs() if here else []):
        for p in sorted(glob.glob(os.path.join(os.path.expanduser(d), "**", "*.gguf"), recursive=True)):
            ap = os.path.abspath(p)
            if ap in seen or "mmproj" in os.path.basename(p).lower():
                continue
            seen.add(ap)
            rows.append({"key": os.path.basename(p), "source": "local", "role": None, "arch": None,
                         "gguf": p, "present": True, "bytes": os.path.getsize(p), "on_host_node": None})
    for r in rows:
        r["est_mib"] = None if r["bytes"] is None else int(r["bytes"] / MIB + OVERHEAD_MIB)
        r["fits"] = None if (r["est_mib"] is None or budget is None) else r["est_mib"] <= budget
        name = (r["key"] + " " + str(r["gguf"])).lower()
        r["measured_tps"] = max([v for k, v in reg.items() if any(t in k for t in name.split("/")[-1:])] or [0]) or None
        r["arch_ok"] = None if (not archs or not r["arch"]) else r["arch"] in archs
        r["role_match"] = bool(role) and r["role"] == role
        r["role_clash"] = bool(role) and r["role"] is not None and r["role"] != role
        r["score"] = score(r)
    rows.sort(key=lambda r: (-r["score"], r["key"]))
    return {"host": host_name, "budget_mib": budget, "role": role, "models": rows}


def score(r):
    s = 0.0
    if r["fits"] is False:
        return -1000.0 + (r["est_mib"] or 0) / -1e6
    if r["fits"]:
        s += 100
    if r["present"]:
        s += 50
    if r["role_match"]:
        s += 80
    if r["role_clash"]:
        s -= 80
    if r["arch_ok"] is False:
        s -= 150   # the host's runtimes cannot load this architecture
    if r["on_host_node"]:
        s += 20
    if r["source"] == "graph":
        s += 10
    if r["measured_tps"]:
        s += min(r["measured_tps"], 50)
    if r["est_mib"]:
        s += min(r["est_mib"] / 1024.0, 20)  # bigger that fits is more capable
    return round(s, 2)


def search(rows, query):
    words = [w.lower() for w in (query or "").split() if w]
    return [r for r in rows if all(w in (r["key"] + " " + str(r["gguf"]) + " " + str(r["role"])).lower() for w in words)]


def host_default(cat):
    """Enter on the header: the existing node's model for the role, else the top fitting graph model."""
    rows = cat["models"]
    for r in rows:
        if r["on_host_node"] and r["role_match"]:
            return r
    for r in rows:
        if (r["source"] == "graph" and r["fits"] is not False and r.get("arch_ok") is not False
                and (r["role_match"] or not cat["role"])):
            return r
    return rows[0] if rows else None


def _color(code, s):
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"\033[{code}m{s}\033[0m"
    return s


def fmt_row(i, r):
    fit = {True: "fits", False: "TOO BIG", None: "fit?"}[r["fits"]]
    if r.get("arch_ok") is False and r["fits"] is not False:
        fit = "NO-ARCH"
    est = "?" if r["est_mib"] is None else f"{r['est_mib']}MiB"
    flags = ",".join(x for x in ({True: "here", False: "absent", None: "remote"}[r["present"]], r["source"],
                                 (f"node={r['on_host_node']}" if r["on_host_node"] else ""),
                                 (f"{r['measured_tps']}t/s" if r["measured_tps"] else "")) if x)
    line = f"{i:3d}. {r['key']:<40} {str(r['role'] or '-'):<9} {est:>9} {fit:<7} {flags}"
    return _color("31", line) if (r["fits"] is False or r.get("arch_ok") is False) else line


def print_list(cat, rows):
    print(f"host {cat['host']}: budget {cat['budget_mib'] if cat['budget_mib'] is not None else 'unknown'} MiB"
          f" (ram_mib - reserve_ram_mib), role {cat['role'] or 'any'}, {len(rows)} model(s)")
    for i, r in enumerate(rows, 1):
        print(fmt_row(i, r))


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("FAMILIA_NO_TTY") != "1"


def choose(cat, rows, choice):
    """choice: '' = host default, a number (1-based in rows), or a models key / file name."""
    if choice is None or choice.strip() == "":
        return host_default(cat)
    c = choice.strip()
    if c.isdigit() and 1 <= int(c) <= len(rows):
        return rows[int(c) - 1]
    for r in cat["models"]:
        if r["key"] == c:
            return r
    hits = search(rows, c)
    return hits[0] if len(hits) == 1 else None


def export_graph(graph, host, model_key, role=None):
    import node_role
    models = graph.get("models") or {}
    if model_key not in models:
        raise SystemExit(f"model_pick: {model_key!r} is not a graph.yaml models: key; register the file first "
                         f"(Models: Add a model), then pick it again")
    try:
        g = node_role.private_topology(graph, host)
    except ValueError as e:
        raise SystemExit(f"model_pick: {e}; add a node for {host} first (Advanced: modify_graph)")
    nodes = g["nodes"]
    target = role or next((n for n in ("coder", "chat", "general", "decision") if n in nodes), None) or next(iter(nodes))
    if target not in nodes:
        raise SystemExit(f"model_pick: host {host} has no {target!r} node (has: {', '.join(nodes)})")
    base = copy.deepcopy(g)
    old = nodes[target].get("model")
    nodes[target]["model"] = model_key
    return g, target, old, base


def validate_errors(g):
    try:
        import validate_graph
        errs, _ = validate_graph.validate(copy.deepcopy(g), check_files=False)
        return errs
    except SystemExit as e:
        return [str(e)]
    except Exception as e:  # validator import problems are reported, not fatal
        return [f"validator unavailable: {e}"]


def do_export(graph, a):
    import yaml
    g, target, old, base = export_graph(graph, a.host, a.model, a.role)
    before = set(validate_errors(base))
    errs = [e for e in validate_errors(g) if e not in before]   # only what the pick introduced
    out = a.out or os.path.join(os.environ.get("FAMILIA_GENERATED_DIR") or os.path.join(ROOT, "generated"),
                                f"graph-pick-{a.host}.yaml")
    print(f"# model_pick: host {a.host}, node {target}: {old} -> {a.model}")
    print(f"# validate_graph (no file checks): {'OK' if not errs else 'ERRORS'} for this pick"
          + (f"; {len(before)} problem(s) already in this host graph before the pick (not counted)" if before else ""))
    for e in errs:
        print(f"#   {e}")
    text = yaml.safe_dump(g, sort_keys=False, allow_unicode=False)
    if not a.write:
        print(f"# dry run: would write {out} (add --write); graph.yaml is never modified")
        print(yaml.safe_dump({"nodes": {target: g["nodes"][target]}}, sort_keys=False, allow_unicode=False), end="")
        return 1 if errs else 0
    if errs and not a.force:
        print("model_pick: not written (validation errors; --force writes anyway)", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="ascii", errors="replace") as f:
        f.write(f"# generated by scripts/model_pick.py (#398): {a.host} {target}={a.model}\n" + text)
    os.replace(tmp, out)
    print(f"wrote {out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="model_pick.py", description=__doc__.split("\n")[0],
                                 epilog="Example: model_pick.py list --host miryam --role coder",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("list", "default", "pick", "export", "menu"))
    ap.add_argument("--host", required=True)
    ap.add_argument("--role")
    ap.add_argument("--query")
    ap.add_argument("--choice")
    ap.add_argument("--model")
    ap.add_argument("--out")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--graph")
    a = ap.parse_args(argv)
    graph = load_graph(a.graph)
    cat = catalog(graph, a.host, a.role)
    rows = search(cat["models"], a.query)
    if a.cmd == "list":
        if a.json:
            print(json.dumps(dict(cat, models=rows), indent=1))
        else:
            print_list(cat, rows)
        return 0
    if a.cmd == "default":
        r = host_default(cat)
        print(r["key"] if r else "")
        return 0 if r else 1
    if a.cmd == "export":
        if not a.model:
            ap.error("export needs --model KEY")
        return do_export(graph, a)
    choice = a.choice
    if a.cmd == "menu" and choice is None and interactive() and shutil.which("gum") and not os.environ.get("FAMILIA_PICK_NO_GUM"):
        # gum filter: arrows, page up/down, live search; Esc / empty = host default
        d = host_default(cat)
        head = f"[Enter here = host default: {d['key'] if d else '-'}]"
        lines = [head] + [fmt_row(i, r) for i, r in enumerate(rows, 1)]
        res = subprocess.run(["gum", "filter", "--height", "20", "--placeholder", "search models"],
                             input="\n".join(lines), stdout=subprocess.PIPE, text=True)
        pickd = (res.stdout or "").strip()
        choice = "" if (not pickd or pickd == head) else re.sub(r"\x1b\[[0-9;]*m", "", pickd).split(".", 1)[0].strip()
    elif a.cmd == "menu" and choice is None and interactive():
        while True:
            print_list(cat, rows)
            d = host_default(cat)
            ans = input(f"number, models key, /search words, or Enter for host default [{d['key'] if d else '-'}]: ")
            if ans.startswith("/"):
                rows = search(cat["models"], ans[1:])
                continue
            choice = ans
            break
    r = choose(cat, rows, choice)
    if not r:
        print(f"model_pick: no single match for {choice!r}", file=sys.stderr)
        return 1
    print(r["key"])
    if a.cmd == "menu":
        if r["source"] != "graph":
            print(f"model_pick: {r['gguf']} is not registered; run Models: Add a model first", file=sys.stderr)
            return 1
        a.model = r["key"]
        return do_export(graph, a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
