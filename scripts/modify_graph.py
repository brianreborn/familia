#!/usr/bin/env python3
"""modify_graph.py – Helper for programmatic edits to graph.yaml.

Supported actions (via command-line flags):
  --assign-model <node>=<model-name>
      Set nodes.<node>.model to <model-name> (a models: key). Edits the line in
      place and keeps every comment in graph.yaml (#76).

  --assign-model <node>=<role>:<pick>
      Legacy form: resolve the first candidate in
      code-bootstraps-llama.cpp/config/models-manifest.json matching role+pick
      and write that candidate's file path as the model field (same comment-safe
      write). Prefer the <node>=<model-name> form for the familia graph schema.

  --split-node <node> [--suffix <sfx>] [--extra key=value ...]
      Duplicate the given node by copying its raw YAML block (comments kept),
      appending <sfx> to the new node name (default "_2"). Optional --extra
      overwrites scalars on the new node only.

Example: ./scripts/modify_graph.py --assign-model coder=qwen35-2b --dry-run
"""
import argparse
import pathlib
import sys
from typing import Any, Dict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import familia_yaml  # noqa: E402
import yaml  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_GRAPH = REPO_ROOT / "graph.yaml"
MANIFEST = REPO_ROOT / "code-bootstraps-llama.cpp" / "config" / "models-manifest.json"


def load_manifest():
    with MANIFEST.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_candidate(role: str, pick: str) -> str:
    manifest = load_manifest()
    for cand in manifest.get("candidates", []):
        if cand.get("role") == role and cand.get("pick") == pick:
            return f"models/{role}/{cand['file']}"
    raise ValueError(f"No candidate found for role={role!r} pick={pick!r}")


def parse_extra(kv: str) -> Dict[str, Any]:
    if "=" not in kv:
        raise ValueError(f"Extra argument must be key=value, got {kv!r}")
    k, v = kv.split("=", 1)
    if v.isdigit():
        return {k: int(v)}
    try:
        return {k: float(v)}
    except ValueError:
        pass
    if v.lower() in ("true", "false"):
        return {k: v.lower() == "true"}
    return {k: v}


def resolve_assign(spec: str):
    """Return (node, model_value) for --assign-model NODE=MODEL or NODE=ROLE:PICK."""
    try:
        node, rhs = spec.split("=", 1)
    except ValueError:
        sys.exit("modify_graph: --assign-model must be NODE=MODEL or NODE=ROLE:PICK")
    if ":" in rhs and "/" not in rhs and not rhs.endswith(".gguf"):
        role, pick = rhs.split(":", 1)
        return node, find_candidate(role, pick)
    return node, rhs


def main():
    parser = argparse.ArgumentParser(
        description="Programmatic graph.yaml edits (comment-safe in-place writes; #76)",
        epilog="Example: ./scripts/modify_graph.py --assign-model coder=qwen35-2b --dry-run",
    )
    parser.add_argument("--host", help="If set, edit generated/graph-<host>.yaml instead of base")
    parser.add_argument("--assign-model", help="NODE=MODEL or NODE=ROLE:PICK")
    parser.add_argument("--split-node", help="Node name to duplicate")
    parser.add_argument("--suffix", default="_2", help="Suffix for duplicated node")
    parser.add_argument("--extra", action="append", help="Extra key=value pairs on the duplicated node")
    parser.add_argument("--dry-run", action="store_true", help="show the change; write nothing")
    parser.add_argument("--yes", action="store_true", help="non-interactive (reserved; no prompts today)")
    args = parser.parse_args()
    if not (args.assign_model or args.split_node):
        parser.print_help()
        sys.exit("\nmodify_graph: nothing to do. Give --assign-model or --split-node (nothing was written).")

    target_path = BASE_GRAPH if not args.host else REPO_ROOT / "generated" / f"graph-{args.host}.yaml"
    text = target_path.read_text(encoding="utf-8")
    original = text

    if args.assign_model:
        node, model_val = resolve_assign(args.assign_model)
        g = familia_yaml.loads(text)
        if node not in (g.get("nodes") or {}):
            sys.exit(f"modify_graph: node {node!r} not present in graph")
        text = familia_yaml.set_node_scalar(text, "nodes", node, "model", model_val)
        print(f"Set node {node!r} model to {model_val}")

    if args.split_node:
        extra_dict = {}
        if args.extra:
            for kv in args.extra:
                extra_dict.update(parse_extra(kv))
        new_name = f"{args.split_node}{args.suffix}"
        text = familia_yaml.duplicate_node_block(text, "nodes", args.split_node, new_name, extra_dict or None)
        print(f"Created node {new_name!r} as copy of {args.split_node!r}")

    if text == original:
        print("modify_graph: no textual change")
        return
    if args.dry_run:
        # Show a short unified-ish hint without writing
        print(f"[dry-run] would update {target_path} in place (comments kept); nothing written")
        # Count preserved comment lines as a sanity check
        before_c = sum(1 for l in original.splitlines() if l.lstrip().startswith("#"))
        after_c = sum(1 for l in text.splitlines() if l.lstrip().startswith("#"))
        print(f"[dry-run] comment lines: {before_c} -> {after_c}")
        return
    target_path.write_text(text, encoding="utf-8")
    print(f"Graph written to {target_path} (comments kept)")


if __name__ == "__main__":
    main()
