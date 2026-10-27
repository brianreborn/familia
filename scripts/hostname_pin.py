#!/usr/bin/env python3
"""Machine-local graph host pin for familia.

Pin path: $XDG_STATE_HOME/familia/hostname (one line = graph host id).
Precedence helpers used by start_graph / menus / install.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def state_dir(environ=None) -> Path:
    env = os.environ if environ is None else environ
    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "familia"
    xdg = (env.get("XDG_STATE_HOME") or "").strip()
    root = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return root / "familia"


def pin_path(environ=None) -> Path:
    return state_dir(environ) / "hostname"


def read_pin(environ=None) -> str | None:
    p = pin_path(environ)
    try:
        raw = p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    if not raw or not NAME_RE.match(raw):
        return None
    return raw


def write_pin(name: str, environ=None) -> Path:
    name = name.strip()
    if not NAME_RE.match(name):
        raise SystemExit(f"hostname_pin: invalid name {name!r} (want [a-z0-9][a-z0-9_-]*)")
    d = state_dir(environ)
    d.mkdir(parents=True, exist_ok=True)
    p = pin_path(environ)
    p.write_text(name + "\n", encoding="utf-8")
    return p


def resolve_candidate(requested=None, environ=None, hostname=None) -> str:
    """Return the best host *candidate string* before graph lookup.

    Does not validate against graph.yaml — callers pass into select_host.
    """
    env = os.environ if environ is None else environ
    if requested:
        return requested.strip().split(".", 1)[0]
    if env.get("FAMILIA_HOST"):
        return env["FAMILIA_HOST"].strip().split(".", 1)[0]
    pinned = read_pin(env)
    if pinned:
        return pinned
    import socket
    raw = hostname if hostname is not None else socket.gethostname()
    return raw.strip().split(".", 1)[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="familia machine-local hostname pin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("get", help="print pin or empty")
    sub.add_parser("path", help="print pin file path")
    p_set = sub.add_parser("set", help="write pin")
    p_set.add_argument("name")
    sub.add_parser("resolve", help="print resolve_candidate() for this machine")
    a = ap.parse_args(argv)
    if a.cmd == "path":
        print(pin_path())
        return 0
    if a.cmd == "get":
        v = read_pin()
        if v:
            print(v)
        return 0 if v else 1
    if a.cmd == "set":
        p = write_pin(a.name)
        print(f"hostname_pin: wrote {a.name} -> {p}", file=sys.stderr)
        return 0
    if a.cmd == "resolve":
        print(resolve_candidate())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
