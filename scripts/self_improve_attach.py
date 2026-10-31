#!/usr/bin/env python3
"""Shared self-improve attach: sync accepted harness versions before a launcher starts.

Harness² and Terminal-RSI improve a target's files (prompt / memory / skills). Any frontend
that brings an agent up — hermes.sh, graph start.sh / start_graph.py (llama UI path), or a
plain folder reader — should put the accepted version in place first. This module is that
shared hook (docs/harness2.md, #65 / #88).

  python3 scripts/self_improve_attach.py [--graph FILE] [--agent NAME | --target T]
                                         [--force] [--into DIR]

Import: attach(g, graph_path, agent=None, target=None, force=False, into=None,
               log_prefix="self-improve") -> list of (target, status) pairs.

Rules (same as hermes pickup):
  * Idempotent; calling twice is fine.
  * No-op when every matching self_improve mode is off (unless --force / force=True).
  * Agents used by pentest configurations are refused.
  * Missing harness2.py or a sync failure: warn and continue (do not block the launcher).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import config_paths  # DUP-02/DUP-10 owner (after sys.path insert)
import self_improve as SI  # noqa: E402


def _mode_on(g, tname):
    _, s = SI.settings_for(g, tname)
    return bool(s) and s.get("mode") not in ("off", False, None)


def targets_for(g, agent=None, target=None):
    """[(tname, enabled), ...] for an agent, one target, or every declared harness."""
    harnesses = g.get("harnesses") or {}
    if target is not None:
        if target not in harnesses:
            raise SystemExit(
                f"self-improve: no harnesses.{target} (declared: {sorted(harnesses)})"
            )
        return [(target, _mode_on(g, target))]
    if agent is not None:
        out = []
        for t, h in harnesses.items():
            if not isinstance(h, dict) or h.get("agent") != agent:
                continue
            out.append((t, _mode_on(g, t)))
        return out
    return [(t, _mode_on(g, t)) for t, h in harnesses.items() if isinstance(h, dict)]


def refuse_pentest(g, tname, log_prefix="self-improve"):
    h = (g.get("harnesses") or {}).get(tname) or {}
    agent = h.get("agent")
    if agent and agent in SI.pentest_agents(g):
        raise SystemExit(
            f"{log_prefix}: target {tname} is agent {agent!r}, used by a pentest; "
            "pentest agents never self-improve"
        )


def attach(g, graph_path, *, agent=None, target=None, force=False, into=None,
           log_prefix="self-improve"):
    """Sync enabled (or forced) harness targets. Returns [(tname, 'synced'|'skipped'|'failed'|'absent'), ...].

    Raises SystemExit when a selected target/agent is pentest-linked, or when force=True
    and no matching harness exists for the named agent.
    """
    pairs = targets_for(g, agent=agent, target=target)
    if force and agent is not None and not pairs:
        raise SystemExit(
            f"{log_prefix}: --force/--self-improve: no harnesses.* entry has agent: {agent} "
            "(docs/harness2.md)"
        )
    tool = os.path.join(ROOT, "scripts", "harness2.py")
    results = []
    for t, on in pairs:
        if not (on or force):
            results.append((t, "skipped"))
            continue
        refuse_pentest(g, t, log_prefix=log_prefix)
        if not os.path.isfile(tool):
            print(
                f"{log_prefix}: target {t} declared but scripts/harness2.py is absent; "
                "starting without it",
                file=sys.stderr,
            )
            results.append((t, "absent"))
            continue
        cmd = [sys.executable, tool, "--graph", graph_path, "sync", "--target", t]
        if into:
            cmd += ["--into", into]
        r = subprocess.run(cmd, capture_output=True, text=True)
        msg = (r.stdout + r.stderr).strip()
        if r.returncode == 0:
            print(f"{log_prefix} ({t}): {msg or 'ok'}", file=sys.stderr)
            results.append((t, "synced"))
        else:
            print(
                f"{log_prefix} ({t}): sync failed, starting without it: {msg}",
                file=sys.stderr,
            )
            results.append((t, "failed"))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="self_improve_attach.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--graph", default=None)  # DUP-02: resolved lazily after parse
    gsel = ap.add_mutually_exclusive_group()
    gsel.add_argument("--agent", help="sync harnesses.* entries with this agent:")
    gsel.add_argument("--target", help="sync one harnesses.<T> descriptor")
    ap.add_argument(
        "--force",
        action="store_true",
        help="sync even when self_improve mode is off (hermes --self-improve)",
    )
    ap.add_argument("--into", help="export the current version into DIR (single-model hermes)")
    ap.add_argument(
        "--log-prefix",
        default="self-improve",
        help="stderr tag (default self-improve; hermes uses hermes.sh)",
    )
    a = ap.parse_args(argv)
    a.graph = config_paths.graph_path(a.graph)  # DUP-02 lazy resolve
    import familia_yaml

    g = familia_yaml.load(a.graph) or {}  # DUP-01
    g["_path"] = a.graph
    if a.agent and a.agent in SI.pentest_agents(g):
        # Refuse only when something would actually self-improve; a pentest agent with no
        # enabled/forced target must still launch (hermes.sh calls this on every start).
        if not (a.force or any(on for _, on in targets_for(g, agent=a.agent))):
            return 0
        raise SystemExit(
            f"{a.log_prefix}: agent {a.agent!r} is used by a pentest; "
            "pentest agents never self-improve"
        )
    results = attach(
        g,
        a.graph,
        agent=a.agent,
        target=a.target,
        force=a.force,
        into=a.into,
        log_prefix=a.log_prefix,
    )
    # Exit 0 even on per-target sync failure (warn+continue). Non-zero only from SystemExit above.
    enabled = [t for t, st in results if st != "skipped"]
    if not enabled and not a.force:
        # Quiet no-op when everything is off and nothing was asked for by force.
        pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
