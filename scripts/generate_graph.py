#!/usr/bin/env python3
"""generate_graph.py – Dynamically build a per‑host graph.

Usage:
  ./scripts/generate_graph.py <host> [--set <node>=<model_path> ...]

The script reads the canonical ``graph.yaml`` at the repository root,
applies per‑host overrides (if a ``config/host-overrides.yaml`` file
exists) and any ``--set`` arguments supplied on the command line, then
writes the resulting graph to ``generated/graph-<host>.yaml``.

Check the result with ``scripts/validate_graph.py --graph generated/graph-<host>.yaml``.
The original ``graph.yaml`` is not edited.

Example:
  ./scripts/generate_graph.py miryam
"""
import argparse
import pathlib
import sys
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_GRAPH = REPO_ROOT / "graph.yaml"
OVERrides_FILE = REPO_ROOT / "config" / "host-overrides.yaml"
OUTPUT_DIR = REPO_ROOT / "generated"

def load_yaml(path: pathlib.Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def merge_dict(base: dict, overrides: dict):
    """Recursively merge ``overrides`` into ``base``.
    Lists are replaced entirely; scalar values are overwritten.
    """
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge_dict(base[k], v)
        else:
            base[k] = v
    return base

def parse_set_args(set_args):
    """Parse ``node=model_path`` strings into a nested dict.
    Example: "coder=~/models/Qwen3.5-2B.gguf" → {"nodes": {"coder": {"model": "~/models/..."}}}
    """
    result = {}
    for item in set_args:
        if "=" not in item:
            raise ValueError(f"Invalid --set argument: {item!r}")
        node, model_path = item.split("=", 1)
        # Build nested dict structure
        result.setdefault("nodes", {})[node] = {"model": model_path}
    return result

def main():
    parser = argparse.ArgumentParser(description="Write generated/graph-HOST.yaml: graph.yaml plus that host's overrides.",
                                     epilog="Example: ./scripts/generate_graph.py miryam --set coder=~/models/Qwen3.5-2B-Q4_K_M.gguf")
    parser.add_argument("host", help="Name of the host defined in the graph's hosts section")
    parser.add_argument("--set", dest="set_args", action="append", default=[], help="Override node model: <node>=<model_path>")
    args = parser.parse_args()

    hosts = (load_yaml(BASE_GRAPH).get("hosts") or {}) if BASE_GRAPH.is_file() else {}
    if hosts and args.host not in hosts:
        sys.exit(f"generate_graph: no host {args.host!r} in graph.yaml. Hosts: {', '.join(sorted(hosts))}")
    if not BASE_GRAPH.is_file():
        sys.exit(f"Base graph not found at {BASE_GRAPH}")

    base = load_yaml(BASE_GRAPH)
    # Apply host‑specific overrides if present
    if OVERrides_FILE.is_file():
        all_overrides = load_yaml(OVERrides_FILE)
        host_overrides = all_overrides.get(args.host, {})
        if host_overrides:
            base = merge_dict(base, host_overrides)

    # Apply command‑line overrides
    if args.set_args:
        cli_overrides = parse_set_args(args.set_args)
        base = merge_dict(base, cli_overrides)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"graph-{args.host}.yaml"
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(base, f, sort_keys=False)
    print(f"Generated graph for host '{args.host}' → {out_path}")

if __name__ == "__main__":
    main()
