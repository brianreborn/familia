#!/usr/bin/env python3
"""generate_graph.py – Build a per-host graph (private topology by default).

Usage:
  ./scripts/generate_graph.py <host> [--set <node>=<model_key> ...]
  ./scripts/generate_graph.py <host> --fleet-merge   # legacy: full fleet dump + overrides

Default (--private): only nodes with host=<host>, renamed to type/role keys
(coder, chat, embed, …). Placement stays on node.host. This is the design law:
type implies capability; no angel-coder-style fake unique names in the operator
graph. Fleet graph.yaml may still use transitional host-prefixed keys until the
fleet map is reshaped.

Writes generated/graph-<host>.yaml (comments from fleet graph are not preserved;
edit graph.yaml then regenerate).
"""
import argparse
import pathlib
import sys
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from node_role import private_topology, resolve_model_assign  # noqa: E402
from box_archetypes import shape_for, shape_header_lines, merge_shape_roles  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
import familia_yaml  # DUP-01 loader owner
BASE_GRAPH = REPO_ROOT / "graph.yaml"
OVERrides_FILE = REPO_ROOT / "config" / "host-overrides.yaml"
import os
# FAMILIA_GENERATED_DIR redirects output (tests use tmp; CFG-FILE-007b)
import config_paths  # noqa: E402
OUTPUT_DIR = pathlib.Path(config_paths.generated_dir())


def load_yaml(path: pathlib.Path):
    return familia_yaml.load(str(path)) or {}  # DUP-01


def merge_dict(base: dict, overrides: dict):
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge_dict(base[k], v)
        else:
            base[k] = v
    return base


def parse_set_args(set_args, graph):
    """Parse node=model_key (models: keys only)."""
    result = {}
    for item in set_args:
        if "=" not in item:
            raise ValueError(f"Invalid --set argument: {item!r}")
        node, model = item.split("=", 1)
        model = resolve_model_assign(graph, model)
        result.setdefault("nodes", {})[node] = {"model": model}
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Write generated/graph-HOST.yaml (private type-named topology by default).",
        epilog="Example: ./scripts/generate_graph.py angel",
    )
    parser.add_argument("host", help="Name of the host defined in the graph's hosts section")
    parser.add_argument(
        "--set",
        dest="set_args",
        action="append",
        default=[],
        help="Override node model on the output graph: <node>=<models-key>",
    )
    parser.add_argument(
        "--fleet-merge",
        action="store_true",
        help="Legacy: copy full fleet graph + overrides (keeps host-prefixed keys)",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        default=True,
        help="Private topology (default): type-named nodes for this host only",
    )
    parser.add_argument(
        "--no-private",
        action="store_true",
        help="Disable private topology (same as --fleet-merge)",
    )
    args = parser.parse_args()
    private = not (args.fleet_merge or args.no_private)

    hosts = (load_yaml(BASE_GRAPH).get("hosts") or {}) if BASE_GRAPH.is_file() else {}
    if hosts and args.host not in hosts:
        sys.exit(f"generate_graph: no host {args.host!r} in graph.yaml. Hosts: {', '.join(sorted(hosts))}")
    if not BASE_GRAPH.is_file():
        sys.exit(f"Base graph not found at {BASE_GRAPH}")

    base = load_yaml(BASE_GRAPH)
    if OVERrides_FILE.is_file():
        all_overrides = load_yaml(OVERrides_FILE)
        host_overrides = all_overrides.get(args.host, {})
        if host_overrides:
            base = merge_dict(base, host_overrides)

    rename = {}
    if private:
        try:
            from node_role import infer_role, host_prefixes  # noqa: F401
            # Capture rename for the banner
            local = {
                n: d for n, d in (base.get("nodes") or {}).items()
                if isinstance(d, dict) and d.get("host") == args.host
            }
            for old, node in local.items():
                rename[old] = infer_role(old, node, base)
            base = private_topology(base, args.host)
        except ValueError as e:
            sys.exit(f"generate_graph: {e}")

    if args.set_args:
        try:
            cli_overrides = parse_set_args(args.set_args, base)
        except ValueError as e:
            sys.exit(f"generate_graph: {e}")
        base = merge_dict(base, cli_overrides)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"graph-{args.host}.yaml"
    # Never persist internal bookkeeping keys
    base.pop("_familia_private", None)

    host_meta = (base.get("hosts") or {}).get(args.host) or {}
    kind = host_meta.get("kind") or "unknown"
    shape = shape_for(kind)
    # Order private nodes by platform shape roles, then any extras (overrides stay as-is).
    nodes = base.get("nodes") or {}
    if isinstance(nodes, dict) and nodes:
        ordered = {}
        for role in merge_shape_roles(nodes, kind):
            if role in nodes:
                ordered[role] = nodes[role]
        for role, nd in nodes.items():
            if role not in ordered:
                ordered[role] = nd
        base["nodes"] = ordered

    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Generated by scripts/generate_graph.py — do not hand-edit.\n")
        f.write(f"# host: {args.host}  private: {str(private).lower()}\n")
        if rename:
            f.write("# renamed: " + ", ".join(f"{a}->{b}" for a, b in sorted(rename.items())) + "\n")
        f.write("# Source of truth: graph.yaml (regenerate after edits).\n")
        for line in shape_header_lines(kind, args.host):
            f.write(line + "\n")
        implied = list(shape.get("roles") or [])
        present = list((base.get("nodes") or {}).keys())
        missing = [r for r in implied if r not in present]
        if missing:
            f.write(
                "# shape roles not yet placed on this host (add in graph.yaml or --set): "
                + ", ".join(missing) + "\n"
            )
        yaml.safe_dump(base, f, sort_keys=False)
    mode = "private type-named" if private else "fleet-merge"
    print(f"Generated {mode} graph for host '{args.host}' → {out_path}")
    print(f"Platform kind={kind!r} shape roles={shape.get('roles')}")
    if rename:
        print("Renamed:", ", ".join(f"{a}→{b}" for a, b in sorted(rename.items())))
    print("Nodes:", ", ".join(f"{n} (model={(base.get('nodes') or {}).get(n, {}).get('model')}, "
                              f"status={(base.get('nodes') or {}).get(n, {}).get('status')})"
                              for n in (base.get("nodes") or {})))



if __name__ == "__main__":
    main()
