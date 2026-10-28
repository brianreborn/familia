#!/bin/sh
# /run bench entry point (issue #183). THIN STUB: speed smoke only on the smallest
# model; quality benchmarks (lm-eval, BFCL, MTEB) and full model coverage are swarm work.
# Prints a markdown result table on stdout. No sudo. Downloads go to $SWARM_BENCH_CACHE.
# Exit 78 = skipped (no llama-bench on this runner).
set -u
cache=${SWARM_BENCH_CACHE:-$HOME/.cache/familia-bench}
# Entry: repo/file[@revision][#sha256]. Default: LFM3-1.7B-Uncensored (familia's default model,
# pinned and sha256-checked) plus the SmolLM2 smoke model.
lfm3="AtomicChat/LFM3-1.7B-Uncensored-GGUF/LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf@8851ef23eecf16f8d1bae46408cccd4249284bad#b22df65673b54ed326f18f74826d76f3b65dadc237ffd6306cd52be04544827d"
models=${SWARM_BENCH_MODELS:-"$lfm3 bartowski/SmolLM2-135M-Instruct-GGUF/SmolLM2-135M-Instruct-Q8_0.gguf"}
pp=${SWARM_BENCH_PP:-512}; tg=${SWARM_BENCH_TG:-128}
lb=${LLAMA_BENCH:-$(command -v llama-bench 2>/dev/null || true)}
if [ -z "$lb" ]; then
	for c in "$HOME"/code-bootstraps-llama.cpp/build-*/bin/llama-bench /workspace/cbl/build-*/bin/llama-bench; do
		[ -x "$c" ] && { lb=$c; break; }
	done
fi
[ -n "$lb" ] && [ -x "$lb" ] || { echo "llama-bench not found (set LLAMA_BENCH)"; exit 78; }
mkdir -p "$cache"
h=$(hostname | cut -d. -f1); u=$(id -un)
echo "| node | model | backend | threads | test | tok/s |"
echo "|---|---|---|---|---|---|"
rc=0
for m in $models; do
	sha=""; case "$m" in *#*) sha=${m##*#}; m=${m%#*} ;; esac
	rev=main; case "$m" in *@*) rev=${m##*@}; m=${m%@*} ;; esac
	repo=${m%/*}; file=${m##*/}; f=$cache/$file
	if [ ! -s "$f" ] && curl -fsSL --proto '=https' -o "$f.part" "https://huggingface.co/$repo/resolve/$rev/$file"; then mv -f "$f.part" "$f"; fi
	[ -s "$f" ] || { echo "| $h-$u | $file | - | - | download | FAIL |"; rc=1; continue; }
	if [ -n "$sha" ]; then
		got=$( (sha256sum "$f" 2>/dev/null || shasum -a 256 "$f" 2>/dev/null || sha256 -r "$f") | cut -d' ' -f1)
		[ "$got" = "$sha" ] || { mv -f "$f" "$f.bad"; echo "| $h-$u | $file | - | - | sha256 | FAIL |"; rc=1; continue; }
	fi
	"$lb" -m "$f" -p "$pp" -n "$tg" -r 2 -o csv 2>/dev/null > "$cache/out.csv" || { echo "| $h-$u | $file | - | - | llama-bench | FAIL |"; rc=1; continue; }
	python3 - "$cache/out.csv" "$h-$u" "$file" <<'PY'
import csv,sys
for r in csv.DictReader(open(sys.argv[1])):
    t=("pp%s"%r["n_prompt"]) if r.get("n_prompt","0")!="0" else ("tg%s"%r["n_gen"])
    print("| %s | %s | %s | %s | %s | %.1f ± %.1f |"%(sys.argv[2],sys.argv[3],r.get("backends") or r.get("backend","?"),r.get("n_threads","?"),t,float(r["avg_ts"]),float(r.get("stddev_ts") or 0)))
PY
done
echo
echo "_stub: speed only; quality suites pending (#183)_"
exit $rc
