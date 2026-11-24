#!/usr/bin/env python3
"""Opt-in offline security-model benches (#117).

Synthetic fixtures only. Scores operator-supplied baseline/candidate answer
JSON against defensive expect fields (must_find / must_not_find /
remediation_hints). No network, no model download, no live targets, no
attack tools, no exploit PoCs. Does not write graph.yaml, model selection,
targets, or stored artifacts.

Opt-in required: CLI --enable OR env FAMILIA_OFFLINE_SECBENCH=1.
Without opt-in: refuse on stderr, exit 2, load nothing for scoring.

Example:
  FAMILIA_OFFLINE_SECBENCH=1 python3 scripts/offline_secbench.py \\
    --platform linux --answers-dir tests/fixtures/offline_secbench/answers --json
"""
from __future__ import annotations

import argparse
import json
import os
import platform as plat
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FIX = os.path.join(ROOT, "tests", "fixtures", "offline_secbench")
SCHEMA_VERSION = 1
OPTIN_ENV = "FAMILIA_OFFLINE_SECBENCH"


def opted_in(enable_flag: bool) -> bool:
    """True when CLI --enable is set or FAMILIA_OFFLINE_SECBENCH=1."""
    if enable_flag:
        return True
    return os.environ.get(OPTIN_ENV, "").strip() == "1"


def refuse_message() -> str:
    return (
        "offline_secbench: refused — opt-in required. "
        "Pass --enable or set FAMILIA_OFFLINE_SECBENCH=1. "
        "This bench is offline, synthetic-only, and separate from CI / "
        "pentest launch / #116 live assessment. No cases or models will run."
    )


def host_facts() -> dict:
    """Read-only host facts for the report. Never writes graph or artifacts."""
    u = plat.uname()
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = u.node or "unknown"
    return {
        "hostname": hostname,
        "system": u.system,
        "release": u.release,
        "machine": u.machine,
        "python": sys.version.split()[0],
    }


def load_manifest(fix_dir: str) -> list:
    path = os.path.join(fix_dir, "manifest.json")
    if not os.path.isfile(path):
        return []
    data = json.load(open(path, encoding="utf-8"))
    return list(data.get("cases") or [])


def load_case(fix_dir: str, entry: dict) -> dict:
    """Load one fixture JSON; entry may be a filename or an inline stub."""
    if "file" in entry:
        path = os.path.join(fix_dir, entry["file"])
        case = json.load(open(path, encoding="utf-8"))
    else:
        case = dict(entry)
    if "id" not in case:
        raise ValueError(f"fixture missing id: {entry}")
    return case


def case_matches_platform(case: dict, platform_name: str) -> bool:
    platforms = case.get("platforms")
    if platforms is None:
        single = case.get("platform")
        if single is None or single == "*":
            return True
        platforms = [single]
    platforms = [str(p).lower() for p in platforms]
    if "*" in platforms:
        return True
    return platform_name.lower() in platforms


