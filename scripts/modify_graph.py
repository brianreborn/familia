#!/usr/bin/env python3
"""modify_graph.py – Comment-safe edits to graph.yaml (or a private host graph).

Design law: assign models by node *type* (coder, chat, embed, …). On a private
host graph (--host angel) those type names are the node keys. On the fleet
graph.yaml, transitional host-prefixed keys may still exist — prefer
`--host HOST` after `generate_graph.py HOST`.

Supported actions:
  --list
      Show nodes (name, role, host, model, status, port) and models: keys.

  --assign-model <node>=<models-key>
      Set nodes.<node>.model to a models: key (validated). Comment-safe (#76).

  --assign-model <node>=<role>:<pick>
      Resolve to a models: key with matching role (never writes a GGUF path).

  --split-node <node> [--suffix <sfx>] [--extra key=value ...]
      Duplicate a node block (comments kept).

Examples:
  ./scripts/modify_graph.py --list
  ./scripts/modify_graph.py --host angel --list
  ./scripts/modify_graph.py --host angel --assign-model coder=nanbeige43-33b-q4km --dry-run
  ./scripts/modify_graph.py --assign-model coder=qwen35-2b-q4km --dry-run
"""
import argparse
import pathlib
import sys
from typing import Any, Dict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import familia_yaml  # noqa: E402
from node_role import (  # noqa: E402
    infer_role,
    is_host_prefixed,
    model_keys,
    resolve_model_assign,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_GRAPH = REPO_ROOT / "graph.yaml"
MANIFEST = REPO_ROOT / "code-bootstraps-llama.cpp" / "config" / "models-manifest.json"
import os
# FAMILIA_GENERATED_DIR redirects generated graphs (tests use tmp; CFG-FILE-007b)
GENERATED = pathlib.Path(os.environ.get("FAMILIA_GENERATED_DIR") or (REPO_ROOT / "generated"))


def load_manifest():
    import yaml
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


def resolve_assign(spec: str, graph: dict):
    try:
        node, rhs = spec.split("=", 1)
    except ValueError:
        sys.exit("modify_graph: --assign-model must be NODE=MODEL or NODE=ROLE:PICK")
    try:
        model_val = resolve_model_assign(graph, rhs, manifest_finder=find_candidate)
    except ValueError as e:
        sys.exit(f"modify_graph: {e}")
    return node, model_val


def list_graph(path: pathlib.Path, text: str) -> None:
    g = familia_yaml.loads(text)
    nodes = g.get("nodes") or {}
    print(f"graph: {path}")
    print(f"models: {', '.join(model_keys(g))}")
    print("nodes:")
    prefixed = []
    for name, n in nodes.items():
        if not isinstance(n, dict):
            print(f"  {name}: <non-map>")
            continue
        role = infer_role(name, n, g)
        line = (
            f"  {name}: role={role} host={n.get('host')} model={n.get('model')} "
            f"status={n.get('status')} port={n.get('port')}"
        )
        print(line)
        if is_host_prefixed(name, g):
            prefixed.append(name)
    if prefixed:
        print(
            "note: host-prefixed keys are a transitional fleet-graph design error; "
            "prefer private topology: python3 scripts/generate_graph.py HOST && "
            "python3 scripts/modify_graph.py --host HOST --assign-model coder=<models-key>"
        )
        print("      prefixed:", ", ".join(prefixed))


def ensure_host_graph(host: str) -> pathlib.Path:
    path = GENERATED / f"graph-{host}.yaml"
    if not path.is_file():
        print(f"modify_graph: {path} missing — generating private topology…", file=sys.stderr)
        import subprocess
        r = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "generate_graph.py"), host],
            cwd=str(REPO_ROOT),
        )
        if r.returncode != 0 or not path.is_file():
            sys.exit(f"modify_graph: failed to generate {path}")
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Programmatic graph edits (comment-safe; models: keys only)",
        epilog="Example: ./scripts/modify_graph.py --host angel --assign-model coder=nanbeige43-33b-q4km --dry-run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", help="Edit generated/graph-HOST.yaml (private type-named topology)")
    parser.add_argument("--assign-model", help="NODE=MODELS_KEY or NODE=ROLE:PICK")
    parser.add_argument("--split-node", help="Node name to duplicate")
    parser.add_argument("--suffix", default="_2", help="Suffix for duplicated node")
    parser.add_argument("--extra", action="append", help="Extra key=value pairs on the duplicated node")
    parser.add_argument("--list", action="store_true", help="List nodes and models; write nothing")
    parser.add_argument("--dry-run", action="store_true", help="show the change; write nothing")
    parser.add_argument("--yes", action="store_true", help="non-interactive (reserved; no prompts today)")
    parser.add_argument(
        "--regenerate-host",
        action="store_true",
        help="With --host: regenerate private topology from graph.yaml before editing",
    )
    args = parser.parse_args()
    if not (args.assign_model or args.split_node or args.list):
        parser.print_help()
        sys.exit("\nmodify_graph: nothing to do. Give --list, --assign-model, or --split-node.")

    if args.host:
        if args.regenerate_host or not (GENERATED / f"graph-{args.host}.yaml").is_file():
            import subprocess
            r = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "generate_graph.py"), args.host],
                cwd=str(REPO_ROOT),
            )
            if r.returncode != 0:
                sys.exit(f"modify_graph: generate_graph {args.host} failed")
        target_path = ensure_host_graph(args.host)
    else:
        target_path = BASE_GRAPH

    text = target_path.read_text(encoding="utf-8")
    original = text
    g = familia_yaml.loads(text)

    if args.list:
        list_graph(target_path, text)
        return

    if args.assign_model:
        node, model_val = resolve_assign(args.assign_model, g)
        if node not in (g.get("nodes") or {}):
            names = sorted((g.get("nodes") or {}))
            hint = ""
            if not args.host and any(n.endswith("-" + node) or n.startswith(node) for n in names):
                hint = (
                    f" Fleet graph has host-prefixed keys {names}. "
                    f"Use: --host <host> --assign-model {node}={model_val} "
                    f"(private topology uses type names)."
                )
            sys.exit(f"modify_graph: node {node!r} not present in {target_path}.{hint}")
        # Validate again against live models map
        if model_val not in (g.get("models") or {}):
            sys.exit(f"modify_graph: models: key {model_val!r} missing in {target_path}")
        text = familia_yaml.set_node_scalar(text, "nodes", node, "model", model_val)
        print(f"Set node {node!r} model to {model_val}")

    if args.split_node:
        if args.host:
            sys.exit(
                "modify_graph: --split-node on a private host graph usually violates "
                "one-role-per-host; edit fleet graph.yaml without --host, then regenerate"
            )
        extra_dict = {}
        if args.extra:
            for kv in args.extra:
                extra_dict.update(parse_extra(kv))
        new_name = f"{args.split_node}{args.suffix}"
        text = familia_yaml.duplicate_node_block(text, "nodes", args.split_node, new_name, extra_dict or None)
        print(f"Created node {new_name!r} as copy of {args.split_node!r}")

    if text == original:
        print("modify_graph: no textual change")
        # still allow --host assign to report fleet sync status when values match
        if not (args.host and args.assign_model):
            return

    def sync_fleet():
        if not (args.host and args.assign_model):
            return
        fleet_text = BASE_GRAPH.read_text(encoding="utf-8")
        fleet = familia_yaml.loads(fleet_text)
        node, model_val = resolve_assign(args.assign_model, g)
        fleet_name = None
        for fname, fnode in (fleet.get("nodes") or {}).items():
            if not isinstance(fnode, dict):
                continue
            if fnode.get("host") != args.host:
                continue
            if infer_role(fname, fnode, fleet) == node or fname == node:
                fleet_name = fname
                break
        if fleet_name is None:
            print(
                f"warning: no fleet graph.yaml node on host={args.host!r} with role/name {node!r}",
                file=sys.stderr,
            )
            return
        synced = familia_yaml.set_node_scalar(fleet_text, "nodes", fleet_name, "model", model_val)
        if synced == fleet_text:
            print(f"fleet graph.yaml nodes.{fleet_name}.model already {model_val}")
            return
        if args.dry_run:
            print(f"[dry-run] would also sync fleet graph.yaml nodes.{fleet_name}.model → {model_val}")
            return
        BASE_GRAPH.write_text(synced, encoding="utf-8")
        print(f"Also synced fleet graph.yaml nodes.{fleet_name}.model → {model_val}")

    if text != original:
        if args.dry_run:
            print(f"[dry-run] would update {target_path} in place (comments kept); nothing written")
            before_c = sum(1 for l in original.splitlines() if l.lstrip().startswith("#"))
            after_c = sum(1 for l in text.splitlines() if l.lstrip().startswith("#"))
            print(f"[dry-run] comment lines: {before_c} -> {after_c}")
        else:
            target_path.write_text(text, encoding="utf-8")
            print(f"Graph written to {target_path} (comments kept where present)")
    sync_fleet()



if __name__ == "__main__":
    main()
