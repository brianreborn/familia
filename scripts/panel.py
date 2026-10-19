#!/usr/bin/env python3
"""FAMILIA panel proxy: delegates to code-bootstraps-llama.cpp/scripts/panel.py."""
import os
import sys

if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
    print("panel.py: launcher settings form in your browser at http://127.0.0.1:9932 (stdlib only).\n"
          "Usage: python3 scripts/panel.py [--fields | --check KEY VALUE | --write ANSWERS]\n"
          "Saves code-bootstraps-llama.cpp/.cache/panel.env; restart start.sh after saving.\n"
          "Example: python3 scripts/panel.py   (then open http://127.0.0.1:9932)")
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_PANEL = os.path.join(ROOT, "code-bootstraps-llama.cpp", "scripts", "panel.py")

if not os.path.exists(BACKEND_PANEL):
    # If sibling checkout exists in parent directory
    alt = os.path.join(ROOT, "..", "code-bootstraps-llama.cpp", "scripts", "panel.py")
    if os.path.exists(alt):
        BACKEND_PANEL = alt

if not os.path.exists(BACKEND_PANEL):
    print("familia: the settings form (code-bootstraps-llama.cpp/scripts/panel.py) is not here yet.\n"
          "Next: run sh scripts/configure.sh to fetch it, then run this again.", file=sys.stderr)
    sys.exit(1)

os.execv(sys.executable, [sys.executable, BACKEND_PANEL] + sys.argv[1:])
