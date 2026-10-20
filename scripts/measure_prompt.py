#!/usr/bin/env python3
"""Measure fixed-prompt size for hermes lean/full and Harness² base (#89 / #85).

usage: measure_prompt.py [--endpoint URL] [--json]
"""
import argparse, json, os, sys, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh  # noqa: E402

def toks(text):
    return max(0, len(text) // 4)

def tokenize(endpoint, text):
    if not endpoint:
        return toks(text), "chars/4"
    try:
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/tokenize",
            data=json.dumps({"content": text}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        n = d.get("tokens") or d.get("n_tokens") or d.get("tokens_list")
        if isinstance(n, list):
            n = len(n)
        return int(n), "endpoint"
    except Exception as e:
        return toks(text), f"chars/4 ({e.__class__.__name__})"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint")
    ap.add_argument("--json", action="store_true")
    o = ap.parse_args()
    base = os.path.join(ROOT, "harness", "base")
    files = {}
    for name in ("systemprompt.md", "guardrails.md", "LongTermMEMORY.md"):
        p = os.path.join(base, name)
        files[name] = open(p).read() if os.path.isfile(p) else ""
    blob = "\n\n".join(files[k] for k in files)
    n, how = tokenize(o.endpoint, blob)
    lean_aux = [t for t in hh.AUX_TASKS if t not in hh.LEAN_AUX_DROP]
    rows = {
        "harness2_base": {"chars": len(blob), "tokens": n, "how": how,
                          "files": {k: {"chars": len(v), "tokens": toks(v)} for k, v in files.items()}},
        "hermes_lean": {"toolsets": list(hh.LEAN_TOOLSETS), "aux_tasks": lean_aux, "aux_count": len(lean_aux)},
        "hermes_full": {"toolsets": "full", "aux_tasks": list(hh.AUX_TASKS), "aux_count": len(hh.AUX_TASKS)},
        "lean_aux_drop": list(hh.LEAN_AUX_DROP),
    }
    if o.json:
        print(json.dumps(rows, indent=2)); return
    print(f"harness2 base: {rows['harness2_base']['chars']} chars, "
          f"~{rows['harness2_base']['tokens']} tokens ({rows['harness2_base']['how']})")
    for k, v in rows["harness2_base"]["files"].items():
        print(f"  {k}: {v['chars']} chars ~{v['tokens']} tok")
    for p in ("lean", "full"):
        r = rows[f"hermes_{p}"]
        print(f"hermes {p}: aux_tasks={r['aux_count']} toolsets={r['toolsets']}")
    print(f"lean drops aux: {', '.join(rows['lean_aux_drop'])}")

if __name__ == "__main__":
    main()
