#!/usr/bin/env python3
"""Set a guardian role's supported operating level without weakening seatbelts.

Levels:
  disabled    planned status; no guardian model start
  model-only  active after local weights and sha are verified; Hermes tools remain disabled

Tool-enabled levels are intentionally unavailable until the Hermes per-action
confirmation path is implemented. This script never fetches weights or starts a process.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import familia_yaml
from graph_types import validate_types

ROLE_NODE = {"fleet": "fleet-guardian", "freebsd-guardian": "freebsd-guardian"}
MODEL = "dolphin3-cyber-8b-q2k"
LEVELS = ("disabled", "model-only")


def die(message: str, code: int = 2) -> None:
    print(f"guardian_power: {message}", file=sys.stderr)
    raise SystemExit(code)


def set_status(text: str, section: str, name: str, status: str) -> str:
    return familia_yaml.set_node_scalar(text, section, name, "status", status)


def weight_ready(graph: dict, role: str) -> tuple[bool, str]:
    model = (graph.get("models") or {}).get(MODEL) or {}
    path = pathlib.Path(os.path.expanduser(str(model.get("gguf") or "")))
    expected = model.get("sha256")
    if not path.is_file():
        return False, f"weights missing: {path}"
    if not expected or expected == "unmeasured":
        return False, "model sha256 is unmeasured"
    digest = hashlib.sha256()
    with path.open("rb") as weights:
        for chunk in iter(lambda: weights.read(1 << 20), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != str(expected).lower():
        return False, f"weight sha256 mismatch for {path}"
    node_name = ROLE_NODE[role]
    node = (graph.get("nodes") or {}).get(node_name) or {}
    if node.get("model") != MODEL:
        return False, f"nodes.{node_name} does not use {MODEL}"
    return True, str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", required=True, choices=sorted(ROLE_NODE), help="guardian entry in pentests:")
    parser.add_argument("--level", required=True, help="disabled | model-only (tool-enabled levels are not implemented)")
    parser.add_argument("--graph", type=pathlib.Path, default=ROOT / "graph.yaml")
    parser.add_argument("--write", action="store_true", help="persist the reviewed change; default prints a preview")
    args = parser.parse_args(argv)
    if args.level not in LEVELS:
        die(f"unsupported level {args.level!r}; supported: {', '.join(LEVELS)}. "
            "Hermes guardian tools are fail-closed until per-action confirmation is implemented.")

    path = args.graph.expanduser().resolve()
    if not path.is_file():
        die(f"graph not found: {path}")
    text = path.read_text(encoding="utf-8")
    graph = familia_yaml.loads(text)
    node_name = ROLE_NODE[args.role]
    pentest = (graph.get("pentests") or {}).get(args.role)
    node = (graph.get("nodes") or {}).get(node_name)
    if not isinstance(pentest, dict) or not isinstance(node, dict):
        die(f"role {args.role!r} needs pentests.{args.role} and nodes.{node_name} in this graph")
    if node.get("model") != MODEL:
        die(f"nodes.{node_name}.model must be {MODEL}; refusing to change a different role/model")
    if pentest.get("node") != node_name:
        die(f"pentests.{args.role}.node must be {node_name}")
    if (pentest.get("tools") or {}).get("allow") != []:
        die(f"pentests.{args.role}.tools.allow must remain [] for supported levels")
    if pentest.get("launch_test_only") is not True:
        die(f"pentests.{args.role}.launch_test_only must remain true for supported levels")
    if pentest.get("requires_operator_confirm") is not True:
        die(f"pentests.{args.role}.requires_operator_confirm must remain true")

    status = "planned" if args.level == "disabled" else "active"
    if args.level == "model-only":
        ready, detail = weight_ready(graph, args.role)
        if not ready:
            die(f"cannot select model-only: {detail}; see docs/guardian-weights.md")
        print(f"guardian_power: verified weights {detail}")

    updated = set_status(text, "nodes", node_name, status)
    updated = set_status(updated, "pentests", args.role, status)
    result = familia_yaml.loads(updated)
    errors = validate_types(result)
    if errors:
        die("result fails graph schema:\n  " + "\n  ".join(errors), 1)

    print(f"guardian_power: {args.role} -> {args.level} (status={status})")
    print("guardian_power: tools.allow=[], launch_test_only=true, requires_operator_confirm=true")
    print("guardian_power: no weights fetched and no process started")
    if args.write:
        path.write_text(updated, encoding="utf-8")
        print(f"guardian_power: wrote {path}")
    else:
        print("guardian_power: preview only; add --write to persist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
