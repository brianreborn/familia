#!/usr/bin/env python3
"""Dogfood Harness² real-loop adapter (#110).

Wraps ``scripts/harness2.py propose`` (self_improve / Harness² engine path).
Not a single chat completion — propose runs the real engine loop against a
harness target (default ``hermes-lab``).

Smoke: ``--dry-run`` (no model). Live: under host lock / admission from dispatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]


def build_propose_cmd(
    target: str,
    *,
    smoke: bool,
    max_tasks: int = 1,
    enable: bool = True,
    repo_root=None,
    python=None,
) -> list:
    """Argv for ``harness2.py propose --target …``."""
    root = Path(repo_root) if repo_root else HERE
    cmd = [
        python or sys.executable,
        str(root / "scripts" / "harness2.py"),
        "propose",
        "--target", target,
        "--max-tasks", str(max_tasks),
        "--yes",
    ]
    if enable:
        cmd.append("--enable")
    if smoke:
        cmd.append("--dry-run")
    return cmd


def run_propose(
    target: str,
    *,
    sh,
    smoke: bool,
    max_tasks: int = 1,
    enable: bool = True,
    repo_root=None,
    lock_prefix=None,
    timeout: int = 7200,
    cwd=None,
):
    """Run Harness² propose. Returns (rc, out, cmd)."""
    root = Path(repo_root) if repo_root else HERE
    cmd = build_propose_cmd(
        target, smoke=smoke, max_tasks=max_tasks, enable=enable, repo_root=root,
    )
    run_cwd = str(cwd if cwd is not None else root)
    if smoke or not lock_prefix:
        rc, out = sh(cmd, cwd=run_cwd, timeout=timeout)
    else:
        rc, out = sh(list(lock_prefix) + cmd, cwd=run_cwd, timeout=timeout)
    return rc, out, cmd


def propose_accepted(rc: int, out: str, *, smoke: bool) -> bool:
    """Accept gate for a propose run (matches prior dispatch semantics)."""
    if smoke:
        return rc == 0 and ("dry-run:" in (out or ""))
    return rc == 0
