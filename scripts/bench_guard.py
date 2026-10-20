#!/usr/bin/env python3
"""bench_guard.py: checks every familia perf / bench run makes before it starts a model.

  meta      read the GGUF header (no deps) and validate what the run needs. Missing
            architecture, context length or tokenizer is CRITICAL; missing rope settings,
            chat template or recommended sampling is CRITICAL unless the run documents the
            default it will use instead (never a silent fallback). REQUIREMENTS.md.
  flags     rewrite legacy llama.cpp flag spellings to the ones the pinned build has
            (-mmp 0 -> -lm none, --draft-max N -> --spec-type draft-simple --spec-draft-n-max N),
            checked against registry/llama-builds/<build>.json when it is known.
  encoder   encoder / embedding / reranker models (non-causal or pooled) need
            n_ubatch >= the prompt length (and n_batch >= n_ubatch), else llama.cpp aborts.
  memcap    a per-run RSS cap from the measured mmap peak plus a margin, clamped to the
            host's limit, instead of one fixed number for every model.
  check     launch guard: refuse removed flags, ctx > train, encoder ubatch < prompt,
            quantized V without FA, -ngl > 0 on a legacy GPU, unreadable GGUF (exit 3).
  effective the values a run really used, read from its -v load log.

  bench_guard.py meta FILE [--json] [--default FIELD=TEXT ...]
            (--default documents the default a run uses for a missing rope / chat_template /
            sampling field; it is echoed as a note so the log and perf doc carry it)
  bench_guard.py label FILE      (name + version + quant from the header; never a hash)
  bench_guard.py memcap PEAK_MIB [--host-limit MIB]
Stdlib only. Docs: docs/perf/2026-10-19-tuning-2.md."""
import json
import os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_T = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def read_gguf(path, max_arr=64):
    """GGUF key/values. Arrays longer than max_arr are summarized as {array_len, elem_type}."""
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(path + ": not a GGUF file")
        ver, = struct.unpack("<I", f.read(4))
        nt, nkv = struct.unpack("<QQ", f.read(16))

        def s():
            n, = struct.unpack("<Q", f.read(8))
            return f.read(n).decode("utf-8", "replace")

        def val(t):
            if t == 8:
                return s()
            if t == 9:
                it, n = struct.unpack("<IQ", f.read(12))
                if n > max_arr and it in _T:  # skip big numeric arrays without decoding
                    f.seek(n * struct.calcsize(_T[it]), 1)
                    return {"array_len": n, "elem_type": it}
                items = [val(it) for _ in range(n)]
                return items if n <= max_arr else {"array_len": n, "elem_type": it}
            fmt = _T[t]
            return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]

        kv = {}
        for _ in range(nkv):
            k = s()
            t, = struct.unpack("<I", f.read(4))
            kv[k] = val(t)
    kv["_gguf_version"], kv["_n_tensors"] = ver, nt
    return kv


def summarize(kv):
    a = kv.get("general.architecture")
    g = lambda k: kv.get("%s.%s" % (a, k))
    toks = kv.get("tokenizer.ggml.tokens")
    tmpl = kv.get("tokenizer.chat_template")
    return {
        "architecture": a, "name": kv.get("general.name"), "file_type": kv.get("general.file_type"),
        "context_length": g("context_length"),
        "rope": {k.split(".", 1)[1]: v for k, v in kv.items() if k.startswith("%s.rope." % a)} or None,
        "causal": g("attention.causal"), "pooling_type": g("pooling_type"),
        "tokenizer_model": kv.get("tokenizer.ggml.model"), "tokenizer_pre": kv.get("tokenizer.ggml.pre"),
        "vocab_size": toks.get("array_len") if isinstance(toks, dict) else (len(toks) if isinstance(toks, list) else g("vocab_size")),
        "chat_template": None if tmpl is None else {"chars": len(tmpl), "head": tmpl[:60]},
        "sampling": {k: v for k, v in kv.items() if k.startswith("general.sampling.")} or None,
    }


