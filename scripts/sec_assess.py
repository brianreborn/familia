#!/usr/bin/env python3
"""Operator-authorized, safety-bounded security assessment mode (#116).

Fail closed. Deliberately separate from start.sh, graph startup, and CI.
Never opens sockets to assessment targets. Low mode reads declared inventory /
static policy files only. Detail mode emits a supervised plan and refuses real
network actions in this implementation. Remediation is propose-only until an
explicit human approval token is supplied (apply still refuses until approved).

Invocation requires ALL of:
  * deliberate subcommand (run / preflight)
  * FAMILIA_SEC_ASSESS_CONFIRM=yes
  * --i-authorize-assessment
  * non-empty exact --allowlist
  * --mode low|detail
  * bounded window (--until ISO8601 or --window-minutes N)

Do not infer consent from graph placement, host reachability, or a prior run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIRM_ENV = "FAMILIA_SEC_ASSESS_CONFIRM"
CONFIRM_VALUE = "yes"
AUDIT_ENV = "FAMILIA_SEC_ASSESS_AUDIT"
STATE_ENV = "FAMILIA_SEC_ASSESS_STATE"
GRAPH_ENV = "FAMILIA_GRAPH"
STOP_NAME = "STOP"
RUN_NAME = "run.json"
MODES = ("low", "detail")
MAX_CONCURRENCY = 1  # bounded; assessment never fans out
RATE_NOTE = "fixture-only; no network rate applicable"

# Seatbelt files that must stay dual-disabled (never mutated by this tool).
SEATBELT_FILES = (
    ROOT / "scripts" / "guardian-role.json",
    ROOT / "scripts" / "pentest-role.json",
)


class GateError(SystemExit):
    """Fail-closed exit with a clear message on stderr."""

    def __init__(self, msg: str, code: int = 2):
        print(f"sec_assess: REFUSED — {msg}", file=sys.stderr)
        super().__init__(code)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_until(s: str) -> dt.datetime:
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        when = dt.datetime.fromisoformat(raw)
    except ValueError as e:
        raise GateError(f"invalid --until ISO timestamp: {s!r} ({e})") from e
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(dt.timezone.utc)


def state_dir() -> Path:
    override = os.environ.get(STATE_ENV)
    if override:
        return Path(override)
    share = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(share) / "familia" / "sec-assess"


def audit_path() -> Path:
    override = os.environ.get(AUDIT_ENV)
    if override:
        return Path(override)
    return state_dir() / "audit.jsonl"


def ensure_dirs() -> None:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    ap = audit_path()
    ap.parent.mkdir(parents=True, exist_ok=True)


def audit(event: str, **fields) -> None:
    ensure_dirs()
    rec = {
        "ts": _utcnow().isoformat(),
        "event": event,
        "pid": os.getpid(),
        **fields,
    }
    with open(audit_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def operator_id() -> str:
    return (
        os.environ.get("FAMILIA_SEC_ASSESS_OPERATOR")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "unknown"
    )


def parse_allowlist(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        raise GateError("exact non-empty --allowlist required (comma-separated host names)")
    items = [p.strip() for p in str(raw).split(",")]
    items = [p for p in items if p]
    if not items:
        raise GateError("exact non-empty --allowlist required (comma-separated host names)")
    # Exact tokens only — no wildcards, CIDR expansion, or graph-inferred hosts.
    for h in items:
        if any(ch in h for ch in "*?[]/\\"):
            raise GateError(f"allowlist entry {h!r}: wildcards/paths rejected; exact host names only")
    # Preserve order, drop exact duplicates
    seen, out = set(), []
    for h in items:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def require_confirm(args) -> None:
    env_ok = os.environ.get(CONFIRM_ENV) == CONFIRM_VALUE
    flag_ok = bool(getattr(args, "i_authorize_assessment", False))
    if not env_ok:
        raise GateError(
            f"set {CONFIRM_ENV}={CONFIRM_VALUE} (do not infer consent from graph, reachability, or a prior run)"
        )
    if not flag_ok:
        raise GateError("pass --i-authorize-assessment (deliberate operator confirmation required)")


def require_mode(args) -> str:
    mode = getattr(args, "mode", None)
    if mode not in MODES:
        raise GateError(f"--mode must be one of {MODES}; got {mode!r}")
    return mode


def require_window(args) -> tuple[dt.datetime, dt.datetime]:
    now = _utcnow()
    until = getattr(args, "until", None)
    minutes = getattr(args, "window_minutes", None)
    if until and minutes is not None:
        raise GateError("pass only one of --until or --window-minutes")
    if until:
        end = _parse_until(until)
    elif minutes is not None:
        if minutes <= 0:
            raise GateError("--window-minutes must be a positive integer")
        end = now + dt.timedelta(minutes=int(minutes))
    else:
        raise GateError("bounded time window required: --until ISO8601 or --window-minutes N")
    if end <= now:
        raise GateError(f"time window already expired (until={end.isoformat()}, now={now.isoformat()})")
    return now, end


def stop_requested() -> bool:
    return (state_dir() / STOP_NAME).is_file()


def write_stop() -> Path:
    ensure_dirs()
    p = state_dir() / STOP_NAME
    p.write_text(_utcnow().isoformat() + "\n", encoding="utf-8")
    return p


def clear_stop() -> None:
    p = state_dir() / STOP_NAME
    if p.exists():
        p.unlink()


def load_graph(path: Path) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    import familia_yaml  # noqa: WPS433

    return familia_yaml.load(str(path))


def graph_path(args) -> Path:
    p = getattr(args, "graph", None) or os.environ.get(GRAPH_ENV) or str(ROOT / "graph.yaml")
    return Path(p)


def verify_seatbelts_intact() -> list[str]:
    """Read-only check that dual-disable seatbelt stubs remain empty+launch_test_only."""
    notes = []
    for path in SEATBELT_FILES:
        if not path.is_file():
            notes.append(f"missing seatbelt file: {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        tools = ((data.get("tools") or {}).get("allow"))
        lto = data.get("launch_test_only")
        if tools != []:
            notes.append(f"{path.name}: tools.allow is not [] (seatbelt broken)")
        if lto is not True:
            notes.append(f"{path.name}: launch_test_only is not true (seatbelt broken)")
    return notes


def low_checks(allowlist: list[str], graph: dict, policy_path: Path | None) -> list[dict]:
    """Non-invasive, local-only checks. NO sockets, NO probes, NO network."""
    findings = []
    hosts = graph.get("hosts") or {}
    pentests = graph.get("pentests") or {}

    for name in allowlist:
        host = hosts.get(name)
        if host is None:
            findings.append(
                {
                    "severity": "medium",
                    "check": "inventory_declared",
                    "host": name,
                    "result": "missing",
                    "detail": "host not declared in inventory; assessment does not invent targets",
                    "remediation_hint": "add a measured hosts.<name> entry or remove from allowlist",
                }
            )
            continue
        if not isinstance(host, dict):
            findings.append(
                {
                    "severity": "low",
                    "check": "inventory_shape",
                    "host": name,
                    "result": "invalid",
                    "detail": "host entry is not a mapping",
                }
            )
            continue
        measured = host.get("measured")
        findings.append(
            {
                "severity": "info" if measured else "low",
                "check": "inventory_measured",
                "host": name,
                "result": "ok" if measured else "unmeasured",
                "detail": f"kind={host.get('kind')!r} os={host.get('os')!r} measured={measured!r}",
                "remediation_hint": None if measured else "measure host before treating inventory as authoritative",
            }
        )

    for pname, pent in pentests.items():
        if not isinstance(pent, dict):
            continue
        tools = ((pent.get("tools") or {}).get("allow"))
        lto = pent.get("launch_test_only")
        if tools != [] or lto is not True:
            findings.append(
                {
                    "severity": "high",
                    "check": "guardian_seatbelt",
                    "host": None,
                    "pentest": pname,
                    "result": "seatbelt_widened",
                    "detail": f"tools.allow={tools!r} launch_test_only={lto!r}",
                    "remediation_hint": "restore tools.allow: [] and launch_test_only: true for automation",
                }
            )
        else:
            findings.append(
                {
                    "severity": "info",
                    "check": "guardian_seatbelt",
                    "host": None,
                    "pentest": pname,
                    "result": "ok",
                    "detail": "dual-disable intact (tools.allow [] + launch_test_only true)",
                }
            )

    seatbelt_notes = verify_seatbelts_intact()
    for n in seatbelt_notes:
        findings.append(
            {
                "severity": "high",
                "check": "role_json_seatbelt",
                "result": "broken",
                "detail": n,
                "remediation_hint": "restore scripts/guardian-role.json and scripts/pentest-role.json dual-disable",
            }
        )
    if not seatbelt_notes:
        findings.append(
            {
                "severity": "info",
                "check": "role_json_seatbelt",
                "result": "ok",
                "detail": "guardian-role.json / pentest-role.json dual-disable intact",
            }
        )

    if policy_path and policy_path.is_file():
        try:
            pol = json.loads(policy_path.read_text(encoding="utf-8"))
            findings.append(
                {
                    "severity": "info",
                    "check": "static_policy",
                    "result": "read",
                    "detail": f"policy={pol.get('name')!r} seatbelts={pol.get('seatbelts')!r}",
                }
            )
        except json.JSONDecodeError as e:
            findings.append(
                {
                    "severity": "low",
                    "check": "static_policy",
                    "result": "invalid_json",
                    "detail": str(e),
                }
            )

    findings.append(
        {
            "severity": "info",
            "check": "network_boundary",
            "result": "no_sockets",
            "detail": "low mode never opens sockets to allowlisted hosts; inventory/policy files only",
        }
    )
    return findings


def detail_plan(allowlist: list[str], until: dt.datetime) -> dict:
    """Higher-detail mode: supervised plan only; refuse real network actions."""
    return {
        "mode": "detail",
        "status": "refused_network",
        "reason": (
            "detail mode requires human-supervised non-invasive inventory helpers; "
            "this build refuses sockets/probes/exploits and emits a plan only"
        ),
        "allowlist": list(allowlist),
        "until": until.isoformat(),
        "proposed_supervised_steps": [
            "Confirm each allowlist host is owned and in-scope with the operator present.",
            "Review graph.yaml hosts.* and pentests.* seatbelts offline (already covered by low mode).",
            "If further non-invasive inventory is needed, call existing offline unit-tested helpers only — never nmap/exploit/live scan.",
            "Any change to a target must go through propose-remediation + explicit approval.",
        ],
        "forbidden": [
            "autonomous exploitation",
            "live network probes",
            "credential collection",
            "persistence testing",
            "silent configuration changes",
        ],
    }


def save_run(doc: dict) -> Path:
    ensure_dirs()
    p = state_dir() / RUN_NAME
    p.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def load_run() -> dict | None:
    p = state_dir() / RUN_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "corrupt", "path": str(p)}


def cmd_preflight(args) -> int:
    """Validate gates without starting assessment work."""
    require_confirm(args)
    mode = require_mode(args)
    allowlist = parse_allowlist(args.allowlist)
    start, end = require_window(args)
    if stop_requested() and not getattr(args, "clear_stop", False):
        raise GateError("STOP flag present; run `sec_assess.py stop` already set — clear via status --clear-stop or remove STOP file")
    gp = graph_path(args)
    if not gp.is_file():
        raise GateError(f"graph not found: {gp}")
    audit(
        "preflight_ok",
        operator=operator_id(),
        mode=mode,
        allowlist=allowlist,
        window_start=start.isoformat(),
        window_until=end.isoformat(),
        graph=str(gp),
    )
    print(
        json.dumps(
            {
                "status": "preflight_ok",
                "mode": mode,
                "allowlist": allowlist,
                "until": end.isoformat(),
                "concurrency_limit": MAX_CONCURRENCY,
                "network": "disabled",
            },
            indent=2,
        )
    )
    return 0


def cmd_run(args) -> int:
    require_confirm(args)
    mode = require_mode(args)
    # Fail closed: never silently downgrade detail → low.
    if mode == "detail" and not (
        os.environ.get(CONFIRM_ENV) == CONFIRM_VALUE and getattr(args, "i_authorize_assessment", False)
    ):
        raise GateError("detail mode auth failed; aborting (will not fall back to low)")

    allowlist = parse_allowlist(args.allowlist)
    start, end = require_window(args)

    if stop_requested():
        audit("run_refused_stop_flag", operator=operator_id(), mode=mode, allowlist=allowlist)
        raise GateError("STOP flag present; assessment will not start")

    clear_stop()  # fresh run; prior STOP already checked
    run_id = str(uuid.uuid4())
    gp = graph_path(args)
    if not gp.is_file():
        raise GateError(f"graph not found: {gp}")

    doc = {
        "run_id": run_id,
        "status": "running",
        "operator": operator_id(),
        "mode": mode,
        "allowlist": allowlist,
        "started": start.isoformat(),
        "until": end.isoformat(),
        "concurrency_limit": MAX_CONCURRENCY,
        "rate": RATE_NOTE,
        "findings": [],
        "plan": None,
        "stopped": False,
        "incomplete": False,
    }
    save_run(doc)
    audit(
        "run_start",
        operator=operator_id(),
        run_id=run_id,
        mode=mode,
        allowlist=allowlist,
        until=end.isoformat(),
        actions=["authorize", "load_inventory"],
    )

    # Re-check window / stop before any work.
    if _utcnow() >= end:
        doc["status"] = "incomplete"
        doc["incomplete"] = True
        doc["detail"] = "window expired before checks"
        save_run(doc)
        audit("run_incomplete_expired", run_id=run_id)
        print(json.dumps(doc, indent=2, sort_keys=True))
        return 3

    if stop_requested():
        doc["status"] = "stopped"
        doc["stopped"] = True
        save_run(doc)
        audit("run_stopped", run_id=run_id)
        print(json.dumps(doc, indent=2, sort_keys=True))
        return 4

    graph = load_graph(gp)
    policy = Path(args.policy) if args.policy else None

    if mode == "low":
        findings = low_checks(allowlist, graph, policy)
        doc["findings"] = findings
        doc["status"] = "completed"
        doc["network"] = "none"
        doc["note"] = "low mode: local fixture/inventory/policy reads only; no sockets to targets"
        audit(
            "run_complete_low",
            run_id=run_id,
            operator=operator_id(),
            finding_count=len(findings),
            actions=["inventory_read", "seatbelt_read", "policy_read"],
        )
    else:
        # detail: refuse network; emit plan
        plan = detail_plan(allowlist, end)
        # Still run local inventory checks (same as low) so the operator gets offline findings.
        findings = low_checks(allowlist, graph, policy)
        doc["findings"] = findings
        doc["plan"] = plan
        doc["status"] = "completed_plan_only"
        doc["network"] = "refused"
        doc["note"] = "detail mode refused real network actions; supervised plan recorded"
        audit(
            "run_complete_detail_plan",
            run_id=run_id,
            operator=operator_id(),
            finding_count=len(findings),
            actions=["inventory_read", "emit_supervised_plan", "refuse_network"],
        )

    if stop_requested():
        doc["status"] = "stopped"
        doc["stopped"] = True
        doc["incomplete"] = True
        audit("run_stopped_mid", run_id=run_id)

    if _utcnow() >= end and doc["status"] not in ("stopped",):
        doc["incomplete"] = True
        if doc["status"] == "running":
            doc["status"] = "incomplete"

    save_run(doc)
    print(json.dumps(doc, indent=2, sort_keys=True))
    return 0 if not doc.get("stopped") else 4


def cmd_stop(args) -> int:
    p = write_stop()
    run = load_run()
    if isinstance(run, dict) and run.get("status") == "running":
        run["status"] = "stopped"
        run["stopped"] = True
        run["incomplete"] = True
        run["stopped_at"] = _utcnow().isoformat()
        save_run(run)
    audit("stop", operator=operator_id(), stop_file=str(p))
    print(json.dumps({"status": "stopped", "stop_file": str(p)}, indent=2))
    return 0


def cmd_status(args) -> int:
    ensure_dirs()
    run = load_run()
    stopped = stop_requested()
    out = {
        "stop_flag": stopped,
        "state_dir": str(state_dir()),
        "audit": str(audit_path()),
        "run": run,
    }
    if getattr(args, "clear_stop", False) and stopped:
        clear_stop()
        out["stop_flag"] = False
        out["cleared_stop"] = True
        audit("stop_cleared", operator=operator_id())
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_propose_remediation(args) -> int:
    """Write a remediation proposal; never apply changes."""
    require_confirm(args)
    allowlist = parse_allowlist(args.allowlist)
    run = load_run() or {}
    findings = run.get("findings") or []
    proposals = []
    for f in findings:
        hint = f.get("remediation_hint")
        if not hint:
            continue
        proposals.append(
            {
                "host": f.get("host"),
                "check": f.get("check"),
                "severity": f.get("severity"),
                "proposal": hint,
                "apply": "refused_until_approved",
            }
        )
    if args.note:
        proposals.append(
            {
                "host": None,
                "check": "operator_note",
                "severity": "info",
                "proposal": args.note,
                "apply": "refused_until_approved",
            }
        )
    ensure_dirs()
    plan_path = state_dir() / f"remediation-{_utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    plan = {
        "created": _utcnow().isoformat(),
        "operator": operator_id(),
        "allowlist": allowlist,
        "source_run": run.get("run_id"),
        "proposals": proposals,
        "apply_status": "refused_until_approved",
        "approval_token_required": "FAMILIA_SEC_ASSESS_APPLY=I-APPROVE-REMEDIATION",
        "note": "Remediation is a proposed plan only. This tool will not alter targets or graph silently.",
    }
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit(
        "propose_remediation",
        operator=operator_id(),
        plan=str(plan_path),
        proposal_count=len(proposals),
        actions=["write_plan", "refuse_apply"],
    )

    # Explicit apply path: still refuse unless the strong approval env is set —
    # and even then, this MVP refuses to mutate (stub).
    apply_env = os.environ.get("FAMILIA_SEC_ASSESS_APPLY")
    if getattr(args, "apply", False):
        if apply_env != "I-APPROVE-REMEDIATION":
            audit("apply_refused_missing_token", operator=operator_id())
            raise GateError(
                "apply refused: set FAMILIA_SEC_ASSESS_APPLY=I-APPROVE-REMEDIATION after human review "
                "(this MVP still will not mutate targets; approval is recorded only)"
            )
        # Stub: acknowledge approval but do not change anything.
        audit("apply_stub_refuse_mutate", operator=operator_id(), plan=str(plan_path))
        plan["apply_status"] = "approved_but_apply_not_implemented"
        plan["apply_note"] = (
            "Human approval recorded; automatic apply is not implemented. "
            "Operator must apply the proposed diff/plan by hand."
        )
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sec_assess.py",
        description="Operator-authorized security assessment (fail closed; #116). Not invoked by start.sh/CI.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_auth(p):
        p.add_argument(
            "--i-authorize-assessment",
            action="store_true",
            help="Deliberate operator confirmation (also require FAMILIA_SEC_ASSESS_CONFIRM=yes)",
        )
        p.add_argument(
            "--allowlist",
            help="Exact comma-separated host names (non-empty; no wildcards)",
        )
        p.add_argument("--mode", choices=MODES, help="low = local inventory/policy only; detail = supervised plan, no network")
        p.add_argument("--until", help="ISO8601 end of authorization window (UTC preferred)")
        p.add_argument("--window-minutes", type=int, help="Authorization window length in minutes from now")
        p.add_argument("--graph", help="Path to graph/inventory YAML (default graph.yaml / FAMILIA_GRAPH)")
        p.add_argument("--policy", help="Optional static policy JSON (local read only)")

    p_pre = sub.add_parser("preflight", help="Validate authorization gates without running checks")
    add_auth(p_pre)
    p_pre.set_defaults(func=cmd_preflight)

    p_run = sub.add_parser("run", help="Run assessment under fail-closed gates")
    add_auth(p_run)
    p_run.set_defaults(func=cmd_run)

    p_stop = sub.add_parser("stop", help="Request cooperative stop; status reports stopped")
    p_stop.set_defaults(func=cmd_stop)

    p_stat = sub.add_parser("status", help="Show last run + stop flag")
    p_stat.add_argument("--clear-stop", action="store_true", help="Clear STOP flag after review")
    p_stat.set_defaults(func=cmd_status)

    p_rem = sub.add_parser(
        "propose-remediation",
        help="Write remediation proposal from last run; never applies silently",
    )
    p_rem.add_argument("--i-authorize-assessment", action="store_true")
    p_rem.add_argument("--allowlist", help="Scope of the proposal (exact host names)")
    p_rem.add_argument("--note", help="Optional operator note to include in the plan")
    p_rem.add_argument(
        "--apply",
        action="store_true",
        help="Attempt apply after human approval env (MVP still refuses to mutate targets)",
    )
    p_rem.set_defaults(func=cmd_propose_remediation)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return int(args.func(args))
    except GateError:
        raise
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
