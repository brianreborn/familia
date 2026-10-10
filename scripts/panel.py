#!/usr/bin/env python3
"""FAMILIA panel proxy: delegates to code-bootstraps-llama.cpp/scripts/panel.py."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_PANEL = os.path.join(ROOT, "code-bootstraps-llama.cpp", "scripts", "panel.py")

if not os.path.exists(BACKEND_PANEL):
    # If sibling checkout exists in parent directory
    alt = os.path.join(ROOT, "..", "code-bootstraps-llama.cpp", "scripts", "panel.py")
    if os.path.exists(alt):
        BACKEND_PANEL = alt

if not os.path.exists(BACKEND_PANEL):
    print("familia: panel.py backend not found. Run sh scripts/configure.sh first.", file=sys.stderr)
    sys.exit(1)

os.execv(sys.executable, [sys.executable, BACKEND_PANEL] + sys.argv[1:])
