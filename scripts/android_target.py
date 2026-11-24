#!/usr/bin/env python3
"""Print 'ADDR USER PORT' for an Android host in graph.yaml (#18).

Connection details come from the hosts overlay (#104) merged into graph hosts.*,
or from env overrides. Env overrides win: ANDROID_HOST, ANDROID_USER, ANDROID_PORT.
Nothing is hardcoded.
  android_target.py phone7            -> <overlay-or-env addr user port>
  android_target.py --list            -> phone hosts that have addr/user (one per line)
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hosts_overlay  # noqa: E402


def load(path):
    return (hosts_overlay.load_graph_with_overlay(path).get("hosts") or {})


def _real(value):
    if value is None or hosts_overlay.is_placeholder(value):
        return None
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--graph", default=os.environ.get("FAMILIA_GRAPH", os.path.join(ROOT, "graph.yaml")))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    env = {k: os.environ.get("ANDROID_" + k.upper()) for k in ("host", "user", "port")}
    if a.list:
        for n, h in load(a.graph).items():
            if (h or {}).get("kind") == "phone" and _real(h.get("addr")) and _real(h.get("user")):
                print(n)
        return 0
    h = {}
    if a.name:
        hosts = load(a.graph)
        if a.name not in hosts:
            sys.exit("android_target: no host %r in %s" % (a.name, a.graph))
        h = hosts[a.name] or {}
    addr = env["host"] or _real(h.get("addr"))
    user = env["user"] or _real(h.get("user"))
    port = env["port"] or _real(h.get("port")) or 8022
    if not addr or not user:
        sys.exit(
            "android_target: need addr and user (hosts overlay ~/.config/familia/hosts.local.yaml "
            "or ANDROID_HOST/ANDROID_USER; see docs/hosts-overlay.md) for hosts.%s"
            % (a.name or "?")
        )
    print(addr, user, port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
