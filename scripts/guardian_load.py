#!/usr/bin/env python3
"""Guardian weight gate for Hermes (fail closed).

Before Hermes adopts a guardian node (nodes.*.role guardian/pentest, e.g. miryam-pentest,
angel-guardian), the guardian GGUF must exist and its sha256 must match the pinned digest.
Missing, unreadable, or mismatched weights refuse the launch. Never fetches, never edits graph.

Path resolution (first wins):
  1. $FAMILIA_GUARDIAN_GGUF
  2. graph models.dolphin3-cyber-8b-q2k.gguf
  3. ~/.local/share/gguf/models/pentest/<GGUF_NAME>  (activate_guardian_weights.DEFAULT_GGUF)

usage: python3 scripts/guardian_load.py [--graph FILE] [--path GGUF]
exit 0 = verified, 1 = refused
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODEL_KEY = "dolphin3-cyber-8b-q2k"
GGUF_NAME = "Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.gguf"
DEFAULT_GGUF = f"~/.local/share/gguf/models/pentest/{GGUF_NAME}"
EXPECTED_SHA256 = "8944d35bdd613fe9279198b76eebeb9ab79c09a2bba526988ee3e3297862ea91"
ENV_PATH = "FAMILIA_GUARDIAN_GGUF"
GUARDIAN_ROLES = ("guardian", "pentest")


class GuardianRefused(RuntimeError):
    pass


def is_guardian_node(g: dict, n: dict) -> bool:
    if not isinstance(n, dict):
        return False
    if n.get("role") in GUARDIAN_ROLES:
        return True
    m = ((g or {}).get("models") or {}).get(n.get("model")) or {}
    return m.get("role") in GUARDIAN_ROLES


def resolve_path(g: dict | None = None, env=None) -> str:
    env = os.environ if env is None else env
    p = env.get(ENV_PATH)
    if not p:
        p = (((g or {}).get("models") or {}).get(MODEL_KEY) or {}).get("gguf") or DEFAULT_GGUF
    return os.path.expanduser(p)


def expected_sha(g: dict | None = None) -> str:
    """Pinned digest; a graph value that disagrees is itself a refusal (no silent override)."""
    gs = (((g or {}).get("models") or {}).get(MODEL_KEY) or {}).get("sha256")
    if gs and str(gs).lower() != EXPECTED_SHA256:
        raise GuardianRefused(f"graph models.{MODEL_KEY}.sha256 {gs} != pinned {EXPECTED_SHA256}")
    return EXPECTED_SHA256


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: str, want: str = EXPECTED_SHA256) -> str:
    if not os.path.isfile(path):
        raise GuardianRefused(f"guardian GGUF missing: {path} (set {ENV_PATH} or fetch per scripts/activate_guardian_weights.py)")
    try:
        got = sha256_file(path)
    except OSError as e:
        raise GuardianRefused(f"guardian GGUF unreadable: {path}: {e}") from e
    if got != want.lower():
        raise GuardianRefused(f"guardian GGUF sha256 mismatch at {path}: got {got} want {want}")
    return got


def require(g: dict, n: dict, env=None) -> str | None:
    """Gate for Hermes: no-op for non-guardian nodes, raises GuardianRefused otherwise."""
    if not is_guardian_node(g, n):
        return None
    path = resolve_path(g, env)
    verify(path, expected_sha(g))
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify guardian GGUF sha256 (fail closed)")
    ap.add_argument("--graph")
    ap.add_argument("--path")
    a = ap.parse_args(argv)
    g = None
    if a.graph:
        import familia_yaml
        g = familia_yaml.loads(open(a.graph, encoding="utf-8").read()) or {}
    path = os.path.expanduser(a.path) if a.path else resolve_path(g)
    try:
        verify(path, expected_sha(g))
    except GuardianRefused as e:
        print(f"guardian_load: REFUSED: {e}", file=sys.stderr)
        return 1
    print(f"guardian_load: OK {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
