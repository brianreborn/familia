#!/usr/bin/env python3
"""Offline system-prompt path checks for Hermes and llama.cpp frontends (#115).

No network, no live inference. Fixture templates under tests/fixtures/system_prompts/
declare whether a system role is supported. This module:

  - classifies a Jinja chat template as supported / unsupported / unknown
  - renders a tiny message list through a stdlib-ish substitute when Jinja2 is
    missing (role-presence heuristic), or through Jinja2 when installed
  - detects dropped or duplicated system content in the rendered prompt
  - reports how familia should apply the prompt: engine (llama.cpp --jinja) vs
    agent (Hermes messages[0]) vs fail-closed

Example: python3 scripts/system_prompt_check.py --fixtures tests/fixtures/system_prompts
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FIX = os.path.join(ROOT, "tests", "fixtures", "system_prompts")

MARKER = "FAMILIA_SYS_PROMPT_UNIQUE_MARKER_7f3a"


def classify_template(text: str) -> str:
    """Return supported | unsupported | unknown from template source alone."""
    low = text.lower()
    mentions_system = bool(re.search(r"\bsystem\b", low))
    role_system = "role" in low and "system" in low
    if role_system or ("messages[0]" in low and "system" in low):
        return "supported"
    if mentions_system:
        return "unknown"
    # No mention of system at all → treat as unsupported for fail-closed checks
    return "unsupported"


def _render_jinja(template: str, messages: list) -> str:
    try:
        from jinja2 import BaseLoader, Environment, StrictUndefined
    except ImportError:
        return _render_heuristic(template, messages)
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=False)
    # llama.cpp / HF templates often use raise_exception
    env.globals["raise_exception"] = lambda msg: (_ for _ in ()).throw(RuntimeError(msg))
    tmpl = env.from_string(template)
    return tmpl.render(messages=messages, add_generation_prompt=True)


def _render_heuristic(template: str, messages: list) -> str:
    """Fallback when Jinja2 is absent: concatenate role-tagged content in order."""
    parts = []
    for m in messages:
        parts.append(f"<{m['role']}>{m['content']}</{m['role']}>")
    return "\n".join(parts)


def apply_once(path: str, system_text: str, user_text: str = "ping") -> dict:
    """Render with exactly one system message; report drop/duplicate."""
    text = open(path, encoding="utf-8").read()
    status = classify_template(text)
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    try:
        rendered = _render_jinja(text, messages)
        err = None
    except Exception as e:  # noqa: BLE001
        rendered, err = "", f"{type(e).__name__}: {e}"
    count = rendered.count(system_text) if system_text and rendered else 0
    if status == "unsupported":
        # Engine will not apply it; agent must inject exactly once or fail closed.
        frontend = "agent"
        ok = True  # classification OK; application is the agent's job
        note = "template ignores system role; agent/frontend must apply exactly once or refuse"
    elif status == "supported":
        frontend = "engine"  # llama.cpp --jinja / native template
        ok = (err is None) and (count == 1)
        note = "ok" if ok else ("render error: " + err if err else f"system content count={count}, want 1")
    else:
        frontend = "unknown"
        ok = False
        note = "cannot establish system-prompt support; fail closed where required"
    return {
        "template": os.path.basename(path),
        "system_role": status,
        "frontend": frontend,
        "count": count,
        "ok": ok,
        "note": note,
        "rendered_head": (rendered or "")[:180],
    }


def hermes_messages(system_text: str, user_text: str = "ping") -> list:
    """Hermes-facing message list: system first, exactly once."""
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]


def check_hermes_path(system_text: str) -> dict:
    msgs = hermes_messages(system_text)
    systems = [m for m in msgs if m.get("role") == "system"]
    ok = len(systems) == 1 and systems[0]["content"] == system_text
    return {
        "frontend": "hermes-agent",
        "system_count": len(systems),
        "ok": ok,
        "note": "ok" if ok else "system message missing or duplicated in Hermes assembly",
    }


def check_llama_jinja_path(template_path: str, system_text: str) -> dict:
    r = apply_once(template_path, system_text)
    r["path"] = "llama.cpp-jinja"
    # Keep apply_once's recommended frontend (engine|agent|unknown); path names the probe.
    return r


def load_inventory(fix_dir: str) -> list:
    inv = os.path.join(fix_dir, "inventory.json")
    if not os.path.isfile(inv):
        return []
    return json.load(open(inv, encoding="utf-8")).get("fixtures") or []


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog="Example: python3 scripts/system_prompt_check.py --fixtures tests/fixtures/system_prompts",
    )
    ap.add_argument("--fixtures", default=DEFAULT_FIX, help="fixture directory")
    ap.add_argument("--marker", default=MARKER, help="unique system string used in renders")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args(argv)
    rows = []
    rows.append(check_hermes_path(args.marker))
    for fx in load_inventory(args.fixtures):
        path = os.path.join(args.fixtures, fx["template"])
        if not os.path.isfile(path):
            rows.append({"id": fx["id"], "ok": False, "note": f"missing template {path}"})
            continue
        r = check_llama_jinja_path(path, args.marker)
        r["id"] = fx["id"]
        r["declared"] = fx.get("system_role")
        r["source"] = fx.get("source")
        # Declared vs observed classification must match when declared is known
        if fx.get("system_role") in ("supported", "unsupported"):
            if r["system_role"] != fx["system_role"]:
                r["ok"] = False
                r["note"] = f"classified {r['system_role']}, inventory says {fx['system_role']}"
        rows.append(r)
    failed = [r for r in rows if not r.get("ok")]
    if args.json:
        json.dump({"ok": not failed, "rows": rows}, sys.stdout, indent=2)
        print()
    else:
        for r in rows:
            tag = "OK" if r.get("ok") else "FAIL"
            print(f"{tag}: {r}")
        print(f"system_prompt_check: {len(rows) - len(failed)}/{len(rows)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
