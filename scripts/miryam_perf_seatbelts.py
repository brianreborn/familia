"""Race seatbelts for miryam coder perf (#83 / #82).

Platform owns layout / ICD / refuse_soname_skew (docs/platform/gpu-path-layout.md,
mirror /workspace/reviews/gpu-path-layout-miryam.md). Race owns spawn policy:
prefer CPU packs for ngl==0, inject empty GGML_VK_VISIBLE_DEVICES + --no-op-offload
when stuck on a Vulkan prebuilt, check_soname_skew (soft→hard), and
assert_fingerprint_stable TOCTOU re-stat before screen attach / exec.

Win empty-env / serve.ps1 is out of scope this cut.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple
import argparse
import json
import sys

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


# Platform fingerprint() file-id fields Race compares for TOCTOU (no fingerprints_equal).
_FP_ID_KEYS = ("ino", "mtime_ns", "size", "dev")


def _file_id_slice(entry: object) -> tuple:
    """Extract (ino, mtime_ns, size, dev) from a Platform fingerprint file_id dict."""
    if not isinstance(entry, dict):
        return ()
    return tuple(entry.get(k) for k in _FP_ID_KEYS)


def check_soname_skew(bin_path: str, *, note_sink: Optional[List[str]] = None) -> bool:
    """First refuse after PolicyGate (soft skip if Platform missing → hard when present).

    Calls Platform ``refuse_soname_skew`` when importable. Soft→hard is Race-side:
    a Platform ``{ok: false}`` dict refuses; ImportError skips with a note.
    Returns True if OK to proceed, False if refused.
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
        result = refuse_soname_skew(bin_path)
    except Exception as exc:  # noqa: BLE001 — surface Platform refusal
        if note_sink is not None:
            note_sink.append(f"check_soname_skew: refuse_soname_skew error: {exc}")
        return False
    # Soft→hard: Platform returns a JSON dict with ok; legacy False also refuses.
    if isinstance(result, dict):
        if result.get("ok"):
            return True
        reason = result.get("reason") or "soname_skew"
        if note_sink is not None:
            note_sink.append(
                f"check_soname_skew: refuse_soname_skew refused {bin_path} ({reason})"
            )
        return False
    if result is False:
        if note_sink is not None:
            note_sink.append(f"check_soname_skew: refuse_soname_skew refused {bin_path}")
        return False
    return True


def capture_spawn_fingerprint(
    bin_path: str, *, note_sink: Optional[List[str]] = None
) -> Optional[dict]:
    """Stat bin + pack libs after first refuse (Platform ``fingerprint`` when present).

    Returns None when Platform is not importable (caller treats as soft skip).
    """
    if not bin_path:
        return None
    try:
        from refuse_soname_skew import fingerprint  # type: ignore
    except ImportError:
        if note_sink is not None:
            note_sink.append(
                "capture_spawn_fingerprint: Platform fingerprint not importable; skip"
            )
        return None
    try:
        return fingerprint(bin_path)
    except Exception as exc:  # noqa: BLE001
        if note_sink is not None:
            note_sink.append(f"capture_spawn_fingerprint: fingerprint error: {exc}")
        return None