REQUIRED = ("architecture", "context_length", "tokenizer_model")
DOCUMENTABLE = ("rope", "chat_template", "sampling")


_HEX = re.compile(r"^[0-9a-f]{32,64}$")


def model_label(path, kv=None):
    """Human label for a weight file: '<general.name> [<general.version>] <quant>' from the GGUF header,
    quant from the filename (else general.file_type); falls back to the filename stem. Never a hash."""
    import add_model as am
    base = os.path.basename(path)
    stem = base[:-5] if base.endswith(".gguf") else base
    if kv is None:
        try:
            kv = read_gguf(path)
        except (OSError, ValueError, struct.error):
            kv = {}
    name = kv.get("general.name")
    if not isinstance(name, str) or not name.strip() or _HEX.match(name.strip().lower()):
        name = None if _HEX.match(stem.lower()) else stem
    ver = kv.get("general.version")
    quant = am.quant_of(base) or (am.FTYPES.get(kv.get("general.file_type")) if isinstance(kv.get("general.file_type"), int) else None)
    parts = [name or "unknown-model"]
    if isinstance(ver, str) and ver.strip() and ver.strip() not in parts[0]:
        parts.append(ver.strip())
    if quant and quant.lower() not in parts[0].lower():
        parts.append(quant)
    return " ".join(parts)


def validate(meta, documented_missing=None):
    """(problems, notes). Any problem means: do not run the model.

    documented_missing maps a DOCUMENTABLE field to the default the run uses instead; that
    text must also go in the log and the perf doc. REQUIRED fields cannot be documented away."""
    documented_missing = documented_missing or {}
    problems, notes = [], []
    for k in REQUIRED:
        if meta.get(k) in (None, ""):
            problems.append("CRITICAL: %s missing from GGUF header" % k)
    for k in DOCUMENTABLE:
        if meta.get(k) in (None, "", {}):
            d = documented_missing.get(k)
            if d:
                notes.append("%s: missing, defaults used: %s" % (k, d))
            else:
                problems.append("CRITICAL: %s missing and no documented default" % k)
    return problems, notes


def is_encoder(meta):
    """Non-causal attention or a pooling head (embedding / reranker models)."""
    return meta.get("causal") is False or meta.get("pooling_type") not in (None, 0)


def encoder_batch(meta, prompt_tokens, ubatch=512, batch=2048):
    """(n_batch, n_ubatch) for a run: an encoder evaluates the whole prompt in one ubatch."""
    if is_encoder(meta) and prompt_tokens > ubatch:
        ubatch = prompt_tokens
    return max(batch, ubatch), ubatch


_LEGACY = {  # old spelling -> function(value) giving the current args
    "-mmp": lambda v: ["-lm", "none" if str(v) in ("0", "false") else "mmap"],
    "--mmap": lambda v: ["-lm", "mmap"],
    "--no-mmap": lambda v: ["-lm", "none"],
    "--draft-max": lambda v: ["--spec-draft-n-max", str(v)],
    "--draft": lambda v: ["--spec-draft-n-max", str(v)],
}
_NARGS = {"-mmp": 1, "--mmap": 0, "--no-mmap": 0, "--draft-max": 1, "--draft": 1}


def modern_args(args, build=None, tool="LLAMA_EXAMPLE_SERVER"):
    """Rewrite legacy flags the build no longer has. build is a llama_flags table name or
    None (unknown build: always rewrite). Adds --spec-type draft-simple for a draft model
    when no --spec-type is given. Raises ValueError for a flag the build does not have."""
    tbl = None
    if build:
        import llama_flags
        tbl = llama_flags.load(build)
    has = lambda f: tbl is None or bool(__import__("llama_flags").supports(tbl, f, tool))
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in _LEGACY and not (tbl is not None and has(a)):
            n = _NARGS[a]
            out += _LEGACY[a](args[i + 1] if n else None)
            i += 1 + n
            continue
        out.append(a)
        i += 1
    if any(a in ("-md", "--model-draft") for a in out) and "--spec-type" not in out:
        out += ["--spec-type", "draft-simple"]
    if tbl is not None:
        bad = [a for a in out if a.startswith("-") and not re.match(r"^-\d", a) and not has(a)]
        if bad:
            raise ValueError("flags not in build %s: %s" % (build, " ".join(bad)))
    return out