def load_answer(path: str) -> dict:
    data = json.load(open(path, encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"answer file must be a JSON object: {path}")
    text = data.get("text")
    if text is None:
        text = data.get("response") or data.get("output") or ""
    return {
        "model": data.get("model") or data.get("name") or "unknown",
        "runtime": data.get("runtime") or data.get("engine") or "unknown",
        "revision": data.get("revision") or data.get("version") or "unknown",
        "text": str(text),
        "path": path,
    }


def _norm(s: str) -> str:
    return " ".join(str(s).lower().split())


def _mentions(text: str, needle: str) -> bool:
    """Keyword / phrase presence (case-insensitive, whitespace-normalized)."""
    t = _norm(text)
    n = _norm(needle)
    if not n:
        return False
    if n in t:
        return True
    # Also allow hyphen/underscore variants of multi-word tokens
    alt = n.replace("-", " ").replace("_", " ")
    return alt in t if alt != n else False


def score_answer(case: dict, answer_text: str) -> dict:
    """Heuristic rubric against fixture expect fields. Pure string scoring."""
    expect = case.get("expect") or {}
    must_find = list(expect.get("must_find") or [])
    must_not_find = list(expect.get("must_not_find") or [])
    rem_hints = list(expect.get("remediation_hints") or [])

    found_ok = []
    found_miss = []
    for cat in must_find:
        if _mentions(answer_text, cat):
            found_ok.append(cat)
        else:
            found_miss.append(cat)

    fp_hits = []
    for cat in must_not_find:
        if _mentions(answer_text, cat):
            fp_hits.append(cat)

    rem_ok = []
    rem_miss = []
    for hint in rem_hints:
        if _mentions(answer_text, hint):
            rem_ok.append(hint)
        else:
            rem_miss.append(hint)

    # Weights: finding coverage 0.5, false-positive avoidance 0.25, remediation 0.25
    find_score = (len(found_ok) / len(must_find)) if must_find else 1.0
    fp_score = 1.0 if not must_not_find else max(0.0, 1.0 - (len(fp_hits) / len(must_not_find)))
    rem_score = (len(rem_ok) / len(rem_hints)) if rem_hints else 1.0
    total = 0.5 * find_score + 0.25 * fp_score + 0.25 * rem_score

    notes = []
    if found_miss:
        notes.append("missed findings: " + ", ".join(found_miss))
    if fp_hits:
        notes.append("false positives: " + ", ".join(fp_hits))
    if rem_miss:
        notes.append("missed remediation hints: " + ", ".join(rem_miss))
    if not notes:
        notes.append("all expect checks passed")

    return {
        "score": round(total, 4),
        "find_score": round(find_score, 4),
        "fp_score": round(fp_score, 4),
        "rem_score": round(rem_score, 4),
        "found_ok": found_ok,
        "found_miss": found_miss,
        "fp_hits": fp_hits,
        "rem_ok": rem_ok,
        "rem_miss": rem_miss,
        "notes": "; ".join(notes),
    }


def resolve_answers(
    case_id: str,
    baseline_path: str | None,
    candidate_path: str | None,
    answers_dir: str | None,
) -> tuple[dict | None, dict | None]:
    """Load baseline/candidate answers for one case."""
    bas = cand = None
    if answers_dir:
        bp = os.path.join(answers_dir, f"{case_id}.baseline.json")
        cp = os.path.join(answers_dir, f"{case_id}.candidate.json")
        if os.path.isfile(bp):
            bas = load_answer(bp)
        if os.path.isfile(cp):
            cand = load_answer(cp)
    # Explicit --baseline / --candidate override per-run (same file for all cases)
    if baseline_path and os.path.isfile(baseline_path):
        bas = load_answer(baseline_path)
    if candidate_path and os.path.isfile(candidate_path):
        cand = load_answer(candidate_path)
    return bas, cand


def meta_from_answer(ans: dict | None) -> dict:
    if not ans:
        return {"model": None, "runtime": None, "revision": None, "present": False}
    return {
        "model": ans.get("model"),
        "runtime": ans.get("runtime"),
        "revision": ans.get("revision"),
        "present": True,
    }


def decide_benefit(baseline_mean: float | None, candidate_mean: float | None) -> dict:
    """Whether the specialized/candidate model shows a measured benefit."""
    if baseline_mean is None or candidate_mean is None:
        return {
            "benefit": "inconclusive",
            "reason": "missing baseline or candidate scores for comparison",
        }
    delta = candidate_mean - baseline_mean
    # Small absolute margin so noise does not flip the label
    if delta > 0.05:
        return {
            "benefit": True,
            "reason": (
                f"candidate mean {candidate_mean:.4f} exceeds baseline "
                f"{baseline_mean:.4f} by {delta:.4f}"
            ),
        }
    if delta < -0.05:
        return {
            "benefit": False,
            "reason": (
                f"candidate mean {candidate_mean:.4f} is below baseline "
                f"{baseline_mean:.4f} by {abs(delta):.4f}; no measured benefit"
            ),
        }
    return {
        "benefit": "inconclusive",
        "reason": (
            f"candidate mean {candidate_mean:.4f} within 0.05 of baseline "
            f"{baseline_mean:.4f}; no clear measured benefit"
        ),
    }


def run_bench(
    fixtures_dir: str,
    platform_name: str,
    baseline_path: str | None = None,
    candidate_path: str | None = None,
    answers_dir: str | None = None,
) -> dict:
    """Score fixtures for platform; never mutates graph/model/targets/artifacts."""
    entries = load_manifest(fixtures_dir)
    cases_out = []
    bas_scores = []
    cand_scores = []
    baseline_meta = {"model": None, "runtime": None, "revision": None, "present": False}
    candidate_meta = {"model": None, "runtime": None, "revision": None, "present": False}

    for entry in entries:
        case = load_case(fixtures_dir, entry)
        if not case_matches_platform(case, platform_name):
            continue
        bas, cand = resolve_answers(
            case["id"], baseline_path, candidate_path, answers_dir
        )
        row = {
            "id": case["id"],
            "title": case.get("title") or case["id"],
            "score_baseline": None,
            "score_candidate": None,
            "delta": None,
            "notes": "",
        }
        notes = []
        if bas:
            sb = score_answer(case, bas["text"])
            row["score_baseline"] = sb["score"]
            bas_scores.append(sb["score"])
            notes.append("baseline: " + sb["notes"])
            baseline_meta = meta_from_answer(bas)
        else:
            notes.append("baseline: no answer file")
        if cand:
            sc = score_answer(case, cand["text"])
            row["score_candidate"] = sc["score"]
            cand_scores.append(sc["score"])
            notes.append("candidate: " + sc["notes"])
            candidate_meta = meta_from_answer(cand)
        else:
            notes.append("candidate: no answer file")
        if row["score_baseline"] is not None and row["score_candidate"] is not None:
            row["delta"] = round(row["score_candidate"] - row["score_baseline"], 4)
        row["notes"] = " | ".join(notes)
        cases_out.append(row)

    b_mean = round(sum(bas_scores) / len(bas_scores), 4) if bas_scores else None
    c_mean = round(sum(cand_scores) / len(cand_scores), 4) if cand_scores else None
    benefit = decide_benefit(b_mean, c_mean)

    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": True,
        "platform": platform_name,
        "host_facts": host_facts(),
        "baseline_meta": baseline_meta,
        "candidate_meta": candidate_meta,
        "cases": cases_out,
        "summary": {
            "baseline_mean": b_mean,
            "candidate_mean": c_mean,
            "benefit": benefit["benefit"],
            "reason": benefit["reason"],
            "n_cases": len(cases_out),
        },
    }


