#!/usr/bin/env python3
"""Offline guardian/defender readiness check (#147 Boundary / seatbelt lane).

Fail-closed. Never flips graph status planned→active. Never fetches weights.
No network calls.

Reads graph.yaml pentests + guardian nodes (miryam-pentest / angel-guardian /
private key guardian) and:

  1. Verifies dual-disable seatbelts (tools.allow empty, launch_test_only true,
     requires_operator_confirm true).
  2. Checks role JSON stubs still dual-disable.
  3. Reports GGUF path presence + sha256 vs graph (READY / MISSING / UNMEASURED /
     MISMATCH). Never auto-activates.

Exit codes:
  0  seatbelts OK and every checked weight is READY (present + sha matches)
  2  seatbelts OK but weights missing / unmeasured / mismatch
  1  seatbelt or schema failure

Example:
  python3 scripts/guardian_ready.py
  python3 scripts/guardian_ready.py --graph graph.yaml --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import familia_yaml  # noqa: E402

DEFAULT_GRAPH = os.path.join(ROOT, "graph.yaml")
ROLE_JSONS = (
    os.path.join(ROOT, "scripts", "guardian-role.json"),
    os.path.join(ROOT, "scripts", "pentest-role.json"),
)
GUARDIAN_NODE_KEYS = ("miryam-pentest", "angel-guardian", "guardian")


def _load_graph(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        g = familia_yaml.loads(f.read()) or {}
    g["_path"] = path
    return g


def _expand(path: str) -> str:
    return os.path.expanduser(path)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tools_allow(entry: dict):
    tools = entry.get("tools")
    if not isinstance(tools, dict):
        return None
    allow = tools.get("allow")
    if not isinstance(allow, list):
        return None
    return allow


def check_role_json(path: str) -> dict:
    """Seatbelt stub must keep empty tools.allow + launch_test_only true."""
    out = {"path": path, "ok": False, "errors": []}
    if not os.path.isfile(path):
        out["errors"].append(f"missing role json: {path}")
        return out
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        out["errors"].append(f"unreadable role json {path}: {e}")
        return out
    allow = _tools_allow(data)
    if allow is None:
        out["errors"].append(f"{os.path.basename(path)}: tools.allow must be a list")
    elif allow:
        out["errors"].append(
            f"{os.path.basename(path)}: tools.allow must stay empty "
            f"(dual-disable); got {allow!r}"
        )
    if data.get("launch_test_only") is not True:
        out["errors"].append(
            f"{os.path.basename(path)}: launch_test_only must be true (seatbelt)"
        )
    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    if "allow" in scope and not isinstance(scope.get("allow"), list):
        out["errors"].append(f"{os.path.basename(path)}: scope.allow must be a list")
    out["ok"] = not out["errors"]
    out["tools_allow"] = allow
    out["launch_test_only"] = data.get("launch_test_only")
    return out


def check_pentest_seatbelts(name: str, p: dict) -> dict:
    """Default seatbelts: empty tools.allow, launch_test_only true, confirm gate."""
    w = f"pentests.{name}"
    out = {"name": name, "ok": False, "errors": [], "warnings": []}
    if not isinstance(p, dict):
        out["errors"].append(f"{w}: expected mapping")
        return out

    allow = _tools_allow(p)
    if allow is None:
        out["errors"].append(f"{w}.tools.allow: required list (empty = dual-disable)")
    elif allow:
        out["errors"].append(
            f"{w}.tools.allow: non-empty {allow!r}; default seatbelt is [] "
            "(widen only by operator graph edit + confirm; do not remove for CI)"
        )

    if p.get("launch_test_only") is not True:
        out["errors"].append(
            f"{w}: launch_test_only must be true for default seatbelt "
            f"(got {p.get('launch_test_only')!r})"
        )

    if p.get("requires_operator_confirm") is not True:
        out["errors"].append(
            f"{w}: requires_operator_confirm must be true "
            f"(got {p.get('requires_operator_confirm')!r})"
        )

    scope = p.get("scope") if isinstance(p.get("scope"), dict) else None
    if scope is None:
        out["errors"].append(f"{w}.scope: expected mapping with allow/deny")
    else:
        if "allow" not in scope or "deny" not in scope:
            out["errors"].append(f"{w}.scope: need allow and deny keys")
        allow_s = scope.get("allow")
        if allow_s is not None and not isinstance(allow_s, list):
            out["errors"].append(f"{w}.scope.allow: expected list")
        if isinstance(allow_s, list) and not allow_s:
            out["warnings"].append(
                f"{w}.scope.allow empty = default-deny appliances (OK seatbelt)"
            )

    status = p.get("status")
    if status == "active":
        out["warnings"].append(
            f"{w}: status active — ready-check never flips this; "
            "Hermes/operator own planned→active after measured sha"
        )
    elif status not in ("planned", None):
        out["errors"].append(f"{w}: unexpected status {status!r}")

    out["ok"] = not out["errors"]
    out["status"] = status
    out["node"] = p.get("node")
    out["tools_allow"] = allow
    out["launch_test_only"] = p.get("launch_test_only")
    out["requires_operator_confirm"] = p.get("requires_operator_confirm")
    return out


def check_weight(model_name: str, model: dict) -> dict:
    """Report GGUF presence/sha. Fail closed: never claim READY on unmeasured."""
    out = {
        "model": model_name,
        "state": "MISSING",
        "gguf": None,
        "path": None,
        "expected_sha256": None,
        "actual_sha256": None,
        "ready": False,
        "errors": [],
    }
    if not isinstance(model, dict):
        out["errors"].append(f"models.{model_name}: missing")
        return out
    gguf = model.get("gguf")
    sha = model.get("sha256")
    out["gguf"] = gguf
    out["expected_sha256"] = sha
    if not gguf or not isinstance(gguf, str):
        out["errors"].append(f"models.{model_name}: gguf path missing")
        return out
    path = _expand(gguf)
    out["path"] = path
    if not os.path.isfile(path):
        out["state"] = "MISSING"
        out["errors"].append(f"models.{model_name}: GGUF not present at {path}")
        return out
    if not sha or sha == "unmeasured":
        out["state"] = "UNMEASURED"
        out["errors"].append(
            f"models.{model_name}: sha256 unmeasured "
            "(Hermes/operator: measure after fetch; ready-check will not activate)"
        )
        return out
    try:
        actual = _sha256_file(path)
    except OSError as e:
        out["state"] = "MISSING"
        out["errors"].append(f"models.{model_name}: cannot read {path}: {e}")
        return out
    out["actual_sha256"] = actual
    if actual.lower() != str(sha).lower():
        out["state"] = "MISMATCH"
        out["errors"].append(
            f"models.{model_name}: sha256 mismatch "
            f"(expected {sha}, got {actual})"
        )
        return out
    out["state"] = "READY"
    out["ready"] = True
    return out


def check_guardian_node(name: str, node: dict, models: dict) -> dict:
    out = {"node": name, "ok": True, "errors": [], "warnings": [], "weight": None}
    if not isinstance(node, dict):
        out["ok"] = False
        out["errors"].append(f"nodes.{name}: missing")
        return out
    role = node.get("role")
    if role not in ("guardian", "pentest"):
        out["warnings"].append(
            f"nodes.{name}: role is {role!r} (expected guardian or pentest synonym)"
        )
    status = node.get("status")
    out["status"] = status
    if status == "active":
        out["warnings"].append(
            f"nodes.{name}: status active — Boundary ready-check does not flip this"
        )
    model_name = node.get("model")
    out["model"] = model_name
    m = models.get(model_name) if model_name else None
    out["weight"] = check_weight(model_name or "?", m or {})
    return out


def collect_guardian_nodes(g: dict) -> dict:
    """Nodes referenced by pentests.* plus known guardian keys present in graph."""
    nodes = g.get("nodes") or {}
    found = {}
    for _pname, p in (g.get("pentests") or {}).items():
        if isinstance(p, dict) and p.get("node"):
            n = p["node"]
            if n in nodes:
                found[n] = nodes[n]
    for key in GUARDIAN_NODE_KEYS:
        if key in nodes and key not in found:
            nd = nodes[key]
            if isinstance(nd, dict) and (
                nd.get("role") in ("guardian", "pentest") or key in GUARDIAN_NODE_KEYS
            ):
                found[key] = nd
    return found


def run_check(graph_path: str) -> dict:
    """Full offline check. Never mutates the graph."""
    report = {
        "ok_seatbelts": False,
        "weights_ready": False,
        "exit_hint": 1,
        "graph": graph_path,
        "role_jsons": [],
        "pentests": [],
        "nodes": [],
        "errors": [],
        "warnings": [],
        "note": (
            "Fail-closed: never sets status active. "
            "Hermes Wiring owns GGUF fetch + measured sha + planned→active. "
            "Boundary owns seatbelts + this ready-check."
        ),
    }
    try:
        g = _load_graph(graph_path)
    except (OSError, ValueError) as e:
        report["errors"].append(f"cannot load graph: {e}")
        report["exit_hint"] = 1
        return report

    for path in ROLE_JSONS:
        rj = check_role_json(path)
        report["role_jsons"].append(rj)

    pentests = g.get("pentests") or {}
    if not pentests:
        report["errors"].append(
            "graph has no pentests: section (guardian seatbelts live there)"
        )
    for name, p in pentests.items():
        pc = check_pentest_seatbelts(name, p if isinstance(p, dict) else {})
        report["pentests"].append(pc)
        report["warnings"].extend(pc.get("warnings") or [])

    models = g.get("models") or {}
    gnodes = collect_guardian_nodes(g)
    if not gnodes:
        report["errors"].append(
            "no guardian nodes found (expected miryam-pentest / angel-guardian)"
        )

    weight_msgs = []
    all_weights_ready = True
    any_weight = False
    for name, node in gnodes.items():
        nc = check_guardian_node(name, node, models)
        report["nodes"].append(nc)
        report["warnings"].extend(nc.get("warnings") or [])
        if nc.get("errors"):
            report["errors"].extend(nc["errors"])
        w = nc.get("weight")
        if w:
            any_weight = True
            if not w.get("ready"):
                all_weights_ready = False
            for e in w.get("errors") or []:
                if e not in weight_msgs:
                    weight_msgs.append(e)

    report["warnings"].extend(weight_msgs)

    for r in report["role_jsons"]:
        report["errors"].extend(r["errors"])
    for p in report["pentests"]:
        report["errors"].extend(p["errors"])

    report["ok_seatbelts"] = (
        all(r["ok"] for r in report["role_jsons"])
        and all(p["ok"] for p in report["pentests"])
        and bool(gnodes)
        and not any(
            e.startswith("no guardian")
            or e.startswith("graph has no pentests")
            or e.startswith("cannot load")
            or e.startswith("nodes.")
            for e in report["errors"]
        )
        and not any(r["errors"] for r in report["role_jsons"])
        and not any(p["errors"] for p in report["pentests"])
    )
    report["weights_ready"] = bool(any_weight and all_weights_ready)

    if not report["ok_seatbelts"]:
        report["exit_hint"] = 1
    elif report["weights_ready"]:
        report["exit_hint"] = 0
    else:
        report["exit_hint"] = 2
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Offline guardian seatbelt + weight readiness "
            "(fail-closed; no network; never activates)"
        )
    )
    ap.add_argument("--graph", default=DEFAULT_GRAPH, help="path to graph.yaml")
    ap.add_argument("--json", action="store_true", help="print machine-readable report")
    args = ap.parse_args(argv)
    report = run_check(args.graph)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"guardian_ready: graph={report['graph']}")
        print(f"  seatbelts: {'OK' if report['ok_seatbelts'] else 'FAIL'}")
        print(f"  weights:   {'READY' if report['weights_ready'] else 'NOT READY'}")
        for rj in report["role_jsons"]:
            mark = "OK" if rj["ok"] else "FAIL"
            print(f"  role_json {os.path.basename(rj['path'])}: {mark}")
        for p in report["pentests"]:
            mark = "OK" if p["ok"] else "FAIL"
            print(
                f"  pentest {p['name']}: {mark} "
                f"(launch_test_only={p.get('launch_test_only')} "
                f"tools.allow={p.get('tools_allow')} status={p.get('status')})"
            )
        for n in report["nodes"]:
            w = n.get("weight") or {}
            print(
                f"  node {n['node']}: status={n.get('status')} "
                f"model={n.get('model')} weight={w.get('state')}"
            )
        for e in report["errors"]:
            print(f"  ERROR: {e}")
        for w in report["warnings"]:
            print(f"  WARN:  {w}")
        print(f"  note: {report['note']}")
        print(f"  exit: {report['exit_hint']}")
    return int(report["exit_hint"])


if __name__ == "__main__":
    sys.exit(main())
