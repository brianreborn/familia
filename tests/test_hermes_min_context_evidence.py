"""R-2: hermes-agent MINIMUM_CONTEXT_LENGTH evidence + phone installer gate."""
from __future__ import annotations

import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "hermes-agent")
TERMUX = os.path.join(ROOT, "install", "termux")


def test_upstream_excerpt_declares_64000_floor():
    excerpt = open(os.path.join(FIX, "MINIMUM_CONTEXT_LENGTH.excerpt.txt"), encoding="utf-8").read()
    assert "MINIMUM_CONTEXT_LENGTH = 64_000" in excerpt or "MINIMUM_CONTEXT_LENGTH = 64000" in excerpt
    enforce = open(os.path.join(FIX, "enforce_minimum_context.excerpt.py"), encoding="utf-8").read()
    assert "_enforce_minimum_context" in enforce or "below the minimum" in enforce
    assert "MINIMUM_CONTEXT_LENGTH" in enforce
    # LM Studio is the only below-floor exception called out in the excerpt.
    assert "lmstudio" in enforce.lower()
    assert "llama.cpp" in enforce.lower() or "local" in enforce.lower()


def test_installer_gate_matches_upstream_floor():
    text = open(os.path.join(TERMUX, "install-hermes-android.sh"), encoding="utf-8").read()
    assert "HERMES_MIN_CTX=64000" in text
    assert "hermes_ctx_ok" in text
    assert "MINIMUM_CONTEXT_LENGTH" in text
