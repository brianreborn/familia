#!/usr/bin/env python3
"""FAMILIA settings panel: a simple browser window for configuring familia.

Usable with a mouse, a keyboard only, a single switch (scanning) or a screen reader:
short pages, big buttons, a visible focus ring, no timeouts, no dragging, no JavaScript.
Every change is shown before it is saved, and saves can be undone.

Pages: Skills, Licenses, Hermes agent, Harness2, Models and launch parameters
(scripts/panel_familia.py), plus the launcher settings of code-bootstraps-llama.cpp.
It is that project's scripts/panel.py, started with familia's pages added.

Usage: ./familia panel   or   python3 scripts/panel.py [--no-browser] [--port N]
       python3 scripts/panel.py --a11y-check     check every page for accessibility problems
Listens on 127.0.0.1:9932 only. From another computer: ssh -L 9932:127.0.0.1:9932 HOST,
then open http://127.0.0.1:9932/ there. Docs: docs/panel.md.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
    print(__doc__.strip())
    sys.exit(0)


def backend():
    for base in (os.path.join(ROOT, "code-bootstraps-llama.cpp"), os.path.join(ROOT, "..", "code-bootstraps-llama.cpp")):
        p = os.path.join(base, "scripts", "panel.py")
        if os.path.exists(p):
            return p
    return None


BACKEND_PANEL = backend()
if not BACKEND_PANEL:
    print("familia: the settings panel (code-bootstraps-llama.cpp/scripts/panel.py) is not here yet.\n"
          "Next: run sh scripts/configure.sh to fetch it, then run this again.", file=sys.stderr)
    sys.exit(1)

args = sys.argv[1:]
plain = [a for a in args if a != "--no-browser"]
serving = not any(a in ("--fields", "--check", "--write", "--a11y-check") for a in args)
if serving and "--no-browser" not in args and "--open" not in args and os.environ.get("NO_BROWSER", "0") != "1":
    plain.append("--open")
os.environ.setdefault("PANEL_EXTRA", os.path.join(HERE, "panel_familia.py"))
os.environ.setdefault("PANEL_TITLE", "familia settings")
os.execv(sys.executable, [sys.executable, BACKEND_PANEL] + plain)