def assert_fingerprint_stable(
    bin_path: str,
    capture: Optional[dict],
    *,
    note_sink: Optional[List[str]] = None,
) -> dict:
    """Late re-stat before screen attach / final exec. Hard-refuse on drift.

    Compares Platform ``fingerprint(bin)`` dicts directly: top-level ``bin`` plus
    each ``libs[]`` ``ino`` / ``mtime_ns`` / ``size`` / ``dev``. No
    ``fingerprints_equal`` helper — Race owns the compare.

    Returns JSON-shaped ``{ok, reason, hook, ...}``. Soft skip when Platform
    fingerprint is unavailable or there was no prior capture.
    """
    result: dict = {
        "ok": True,
        "reason": "ok",
        "hook": "assert_fingerprint_stable",
        "bin": bin_path,
        "capture": capture,
        "capture2": None,
    }
    try:
        from refuse_soname_skew import fingerprint  # type: ignore
    except ImportError:
        result["reason"] = "skipped_no_platform"
        if note_sink is not None:
            note_sink.append(
                "assert_fingerprint_stable: Platform fingerprint not importable; skip"
            )
        return result

    if capture is None:
        result["reason"] = "skipped_no_prior_capture"
        if note_sink is not None:
            note_sink.append(
                "assert_fingerprint_stable: no prior capture; skip (soft)"
            )
        return result

    try:
        capture2 = fingerprint(bin_path)
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["reason"] = "fingerprint_error"
        result["error"] = str(exc)
        if note_sink is not None:
            note_sink.append(f"assert_fingerprint_stable: fingerprint error: {exc}")
        return result
    result["capture2"] = capture2

    b1 = capture.get("bin") if isinstance(capture, dict) else None
    b2 = capture2.get("bin") if isinstance(capture2, dict) else None
    if _file_id_slice(b1) != _file_id_slice(b2):
        result["ok"] = False
        result["reason"] = "soname_fingerprint_drift"
        result["drift"] = {"bin": {"before": b1, "after": b2}}
        if note_sink is not None:
            note_sink.append(
                f"assert_fingerprint_stable: bin fingerprint drift for {bin_path}"
            )
        return result

    libs1 = list((capture.get("libs") or []) if isinstance(capture, dict) else [])
    libs2 = list((capture2.get("libs") or []) if isinstance(capture2, dict) else [])

    def _by_path(libs: List[object]) -> dict:
        out: dict = {}
        for entry in libs:
            if not isinstance(entry, dict):
                continue
            out[entry.get("path")] = entry
        return out

    m1, m2 = _by_path(libs1), _by_path(libs2)
    if set(m1.keys()) != set(m2.keys()):
        result["ok"] = False
        result["reason"] = "soname_fingerprint_drift"
        result["drift"] = {
            "libs_paths": {
                "before": sorted(k for k in m1 if k is not None),
                "after": sorted(k for k in m2 if k is not None),
            }
        }
        if note_sink is not None:
            note_sink.append(
                f"assert_fingerprint_stable: libs path set drift for {bin_path}"
            )
        return result
    for path_key, before in m1.items():
        after = m2[path_key]
        if _file_id_slice(before) != _file_id_slice(after):
            result["ok"] = False
            result["reason"] = "soname_fingerprint_drift"
            result["drift"] = {"lib": path_key, "before": before, "after": after}
            if note_sink is not None:
                note_sink.append(
                    f"assert_fingerprint_stable: lib fingerprint drift {path_key}"
                )
            return result
    return result


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


def main(argv: Optional[List[str]] = None) -> int:
    """CLI for serve.sh: capture / assert-stable fingerprint TOCTOU."""
    ap = argparse.ArgumentParser(description="Race miryam spawn fingerprint TOCTOU")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="print Platform fingerprint JSON or null")
    cap.add_argument("--bin", required=True)

    ast = sub.add_parser(
        "assert-stable",
        help="re-stat fingerprint; refuse soname_fingerprint_drift (exit 1)",
    )
    ast.add_argument("--bin", required=True)
    ast.add_argument(
        "--capture-json",
        default="-",
        help="prior capture JSON path, or - for stdin (default)",
    )

    chk = sub.add_parser("check-skew", help="first refuse_soname_skew (exit 1 if refused)")
    chk.add_argument("--bin", required=True)

    a = ap.parse_args(argv)
    if a.cmd == "capture":
        fp = capture_spawn_fingerprint(a.bin)
        print(json.dumps(fp, sort_keys=True))
        return 0
    if a.cmd == "check-skew":
        notes: List[str] = []
        ok = check_soname_skew(a.bin, note_sink=notes)
        print(json.dumps({"ok": ok, "notes": notes}, sort_keys=True))
        return 0 if ok else 1
    # assert-stable
    if a.capture_json == "-":
        raw = sys.stdin.read().strip()
    else:
        with open(a.capture_json, encoding="utf-8") as f:
            raw = f.read().strip()
    capture = None if not raw or raw == "null" else json.loads(raw)
    notes = []
    result = assert_fingerprint_stable(a.bin, capture, note_sink=notes)
    if notes:
        result = dict(result)
        result["notes"] = notes
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
