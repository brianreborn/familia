#!/usr/bin/env python3
"""activate_guardian_weights.py — Dolphin3-Cyber-8B Q2_K fetch / measure / planned→active.

Hermes Wiring track for familia#147 (branch swarm/hermes/guardian-147).
Seatbelts (tools.allow, launch_test_only, scope.allow, dual-disable) are owned by
Boundary — this script never edits those fields.

Default is dry-run: print the operator path and what would change. Full fetch of
~3.0 GiB Q2_K is opt-in (--fetch) and usually run on miryam/angel, not CI.

Field Boundary ready-check should read after measure:
  models.dolphin3-cyber-8b-q2k.sha256   (64-hex; never "unmeasured")

usage:
  python3 scripts/activate_guardian_weights.py              # dry-run status
  python3 scripts/activate_guardian_weights.py --apply-expected-sha [--write]
  python3 scripts/activate_guardian_weights.py --measure PATH.gguf [--write]
  python3 scripts/activate_guardian_weights.py --activate [--write]
  python3 scripts/activate_guardian_weights.py --fetch [--write]   # huge; host only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import familia_yaml  # noqa: E402

MODEL_KEY = "dolphin3-cyber-8b-q2k"
DB_ID = "RavichandranJ--Dolphin3-Cyber-8B-GGUF--Dolphin3.0-Llama3.1-8B-abliterated.Q2_K"
HF_REPO = "RavichandranJ/Dolphin3-Cyber-8B-GGUF"
QUANT = "Q2_K"
GGUF_NAME = "Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.gguf"
DEFAULT_GGUF = f"~/.local/share/gguf/models/pentest/{GGUF_NAME}"

# Fleet graph keys that flip planned → active after local weights match sha.
# Never touch tools.allow / launch_test_only / requires_operator_confirm / scope.
NODE_KEYS = ("miryam-pentest", "angel-guardian")
PENTEST_KEYS = ("fleet", "angel")

# Private topology node name after generate_graph.py HOST
PRIVATE_NODE = "guardian"


def die(msg: str, code: int = 2) -> None:
    print(f"activate_guardian_weights: {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_registry_sha() -> tuple[str, int]:
    path = ROOT / "registry" / "models" / f"{DB_ID}.json"
    if not path.is_file():
        die(f"registry entry missing: {path}")
    e = json.loads(path.read_text(encoding="utf-8"))
    sha = e.get("sha256")
    if not sha or sha == "unmeasured" or len(sha) != 64:
        die(f"registry {path.name} has no usable sha256")
    return sha, int(e.get("bytes") or 0)


def expand_gguf(graph: dict) -> pathlib.Path:
    m = (graph.get("models") or {}).get(MODEL_KEY) or {}
    raw = m.get("gguf") or DEFAULT_GGUF
    return pathlib.Path(os.path.expanduser(str(raw)))


def sha256_file(path: pathlib.Path, progress: bool = False) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with path.open("rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress and size > (256 << 20) and done % (256 << 20) < (1 << 20):
                print(f"  sha256 {path.name}: {done * 100 // size}%", file=sys.stderr)
    return h.hexdigest()


def graph_path(host: str | None) -> pathlib.Path:
    if host:
        p = ROOT / "generated" / f"graph-{host}.yaml"
        if not p.is_file():
            die(f"private graph missing: {p} (run: python3 scripts/generate_graph.py {host})")
        return p
    return ROOT / "graph.yaml"


def status_report(text: str, path: pathlib.Path) -> dict:
    g = familia_yaml.loads(text)
    m = (g.get("models") or {}).get(MODEL_KEY) or {}
    expected, nbytes = load_registry_sha()
    gguf = expand_gguf(g)
    local_sha = None
    if gguf.is_file():
        # cheap size gate before hashing
        if nbytes and gguf.stat().st_size != nbytes:
            local_sha = f"size-mismatch:{gguf.stat().st_size}"
        else:
            local_sha = "(present; use --measure to hash)"
    nodes = {k: ((g.get("nodes") or {}).get(k) or {}).get("status") for k in NODE_KEYS}
    if PRIVATE_NODE in (g.get("nodes") or {}):
        nodes[PRIVATE_NODE] = g["nodes"][PRIVATE_NODE].get("status")
    pentests = {k: ((g.get("pentests") or {}).get(k) or {}).get("status") for k in PENTEST_KEYS}
    return {
        "graph": str(path),
        "model": MODEL_KEY,
        "graph_sha256": m.get("sha256"),
        "expected_sha256": expected,
        "expected_bytes": nbytes,
        "gguf": str(gguf),
        "gguf_present": gguf.is_file(),
        "local_note": local_sha,
        "nodes": nodes,
        "pentests": pentests,
        "seatbelts_untouched": True,
    }


def print_report(rep: dict) -> None:
    print("activate_guardian_weights (dry-run / status)")
    print(f"  graph:            {rep['graph']}")
    print(f"  model:            {rep['model']}")
    print(f"  graph sha256:     {rep['graph_sha256']}")
    print(f"  expected sha256:  {rep['expected_sha256']}  (registry HF LFS oid)")
    print(f"  expected bytes:   {rep['expected_bytes']}")
    print(f"  gguf path:        {rep['gguf']}")
    print(f"  gguf present:     {rep['gguf_present']}  {rep['local_note'] or ''}")
    print(f"  nodes status:     {rep['nodes']}")
    print(f"  pentests status:  {rep['pentests']}")
    print()
    print("Operator path (once weights exist on the host):")
    print(f"  1) Fetch (~3.0 GiB): scripts/add-model.sh --fetch {HF_REPO} --quant {QUANT} --role pentest --accept-licenses")
    print("     or: python3 scripts/activate_guardian_weights.py --fetch --write")
    print("  2) Measure + pin sha: python3 scripts/activate_guardian_weights.py --measure $GGUF --write")
    print("  3) Flip planned→active (nodes + pentests only): python3 scripts/activate_guardian_weights.py --activate --write")
    print("  4) Regenerate private graphs: python3 scripts/generate_graph.py miryam && python3 scripts/generate_graph.py angel")
    print("  5) Model-only start: FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start")
    print("  6) Hermes READY (pentest-ops → guardian aliases): after node READY,")
    print("     bash scripts/hermes.sh --agent pentest-ops   # or --model miryam-pentest / --model guardian on private graph")
    print()
    print("galaxy1 / galaxy2: fleet names for A57 Termux phones (SSH via angel). Prefer them in")
    print("  pentests.*.scope.allow (Boundary owns allowlists). Place guardian weights on miryam/angel")
    print("  first; phone placement is a later host-ready step, not this script.")
    print()
    print("Boundary ready-check field: models.dolphin3-cyber-8b-q2k.sha256")


def apply_expected_sha(text: str, expected: str) -> str:
    return familia_yaml.set_node_scalar(text, "models", MODEL_KEY, "sha256", expected)


def apply_status_active(text: str, g: dict) -> str:
    out = text
    for key in NODE_KEYS:
        if key in (g.get("nodes") or {}):
            out = familia_yaml.set_node_scalar(out, "nodes", key, "status", "active")
    if PRIVATE_NODE in (g.get("nodes") or {}):
        out = familia_yaml.set_node_scalar(out, "nodes", PRIVATE_NODE, "status", "active")
    for key in PENTEST_KEYS:
        if key in (g.get("pentests") or {}):
            out = familia_yaml.set_node_scalar(out, "pentests", key, "status", "active")
    return out


def run_fetch() -> None:
    cmd = [
        str(ROOT / "scripts" / "add-model.sh"),
        "--fetch",
        HF_REPO,
        "--quant",
        QUANT,
        "--role",
        "pentest",
        "--accept-licenses",
    ]
    print("activate_guardian_weights: running:", " ".join(cmd), file=sys.stderr)
    raise SystemExit(subprocess.call(cmd))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", type=pathlib.Path, help="graph.yaml path (default: repo graph.yaml)")
    ap.add_argument("--host", help="use generated/graph-HOST.yaml (private topology)")
    ap.add_argument("--write", action="store_true", help="persist edits (default: print / dry-run only)")
    ap.add_argument("--apply-expected-sha", action="store_true",
                    help="set models.dolphin3-cyber-8b-q2k.sha256 from registry HF LFS oid (keeps planned)")
    ap.add_argument("--measure", metavar="GGUF", help="sha256 local GGUF and pin into model entry")
    ap.add_argument("--activate", action="store_true",
                    help="flip miryam-pentest / angel-guardian (+ private guardian) and pentests.fleet/angel to active when sha matches and gguf exists")
    ap.add_argument("--fetch", action="store_true", help="run add-model.sh --fetch for Q2_K (~3 GiB; host only)")
    ap.add_argument("--json", action="store_true", help="print status as JSON")
    args = ap.parse_args(argv)

    if args.fetch:
        if not args.write:
            print("activate_guardian_weights: --fetch needs --write (refusing accidental download)", file=sys.stderr)
            return 2
        run_fetch()

    path = args.graph or graph_path(args.host)
    text = path.read_text(encoding="utf-8")
    g = familia_yaml.loads(text)
    expected, nbytes = load_registry_sha()
    changed = False

    if args.apply_expected_sha:
        cur = ((g.get("models") or {}).get(MODEL_KEY) or {}).get("sha256")
        print(f"activate_guardian_weights: pin expected sha {expected} (was {cur})", file=sys.stderr)
        text = apply_expected_sha(text, expected)
        g = familia_yaml.loads(text)
        changed = True

    if args.measure:
        mp = pathlib.Path(os.path.expanduser(args.measure))
        if not mp.is_file():
            die(f"measure file not found: {mp}")
        if nbytes and mp.stat().st_size != nbytes:
            print(
                f"activate_guardian_weights: warn size {mp.stat().st_size} != registry {nbytes}",
                file=sys.stderr,
            )
        got = sha256_file(mp, progress=True)
        print(f"activate_guardian_weights: measured {got}", file=sys.stderr)
        if got != expected:
            die(f"measured sha {got} != registry expected {expected}")
        text = apply_expected_sha(text, got)
        # also ensure gguf path points at measured file when under home
        text = familia_yaml.set_node_scalar(text, "models", MODEL_KEY, "gguf", str(mp))
        g = familia_yaml.loads(text)
        changed = True

    if args.activate:
        m = (g.get("models") or {}).get(MODEL_KEY) or {}
        sha = m.get("sha256")
        if not sha or sha == "unmeasured":
            die("refuse --activate: models.dolphin3-cyber-8b-q2k.sha256 is unmeasured; --apply-expected-sha or --measure first")
        if sha != expected:
            die(f"refuse --activate: graph sha {sha} != registry expected {expected}")
        gguf = expand_gguf(g)
        if not gguf.is_file():
            die(f"refuse --activate: weights absent at {gguf} (LF_MODEL_FILE); fetch first")
        # verify size quickly; optional full hash if --measure already done
        if nbytes and gguf.stat().st_size != nbytes:
            die(f"refuse --activate: {gguf} size {gguf.stat().st_size} != {nbytes}")
        text = apply_status_active(text, g)
        g = familia_yaml.loads(text)
        changed = True
        print(
            "activate_guardian_weights: flipped node/pentest status→active "
            "(tools.allow / launch_test_only / scope untouched)",
            file=sys.stderr,
        )

    if changed and args.write:
        path.write_text(text, encoding="utf-8")
        print(f"activate_guardian_weights: wrote {path}", file=sys.stderr)
    elif changed and not args.write:
        print("activate_guardian_weights: dry-run only (pass --write to persist)", file=sys.stderr)
        # show a tiny unified-ish hint
        if args.activate or args.apply_expected_sha or args.measure:
            print("--- would write ---", file=sys.stderr)
            print(f"models.{MODEL_KEY}.sha256 → {((familia_yaml.loads(text).get('models') or {}).get(MODEL_KEY) or {}).get('sha256')}", file=sys.stderr)

    rep = status_report(text if changed else path.read_text(encoding="utf-8"), path)
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))
    else:
        print_report(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
