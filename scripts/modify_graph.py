#!/usr/bin/env python3
"""modify_graph.py – Helper for programmatic edits to graph.yaml.

Supported actions (via command‑line flags):
  --assign-model <node>=<role>:<pick>
      Resolve the first candidate in `code-bootstraps-llama.cpp/config/models-manifest.json`
      matching the given role and pick (default/fallback/step‑up) and set the
      `model` field of the specified node to the relative path of that model.

  --split-node <node> [--suffix <sfx>] [--filter <expr>]
      Duplicate the given node, appending <sfx> to the new node name (default "_2").
      The new node inherits all fields; you can optionally add a `filter` field
      (or any extra YAML mapping) via the <expr> which is a ``key=value`` pair.

Usage examples:
  ./scripts/modify_graph.py --assign-model coder=coder:default
  ./scripts/modify_graph.py --split-node coder --suffix "_alt" --filter "parallel=2"

The script updates the *per‑host* generated graph if a host argument is given
(`--host <host>`), otherwise it edits the source `graph.yaml` in‑place.
"""
import argparse
import pathlib
import sys
import yaml
from typing import Dict, Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_GRAPH = REPO_ROOT / "graph.yaml"
MANIFEST = REPO_ROOT / "code-bootstraps-llama.cpp" / "config" / "models-manifest.json"

def load_yaml(path: pathlib.Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def dump_yaml(data: Dict[str, Any], path: pathlib.Path):
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)

def load_manifest():
    with MANIFEST.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)  # JSON format works with yaml loader

def find_candidate(role: str, pick: str):
    manifest = load_manifest()
    for cand in manifest.get("candidates", []):
        if cand.get("role") == role and cand.get("pick") == pick:
            # Build relative path that the preset expects
            rel_path = f"models/{role}/{cand['file']}"
            return rel_path
    raise ValueError(f"No candidate found for role={role!r} pick={pick!r}")

def assign_model(graph: Dict[str, Any], node: str, role: str, pick: str):
    if "nodes" not in graph:
        raise KeyError("graph missing 'nodes' section")
    if node not in graph["nodes"]:
        raise KeyError(f"Node {node!r} not present in graph")
    model_path = find_candidate(role, pick)
    graph["nodes"][node]["model"] = model_path
    print(f"Set node {node!r} model to {model_path}")

def split_node(graph: Dict[str, Any], node: str, suffix: str, extra: Dict[str, Any]):
    nodes = graph.get("nodes", {})
    if node not in nodes:
        raise KeyError(f"Node {node!r} not found")
    new_name = f"{node}{suffix}"
    if new_name in nodes:
        raise KeyError(f"Target node {new_name!r} already exists")
    # Deep copy the original node dict
    import copy
    new_node = copy.deepcopy(nodes[node])
    # Apply any extra fields supplied via --filter or similar
    new_node.update(extra)
    nodes[new_name] = new_node
    print(f"Created node {new_name!r} as copy of {node!r}")

def parse_extra(kv: str) -> Dict[str, Any]:
    # Expect "key=value" where value is parsed as int/float/bool if possible
    if "=" not in kv:
        raise ValueError(f"Extra argument must be key=value, got {kv!r}")
    k, v = kv.split("=", 1)
    # Try to interpret the value
    if v.isdigit():
        v_parsed = int(v)
    else:
        try:
            v_parsed = float(v)
        except ValueError:
            if v.lower() in ("true", "false"):
                v_parsed = v.lower() == "true"
            else:
                v_parsed = v  # leave as string
    return {k: v_parsed}

def main():
    parser = argparse.ArgumentParser(description="Programmatic graph.yaml edits")
    parser.add_argument("--host", help="If set, edit generated/graph-<host>.yaml instead of base")
    parser.add_argument("--assign-model", help="node=role:pick")
    parser.add_argument("--split-node", help="Node name to duplicate")
    parser.add_argument("--suffix", default="_2", help="Suffix for duplicated node")
    parser.add_argument("--extra", action="append", help="Extra key=value pairs to add to duplicated node")
    args = parser.parse_args()

    target_path = BASE_GRAPH if not args.host else REPO_ROOT / "generated" / f"graph-{args.host}.yaml"
    graph = load_yaml(target_path)

    if args.assign_model:
        try:
            node_part, role_pick = args.assign_model.split("=", 1)
            role, pick = role_pick.split(":", 1)
        except ValueError:
            sys.exit("--assign-model must be NODE=ROLE:PICK")
        assign_model(graph, node_part, role, pick)

    if args.split_node:
        extra_dict = {}
        if args.extra:
            for kv in args.extra:
                extra_dict.update(parse_extra(kv))
        split_node(graph, args.split_node, args.suffix, extra_dict)

    dump_yaml(graph, target_path)
    print(f"Graph written to {target_path}")

if __name__ == "__main__":
    main()
