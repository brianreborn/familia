"""Race seatbelts for miryam coder perf (#83 / #82).

Platform owns layout / ICD / refuse_soname_skew (docs/platform/gpu-path-layout.md,
mirror /workspace/reviews/gpu-path-layout-miryam.md). Race owns spawn policy:
prefer CPU packs for ngl==0, inject empty GGML_VK_VISIBLE_DEVICES + --no-op-offload
when stuck on a Vulkan prebuilt, and a thin check_soname_skew TOCTOU hook.

Win empty-env / serve.ps1 is out of scope this cut.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

# Soft thread budget reminder (L-miryam-perf / L14): keep existing host locks.
# Resident small jobs ~4 threads total; sprint / with-host-lock big jobs ~6.
# Do not pin coder -t high while a same-host Vulkan ngl>0 node is also active
# without documenting the fight for the iGPU + CPU.
THREAD_BUDGET_RESIDENT = 4
THREAD_BUDGET_SPRINT = 6


def bin_is_vulkan_pack(bin_path: str) -> bool:
    """True when the path looks like a Vulkan prebuilt pack (not a CPU pack)."""
    if not bin_path:
        return False
    parts = os.path.normpath(bin_path).replace("\\", "/").lower().split("/")
    # e.g. .../llama-b11374-linux-x64-vulkan/llama-server
    return any("vulkan" in p for p in parts)


def bin_is_cpu_pack(bin_path: str) -> bool:
    if not bin_path:
        return False
    parts = os.path.normpath(bin_path).replace("\\", "/").lower().split("/")
    if any("vulkan" in p for p in parts):
        return False
    return any(
        p == "cpu" or p.endswith("-cpu") or "-cpu-" in p or p.endswith("_cpu")
        for p in parts
    )


def _runtime_bin(graph, runtime_name: str) -> Optional[str]:
    r = (graph.get("runtimes") or {}).get(runtime_name) or {}
    b = r.get("bin")
    if not b:
        return None
    b = os.path.expanduser(b)
    if os.path.isabs(b):
        return b
    root = os.path.dirname(os.path.abspath(graph.get("_path", "graph.yaml")))
    return os.path.join(root, b)


def node_wants_cpu(graph, name: str) -> bool:
    """CPU-intended when ngl==0, or backend cpu with ngl omitted/0 (not when ngl>0)."""
    n = graph["nodes"][name]
    off = n.get("offload") or {}
    ngl = off.get("ngl")
    if ngl == 0:
        return True
    if off.get("backend") == "cpu" and (ngl is None or ngl == 0):
        return True
    return False


def prefer_cpu_runtime_bin(graph, name: str) -> Tuple[str, Optional[str], List[str]]:
    """Resolve argv[0] for a node: prefer a CPU pack when ngl==0 / backend cpu.

    Returns (bin_path, runtime_name_used_or_None, notes).
    runtime_name_used is the graph runtime key when rewritten, else the node's own.
    """
    notes: List[str] = []
    n = graph["nodes"][name]
    rt_name = n["runtime"]
    bin_path = _runtime_bin(graph, rt_name)
    if bin_path is None:
        return "", rt_name, notes
    if not node_wants_cpu(graph, name):
        return bin_path, rt_name, notes
    if not bin_is_vulkan_pack(bin_path):
        return bin_path, rt_name, notes

    host = n.get("host")
    cur = graph["runtimes"].get(rt_name) or {}
    cur_build = str(cur.get("build") or "")
    best = None  # (score, rn, path)
    for rn, r in (graph.get("runtimes") or {}).items():
        if (r or {}).get("kind", "llama-server") != "llama-server":
            continue
        hosts = r.get("hosts")
        if hosts is not None and host is not None and host not in hosts:
            continue
        bp = _runtime_bin(graph, rn)
        if not bp or bin_is_vulkan_pack(bp):
            continue
        if not bin_is_cpu_pack(bp) and "cpu" not in (r.get("backends") or []):
            # Still allow if path has no vulkan and backends is cpu-only.
            backends = list(r.get("backends") or [])
            if backends and backends != ["cpu"]:
                continue
        score = 0
        if cur_build and str(r.get("build") or "") == cur_build:
            score += 100
        # Prefer backends == [cpu] (true CPU pack metadata).
        if list(r.get("backends") or []) == ["cpu"]:
            score += 50
        if bin_is_cpu_pack(bp):
            score += 20
        # Prefer an existing file when checking files; still rewrite for --args dry.
        if os.path.isfile(bp):
            score += 10
        if best is None or score > best[0]:
            best = (score, rn, bp)
    if best is None:
        notes.append(
            f"nodes.{name}: ngl 0 on Vulkan pack {bin_path}; no CPU runtime found on host "
            f"{host!r} — will inject --no-op-offload + empty GGML_VK_VISIBLE_DEVICES (#83)"
        )
        return bin_path, rt_name, notes
    notes.append(
        f"nodes.{name}: ngl 0 preferred CPU runtime {best[1]} over Vulkan pack "
        f"{rt_name} (#83; see docs/miryam-perf-race.md)"
    )
    return best[2], best[1], notes


def needs_no_op_offload(graph, name: str, bin_path: str) -> bool:
    """Inject --no-op-offload when ngl==0 but still on a Vulkan prebuilt."""
    if not node_wants_cpu(graph, name):
        return False
    return bin_is_vulkan_pack(bin_path)


def apply_no_op_offload(argv: List[str]) -> List[str]:
    """Ensure --no-op-offload is present in llama-server argv (after the binary)."""
    if "--no-op-offload" in argv:
        return list(argv)
    if not argv:
        return ["--no-op-offload"]
    # Keep binary at [0]; insert flag early among options.
    return [argv[0], "--no-op-offload", *argv[1:]]


def check_soname_skew(bin_path: str, *, note_sink: Optional[List[str]] = None) -> bool:
    """TOCTOU hook before screen-attach / exec.

    Calls Platform ``refuse_soname_skew`` when importable; otherwise skips with a note.
    Returns True if OK to proceed, False if Platform refused.
    """
    if not bin_path:
        return True
    try:
        from refuse_soname_skew import refuse_soname_skew  # type: ignore
    except ImportError:
        msg = (
            "check_soname_skew: Platform refuse_soname_skew not importable; "
            "skip (layout owned by swarm/platform/vulkan-cuda-miryam)"
        )
        if note_sink is not None:
            note_sink.append(msg)
        return True
    try:
        # Platform helper: raise / return False on skew.
        ok = refuse_soname_skew(bin_path)
        if ok is False:
            if note_sink is not None:
                note_sink.append(f"check_soname_skew: refuse_soname_skew refused {bin_path}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — surface Platform refusal
        if note_sink is not None:
            note_sink.append(f"check_soname_skew: refuse_soname_skew error: {exc}")
        return False


def warn_thread_oversubscribe(graph, name: str, notes: Optional[List[str]] = None) -> List[str]:
    """Document-only: if same host has active Vulkan ngl>0 and this CPU node pins many -t."""
    out: List[str] = [] if notes is None else notes
    n = graph["nodes"][name]
    if not node_wants_cpu(graph, name):
        return out
    host = n.get("host")
    threads = int(n.get("threads") or 0)
    vulkan_peers = []
    for oname, o in (graph.get("nodes") or {}).items():
        if oname == name or o.get("host") != host:
            continue
        if o.get("status") not in ("active", "experimental"):
            continue
        off = o.get("offload") or {}
        if int(off.get("ngl") or 0) > 0 and off.get("backend") == "vulkan":
            vulkan_peers.append(oname)
    if vulkan_peers and threads > THREAD_BUDGET_RESIDENT:
        out.append(
            f"nodes.{name}: threads {threads} with same-host Vulkan peer(s) {vulkan_peers}; "
            f"keep <= {THREAD_BUDGET_RESIDENT} resident / {THREAD_BUDGET_SPRINT} sprint "
            f"(with-host-lock); iGPU+CPU fight (docs/miryam-perf-race.md)"
        )
    return out
