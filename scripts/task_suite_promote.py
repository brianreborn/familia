#!/usr/bin/env python3
"""Promote-gate for model configs / defaults (#119).

Refuses active/default promotion when task-suite evidence is missing or failed.
Does not edit graph.yaml; prints a machine-readable decision and exits non-zero
when blocked. Wire this before flipping nodes.*.status or selection: default.

  python3 scripts/task_suite_promote.py check --node-id coder --role coder \\
      --model-name 'Qwen3.5-2B' --radical-trigger quantization

  python3 scripts/task_suite_promote.py check-record PATH.json

Env: FAMILIA_TASK_SUITE_EVIDENCE_DIR (evidence JSON directory).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_suite_lib as T


def cmd_check(args):
    suite, _ = T.load_suite(args.suite)
    decision = T.promotion_blocked(
        node_id=args.node_id or None,
        model_name=args.model_name or None,
        role=args.role or None,
        triggers=list(args.radical_trigger or []),
        suite=suite,
        directory=args.evidence_dir or None,
        force_radical=args.force_radical,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    if decision["blocked"]:
        print("REFUSE active/default promotion", file=sys.stderr)
        return 1
    print("ALLOW promotion (evidence OK)", file=sys.stderr)
    return 0


def cmd_check_record(args):
    suite, _ = T.load_suite(args.suite)
    path = Path(args.record)
    rec = json.loads(path.read_text(encoding="utf-8"))
    ok, reasons = T.gate_allows_promotion(rec, suite=suite)
    out = {"blocked": not ok, "reasons": reasons, "evidence_path": str(path)}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", default=str(T.DEFAULT_SUITE))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="refuse promotion when evidence missing/failed")
    p.add_argument("--node-id", default="")
    p.add_argument("--model-name", default="")
    p.add_argument("--role", default="")
    p.add_argument("--radical-trigger", action="append", default=[])
    p.add_argument("--evidence-dir", default="")
    p.add_argument("--force-radical", action="store_true",
                   help="treat as radical even without triggers (default: always require evidence)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("check-record", help="validate one evidence JSON for promote")
    p.add_argument("record")
    p.set_defaults(func=cmd_check_record)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
