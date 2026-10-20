#!/usr/bin/env python3
"""summary.py LOGDIR: <=20-line digest of llama-bench jsonl logs (best tg/pp per tag, exact params, RSS, deaths)."""
import glob, json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bench_guard as bg  # noqa: E402
d = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/perf/logs")
rows = []
for f in sorted(glob.glob(d + "/*.jsonl")):
    tag = os.path.basename(f)[:-6]
    v = [json.loads(l) for l in open(f) if l.strip()]
    if not v:
        continue
    err = open(f[:-6] + ".err").read() if os.path.exists(f[:-6] + ".err") else ""
    rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", err)
    tg = max((x for x in v if x["n_gen"]), key=lambda x: x["avg_ts"], default=None)
    pp = max((x for x in v if x["n_prompt"]), key=lambda x: x["avg_ts"], default=None)
    p = lambda x: "t%s ub%s d%s k%s lm%s" % (x["n_threads"], x["n_ubatch"], x.get("n_depth", 0), x["type_k"], x.get("load_mode", "?")) if x else "-"
    rows.append("%-22s %-28s tg %6.2f [%s] pp %6.1f [%s] rss %sMiB" % (
        tag, bg.model_label(os.path.expanduser("~/models/" + os.path.basename(v[0]["model_filename"])))[:28], tg["avg_ts"] if tg else 0, p(tg), pp["avg_ts"] if pp else 0, p(pp),
        int(rss.group(1)) // 1024 if rss else "?"))
print("\n".join(rows[-20:]))
