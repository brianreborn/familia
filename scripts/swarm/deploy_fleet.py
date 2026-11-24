#!/usr/bin/env python3
"""Deploy an already-tested Familia revision to enrolled hosts.

The controller never invokes a model binary directly. It updates a clean checkout,
regenerates the host graph, runs the graph validator, starts through start.sh, and
checks the declared health endpoints. Failed hosts stay on the attempted revision
and are retried by the caller using the recorded backoff ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HOSTS = ("angel", "miryam", "surface1", "galaxy1", "galaxy2", "note9")
REMOTE_ROOTS = {
    "miryam": "~/familia",
    "surface1": "~/swarm/familia-repo",
    "surface7": "~/swarm/familia-repo",
    "galaxy1": "/data/data/com.termux/files/home/familia/repo",
    "galaxy2": "/data/data/com.termux/files/home/familia/repo",
    "note9": "/data/data/com.termux/files/home/familia/repo",
}
HEALTH_PORTS = {"miryam": 9931, "surface1": 47201, "surface7": 47201,
                "galaxy1": 9931, "galaxy2": 9931, "note9": 9931}
ROOT = Path(__file__).resolve().parents[2]
LEDGER = Path(os.environ.get("FAMILIA_DEPLOY_LEDGER", ROOT / ".cache" / "fleet-deploy.jsonl"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, check=False)
        return p.returncode, p.stdout[-12000:]
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "")[-12000:] + "\nTIMEOUT\n"


def record(entry: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def deploy(host: str, ref: str, *, apply: bool, timeout: int) -> dict:
    target = "local" if host == "angel" else host
    if not apply:
        return {"host": host, "ref": ref, "status": "dry-run", "target": target, "ts": now()}
    if host == "angel":
        command = ["sh", "-c", f"cd {ROOT!s} && git fetch origin {ref} && git checkout --detach {ref} && git diff --quiet && python3 scripts/generate_graph.py angel && python3 scripts/validate_graph.py --graph generated/graph-angel.yaml --host angel && DETACH_MODE=screen sh ./start.sh --host angel --yes && sleep 2 && curl -fsS http://127.0.0.1:18080/health"]
    else:
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target,
                   f"cd {REMOTE_ROOTS.get(host, '~/familia')} && git fetch origin {ref} && git checkout --detach {ref} && git diff --quiet && python3 scripts/generate_graph.py {host} && python3 scripts/validate_graph.py --graph generated/graph-{host}.yaml --host {host} && DETACH_MODE=screen sh ./start.sh --host {host} --yes && sleep 2 && curl -fsS http://127.0.0.1:{HEALTH_PORTS.get(host, 9931)}/health"]
    rc, output = run(command, timeout)
    return {"host": host, "ref": ref, "status": "healthy" if rc == 0 else "failed",
            "rc": rc, "output": output, "ts": now()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="main")
    ap.add_argument("--hosts", default=",".join(DEFAULT_HOSTS))
    ap.add_argument("--apply", action="store_true", help="perform deployment; default is a plan")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--retry", action="store_true", help="retry failed hosts with documented backoff")
    args = ap.parse_args()
    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    failures = 0
    for host in hosts:
        attempt = 0
        while True:
            attempt += 1
            result = deploy(host, args.ref, apply=args.apply, timeout=args.timeout)
            result["attempt"] = attempt
            record(result)
            print(json.dumps(result, sort_keys=True))
            if result["status"] in ("healthy", "dry-run"):
                break
            failures += 1
            if not args.retry:
                break
            time.sleep(min(900, 30 * (2 ** min(attempt - 1, 5))))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
