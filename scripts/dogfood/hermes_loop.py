#!/usr/bin/env python3
"""Dogfood hermes real-loop adapter (#110).

Provides the hermes **single** and **graph** agent-loop wiring that
``scripts/dogfood/dispatch.py`` (and any Continuity/orchestrator) calls.

This is NOT a single chat-completions call returning whole files. Each
iteration:

1. ``scripts/hermes.sh --mode single|graph [--model NODE] --render-only``
   renders ``HERMES_HOME`` from the graph (``hermes_modes`` / ``hermes_harness``).
2. Live: ``hermes-agent -z PROMPT -t file,terminal,todo`` runs inside the task
   worktree (tools limited to that cwd). Binary resolved via
   ``hermes_harness.resolve_hermes`` (snap / FreeBSD ports / ``HERMES_BIN``).
3. Child env uses ``hermes_harness.hermes_child_env`` (env-probe overlay).

Smoke mode stops after render + argv/bin check (no weights).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
if str(HERE / "scripts") not in sys.path:
    sys.path.insert(0, str(HERE / "scripts"))

# Lean coding surface only — no web/search/browser (stay inside the worktree cwd).
TOOLSETS = "file,terminal,todo"
HARNESS_TO_MODE = {"hermes": "single", "hermes-graph": "graph"}
MODES = ("single", "graph")


def home_for(mode: str, agent: str, node: str) -> Path:
    """HERMES_HOME path matching hermes_modes / hermes_harness layout."""
    if mode == "single":
        return Path(os.path.expanduser(f"~/.cache/familia/hermes-{agent}@{node}"))
    return Path(os.path.expanduser(f"~/.cache/familia/hermes-{agent}"))


def resolve_agent_bin(*, missing: str = "defaults") -> str:
    """Return hermes-agent path (snap / FreeBSD / PATH / HERMES_BIN)."""
    import hermes_harness as hh

    bin_path, _py, _sp = hh.resolve_hermes(missing=missing)
    return bin_path


def build_render_cmd(mode: str, node: str, agent: str = "hermes", *, repo_root=None) -> list:
    """Argv for ``hermes.sh --mode … --render-only`` (no server / no weights)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    root = Path(repo_root) if repo_root else HERE
    cmd = [
        "bash", str(root / "scripts" / "hermes.sh"),
        "--mode", mode, "--agent", agent, "--yes", "--render-only",
    ]
    if mode == "single":
        cmd += ["--model", node]
    return cmd


def build_agent_cmd(prompt: str, toolsets: str = TOOLSETS, hermes_bin: str | None = None) -> list:
    """Argv for hermes-agent oneshot inside the task worktree (after render)."""
    bin_path = hermes_bin or resolve_agent_bin(missing="defaults")
    return [
        bin_path,
        "-z", prompt,
        "-t", toolsets,
        "--yolo",
        "--accept-hooks",
        "--source", "tool",
    ]


def agent_env(home, extra=None) -> dict:
    """Env for a live hermes-agent child (HERMES_HOME + probe overlay)."""
    import hermes_harness as hh

    base = {"HERMES_HOME": str(home), "FAMILIA_SYNC": "0"}
    if extra:
        base.update(extra)
    return hh.hermes_child_env(base)


def run_render(mode: str, node: str, *, sh, agent: str = "hermes",
               repo_root=None, timeout: int = 600):
    """Run hermes.sh render-only. Returns (rc, out, cmd)."""
    cmd = build_render_cmd(mode, node, agent=agent, repo_root=repo_root)
    root = Path(repo_root) if repo_root else HERE
    import familia_auth

    # render writes the instance key into HERMES_HOME config: pin it to the parent's key file
    rc, out = sh(cmd, cwd=str(root), timeout=timeout, env=familia_auth.child_env({"FAMILIA_SYNC": "0"}))
    return rc, out, cmd


def run_oneshot(worktree, prompt: str, home, *, sh, lock_prefix=None,
                timeout: int = 7200, toolsets: str = TOOLSETS,
                hermes_bin: str | None = None, extra_env=None):
    """Live hermes-agent oneshot in *worktree*. Returns (rc, out, cmd, env).

    *lock_prefix* is prepended when holding ``with-host-lock`` / flock (big.lock).
    """
    cmd = build_agent_cmd(prompt, toolsets=toolsets, hermes_bin=hermes_bin)
    env = agent_env(home, extra=extra_env)
    locked = list(lock_prefix or []) + cmd
    rc, out = sh(locked, cwd=str(worktree), timeout=timeout, env=env)
    return rc, out, cmd, env


def smoke_ok(agent_cmd: list) -> bool:
    """True if the hermes binary path in *agent_cmd* exists (smoke gate)."""
    bin_path = agent_cmd[0] if agent_cmd else ""
    return bool(bin_path) and (os.path.isfile(bin_path) or os.path.islink(bin_path))
