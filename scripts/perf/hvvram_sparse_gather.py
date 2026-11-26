#!/usr/bin/env python3
"""Bounded benchmark for file-backed sparse read-only tables.

This is a storage experiment, not an inference engine.  It compares ``mmap``,
``pread`` and an explicit full-load baseline while recording gather latency,
process RSS, and resident file pages when the platform exposes ``mincore``.
Cold-cache runs require an explicit operator-supplied command; the benchmark
never writes a kernel cache-control interface by itself.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import mmap
import os
import platform
import random
try:
    import resource
except ImportError:  # Windows; /proc is unavailable and RSS remains best-effort.
    resource = None
import signal
import subprocess
import sys
import time
from pathlib import Path


class Timeout(Exception):
    pass


def _alarm(_signum: int, _frame: object) -> None:
    raise Timeout


def boot_identity() -> str | None:
    """Return a stable identifier for the current boot when the host exposes one."""
    linux_boot_id = Path("/proc/sys/kernel/random/boot_id")
    try:
        return linux_boot_id.read_text(encoding="ascii").strip() or None
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["sysctl", "-n", "kern.boottime"],
            check=False, capture_output=True, text=True, timeout=2,
        )
        value = result.stdout.strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


def provenance(path: Path) -> dict[str, object]:
    """Record enough host and filesystem facts to compare reboot runs."""
    stat = path.stat()
    fs = os.statvfs(path.parent)
    return {
        "platform": sys.platform,
        "machine": platform.machine(),
        "kernel": platform.release(),
        "boot_id": boot_identity(),
        "file_device": stat.st_dev,
        "filesystem_block_bytes": fs.f_bsize,
        "filesystem_free_bytes": fs.f_bavail * fs.f_frsize,
    }


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * p))]


def rss_mib() -> float | None:
    if resource is None:
        return None
    try:
        with open("/proc/self/status", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError):
        pass
    try:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS/BSD report bytes.
        return value / (1024.0 if value < 10**8 else 1024.0 * 1024.0)
    except (AttributeError, OSError, ValueError):
        return None


def resident_pages(mm: mmap.mmap, length: int) -> int | None:
    """Return file-backed resident pages through mincore, or None if unsupported."""
    if not length or not hasattr(ctypes.CDLL(None), "mincore"):
        return None
    page = mmap.PAGESIZE
    rounded = ((length + page - 1) // page) * page
    try:
        view = (ctypes.c_ubyte * rounded).from_buffer(mm)
        vec = (ctypes.c_ubyte * ((rounded + page - 1) // page))()
        libc = ctypes.CDLL(None, use_errno=True)
        libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_ubyte)]
        libc.mincore.restype = ctypes.c_int
        if libc.mincore(ctypes.addressof(view), rounded, vec) != 0:
            return None
        return sum(byte & 1 for byte in vec)
    except (BufferError, OSError, ValueError):
        return None


def make_table(path: Path, rows: int, row_bytes: int, seed: int, chunk_rows: int = 1024) -> None:
    if path.exists() and path.stat().st_size == rows * row_bytes:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    with path.open("wb") as stream:
        for start in range(0, rows, chunk_rows):
            count = min(chunk_rows, rows - start)
            buf = bytearray(count * row_bytes)
            for i in range(count):
                value = (start + i).to_bytes(8, "little") + rng.randbytes(max(0, row_bytes - 8))
                off = i * row_bytes
                buf[off:off + row_bytes] = value[:row_bytes]
            stream.write(buf)
    os.sync()


def drop_cache(command: str) -> None:
    if not command:
        raise RuntimeError("cold run requires --drop-cache-command; refusing an implicit cache drop")
    subprocess.run(command, shell=True, check=True)


def apply_advice(mm: mmap.mmap, advice: str) -> bool:
    if advice == "none":
        return False
    value = getattr(mmap, "MADV_RANDOM" if advice == "random" else "MADV_SEQUENTIAL", None)
    if value is None or not hasattr(mm, "madvise"):
        return False
    mm.madvise(value)
    return True


def run_arm(path: Path, mode: str, advice: str, indexes: list[int], row_bytes: int,
            timeout: int) -> dict[str, object]:
    latencies: list[float] = []
    digest = hashlib.sha256()
    before = rss_mib()
    file_pages: int | None = None
    started = time.monotonic()
    fd = os.open(path, os.O_RDONLY)
    mm: mmap.mmap | None = None
    loaded: bytes | None = None
    try:
        if mode == "mmap":
            mm = mmap.mmap(fd, 0, access=mmap.ACCESS_COPY)
            advice_applied = apply_advice(mm, advice)
            file_pages = resident_pages(mm, path.stat().st_size)
        elif mode == "load":
            loaded = os.read(fd, path.stat().st_size)
            advice_applied = False
        else:
            advice_applied = False
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(timeout)
        try:
            for row in indexes:
                t0 = time.perf_counter_ns()
                off = row * row_bytes
                if mode == "mmap":
                    data = mm[off:off + row_bytes]  # type: ignore[index]
                elif mode == "load":
                    data = loaded[off:off + row_bytes]  # type: ignore[index]
                else:
                    data = os.pread(fd, row_bytes, off)
                digest.update(data)
                latencies.append((time.perf_counter_ns() - t0) / 1_000_000.0)
        finally:
            signal.alarm(0)
        if mm is not None:
            file_pages = resident_pages(mm, path.stat().st_size)
        return {
            "mode": mode, "advice": advice, "advice_applied": advice_applied,
            "gathers": len(latencies), "p50_ms": percentile(latencies, .50),
            "p99_ms": percentile(latencies, .99), "max_ms": max(latencies or [0]),
            "rss_before_mib": before, "rss_after_mib": rss_mib(),
            "resident_file_pages": file_pages, "sha256": digest.hexdigest(),
            "elapsed_s": round(time.monotonic() - started, 6), "status": "ok",
        }
    except Timeout:
        return {"mode": mode, "advice": advice, "status": "timeout", "gathers": len(latencies),
                "rss_before_mib": before, "rss_after_mib": rss_mib()}
    finally:
        if mm is not None:
            mm.close()
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--rows", type=int, default=4096)
    ap.add_argument("--row-bytes", type=int, default=4096)
    ap.add_argument("--gathers", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=298)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--max-bytes", type=int, default=8 * 1024**3)
    ap.add_argument("--mode", choices=("all", "mmap", "pread", "load"), default="all")
    ap.add_argument("--advice", choices=("none", "random", "sequential"), default="random")
    ap.add_argument("--cache", choices=("warm", "cold"), default="warm")
    ap.add_argument("--drop-cache-command", default="")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    if min(args.rows, args.row_bytes, args.gathers, args.timeout) < 1:
        ap.error("rows, row-bytes, gathers, and timeout must be positive")
    total = args.rows * args.row_bytes
    if total > args.max_bytes:
        ap.error(f"table is {total} bytes, above --max-bytes {args.max_bytes}; raise it explicitly")
    make_table(args.file, args.rows, args.row_bytes, args.seed)
    rng = random.Random(args.seed + 1)
    indexes = [rng.randrange(args.rows) for _ in range(args.gathers)]
    modes = ("mmap", "pread", "load") if args.mode == "all" else (args.mode,)
    report = {"schema": 2, "experiment": "hvvram-sparse-gather", "cache": args.cache,
              "file": str(args.file), "bytes": total, "rows": args.rows,
              "row_bytes": args.row_bytes, "seed": args.seed, "gathers": args.gathers,
              "provenance": provenance(args.file), "results": []}
    for mode in modes:
        # Create and flush the table before touching the cache. Each cold arm
        # receives its own explicit operator-authorized cache reset so a prior
        # arm cannot warm the next arm's result.
        if args.cache == "cold":
            drop_cache(args.drop_cache_command)
        result = run_arm(args.file, mode, args.advice, indexes, args.row_bytes, args.timeout)
        report["results"].append(result)
        if result.get("status") == "timeout":
            break
    text = json.dumps(report, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if all(r.get("status") == "ok" for r in report["results"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
