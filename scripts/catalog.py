#!/usr/bin/env python3
"""List every model and every graph an operator can configure.

The home menu and the legacy catalog both call this so models and graphs
are reachable without opening Advanced.

Usage:
  python3 scripts/catalog.py models
  python3 scripts/catalog.py graphs
  python3 scripts/catalog.py configure [GRAPH]

Examples:
  python3 scripts/catalog.py models
  python3 scripts/catalog.py graphs
  python3 scripts/catalog.py configure graph.yaml
  python3 scripts/catalog.py configure angel
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_paths  # noqa: E402
import familia_yaml  # noqa: E402

ROOT = config_paths.ROOT


def _die(msg: str, code: int = 2) -> None:
    print(f"catalog: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _load(path: str) -> dict:
    try:
        data = familia_yaml.load(path)
    except OSError as e:
        _die(f"cannot read {path}: {e}")
    if not isinstance(data, dict):
        return {}
    return data


def _graph_files() -> list[tuple[str, str]]:
    """(absolute path, kind) for every graph an operator might configure."""
    found: list[tuple[str, str]] = []
    fleet = os.path.join(ROOT, "graph.yaml")
    if os.path.isfile(fleet):
        found.append((fleet, "fleet"))
    gen = config_paths.generated_dir()
    hosts = set()
    if os.path.isfile(fleet):
        hosts = set((_load(fleet).get("hosts") or {}))
    for path in sorted(glob.glob(os.path.join(gen, "graph-*.yaml"))):
        stem = os.path.basename(path)[len("graph-"):-len(".yaml")]
        kind = "private-host" if stem in hosts else "template"
        found.append((path, kind))
    for pattern in (
        os.path.join(ROOT, "examples", "graphs", "**", "*.yaml"),
        os.path.join(ROOT, "skills", "protograph", "examples", "*.yaml"),
    ):
        for path in sorted(glob.glob(pattern, recursive=True)):
            found.append((path, "example"))
    return found


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def _used_by(graph: dict) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for name, node in (graph.get("nodes") or {}).items():
        if isinstance(node, dict) and isinstance(node.get("model"), str):
            used.setdefault(node["model"], []).append(name)
    return used


def cmd_models(graph_path: str | None = None) -> None:
    path = graph_path or config_paths.graph_path()
    g = _load(path)
    models = g.get("models") or {}
    used = _used_by(g)
    print(f"Graph models ({_rel(path)} models:)")
    if not models:
        print("  (none)")
    for key in sorted(models):
        m = models[key] if isinstance(models[key], dict) else {}
        role = m.get("role") or "-"
        arch = m.get("arch") or "-"
        nodes = ", ".join(used.get(key) or []) or "(no node)"
        print(f"  {key}  role={role} arch={arch}  nodes: {nodes}")
    options = g.get("options") or {}
    catalog = []
    if isinstance(options, dict):
        for key, opt in options.items():
            if isinstance(opt, dict) and (opt.get("role") or opt.get("hf_repo") or opt.get("unverified")):
                catalog.append((key, opt.get("role") or "-", opt.get("hf_repo") or ""))
    print()
    print(f"Unplaced options ({_rel(path)} options:):")
    if not catalog:
        print("  (none)")
    for key, role, repo in catalog:
        extra = f"  repo={repo}" if repo else ""
        print(f"  {key}  role={role}{extra}")
    db_dir = config_paths.model_db_dir()
    print()
    print(f"Model database ({_rel(db_dir)}):")
    ids = []
    if os.path.isdir(db_dir):
        for p in sorted(glob.glob(os.path.join(db_dir, "*.json"))):
            try:
                with open(p, encoding="utf-8") as fh:
                    entry = json.load(fh)
            except (OSError, json.JSONDecodeError):
                ids.append(os.path.splitext(os.path.basename(p))[0] + "  (unreadable)")
                continue
            eid = entry.get("id") if isinstance(entry, dict) else None
            ids.append(eid or os.path.splitext(os.path.basename(p))[0])
    if not ids:
        print("  (none)")
    for eid in ids:
        print(f"  {eid}")
    print()
    print(f"{len(models)} graph model(s), {len(catalog)} unplaced option(s), {len(ids)} database entries.")
    print("Show one database entry: python3 scripts/model_db.py show ID")
    print("Assign a graph model:    python3 scripts/modify_graph.py --list")


def _configure_hint(path: str, kind: str) -> str:
    rel = _rel(path)
    if kind == "fleet":
        return (
            "python3 scripts/modify_graph.py --list"
            "  |  python3 scripts/modify_graph.py --assign-model NODE=MODELS_KEY --dry-run"
            "  |  python3 scripts/validate_graph.py --graph graph.yaml --no-files"
        )
    if kind == "private-host":
        host = os.path.basename(path)[len("graph-"):-len(".yaml")]
        return (
            f"python3 scripts/generate_graph.py {host}"
            f"  |  python3 scripts/modify_graph.py --host {host} --list"
            f"  |  python3 scripts/modify_graph.py --host {host} --assign-model ROLE=MODELS_KEY --dry-run"
        )
    if kind == "example" and rel.endswith(".recipe.yaml"):
        return f"python3 scripts/protograph.py {rel}"
    return f"python3 scripts/validate_graph.py --graph {rel} --no-files"


def cmd_graphs() -> None:
    rows = _graph_files()
    print("Graphs you can configure (fleet, private host, template, example):")
    if not rows:
        print("  (none)")
        return
    for path, kind in rows:
        print(f"  [{kind}] {_rel(path)}")
        print(f"      {_configure_hint(path, kind)}")
    print()
    print("List models on the fleet graph: python3 scripts/catalog.py models")
    print("List nodes on one graph:        python3 scripts/catalog.py configure GRAPH")


def _resolve_configure(arg: str) -> tuple[str, str]:
    if arg in ("fleet", "graph.yaml", "graph.yml"):
        return os.path.join(ROOT, "graph.yaml"), "fleet"
    for path, kind in _graph_files():
        if arg == path or arg == _rel(path) or os.path.basename(arg) == os.path.basename(path):
            return path, kind
    host_graph = os.path.join(config_paths.generated_dir(), f"graph-{arg}.yaml")
    if os.path.isfile(host_graph):
        fleet_hosts = set((_load(os.path.join(ROOT, "graph.yaml")).get("hosts") or {}))
        kind = "private-host" if arg in fleet_hosts else "template"
        return host_graph, kind
    direct = arg if os.path.isabs(arg) else os.path.join(ROOT, arg)
    if os.path.isfile(direct):
        return direct, "file"
    _die(f"no graph {arg!r}. Run: python3 scripts/catalog.py graphs")
    return "", ""


def cmd_configure(arg: str) -> None:
    path, kind = _resolve_configure(arg)
    g = _load(path)
    print(f"configure {_rel(path)}  ({kind})")
    print(f"  {_configure_hint(path, kind)}")
    print()
    nodes = g.get("nodes") or {}
    if isinstance(nodes, dict) and nodes:
        print("Nodes:")
        for name in nodes:
            node = nodes[name] if isinstance(nodes[name], dict) else {}
            print(
                f"  {name}: role={node.get('role') or '-'} host={node.get('host') or '-'} "
                f"model={node.get('model') or '-'} status={node.get('status') or '-'}"
            )
    elif isinstance(g.get("graph"), dict):
        print("Alias-style entries under graph: (template, not a fleet graph.yaml):")
        for name in g["graph"]:
            print(f"  {name}")
    else:
        models = g.get("models")
        if isinstance(models, list):
            print("Template model list (not graph.yaml models: map):")
            for m in models:
                if isinstance(m, dict):
                    print(f"  {m.get('name') or '?'}  role={m.get('role') or '-'}")
        elif isinstance(models, dict) and models:
            print("Models:")
            for name in models:
                print(f"  {name}")
        else:
            print("No nodes: section. Use the command above to validate or render this file.")
    print()
    print("Nothing was written.")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    cmd = argv[0]
    if cmd == "models":
        cmd_models(argv[1] if len(argv) > 1 else None)
        return 0
    if cmd == "graphs":
        cmd_graphs()
        return 0
    if cmd == "configure":
        if len(argv) < 2:
            _die("configure needs a graph path or host name. Example: python3 scripts/catalog.py configure graph.yaml")
        cmd_configure(argv[1])
        return 0
    _die(f"unknown command {cmd!r}. Try: python3 scripts/catalog.py --help")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