def format_human(report: dict) -> str:
    lines = []
    lines.append(
        f"offline_secbench schema={report['schema_version']} "
        f"platform={report['platform']} enabled={report['enabled']}"
    )
    hf = report.get("host_facts") or {}
    lines.append(
        f"host: {hf.get('hostname')} {hf.get('system')} "
        f"{hf.get('release')} {hf.get('machine')}"
    )
    bm = report.get("baseline_meta") or {}
    cm = report.get("candidate_meta") or {}
    lines.append(
        f"baseline: model={bm.get('model')} runtime={bm.get('runtime')} "
        f"revision={bm.get('revision')}"
    )
    lines.append(
        f"candidate: model={cm.get('model')} runtime={cm.get('runtime')} "
        f"revision={cm.get('revision')}"
    )
    for c in report.get("cases") or []:
        lines.append(
            f"  {c['id']}: bas={c['score_baseline']} cand={c['score_candidate']} "
            f"delta={c['delta']} — {c['notes']}"
        )
    s = report.get("summary") or {}
    lines.append(
        f"summary: baseline_mean={s.get('baseline_mean')} "
        f"candidate_mean={s.get('candidate_mean')} "
        f"benefit={s.get('benefit')} — {s.get('reason')}"
    )
    lines.append(
        "note: measured results only; do not auto-select or enable a specialized "
        "model. Operator decides next steps. Not #116 live assessment; not pentest launch."
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety: synthetic fixtures only; no live targets, network probes, "
            "attack tools, or exploit PoCs. Does not alter graph.yaml."
        ),
    )
    ap.add_argument(
        "--enable",
        action="store_true",
        help="opt-in to run the offline secbench (or set FAMILIA_OFFLINE_SECBENCH=1)",
    )
    ap.add_argument(
        "--fixtures",
        default=DEFAULT_FIX,
        help="fixture directory (default: tests/fixtures/offline_secbench)",
    )
    ap.add_argument(
        "--platform",
        default="linux",
        help="platform name recorded in the report (linux, windows, android, freebsd, …)",
    )
    ap.add_argument(
        "--baseline",
        default=None,
        help="JSON answer file for the baseline model (applies to every case)",
    )
    ap.add_argument(
        "--candidate",
        default=None,
        help="JSON answer file for the candidate/specialized model",
    )
    ap.add_argument(
        "--answers-dir",
        default=None,
        help="dir with {case_id}.baseline.json / {case_id}.candidate.json",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    ap.add_argument(
        "--list",
        action="store_true",
        help="with opt-in: list fixture ids for the platform and exit",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="optional path to write the JSON report (default: print only)",
    )
    args = ap.parse_args(argv)

    if not opted_in(args.enable):
        print(refuse_message(), file=sys.stderr)
        return 2

    if args.list:
        entries = load_manifest(args.fixtures)
        ids = []
        for entry in entries:
            case = load_case(args.fixtures, entry)
            if case_matches_platform(case, args.platform):
                ids.append(case["id"])
        if args.json:
            json.dump({"enabled": True, "platform": args.platform, "ids": ids}, sys.stdout, indent=2)
            print()
        else:
            for i in ids:
                print(i)
        return 0

    report = run_bench(
        fixtures_dir=args.fixtures,
        platform_name=args.platform,
        baseline_path=args.baseline,
        candidate_path=args.candidate,
        answers_dir=args.answers_dir,
    )

    if args.out:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print(format_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
