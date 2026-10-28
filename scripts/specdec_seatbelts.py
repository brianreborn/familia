"""Race seatbelts for draft-model speculative decoding (#91).

Draft weights load **inside** the target's llama-server (`-md`); there is no
orphan draft process. Seatbelts:

- Opt-in only: ``status: planned`` emits nothing (server_args already skips).
- Missing draft GGUF → refuse when the edge is experimental/active.
- Thread / slot budget: warn above resident 4, refuse above sprint 6 (same
  locks as with-host-lock / miryam-perf L14).
- Same-host active peer threads + this node's ``-t`` must not exceed sprint 6
  when draft is enabled (cpu_oversubscribed race).

Hermes and Harness² pick draft up automatically: both start paths call
``validate_graph.server_args`` (and ``preflight_node`` below). Prefer dry
argv / unit tests on this box — no live llama restart, no DETACH_MODE screen
work here.

See docs/specdec-draft.md. Contrast n-gram (#82): prefer ``ngram-mod`` if
enabling ngram; do not revive silent ``ngram-simple`` fleet-wide.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Soft thread budget (L-miryam-perf / L14 / LESSONS "Don't oversubscribe CPU"):
# resident small jobs ~4 threads total; sprint / with-host-lock big jobs ~6.
THREAD_BUDGET_RESIDENT = 4
THREAD_BUDGET_SPRINT = 6


def enabled_draft_edges(graph: dict, node: Optional[str] = None) -> List[Tuple[str, dict]]:
    """Non-planned ``mode: draft`` speculative edges, optionally for one target node."""
    out: List[Tuple[str, dict]] = []
    for name, sp in (graph.get("speculative") or {}).items():
        if not isinstance(sp, dict):
            continue
        if sp.get("status") == "planned" or sp.get("mode") != "draft":
            continue
        if node is not None and sp.get("target") != node:
            continue
        out.append((name, sp))
    return out


def draft_gguf_path(graph: dict, sp: dict) -> Optional[str]:
    """Expanded GGUF path for a draft edge, or None if undeclared."""
    draft = sp.get("draft")
    models = graph.get("models") or {}
    m = models.get(draft) if isinstance(draft, str) else None
    if not isinstance(m, dict) or not m.get("gguf"):
        return None
    return os.path.expanduser(str(m["gguf"]))


def params_shape(graph: dict, edge_name: str) -> Dict[str, Any]:
    """Exact per-weight-file params shape for registry / docs examples (#91).

    Records target + draft model ids, GGUF paths, sha256 when present, and the
    llama.cpp flags ``server_args`` would emit when the edge is enabled.
    Live CentOS / phone speedup measure is deferred — see docs/specdec-draft.md.
    """
    sp = (graph.get("speculative") or {}).get(edge_name)
    if not isinstance(sp, dict) or sp.get("mode") != "draft":
        raise KeyError(f"speculative.{edge_name} is not a draft edge")
    target_name = sp["target"]
    node = graph["nodes"][target_name]
    target_model = graph["models"][node["model"]]
    draft_model = graph["models"][sp["draft"]]
    spec_type = sp.get("spec_type") or "draft-simple"
    shape = {
        "edge": edge_name,
        "status": sp.get("status"),
        "mode": "draft",
        "spec_type": spec_type,
        "target": {
            "node": target_name,
            "model": node["model"],
            "gguf": os.path.expanduser(target_model["gguf"]),
            "sha256": target_model.get("sha256"),
            "arch": target_model.get("arch"),
            "db": target_model.get("db"),
            "threads": node.get("threads"),
            "parallel": node.get("parallel"),
            "ctx": node.get("ctx"),
            "kv_type": node.get("kv_type"),
            "ngl": (node.get("offload") or {}).get("ngl"),
            "host": node.get("host"),
            "runtime": node.get("runtime"),
        },
        "draft": {
            "model": sp["draft"],
            "gguf": os.path.expanduser(draft_model["gguf"]),
            "sha256": draft_model.get("sha256"),
            "arch": draft_model.get("arch"),
            "db": draft_model.get("db"),
            "draft_max": sp.get("draft_max"),
            "draft_min": sp.get("draft_min"),
            "p_min": sp.get("p_min"),
            "draft_ngl": sp.get("draft_ngl", 0),
            "draft_kv_type": sp.get("draft_kv_type"),
            "draft_ctx": sp.get("draft_ctx"),
        },
        "llama_server_flags": {
            "-md": os.path.expanduser(draft_model["gguf"]),
            "--spec-type": spec_type,
            "--spec-draft-n-max": sp.get("draft_max"),
            "--spec-draft-n-min": sp.get("draft_min"),
            "--spec-draft-p-min": sp.get("p_min"),
            "-ngld": sp.get("draft_ngl", 0),
        },
        "contrast_ngram_issue": 82,
        "live_measure": "deferred",
    }
    if sp.get("draft_kv_type"):
        shape["llama_server_flags"]["-ctkd"] = sp["draft_kv_type"]
        shape["llama_server_flags"]["-ctvd"] = sp["draft_kv_type"]
    return shape


def _node_threads(node: dict) -> int:
    t = node.get("threads")
    return int(t) if isinstance(t, int) and t > 0 else 0


def _same_host_active_threads(graph: dict, host: str, exclude: Optional[str] = None) -> int:
    total = 0
    for name, n in (graph.get("nodes") or {}).items():
        if name == exclude or not isinstance(n, dict):
            continue
        if n.get("status") == "planned":
            continue
        if n.get("host") != host:
            continue
        total += _node_threads(n)
    return total


def check_draft_admission(
    graph: dict,
    node: str,
    *,
    check_files: bool = True,
) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) for enabling draft on ``node``.

    Errors refuse start; warnings are soft notes (print / WARNINGS).
    """
    errs: List[str] = []
    warns: List[str] = []
    edges = enabled_draft_edges(graph, node)
    if not edges:
        return errs, warns

    n = graph["nodes"][node]
    threads = _node_threads(n)
    parallel = int(n.get("parallel") or 1)
    host = n.get("host")

    for sn, sp in edges:
        w = f"speculative.{sn}"
        path = draft_gguf_path(graph, sp)
        if path is None:
            errs.append(f"{w}: draft model {sp.get('draft')!r} has no gguf path")
        elif check_files and not os.path.isfile(path):
            errs.append(f"{w}: draft file not found: {path}")

        if threads > THREAD_BUDGET_SPRINT:
            errs.append(
                f"{w}: target {node!r} threads {threads} > sprint budget "
                f"{THREAD_BUDGET_SPRINT} with draft resident (cpu_oversubscribed); "
                f"lower nodes.{node}.threads or keep status: planned"
            )
        elif threads > THREAD_BUDGET_RESIDENT:
            warns.append(
                f"{w}: target {node!r} threads {threads} > resident budget "
                f"{THREAD_BUDGET_RESIDENT}; draft+target share one process — "
                f"prefer ≤{THREAD_BUDGET_RESIDENT} or with-host-lock sprint"
            )

        if parallel > THREAD_BUDGET_RESIDENT:
            warns.append(
                f"{w}: target {node!r} parallel {parallel} > resident "
                f"{THREAD_BUDGET_RESIDENT}; draft slots amplify RAM race"
            )
        if parallel > THREAD_BUDGET_SPRINT:
            errs.append(
                f"{w}: target {node!r} parallel {parallel} > sprint "
                f"{THREAD_BUDGET_SPRINT} with draft enabled"
            )

        if host:
            peers = _same_host_active_threads(graph, host, exclude=node)
            combined = peers + threads
            if combined > THREAD_BUDGET_SPRINT:
                errs.append(
                    f"{w}: host {host!r} active threads {peers} + target {threads} "
                    f"= {combined} > sprint {THREAD_BUDGET_SPRINT} with draft on "
                    f"{node!r} (cpu_oversubscribed); serialize peers or keep planned"
                )
            elif combined > THREAD_BUDGET_RESIDENT:
                warns.append(
                    f"{w}: host {host!r} active threads {peers} + target {threads} "
                    f"= {combined} > resident {THREAD_BUDGET_RESIDENT} with draft"
                )

    return errs, warns


def preflight_node(
    graph: dict,
    node: str,
    *,
    check_files: bool = True,
) -> Tuple[bool, List[str], List[str]]:
    """Start-path hook for serve / start_graph / harness2 / hermes.

    Returns (ok, errors, warnings). ``ok`` is False when any error is present.
    Safe no-op when no enabled draft edge targets ``node``.
    """
    errs, warns = check_draft_admission(graph, node, check_files=check_files)
    return (not errs), errs, warns


def draft_argv_flags(graph: dict, node: str) -> List[str]:
    """Argv fragment ``server_args`` would append for enabled draft edges on ``node``.

    Unit-test helper; production path stays in ``validate_graph.server_args``.
    """
    a: List[str] = []
    for _sn, sp in enabled_draft_edges(graph, node):
        path = draft_gguf_path(graph, sp)
        if path is None:
            continue
        a += [
            "-md",
            path,
            "--spec-type",
            str(sp.get("spec_type") or "draft-simple"),
            "--spec-draft-n-max",
            str(sp["draft_max"]),
            "--spec-draft-n-min",
            str(sp["draft_min"]),
            "--spec-draft-p-min",
            str(sp["p_min"]),
            "-ngld",
            str(sp.get("draft_ngl", 0)),
        ]
        if "draft_kv_type" in sp:
            a += ["-ctkd", sp["draft_kv_type"], "-ctvd", sp["draft_kv_type"]]
    return a
