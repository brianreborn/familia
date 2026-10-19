#!/usr/bin/env python3
"""Parse llama-bench output (-o csv, -o json or -o jsonl) by column NAME, not position.

Column order differs between builds (the Vulkan b11541 build has extra columns), so
positional awk ($43 etc.) silently reads the wrong field. Usage:
    llama-bench ... -o csv | python3 scripts/bench_parse.py [--fields n_threads,type_k,...]
Prints one line per test: test=pp512|tg32|pp512@d1024 ts=<avg>+-<sd> plus the chosen fields.
"""
import csv, io, json, sys

DEFAULT = ("build_number", "n_threads", "n_batch", "n_ubatch", "type_k", "type_v",
           "n_gpu_layers", "flash_attn", "devices")

def rows(text):
    t = text.strip()
    if not t: return []
    if t[0] == "[": return json.loads(t)
    if t[0] == "{": return [json.loads(l) for l in t.splitlines() if l.strip().startswith("{")]
    lines = [l for l in t.splitlines() if l.startswith('"') or "avg_ts" in l]  # header + rows; drop log lines
    return list(csv.DictReader(io.StringIO("\n".join(lines))))

def test_name(r):
    p, n, d = int(r.get("n_prompt") or 0), int(r.get("n_gen") or 0), int(r.get("n_depth") or 0)
    name = (f"pp{p}" if p else "") + ("+" if p and n else "") + (f"tg{n}" if n else "")
    return name + (f"@d{d}" if d else "")

def summarize(text, fields=DEFAULT):
    out = []
    for r in rows(text):
        extra = " ".join(f"{f}={r[f]}" for f in fields if f in r)
        out.append(f"test={test_name(r)} ts={float(r['avg_ts']):.2f}+-{float(r['stddev_ts']):.2f} {extra}".rstrip())
    return out

if __name__ == "__main__":
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__.strip() + "\nExample: llama-bench -m model.gguf -o csv | python3 scripts/bench_parse.py")
        sys.exit(0)
    f = DEFAULT
    if "--fields" in sys.argv: f = tuple(sys.argv[sys.argv.index("--fields") + 1].split(","))
    print("\n".join(summarize(sys.stdin.read(), f)))
