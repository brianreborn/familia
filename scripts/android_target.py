#!/usr/bin/env python3
"""Print 'ADDR USER PORT' for an Android host in graph.yaml (#18).

Env overrides win: ANDROID_HOST, ANDROID_USER, ANDROID_PORT. Nothing is hardcoded.
  android_target.py phone7            -> 192.168.1.7 u0_a439 8022
  android_target.py --list            -> phone hosts that have addr/user (one per line)
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load(path):
    import yaml
    with open(path) as f:
        return (yaml.safe_load(f) or {}).get("hosts") or {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--graph", default=os.environ.get("FAMILIA_GRAPH", os.path.join(ROOT, "graph.yaml")))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    env = {k: os.environ.get("ANDROID_" + k.upper()) for k in ("host", "user", "port")}
    if a.list:
        for n, h in load(a.graph).items():
            if (h or {}).get("kind") == "phone" and h.get("addr") and h.get("user"):
                print(n)
        return 0
    h = {}
    if a.name:
        hosts = load(a.graph)
        if a.name not in hosts:
            sys.exit("android_target: no host %r in %s" % (a.name, a.graph))
        h = hosts[a.name] or {}
    addr = env["host"] or h.get("addr")
    user = env["user"] or h.get("user")
    port = env["port"] or h.get("port") or 8022
    if not addr or not user:
        sys.exit("android_target: need addr and user (graph hosts.%s or ANDROID_HOST/ANDROID_USER)" % (a.name or "?"))
    print(addr, user, port)
    return 0

if __name__ == "__main__":
    sys.exit(main())
