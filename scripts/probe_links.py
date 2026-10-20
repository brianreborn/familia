#!/usr/bin/env python3
"""probe_links.py: measure the links a token's data crosses and write one JSON record per link.

  probe_links.py [--host NAME] [--out registry/links/NAME.jsonl] [--mib 32]
Runs gpu-legacy/bench_links (built on demand with cc, CUDA driver API only; skipped with a note
when no libcuda) and a host-RAM read test (memoryview copy = memcpy). Stdlib only.
Design: docs/design/topology-bandwidth-prototype.md."""
import argparse, json, os, platform, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def host_ram(mib=256, reps=6):
    """Host memcpy bandwidth in GB/s of bytes read (copy reads n and writes n)."""
    src = bytearray(os.urandom(1 << 20)) * mib
    dst = bytearray(len(src))
    dst[:] = src
    t = time.perf_counter()
    for _ in range(reps):
        dst[:] = src
    s = time.perf_counter() - t
    return {"link": "host_ram", "how": "memcpy", "bytes": len(src), "reps": reps, "sec": round(s, 6),
            "GBps": round(len(src) * reps / s / 1e9, 3), "GBps_rw": round(2 * len(src) * reps / s / 1e9, 3)}


def gpu_links(mib):
    src = os.path.join(ROOT, "gpu-legacy", "bench_links.c")
    exe = os.path.join(ROOT, ".cache", "bench_links")
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(src):
        subprocess.run(["cc", "-O2", "-o", exe, src, "-ldl"], check=True)
    p = subprocess.run([exe, str(mib)], capture_output=True, text=True)
    if p.returncode:
        return [{"link": "gpu", "skipped": True, "why": (p.stderr or "").strip()[:200]}]
    return [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")]


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("--host", default=platform.node())
    a.add_argument("--out")
    a.add_argument("--mib", type=int, default=32)
    o = a.parse_args(argv)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    recs = [host_ram()] + gpu_links(o.mib)
    for r in recs:
        r.update(host=o.host, time=stamp)
    text = "".join(json.dumps(r) + "\n" for r in recs)
    if o.out:
        os.makedirs(os.path.dirname(o.out) or ".", exist_ok=True)
        open(o.out, "a").write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