def mem_cap_mib(mmap_peak_mib, margin_frac=0.15, min_margin_mib=256, host_limit_mib=None):
    """RSS cap for one run: measured peak (with mmap, the worst case) plus a margin.

    Clamped to host_limit_mib (e.g. the 3.5 GiB miryam rule). Returns None if even the
    measured peak does not fit under the limit: the run should not start."""
    cap = int(mmap_peak_mib + max(min_margin_mib, mmap_peak_mib * margin_frac))
    if host_limit_mib is not None:
        if mmap_peak_mib >= host_limit_mib:
            return None
        cap = min(cap, int(host_limit_mib))
    return cap


def headroom_cap_mib(reserve_mib=1536, meminfo="/proc/meminfo"):
    """Hard cap from headroom, not peak: MemAvailable minus a reserve (default 1.5 GiB).
    The peak-based mem_cap_mib() is only a soft warning / MemoryHigh hint."""
    for l in open(meminfo):
        if l.startswith("MemAvailable"):
            return max(256, int(l.split()[1]) // 1024 - int(reserve_mib))
    return None


def threads_in_use(ps_out=None):
    """Sum of -t/--threads across running llama-* processes (fleet thread budget: sum <= cores)."""
    import subprocess
    if ps_out is None:
        ps_out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    tot = 0
    for line in ps_out.splitlines():
        a = line.split()
        if not a or "llama-" not in a[0].rsplit("/", 1)[-1]:
            continue
        for i, x in enumerate(a[:-1]):
            if x in ("-t", "--threads"):
                try:
                    tot += max(int(v) for v in a[i + 1].split(","))
                except ValueError:
                    pass
    return tot


_EFF = {
    "n_ctx": r"llama_context: n_ctx\s*=\s*(\d+)", "n_batch": r"llama_context: n_batch\s*=\s*(\d+)",
    "n_ubatch": r"llama_context: n_ubatch\s*=\s*(\d+)", "causal_attn": r"llama_context: causal_attn\s*=\s*(\d+)",
    "flash_attn": r"llama_context: flash_attn\s*=\s*(\S+)", "freq_base": r"llama_context: freq_base\s*=\s*([\d.]+)",
    "freq_scale": r"llama_context: freq_scale\s*=\s*([\d.]+)", "n_threads": r"n_threads\s*=\s*(\d+)",
    "kv_type_k": r"type_k\s*=\s*'?(\w+)", "kv_type_v": r"type_v\s*=\s*'?(\w+)",
    "seed": r"seed\s*[=:]\s*(\d+)", "sampling": r"sampler params:\s*\n?\s*(.+)",
}


def effective(log):
    """Effective values from a -v load log (first match each); missing ones are absent."""
    out = {}
    for k, rx in _EFF.items():
        m = re.search(rx, log)
        if m:
            out[k] = m.group(1).strip()
    return out


def _argval(args, *names):
    for i, a in enumerate(args):
        if a in names and i + 1 < len(args):
            return str(args[i + 1])
    return None


def preflight(args, meta=None, prompt_tokens=None, legacy_gpu=False, build=None):
    """Launch-time param check. (problems, args): problems are 'BAD_PARAMS: ...' or
    'MODEL_FILE: ...' strings; a launcher must refuse to start when there are any.
    args comes back rewritten to the current flag spellings."""
    problems = []
    try:
        args = modern_args([str(a) for a in args], build)
    except ValueError as e:
        problems.append("BAD_PARAMS: %s" % e)
    if meta is not None:
        for k in REQUIRED:
            if meta.get(k) in (None, ""):
                problems.append("MODEL_FILE: %s missing from GGUF header" % k)
        ctx, train = _argval(args, "-c", "--ctx-size"), meta.get("context_length")
        if ctx and train and int(ctx) > int(train) and not _argval(args, "--rope-scaling", "--rope-scale", "--yarn-orig-ctx"):
            problems.append("BAD_PARAMS: -c %s > trained context %s without rope scaling" % (ctx, train))
        if is_encoder(meta):
            ub = int(_argval(args, "-ub", "--ubatch-size") or 512)
            need = prompt_tokens or int(_argval(args, "-p", "--n-prompt") or 0)
            if need > ub:
                problems.append("BAD_PARAMS: encoder model needs -ub >= prompt (%d > %d); llama.cpp aborts (GGML_ASSERT)" % (need, ub))
    ctv, fa = _argval(args, "-ctv", "--cache-type-v"), _argval(args, "-fa", "--flash-attn")
    if ctv and ctv not in ("f16", "f32", "bf16") and fa in ("off", "0", "false"):
        problems.append("BAD_PARAMS: quantized V cache (-ctv %s) needs flash attention, got -fa %s" % (ctv, fa))
    ngl = _argval(args, "-ngl", "--n-gpu-layers", "--gpu-layers")
    if legacy_gpu and ngl not in (None, "0"):
        problems.append("BAD_PARAMS: -ngl %s on a legacy GPU (no supported llama.cpp backend); use -ngl 0" % ngl)
    return problems, args


def check_main(argv):
    """bench_guard.py check [--model F] [--prompt N] [--legacy-gpu] [--build B] -- ARGS..."""
    model = prompt = build = None
    legacy = os.environ.get("FAMILIA_LEGACY_GPU") == "1"
    if "--" in argv:
        opts, args = argv[:argv.index("--")], argv[argv.index("--") + 1:]
    else:
        opts, args = [], argv
    i = 0
    while i < len(opts):
        o = opts[i]
        if o == "--legacy-gpu":
            legacy = True
        elif o in ("--model", "--prompt", "--build") and i + 1 < len(opts):
            v = opts[i + 1]; i += 1
            model, prompt, build = (v, prompt, build) if o == "--model" else (model, int(v), build) if o == "--prompt" else (model, prompt, v)
        i += 1
    model = model or _argval(args, "-m", "--model")
    meta = None
    if model:
        try:
            meta = summarize(read_gguf(model))
        except Exception as e:  # unreadable / not GGUF
            print("familia-guard: MODEL_FILE: %s: %s; not starting" % (model, e), file=sys.stderr)
            return 66  # launch_status LF_MODEL_FILE
    problems, _ = preflight(args, meta, prompt, legacy, build)
    for p in problems:
        print("familia-guard: refusing launch: %s" % p, file=sys.stderr)
    if problems:
        import launch_status as ls
        code = "LF_MODEL_FILE" if problems[0].startswith("MODEL_FILE") else "LF_BAD_PARAMS"
        ls.emit(ls.record(code, "guard", model or "", {"args": args}, evidence="; ".join(problems)))
        return ls.exit_code(code)
    return 0


def main(argv):
    if argv and argv[0] == "check":
        return check_main(argv[1:])
    if len(argv) >= 2 and argv[0] == "meta":
        m = summarize(read_gguf(argv[1]))
        doc = {}
        for i, a in enumerate(argv):
            if a == "--default" and i + 1 < len(argv) and "=" in argv[i + 1]:
                k, v = argv[i + 1].split("=", 1)
                doc[k] = v
        problems, notes = validate(m, doc)
        print(json.dumps({"meta": m, "problems": problems, "notes": notes}, indent=1, default=str)
              if "--json" in argv else "\n".join(problems + notes) or "ok")
        return 1 if problems else 0
    if len(argv) >= 2 and argv[0] == "label":
        print(model_label(argv[1]))
        return 0
    if len(argv) >= 2 and argv[0] == "memcap":
        lim = int(argv[argv.index("--host-limit") + 1]) if "--host-limit" in argv else None
        c = mem_cap_mib(float(argv[1]), host_limit_mib=lim)
        print(c if c is not None else "does not fit")
        return 0 if c is not None else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
