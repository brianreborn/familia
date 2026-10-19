#!/usr/bin/env python3
"""model_params.py: what a model needs on the command line, taken from its cards (#51).

From the model card, the base model's card and the GitHub READMEs they link, this module
  1. extracts every code / command-line example VERBATIM (source file, line range, tool);
  2. parses llama.cpp examples into flags (against the flag table of a pinned build,
     scripts/llama_flags.py) and translates vLLM / SGLang / transformers / Ollama / curl /
     JSON examples into llama.cpp parameters, marked translated, with what does not translate;
  3. derives `required_params`: REQUIRED (chat template / --jinja, embeddings + pooling,
     batch sizes for non-causal models, rope / YaRN past the native window, prompt prefixes
     and templates, stop tokens, the runtime itself), RECOMMENDED (the card's sampling) and
     OPTIONAL (performance), each with its value, source and why it is required;
  4. builds the descriptor: every upstream value with its source, the effective value by
     precedence (card statement > config.json > GGUF header > GitHub README), and conflicts.
Judgement calls that cannot be derived (which chat template to serve when the GGUF's differs,
blockers, client-side prompt formats) live in registry/model-params.yaml; each one must quote
a line that really is in the cited file, or the check fails.
Stdlib only, plus PyYAML for the curated file."""
import ast, hashlib, json, os, re, shlex

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
CURATED = os.path.join(REPO_ROOT, "registry", "model-params.yaml")

# ------------------------------------------------------------------ 1. verbatim extraction
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^`\s]*)[^`]*$")   # list items indent fences by 4+
SHELL_LANGS = {"bash", "sh", "shell", "console", "zsh", "powershell", "ps1", "cmd", "bat", "terminal"}
CITATION = re.compile(r"^\s*@(?:article|misc|inproceedings|online|software|techreport|book)\s*\{", re.I | re.M)
TOOLS = (  # (tool, regex on the block text); first match wins, order matters
    ("llama.cpp", r"(?:^|[\s/`$])(?:\./)?(?:build/bin/)?llama-(?:server|cli|run|embedding|mtmd-cli|simple|bench)(?:\.exe)?\b|(?:^|[\s`$])llama\s+(?:serve|run|cli)\b"),
    ("vllm", r"(?:^|\s)vllm\s+serve\b|python3?\s+-m\s+vllm|\bfrom\s+vllm\b|\bLLM\(\s*model="),
    ("sglang", r"sglang\.launch_server|(?:^|\s)sglang\s+serve\b|\bimport\s+sglang\b"),
    ("ollama", r"(?:^|\s)ollama\s+(?:run|create|pull|serve)\b|^\s*FROM\s+\S+.*\n(?:.*\n)*?\s*(?:PARAMETER|TEMPLATE)\b"),
    ("mlx", r"\bmlx_lm\b|\bmlx-lm\b|from\s+mlx"),
    ("sentence-transformers", r"\bsentence_transformers\b|SentenceTransformer\("),
    ("transformers-serve", r"(?:^|\s)transformers\s+(?:serve|chat)\b"),
    ("transformers", r"\bfrom\s+transformers\b|\bimport\s+transformers\b|AutoModel\w*\.from_pretrained|pipeline\("),
    ("trl", r"(?:^|\s)trl\s+chat\b"),
    ("openai-client", r"\bfrom\s+openai\b|\bOpenAI\("),
    ("curl", r"(?:^|\s)curl\s"),
    ("hf-download", r"(?:^|\s)(?:huggingface-cli|hf)\s+download\b"),
    ("pip", r"(?:^|\s)(?:pip3?|uv\s+pip|uv)\s+install\b"),
    ("git", r"(?:^|\s)git\s+(?:clone|checkout)\b"),
    ("cmake", r"(?:^|\s)cmake\s"),
    ("docker", r"(?:^|\s)docker\s+(?:run|pull)\b"),
    ("mergekit", r"\bmerge_method\s*:"),
    ("python", r"^\s*(?:import|from)\s+\w+|^\s*def\s+\w+\(|^\s*python3?\s"),
)
INLINE_CMD = re.compile(r"`((?:\./)?(?:llama-[a-z-]+|llama\s+serve|vllm\s+serve|ollama\s+run|hf\s+download|huggingface-cli\s+download|"
                        r"python3?\s+-m\s+\S+|sglang\s+serve)\s[^`]+|--?[a-z][\w-]*(?:[ =][^`\s]+)?(?:\s+--?[a-z][\w-]*(?:[ =][^`\s-][^`\s]*)?)+)`")


def detect_tool(text, lang=""):
    for tool, rx in TOOLS:
        if re.search(rx, text, re.M):
            return tool
    lang = (lang or "").lower()
    if lang in ("json", "jsonc"):
        return "json"
    if lang in ("yaml", "yml"):
        return "yaml"
    if lang in SHELL_LANGS:
        return "shell"
    if lang in ("python", "py"):
        return "python"
    return lang or None


def block_kind(tool, lang, text):
    lang = (lang or "").lower()
    if tool in ("llama.cpp", "vllm", "sglang", "ollama", "curl", "hf-download", "pip", "git", "cmake", "docker", "shell",
                "transformers-serve", "trl") and (lang in SHELL_LANGS or not lang or tool in ("ollama",)):
        return "command"
    if tool in ("json", "yaml", "mergekit"):
        return "config"
    if tool in ("python", "transformers", "sentence-transformers", "vllm", "sglang", "mlx", "openai-client"):
        return "code"
    if lang in ("text", "txt", "plaintext", "", "jinja", "markdown", "md", "none") and re.search(r"<\|[\w▁｜]+\|>|<[a-z_]+>|\{[a-z_]+\}|\[INST\]|<start_of_turn>|<｜", text):
        return "prompt-format"
    return "other"


def extract_examples(text, file="README.md", label=None):
    """Every fenced block (verbatim, minus citations) and every inline command span.
    Line numbers are 1-based lines of `file` as stored (front matter included)."""
    lines = text.split("\n")
    out, i = [], 0
    in_fm = bool(lines and lines[0].strip() == "---")
    while i < len(lines):
        if in_fm:
            if i > 0 and lines[i].strip() == "---":
                in_fm = False
            i += 1
            continue
        m = FENCE.match(lines[i])
        if m:
            fence, lang = m.group(2), m.group(3)
            j = i + 1
            while j < len(lines) and not re.match(r"^\s*%s%s*\s*$" % (re.escape(fence[0]) * len(fence), re.escape(fence[0])), lines[j]):
                j += 1
            body = "\n".join(lines[i + 1:j])
            if body.strip() and not CITATION.search(body):
                tool = detect_tool(body, lang)
                out.append({"source": "%s%s:L%d-%d" % ((label + " ") if label else "", file, i + 2, max(i + 2, j)),
                            "file": file, "lines": [i + 2, max(i + 2, j)], "lang": lang or None, "tool": tool,
                            "kind": block_kind(tool, lang, body), "text": body})
            i = j + 1
            continue
        for mm in INLINE_CMD.finditer(lines[i]):
            span = mm.group(1)
            if len(span.split()) < 2:
                continue
            tool = detect_tool(span) or ("llama.cpp" if re.match(r"--?[a-z]", span) else None)
            out.append({"source": "%s%s:L%d" % ((label + " ") if label else "", file, i + 1), "file": file, "lines": [i + 1, i + 1],
                        "lang": None, "tool": tool, "kind": "inline", "text": span})
        i += 1
    return out


# ------------------------------------------------------------------ 2a. llama.cpp argv parsing
def _logical_commands(text):
    """Shell text -> list of (argv, raw) for each command (continuations joined, prompts and comments dropped)."""
    joined = re.sub(r"\\\r?\n", " ", text)
    joined = re.sub(r"`\r?\n", " ", joined)              # PowerShell continuation
    cmds = []
    for raw in joined.split("\n"):
        s = re.sub(r"^\s*(?:\$|>|PS>|#\s*$)\s*", "", raw).strip()
        if not s or s.startswith("#"):
            continue
        for part in re.split(r"\s(?:&&|\|\||;)\s", s):
            try:
                argv = shlex.split(part, comments=True)
            except ValueError:
                argv = part.split()
            if argv:
                cmds.append((argv, part))
    return cmds


LLAMA_TOOL = re.compile(r"(?:^|/)(llama-(?:server|cli|run|embedding|mtmd-cli|simple|bench))(?:\.exe)?$")


def canonical(flag, build):
    r = (build or {}).get("flags", {}).get(flag) if build else None
    if not r:
        return flag
    neg = r.get("neg") or []
    pos = [a for a in r["aliases"] if a not in neg] if flag not in neg else list(neg)
    longs = [a for a in pos if a.startswith("--")]
    return (longs or pos)[0]


def parse_llama(text, build=None):
    """[{tool, raw, flags:[{flag, canonical, value, known, note}], positional, env}] for llama.cpp commands in text."""
    res = []
    for argv, raw in _logical_commands(text):
        env, k = {}, 0
        while k < len(argv) and re.match(r"^[A-Z_][A-Z0-9_]*=", argv[k]):
            a, _, b = argv[k].partition("=")
            env[a] = b
            k += 1
        if k >= len(argv):
            continue
        tok = argv[k]
        m = LLAMA_TOOL.search(tok)
        tool = m.group(1) if m else None
        if tool is None and tok == "llama" and k + 1 < len(argv) and argv[k + 1] in ("serve", "run", "cli"):
            tool, k = "llama " + argv[k + 1], k + 1
        if tool is None:
            continue
        flags, pos, i = [], [], k + 1
        while i < len(argv):
            a = argv[i]
            if not a.startswith("-") or re.match(r"^-\d", a):
                pos.append(a)
                i += 1
                continue
            val, note = None, None
            if "=" in a and a.startswith("--"):
                a, _, val = a.partition("=")
            rec = (build or {}).get("flags", {}).get(a) if build else None
            known = rec is not None if build else None
            nargs = rec["nargs"] if rec else None
            if val is None:
                nxt = argv[i + 1] if i + 1 < len(argv) else None
                takes = nargs if nargs is not None else (1 if nxt is not None and (not nxt.startswith("-") or re.match(r"^-\d", nxt)) else 0)
                if takes:
                    if nxt is None or (nxt.startswith("-") and not re.match(r"^-\d", nxt)):
                        note = "given without a value (older llama.cpp syntax); this build's %s takes a value" % a
                    else:
                        val = nxt
                        i += 1
            flags.append({"flag": a, "canonical": canonical(a, build), "value": val, "known": known, "note": note})
            i += 1
        res.append({"tool": tool, "raw": raw.strip(), "flags": flags, "positional": pos, "env": env or None})
    return res


# ------------------------------------------------------------------ 2b. translation into llama.cpp parameters
SAMPLING_KW = {"temperature": "--temp", "temp": "--temp", "top_p": "--top-p", "top_k": "--top-k", "min_p": "--min-p",
               "presence_penalty": "--presence-penalty", "frequency_penalty": "--frequency-penalty",
               "repetition_penalty": "--repeat-penalty", "repeat_penalty": "--repeat-penalty",
               "max_tokens": "-n", "max_new_tokens": "-n", "num_predict": "-n", "num_ctx": "-c", "seed": "--seed"}
VLLM_MAP = {  # flag -> (llama.cpp flag or None, note)
    "--max-model-len": ("-c", None), "--context-length": ("-c", None),
    "--tool-call-parser": ("--jinja", "llama.cpp parses tool calls from the chat template (--jinja); no separate parser flag"),
    "--enable-auto-tool-choice": ("--jinja", "tool calling comes with --jinja"),
    "--reasoning-parser": ("--reasoning-format", "llama.cpp extracts <think> blocks with --reasoning-format deepseek (its default)"),
    "--enable-reasoning": (None, "reasoning extraction is on by default in llama-server (--reasoning-format deepseek)"),
    "--default-chat-template-kwargs": ("--chat-template-kwargs", None), "--chat-template-kwargs": ("--chat-template-kwargs", None),
    "--chat-template": ("--chat-template-file", None),
    "--served-model-name": ("--alias", None), "--port": ("--port", None), "--host": ("--host", None),
    "--max-num-seqs": ("-np", "slot count; a performance choice"),
    "--language-model-only": (None, "text only: do not pass --mmproj (llama.cpp loads no vision tower without it)"),
    "--hf-overrides": ("@rope", None), "--json-model-override-args": ("@rope", None),
    "--speculative-config": (None, "MTP / speculative heads of the safetensors checkpoint are not in this GGUF; no llama.cpp equivalent here"),
    "--speculative-algorithm": (None, "MTP / NEXTN speculative decoding of the checkpoint; not available for this GGUF"),
    "--speculative-num-steps": (None, "see --speculative-algorithm"), "--speculative-eagle-topk": (None, "see --speculative-algorithm"),
    "--speculative-num-draft-tokens": (None, "see --speculative-algorithm"),
    "--tensor-parallel-size": (None, "multi-GPU tensor parallelism; n/a (one device per llama-server here)"),
    "--tp-size": (None, "multi-GPU tensor parallelism; n/a"), "--tp": (None, "multi-GPU tensor parallelism; n/a"),
    "--mem-fraction-static": (None, "SGLang memory pool fraction; n/a"), "--gpu-memory-utilization": (None, "vLLM memory fraction; n/a"),
    "--dtype": (None, "weights dtype is fixed by the GGUF quant"), "--trust-remote-code": (None, "n/a for GGUF"),
    "--enable-prefix-caching": (None, "llama-server caches prompts per slot (--cache-prompt, default on)"),
    "--task": ("@task", None), "--runner": ("@task", None), "--convert": ("@task", None), "--pooling-type": ("--pooling", None),
    "--attention-backend": (None, "n/a"), "--enable-expert-parallel": (None, "n/a"), "--async-scheduling": (None, "n/a"),
    "--mm-encoder-tp-mode": (None, "n/a"), "--mm-processor-cache-type": (None, "n/a"), "--limit-mm-per-prompt": (None, "n/a"),
    "--max-num-batched-tokens": ("-b", "batch size; a performance choice"), "--model": (None, "the model is the GGUF file"),
    "--model-path": (None, "the model is the GGUF file"), "--force-model": (None, "the model is the GGUF file"),
    "--continuous-batching": (None, "llama-server batches continuously by default (--cont-batching)"),
}


def _rope_from_json(obj):
    """{'rope_scaling': {...}} or {'rope_parameters': {...}} or text_config nesting -> (type, factor, orig) or None."""
    if not isinstance(obj, dict):
        return None
    for k in ("rope_scaling", "rope_parameters"):
        v = obj.get(k)
        if isinstance(v, dict) and str(v.get("rope_type") or v.get("type") or "").lower() == "yarn":
            return {"type": "yarn", "factor": v.get("factor"), "original_ctx": v.get("original_max_position_embeddings")}
    for v in obj.values():
        r = _rope_from_json(v) if isinstance(v, dict) else None
        if r:
            return r
    return None


def _json_objects(s):
    out = []
    for m in re.finditer(r"[\{\[]", s):
        depth, j, q = 0, m.start(), None
        while j < len(s):
            c = s[j]
            if q:
                if c == "\\":
                    j += 1
                elif c == q:
                    q = None
            elif c in "\"'":
                q = c
            elif c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    frag = s[m.start():j + 1]
                    try:
                        out.append(json.loads(frag))
                    except ValueError:
                        try:
                            v = ast.literal_eval(frag)      # Python dict literals (True/False, single quotes)
                            if isinstance(v, (dict, list)):
                                out.append(v)
                        except (ValueError, SyntaxError, MemoryError, RecursionError):
                            pass
                    break
            j += 1
    return out


def rope_flags(r):
    if not r or not r.get("factor"):
        return []
    f = ["--rope-scaling", "yarn", "--rope-scale", _num(r["factor"])]
    if r.get("original_ctx"):
        f += ["--yarn-orig-ctx", str(r["original_ctx"])]
    return f


def _num(v):
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float) and v.is_integer():
        return str(int(v)) if abs(v) >= 1 else str(v)
    return str(v)


def translate(ex):
    """Translate one non-llama.cpp example into llama.cpp parameters.
    -> {"translated": True, "params": [{"flag","value","from"}], "untranslatable": [{"arg","why"}]} or None."""
    tool, text = ex.get("tool"), ex["text"]
    params, untr = [], []

    def add(flag, value, frm):
        params.append({"flag": flag, "value": None if value is None else _num(value), "from": frm})

    if tool in ("vllm", "sglang", "transformers-serve"):
        for argv, raw in _logical_commands(text):
            i = 0
            while i < len(argv):
                a = argv[i]
                if not a.startswith("--"):
                    i += 1
                    continue
                val = None
                if "=" in a:
                    a, _, val = a.partition("=")
                elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    val = argv[i + 1]
                    i += 1
                tgt = VLLM_MAP.get(a)
                frm = "%s %s" % (a, val) if val is not None else a
                if tgt is None:
                    untr.append({"arg": frm, "why": "no llama.cpp mapping known"})
                elif tgt[0] == "@rope":
                    r = next((x for x in (_rope_from_json(o) for o in _json_objects(val or "")) if x), None)
                    if r:
                        fl = rope_flags(r)
                        for k in range(0, len(fl), 2):
                            add(fl[k], fl[k + 1], frm)
                    else:
                        untr.append({"arg": frm, "why": "model override without a YaRN rope_scaling"})
                elif tgt[0] == "@task":
                    if val in ("embed", "embedding", "pooling"):
                        add("--embeddings", None, frm)
                    else:
                        untr.append({"arg": frm, "why": "task %s" % val})
                elif tgt[0] is None:
                    untr.append({"arg": frm, "why": tgt[1]})
                elif tgt[0] == "--reasoning-format":
                    add("--reasoning-format", "deepseek", frm)
                elif tgt[0] == "--jinja":
                    add("--jinja", None, frm)
                elif tgt[0] in ("--port", "--host", "--alias"):
                    pass            # set by the launcher, not by the model
                else:
                    add(tgt[0], val, frm)
                i += 1
    if tool in ("vllm", "sglang", "transformers", "openai-client", "curl", "json", "python", "sentence-transformers",
                "transformers-serve", "mlx", "trl", "shell", None):
        for o in _json_objects(text) + _kwargs(text):
            if not isinstance(o, dict):
                continue
            _translate_obj(o, add, untr, ex)
        for m in re.finditer(r"\b(enable_thinking)\s*[=:]\s*(True|False|true|false)\b", text):
            v = m.group(2).lower()
            add("--chat-template-kwargs", '{"enable_thinking":%s}' % v, m.group(0))
        for m in re.finditer(r"""prompt_name\s*=\s*["'](\w+)["']""", text):
            params.append({"flag": "@prompt", "value": m.group(1), "from": m.group(0)})
        if re.search(r"\bencode_query\(", text):
            params.append({"flag": "@prompt", "value": "query", "from": "encode_query("})
        if re.search(r"\bencode_document\(", text):
            params.append({"flag": "@prompt", "value": "document", "from": "encode_document("})
        if re.search(r"\bdo_sample\s*=\s*False\b", text):
            add("--temp", 0, "do_sample=False")
    if tool == "ollama":
        for m in re.finditer(r"^\s*PARAMETER\s+(\w+)\s+(.+?)\s*$", text, re.M):
            k, v = m.group(1), m.group(2).strip().strip('"')
            if k in SAMPLING_KW:
                add(SAMPLING_KW[k], v, m.group(0).strip())
            elif k == "stop":
                params.append({"flag": "@stop", "value": v, "from": m.group(0).strip()})
            else:
                untr.append({"arg": m.group(0).strip(), "why": "Ollama parameter without a mapping"})
        if re.search(r"(?:^|\\n|\n)\s*TEMPLATE\s", text):
            params.append({"flag": "@template", "value": "Ollama TEMPLATE", "from": "TEMPLATE"})
        for argv, raw in _logical_commands(text):
            if argv[:2] == ["ollama", "run"]:
                untr.append({"arg": raw, "why": "Ollama pulls and runs the model with its own defaults; no flags to translate"})
    # dedupe
    seen, uniq = set(), []
    for p in params:
        key = (p["flag"], p["value"])
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    if not uniq and not untr:
        return None
    return {"translated": True, "params": uniq, "untranslatable": untr or None}


def _kwargs(text):
    """Python call keyword arguments that are sampling settings -> list of dicts."""
    d = {}
    for m in re.finditer(r"\b(temperature|top_p|top_k|min_p|presence_penalty|frequency_penalty|repetition_penalty|max_new_tokens|max_tokens)\s*=\s*(-?[\d.]+)", text):
        d[m.group(1)] = float(m.group(2)) if "." in m.group(2) else int(m.group(2))
    return [d] if d else []


def _translate_obj(o, add, untr, ex):
    for k, v in o.items():
        if k in SAMPLING_KW and isinstance(v, (int, float)) and not isinstance(v, bool):
            if SAMPLING_KW[k] == "-n" and k == "max_tokens" and v == 0:
                continue
            add(SAMPLING_KW[k], v, "%s: %s" % (k, v))
        elif k in ("chat_template_kwargs",) and isinstance(v, dict):
            add("--chat-template-kwargs", json.dumps(v, separators=(",", ":")), "%s: %s" % (k, json.dumps(v)))
        elif k in ("extra_body",) and isinstance(v, dict):
            _translate_obj(v, add, untr, ex)
        elif k in ("rope_scaling", "rope_parameters") and isinstance(v, dict):
            fl = rope_flags(_rope_from_json({k: v}))
            for i in range(0, len(fl), 2):
                add(fl[i], fl[i + 1], "%s: %s" % (k, json.dumps(v)))
        elif k == "stop" and v:
            add("@stop", json.dumps(v, ensure_ascii=False), "stop: %s" % json.dumps(v, ensure_ascii=False))
        elif isinstance(v, dict):
            _translate_obj(v, add, untr, ex)


def examples_for(text, file, label, build=None):
    """extract + parse + translate: the `card_commands` records of one document."""
    out = []
    for ex in extract_examples(text, file, label):
        if ex["tool"] == "llama.cpp":
            p = parse_llama(ex["text"], build)
            if p:
                ex["llama"] = p
        else:
            t = translate(ex)
            if t:
                ex["translation"] = t
        out.append(ex)
    return out


# ------------------------------------------------------------------ 3. GGUF / template / stop facts
POOLING_ENUM = {0: "none", 1: "mean", 2: "cls", 3: "last", 4: "rank"}   # llama.h enum llama_pooling_type


def sha256s(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest() if isinstance(s, str) else None


def token_texts(tok_cfg, tok_json=None):
    """{id: content} from tokenizer_config.json added_tokens_decoder and tokenizer.json added_tokens."""
    out = {}
    for t in (tok_json or {}).get("added_tokens") or []:
        if isinstance(t, dict) and isinstance(t.get("id"), int):
            out[t["id"]] = t.get("content")
    for k, v in ((tok_cfg or {}).get("added_tokens_decoder") or {}).items():
        try:
            out[int(k)] = v.get("content") if isinstance(v, dict) else v
        except ValueError:
            pass
    return out


def stop_analysis(gen_cfg, tok_cfg, meta, eog_texts, gen_src=None, tok_src=None, tok_json=None):
    """Which stop tokens the model's generation_config / tokenizer name, and whether the GGUF + build
    already end generation on each (GGUF eos/eot/eom id, or the build's built-in EOG texts).
    -> {"tokens": [{id, text, source, eog_by}], "missing": [...]}"""
    texts = token_texts(tok_cfg, tok_json)
    want = []
    ids = (gen_cfg or {}).get("eos_token_id")
    for i in (ids if isinstance(ids, list) else [ids] if ids is not None else []):
        want.append({"id": i, "text": texts.get(i), "source": gen_src or "generation_config.json eos_token_id"})
    eos = (tok_cfg or {}).get("eos_token")
    eos = eos.get("content") if isinstance(eos, dict) else eos
    if eos and not any(w["text"] == eos for w in want):
        tid = next((k for k, v in texts.items() if v == eos), None)
        want.append({"id": tid, "text": eos, "source": tok_src or "tokenizer_config.json eos_token"})
    gg = {k: meta.get("tokenizer.ggml.%s_token_id" % k) for k in ("eos", "eot", "eom")}
    eog = set(eog_texts or [])
    out, missing = [], []
    for w in want:
        by = None
        for k, v in gg.items():
            if v is not None and w["id"] is not None and v == w["id"]:
                by = "GGUF tokenizer.ggml.%s_token_id" % k
        if by is None and w["text"] in eog:
            by = "llama.cpp built-in EOG text"
        if by is None and eog_texts is None:
            by = "unknown (build EOG list not known)"
        if by is None and w["text"] is None:
            by = "unknown (token text not in the tokenizer files)"
        w = dict(w, eog_by=by)
        out.append(w)
        if by is None:
            missing.append(w)
    return {"tokens": out, "missing": missing, "gguf": {k: v for k, v in gg.items() if v is not None}}


# ------------------------------------------------------------------ 4. card statements
CTX_RX = [
    re.compile(r"(?i)\b(?:context(?:\s+length|\s+window)?|max(?:imum)?\s+(?:input|sequence|position)\s+(?:length|window)|position window)\b[^\n.]{0,40}?\b(\d{1,3}(?:[,.]\d{3})+|\d{4,7}|\d{1,4}\s?[kK])\b\s*(?:tokens)?"),
    re.compile(r"(?i)\b(\d{1,3}(?:,\d{3})+|\d{4,7}|\d{1,4}\s?[kK])\s*(?:-|\s)?tokens?\s+(?:of\s+)?context"),
]


def parse_count(s):
    s = s.replace(",", "").replace(".", "").strip()
    if s[-1:] in "kK":
        return int(s[:-1].strip()) * 1024
    return int(s)


def card_statements(text, file, label):
    """Context-length statements, YaRN instructions and pooling statements, with line numbers."""
    ctx, yarn, pooling = [], [], []
    lines = text.split("\n")
    for n, ln in enumerate(lines, 1):
        for rx in CTX_RX:
            for m in rx.finditer(ln):
                try:
                    v = parse_count(m.group(1))
                except ValueError:
                    continue
                if 512 <= v <= 10_000_000:
                    ctx.append({"value": v, "source": "%s %s:L%d" % (label, file, n), "quote": ln.strip()[:240]})
        if re.search(r"(?i)\byarn\b", ln):
            yarn.append({"source": "%s %s:L%d" % (label, file, n), "quote": ln.strip()[:240]})
        m = re.search(r"(?i)\bpooling\b[^\n|]{0,20}?\b(mean|cls|last|none)\b|\b(mean|cls|last)\s+pooling\b", ln)
        if m:
            pooling.append({"value": (m.group(1) or m.group(2)).lower(), "source": "%s %s:L%d" % (label, file, n), "quote": ln.strip()[:240]})
    r = None
    for o in _json_objects(text):
        r = _rope_from_json(o) if isinstance(o, dict) else None
        if r:
            break
    return {"ctx": ctx, "yarn_lines": yarn, "yarn": r, "pooling": pooling}


# ------------------------------------------------------------------ 5. required params
REQ, REC, OPT = "REQUIRED", "RECOMMENDED", "OPTIONAL"
CARD_REQUIRED_FLAGS = {"--jinja", "--chat-template-file", "--chat-template", "--chat-template-kwargs", "--pooling", "--embedding",
                       "--rope-scaling", "--rope-scale", "--yarn-orig-ctx", "--rope-freq-base", "--spm-infill", "--override-kv",
                       "--reasoning-format", "--reasoning", "--ubatch-size", "--batch-size", "--context-shift", "--no-context-shift"}
CARD_SAMPLING_FLAGS = {"--temp", "--top-p", "--top-k", "--min-p", "--presence-penalty", "--frequency-penalty", "--repeat-penalty",
                       "--repeat-last-n", "--dry-multiplier", "--typical", "--xtc-probability", "--mirostat"}
NA_FLAGS = {"--model", "--hf-repo", "--hf-file", "--port", "--host", "--alias", "--prompt", "--color", "--conversation", "--log-file",
            "--n-predict", "--interactive", "--interactive-first", "--single-turn", "--no-display-prompt", "--verbose", "--file"}


def item(cls, flag, value, source, why, **kw):
    d = {"class": cls, "flag": flag, "value": None if value is None else str(value), "source": source, "why_required": why}
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def merge_items(items):
    """One item per flag: REQUIRED beats RECOMMENDED beats OPTIONAL; sources are joined."""
    order = {REQ: 0, REC: 1, OPT: 2}
    by = {}
    for it in items:
        k = it["flag"] if not it["flag"].startswith("@") else "%s:%s" % (it["flag"], it.get("value"))
        if k not in by:
            by[k] = dict(it)
            continue
        o = by[k]
        if order[it["class"]] < order[o["class"]]:
            src = o["source"]
            by[k] = dict(it)
            by[k]["also"] = sorted(set((o.get("also") or []) + [src]))
        elif it["source"] != o["source"]:
            o["also"] = sorted(set((o.get("also") or []) + [it["source"]]))
            if it["value"] != o["value"] and order[it["class"]] == order[o["class"]]:
                o.setdefault("conflicts", []).append({"value": it["value"], "source": it["source"]})
    return list(by.values())


def flag_argv(items, include=(REQ, REC), drop=()):
    """argv for llama-server from required_params items (only real flags, not client/runtime notes)."""
    a = []
    for it in items:
        if it["class"] not in include or it["flag"].startswith("@") or it["flag"] in drop:
            continue
        a.append(it["flag"])
        if it.get("value") is not None:
            a.append(it["value"])
    return a


# ------------------------------------------------------------------ 6. curated decisions (quotes verified)
def load_curated(path=None):
    p = path or CURATED
    if not os.path.isfile(p):
        return {}
    import yaml
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


SRC_RX = re.compile(r"^(?P<label>\S+)\s+(?P<file>[^:\s]+):L(?P<a>\d+)(?:-(?P<b>\d+))?$")


def verify_quote(source, quote, docs):
    """docs: {label: {file: text}}. True when `quote` is in the cited lines (whitespace-normalised)."""
    m = SRC_RX.match(source or "")
    if not m or not quote:
        return False, "source must look like 'owner/repo FILE:Lx[-y]' and carry a quote"
    files = docs.get(m.group("label")) or {}
    text = files.get(m.group("file"))
    if text is None:
        return False, "%s: no such document in the snapshots" % source
    lines = text.split("\n")
    a, b = int(m.group("a")), int(m.group("b") or m.group("a"))
    seg = _norm("\n".join(lines[a - 1:b]))
    if _norm(quote) not in seg:
        return False, "%s: quote not found in those lines: %r" % (source, quote[:80])
    return True, None


# ------------------------------------------------------------------ 7. analysis of one model
def _src_ok(x):
    return x is not None and x != [] and x != {}


def _first(*pairs):
    for v, s in pairs:
        if _src_ok(v):
            return v, s
    return None, None


def analyze(inp):
    """inp: dict with
         repo, revision, file, entry (the database entry so far: card_defaults, card_ctx, ...),
         meta (GGUF header), docs {label: {file: text}} (cards, base cards, GitHub READMEs),
         doc_meta [{label, file, kind: card|base-card|github, sha, url}],
         snap/bsnap (snapshot dicts or None), configs {label: {"config.json":{}, ...}},
         chain [base model repos, nearest first, with their card front matter],
         build (llama_flags table for EOG / flag checks, or None), curated (this entry's block)
       -> {"descriptor", "card_commands", "required_params", "template", "stop", "blockers", "problems"}"""
    meta, e, cur = inp.get("meta") or {}, inp.get("entry") or {}, inp.get("curated") or {}
    arch = meta.get("general.architecture")
    problems, blockers = [], []
    # ---- examples, verbatim
    cmds = []
    for d in inp.get("doc_meta", []):
        text = (inp["docs"].get(d["label"]) or {}).get(d["file"])
        if text is None:
            continue
        for ex in examples_for(text, d["file"], d["label"], inp.get("build")):
            ex["doc"] = d["kind"]
            if d.get("sha"):
                ex["doc_sha"] = d["sha"]
            ex["scope"] = _scope(ex, inp)
            cmds.append(ex)
    # ---- statements
    stm = {d["label"] + " " + d["file"]: card_statements(inp["docs"][d["label"]][d["file"]], d["file"], d["label"])
           for d in inp.get("doc_meta", []) if (inp["docs"].get(d["label"]) or {}).get(d["file"]) is not None}
    inp["_stm"] = {k: v for k, v in stm.items() if not k.startswith("github.com/")}
    cfgs = inp.get("configs") or {}
    # ---- descriptor
    desc = descriptor(inp, meta, cfgs, stm, problems)
    # ---- template
    tmpl = template_check(inp, meta, cur, problems)
    # ---- stop tokens
    gen, gsrc, tok, tsrc = None, None, None, None
    for lab, c in cfgs.items():
        if gen is None and isinstance(c.get("generation_config.json"), dict):
            gen, gsrc = c["generation_config.json"], "%s generation_config.json eos_token_id" % lab
        if tok is None and isinstance(c.get("tokenizer_config.json"), dict):
            tok, tsrc = c["tokenizer_config.json"], "%s tokenizer_config.json eos_token" % lab
    tj = next((c["tokenizer.json"] for c in cfgs.values() if isinstance(c.get("tokenizer.json"), dict)), None)
    stop = stop_analysis(gen, tok, meta, (inp.get("build") or {}).get("eog"), gsrc, tsrc, tj) if (gen or tok) else None
    for w in (stop or {}).get("tokens") or []:
        if w["eog_by"] and w["eog_by"].startswith("unknown (token text"):
            problems.append("stop token id %s (%s): its text is not in the stored tokenizer files, so whether llama.cpp ends on it is unverified" % (w["id"], w["source"]))
    # ---- required params
    req = required(inp, meta, desc, tmpl, stop, cmds, cur, problems, blockers)
    for b in cur.get("blockers") or []:
        ok, why = verify_quote(b.get("source"), b.get("quote"), inp["docs"]) if b.get("source") else (True, None)
        if not ok:
            problems.append("curated blocker: %s" % why)
        blockers.append({k: v for k, v in b.items()})
    return {"descriptor": desc, "card_commands": cmds, "required_params": req, "template": tmpl, "stop": stop,
            "blockers": blockers or None, "problems": problems or None}


def _scope(ex, inp):
    """'model' when an example names this model (or none), else 'family: <name>' (another size of the family)."""
    names = re.findall(r"(?:hf\.co/|-hf\s+|--hf-repo\s+|--model(?:-path)?\s+|serve\s+|--force-model\s+|from_pretrained\(\s*[\"']|model\s*=\s*[\"']|model_name\s*=\s*[\"']|model_id\s*=\s*[\"']|\"model\":\s*\"|SentenceTransformer\(\s*[\"'])([\w.-]+/[\w.:-]+)", ex["text"])
    if not names:
        return "model"
    mine = {x.lower() for x in [inp.get("repo")] + [c["repo"] for c in inp.get("chain") or []] if x}
    for n in names:
        if n.split(":")[0].lower() in mine:
            return "model"
    return "family: %s" % names[0]


def descriptor(inp, meta, cfgs, stm, problems):
    arch = meta.get("general.architecture")
    snap, chain = inp.get("snap") or {}, inp.get("chain") or []
    fm = (snap.get("card_data") or {}) if snap else {}
    vals = {}

    def put(field, value, source):
        if value is None or value == "" or value == []:
            return
        vals.setdefault(field, []).append({"value": value, "source": source})

    repo = inp["repo"]
    put("repo_id", snap.get("api_id") or repo, "HF API id")
    if snap.get("api_id") and snap["api_id"] != repo:
        problems.append("repo id: requested %s, the Hub calls it %s (renamed or case)" % (repo, snap["api_id"]))
    put("revision", inp.get("revision"), "pinned (manifest / database)")
    if inp.get("latest_revision"):
        put("latest_revision", inp["latest_revision"], "HF API main")
    sib = (snap.get("files") or {}).get(inp["file"]) or {}
    put("file", inp["file"], "HF API siblings")
    put("bytes", sib.get("size"), "HF API LFS size")
    put("sha256", sib.get("sha256"), "HF API LFS oid")
    q_name = _quant_of(inp["file"])
    put("quant", q_name, "file name")
    ft = meta.get("general.file_type")
    if isinstance(ft, int):
        put("quant", FTYPES.get(ft, "file_type %d" % ft), "GGUF general.file_type")
    # license
    for lab, f_ in [(repo, fm)] + [(c["repo"], c.get("card_data") or {}) for c in chain]:
        if f_.get("license"):
            put("license", f_["license"], "%s card license" % lab)
        if f_.get("license_name"):
            put("license_name", f_["license_name"], "%s card license_name" % lab)
        if f_.get("license_link"):
            put("license_link", f_["license_link"], "%s card license_link" % lab)
    for k, f in (("general.license", "license"), ("general.license.name", "license_name"), ("general.license.link", "license_link")):
        put(f, meta.get(k), "GGUF %s" % k)
    for d in inp.get("doc_meta", []):
        if d["kind"] == "github" and d.get("license_spdx"):
            put("license", d["license_spdx"], "GitHub %s license (spdx)" % d["label"])
        if d["kind"] == "github" and d.get("license_file"):
            put("license_file", "%s@%s/%s" % (d["label"], d["sha"][:12], d["license_file"]), "GitHub %s" % d["label"])
    for p in sorted((snap.get("files") or {})):
        if re.match(r"(?i)^licen[cs]e(\.\w+)?$|^LICENSE", p):
            put("license_file", "%s@%s/%s" % (repo, (inp.get("revision") or "")[:12], p), "%s repo file" % repo)
    for c in chain:
        for p in c.get("license_files") or []:
            put("license_file", "%s@%s/%s" % (c["repo"], (c.get("revision") or "")[:12], p), "%s repo file" % c["repo"])
    # base chain
    bm = fm.get("base_model")
    for c in chain:
        put("base_model_chain", c["repo"], c.get("via") or "card base_model")
    i = 0
    while "general.base_model.%d.name" % i in meta:
        put("gguf_base_model", {"name": meta.get("general.base_model.%d.name" % i), "organization": meta.get("general.base_model.%d.organization" % i),
                                "repo_url": meta.get("general.base_model.%d.repo_url" % i)}, "GGUF general.base_model.%d" % i)
        i += 1
    # architecture
    put("architecture", arch, "GGUF general.architecture")
    if (snap.get("gguf") or {}).get("architecture"):
        put("architecture", snap["gguf"]["architecture"], "HF API gguf.architecture")
    for lab, c in cfgs.items():
        cf = c.get("config.json") or {}
        if cf.get("architectures"):
            put("hf_architectures", cf["architectures"], "%s config.json architectures" % lab)
        if cf.get("model_type"):
            put("hf_model_type", cf["model_type"], "%s config.json model_type" % lab)
    # parameter count
    if (snap.get("gguf") or {}).get("total"):
        put("parameters", snap["gguf"]["total"], "HF API gguf.total (%s)" % repo)
    for c in chain:
        st = (c.get("safetensors") or {}).get("total")
        if st:
            put("parameters", st, "HF API safetensors.total (%s)" % c["repo"])
    put("size_label", meta.get("general.size_label"), "GGUF general.size_label")
    # context
    for key, ss in stm.items():
        for s in ss["ctx"]:
            put("ctx_statements", {"value": s["value"], "quote": s["quote"]}, s["source"])
    if inp.get("entry", {}).get("card_ctx"):
        put("ctx", inp["entry"]["card_ctx"], "card: %s" % inp["entry"].get("card_ctx_source"))
    for lab, c in cfgs.items():
        cf = c.get("config.json") or {}
        tc = cf.get("text_config") if isinstance(cf.get("text_config"), dict) else {}
        v = cf.get("max_position_embeddings") or tc.get("max_position_embeddings")
        if isinstance(v, int):
            put("ctx", v, "%s config.json max_position_embeddings" % lab)
        sbc = c.get("sentence_bert_config.json") or {}
        if isinstance(sbc.get("max_seq_length"), int):
            put("ctx", sbc["max_seq_length"], "%s sentence_bert_config.json max_seq_length" % lab)
    if arch and isinstance(meta.get("%s.context_length" % arch), int):
        put("ctx", meta["%s.context_length" % arch], "GGUF %s.context_length" % arch)
    for key, ss in stm.items():
        if ss.get("yarn"):
            put("rope_yarn", ss["yarn"], "%s (rope_scaling JSON)" % key)
    # pipeline / languages
    put("pipeline_tag", snap.get("pipeline_tag"), "%s HF API pipeline_tag" % repo)
    for c in chain:
        put("pipeline_tag", c.get("pipeline_tag"), "%s HF API pipeline_tag" % c["repo"])
    for lab, f_ in [(repo, fm)] + [(c["repo"], c.get("card_data") or {}) for c in chain]:
        lang = f_.get("language")
        if lang:
            put("languages", lang if isinstance(lang, list) else [lang], "%s card language" % lab)
    put("languages", meta.get("general.languages"), "GGUF general.languages")
    # effective values and conflicts
    out = {}
    for f, vs in vals.items():
        eff = vs[0]
        distinct = []
        for v in vs:
            if v["value"] not in [d["value"] for d in distinct]:
                distinct.append(v)
        rec = {"effective": eff["value"], "source": eff["source"]}
        if len(distinct) > 1 or len(vs) > 1:
            rec["values"] = vs
        if len(distinct) > 1 and f not in ("ctx_statements", "base_model_chain", "gguf_base_model", "license_file", "hf_architectures",
                                           "hf_model_type", "license_name", "license_link"):
            rec["conflict"] = True
        out[f] = rec
    if "ctx" in out:
        out["ctx"]["precedence"] = "card statement > config.json > GGUF header > GitHub README"
    return out


FTYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M",
          13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS",
          21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S",
          29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16", 36: "TQ1_0", 37: "TQ2_0", 38: "MXFP4"}   # llama.h llama_ftype


def _quant_of(f):
    m = re.search(r"(?i)[.-]((?:UD-)?(?:IQ\d_[A-Z]+|Q\d_K(?:_[SMLX]+)?|Q\d_\d|TQ\d_\d|MXFP4|F16|BF16|F32))(?=\.gguf$)", f)
    return m.group(1).upper() if m else None


def template_check(inp, meta, cur, problems):
    """GGUF template vs the repo template (repo first, then the base chain)."""
    t = {}
    g = meta.get("tokenizer.chat_template")
    if isinstance(g, str):
        t["gguf_sha256"], t["gguf_chars"] = sha256s(g), len(g)
    for lab, c in (inp.get("templates") or {}).items():
        if c and "repo_sha256" not in t:
            t["repo_sha256"], t["repo_chars"], t["repo_file"], t["repo_label"] = sha256s(c["text"]), len(c["text"]), c["file"], lab
            t["repo_path"] = c.get("path")
    if "gguf_sha256" in t and "repo_sha256" in t:
        t["same"] = t["gguf_sha256"] == t["repo_sha256"]
    dec = cur.get("template") or {}
    if t.get("same") is False:
        if not dec.get("use"):
            problems.append("chat template: the GGUF's (%s, %d chars) differs from %s %s (%s, %d chars) and registry/model-params.yaml "
                            "has no decision (template.use: repo|gguf with a reason)" % (t["gguf_sha256"][:12], t["gguf_chars"], t["repo_label"],
                                                                                      t["repo_file"], t["repo_sha256"][:12], t["repo_chars"]))
        elif dec.get("sha256") and dec["sha256"] not in (t["repo_sha256"], t["gguf_sha256"]):
            problems.append("chat template: the decision in registry/model-params.yaml was made for template %s, which is neither the GGUF's nor the repo's now"
                            % dec["sha256"][:12])
        t["use"], t["reason"], t["verified"] = dec.get("use"), dec.get("reason"), dec.get("verified")
    elif "gguf_sha256" in t:
        t["use"] = "gguf"
    return t or None


SAMPLING_FLAG_OF = {"temp": "--temp", "top-p": "--top-p", "top-k": "--top-k", "min-p": "--min-p", "repeat-penalty": "--repeat-penalty",
                    "presence-penalty": "--presence-penalty", "frequency-penalty": "--frequency-penalty"}
SERVER_SRC = "llama.cpp tools/server/server-context.cpp (b11374): \"input (%d tokens) is too large to process. increase the physical batch size\" for inputs that cannot be split"
SYSTEMONE_SRC = "llama.cpp tools/server/README.md L1695 (b11374): \"For laya and clef, the whole prompt is evaluated in one batch: it must fit in `--ubatch-size`.\""


def model_kind(meta, cfgs, snap, cur):
    if cur.get("kind"):
        return cur["kind"]
    arch = meta.get("general.architecture") or ""
    if meta.get("%s.decision.type" % arch):
        return "decision"
    if meta.get("%s.pooling_type" % arch) is not None or any("modules.json" in c or "1_Pooling/config.json" in c for c in cfgs.values()):
        if (snap or {}).get("pipeline_tag") in ("sentence-similarity", "feature-extraction") or meta.get("%s.pooling_type" % arch) is not None:
            return "embed"
    if isinstance(meta.get("tokenizer.chat_template"), str):
        return "chat"
    return "raw"


def required(inp, meta, desc, tmpl, stop, cmds, cur, problems, blockers):
    arch = meta.get("general.architecture") or ""
    cfgs = inp.get("configs") or {}
    e = inp.get("entry") or {}
    kind = model_kind(meta, cfgs, inp.get("snap"), cur)
    items = []
    # ---- native window: card statement > config > GGUF (descriptor), widened by the card's own llama.cpp -c for this model
    ctxv = desc.get("ctx") or {}
    native, nsrc = ctxv.get("effective"), ctxv.get("source")
    for ex in cmds:
        if ex["tool"] != "llama.cpp" or ex["scope"] != "model" or ex["doc"] == "github":
            continue
        for c in ex.get("llama") or []:
            for f in c["flags"]:
                if f["canonical"] == "--ctx-size" and f["value"] and f["value"].isdigit() and native and int(f["value"]) > native:
                    gg = meta.get("%s.context_length" % arch)
                    if gg is None or int(f["value"]) <= gg:
                        native, nsrc = int(f["value"]), "%s (the card's own llama.cpp command)" % ex["source"]
    if cur.get("native_ctx"):
        c = cur["native_ctx"]
        ok, why = verify_quote(c.get("source"), c.get("quote"), inp["docs"])
        if not ok:
            problems.append("curated native_ctx: %s" % why)
        native, nsrc = c["value"], c["source"]
    yarn = (desc.get("rope_yarn") or {}).get("effective")
    ysrc = (desc.get("rope_yarn") or {}).get("source")
    # ---- by kind
    if kind == "chat":
        items.append(item(REQ, "--jinja", None, "GGUF tokenizer.chat_template (%s)" % ((tmpl or {}).get("gguf_sha256") or "")[:12],
                          "messages, tool calls and thinking are formatted by the model's chat template; without --jinja llama-server falls back to a built-in approximation"))
        if (tmpl or {}).get("use") == "repo":
            items.append(item(REQ, "--chat-template-file", "${template:%s}" % tmpl["repo_sha256"], "%s %s" % (tmpl["repo_label"], tmpl["repo_file"]),
                              tmpl.get("reason") or "the GGUF's embedded chat template differs from the repo's", template_sha256=tmpl["repo_sha256"]))
    elif kind == "embed":
        items.append(item(REQ, "--embeddings", None, "%s pipeline_tag / GGUF %s.pooling_type" % (inp["repo"], arch), "an embedding model: serve /v1/embeddings, no text generation"))
        pool, psrc = _pooling(meta, cfgs, inp, arch, inp.get("_stm"))
        gp = meta.get("%s.pooling_type" % arch)
        if pool and isinstance(gp, int) and POOLING_ENUM.get(gp) != pool:
            problems.append("pooling: the card / sentence-transformers config says %s but GGUF %s.pooling_type is %s" % (pool, arch, POOLING_ENUM.get(gp)))
        if pool:
            items.append(item(REQ, "--pooling", pool, psrc, "sentence embeddings are the %s-pooled token states, as the model was trained" % pool))
        else:
            problems.append("embedding model without a known pooling type")
        items += _batch_items("non-causal encoder: the whole input must fit in one micro-batch", SERVER_SRC)
        for p in _st_prompts(cfgs):
            items.append(item(REQ, "@prompt", p["prefix"], p["source"], "client: prefix every %s input with this text before embedding (the model was trained with it)" % p["name"],
                              name=p["name"], client=True))
        if any("2_Normalize" in k or "modules.json" in k and "Normalize" in json.dumps(c.get("modules.json")) for lab, c in cfgs.items() for k in c):
            items.append(item(REQ, "@normalize", "euclidean", "sentence-transformers modules.json Normalize",
                              "client: embeddings are L2-normalised; llama-server does this by default (embd_normalize 2)", client=True))
    elif kind == "decision":
        dt = meta.get("%s.decision.type" % arch)
        if dt:
            items.append(item(REQ, "@endpoint", "POST /v1/systemone", "GGUF %s.decision.type = %s" % (arch, dt), "a decision model: answers through /v1/systemone, not chat", client=True))
        if dt in ("laya", "clef") or meta.get("%s.attention.causal" % arch) is False:
            items += _batch_items("decision prompt evaluated in one batch (non-causal encoder)", SYSTEMONE_SRC if dt in ("laya", "clef") else SERVER_SRC)
    # ---- the card's own llama.cpp flags (this model only)
    for ex in cmds:
        if ex["tool"] != "llama.cpp" or ex["scope"] != "model":
            continue
        for c in ex.get("llama") or []:
            for f in c["flags"]:
                cf, v = f["canonical"], f["value"]
                if f.get("known") is False:
                    problems.append("%s: %s is not a flag of the pinned build" % (ex["source"], f["flag"]))
                if cf in CARD_REQUIRED_FLAGS and c["tool"] in ("llama-server", "llama-cli", "llama serve", "llama-embedding"):
                    if cf in ("--ubatch-size", "--batch-size") and any(i["flag"] == cf for i in items):
                        continue
                    items.append(item(REQ, cf, v, ex["source"], "the card's %s command sets it" % c["tool"]))
                elif cf in CARD_SAMPLING_FLAGS:
                    items.append(item(REC, cf, v, ex["source"], "sampling in the card's %s command" % c["tool"]))
                elif cf not in NA_FLAGS and cf not in ("--ctx-size",):
                    items.append(item(OPT, cf, v, ex["source"], "performance / tool option in the card's command" + (" (%s)" % f["note"] if f["note"] else "")))
    # ---- translated examples: the parameters that matter beyond sampling
    for ex in cmds:
        t = ex.get("translation")
        if not t or ex["scope"] != "model":
            continue
        for p in t["params"]:
            if p["flag"] == "--reasoning-format" and kind == "chat":
                items.append(item(REQ, "--reasoning-format", "deepseek", ex["source"], "translated from %s: the card serves it with a reasoning parser; llama-server separates <think> with --reasoning-format deepseek (its default)" % p["from"], translated=True))
            elif p["flag"] == "--jinja" and kind == "chat":
                items.append(item(REQ, "--jinja", None, ex["source"], "translated from %s: tool calls come from the chat template" % p["from"], translated=True))
            elif p["flag"] == "@stop":
                items.append(item(REQ, "@stop", p["value"], ex["source"], "client/server stop strings from the card's example", translated=True, client=True))
    # ---- the card's own examples (scope model, card or base card): sampling keys the chosen set lacks,
    #      and a thinking switch every example sets the same way
    cd = e.get("card_defaults") or {}
    kw_vals = {}
    for ex in cmds:
        t = ex.get("translation")
        if not t or ex["scope"] != "model" or ex["doc"] != "card":
            continue
        for p in t["params"]:
            inv = {v: k for k, v in SAMPLING_FLAG_OF.items()}
            if p["flag"] in inv and inv[p["flag"]] not in cd:
                items.append(item(REC, p["flag"], p["value"], ex["source"], "translated from the card's example (%s); the card's sampling set does not name it" % p["from"], translated=True))
    for ex in cmds:
        for p in (ex.get("translation") or {}).get("params") or []:
            if p["flag"] == "--chat-template-kwargs" and ex["scope"] == "model" and ex["doc"] in ("card", "base-card"):
                kw_vals.setdefault(p["value"], []).append(ex["source"])
    if len(kw_vals) == 1 and kind == "chat":
        v, srcs = next(iter(kw_vals.items()))
        items.append(item(REC, "--chat-template-kwargs", v, srcs[0], "every example on the card passes chat_template_kwargs %s" % v, translated=True,
                          also=srcs[1:] or None))
    for k, v in cd.items():
        if k in SAMPLING_FLAG_OF:
            items.append(item(REC, SAMPLING_FLAG_OF[k], _num(v), (e.get("card_defaults_source") or {}).get(k) or "card",
                              "the card's recommended sampling (%s)" % (e.get("card_default_set") or "card")))
    # ---- stop tokens
    for w in (stop or {}).get("missing") or []:
        items.append(item(REQ, "@stop", w["text"], w["source"], "the model ends turns with %r (id %s) but neither the GGUF eos/eot id nor llama.cpp's built-in end-of-generation list covers it; "
                          "send it as a stop string or set --override-kv tokenizer.ggml.eot_token_id=int:%s" % (w["text"], w["id"], w["id"]), client=True))
    # ---- curated (quotes verified)
    for c in cur.get("requires") or []:
        ok, why = verify_quote(c.get("source"), c.get("quote"), inp["docs"])
        if not ok:
            problems.append("curated %s: %s" % (c.get("flag"), why))
        items.append(item(c.get("class", REQ), c["flag"], c.get("value"), c["source"], c["why"], quote=c.get("quote"), client=c.get("client"),
                          translated=c.get("translated"), name=c.get("name"), curated=True))
    # a curated item replaces derived ones of the same flag (the decision quotes the card)
    cflags = {c["flag"] for c in cur.get("requires") or [] if not c["flag"].startswith("@")}
    if cflags:
        items = [i for i in items if i["flag"] not in cflags or i.get("quote") is not None]
    items = merge_items(items)
    return {"kind": kind, "native_ctx": native, "native_ctx_source": nsrc, "yarn": yarn, "yarn_source": ysrc, "items": items}


def _batch_items(why, src):
    return [item(REQ, "--ubatch-size", "${slot_ctx}", src, why + ": -ub must be at least the longest input (the slot context)"),
            item(REQ, "--batch-size", "${slot_ctx}", src, "llama.cpp caps -ub at -b, so -b must be at least -ub")]


def _pooling(meta, cfgs, inp, arch, stm=None):
    for key, ss in (stm or {}).items():          # the card's own statement first
        for p in ss.get("pooling") or []:
            return p["value"], "%s: %s" % (p["source"], p["quote"][:80])
    for lab, c in cfgs.items():
        pc = c.get("1_Pooling/config.json")
        if isinstance(pc, dict) and isinstance(pc.get("pooling_mode"), str):
            m = {"mean": "mean", "cls": "cls", "lasttoken": "last", "last": "last"}.get(pc["pooling_mode"].lower())
            if m:
                return m, "%s 1_Pooling/config.json pooling_mode" % lab
        if isinstance(pc, dict):
            for k, name in (("pooling_mode_mean_tokens", "mean"), ("pooling_mode_cls_token", "cls"), ("pooling_mode_lasttoken", "last")):
                if pc.get(k):
                    return name, "%s 1_Pooling/config.json %s" % (lab, k)
    pt = meta.get("%s.pooling_type" % arch)
    if pt is None:
        pt = meta.get("%s.classifier.pooling_type" % arch)
    if isinstance(pt, int):
        return POOLING_ENUM.get(pt), "GGUF %s.pooling_type = %d" % (arch, pt)
    return None, None


def _st_prompts(cfgs):
    out = []
    for lab, c in cfgs.items():
        st = c.get("config_sentence_transformers.json")
        if isinstance(st, dict) and isinstance(st.get("prompts"), dict):
            for name, pre in st["prompts"].items():
                if pre:
                    out.append({"name": name, "prefix": pre, "source": "%s config_sentence_transformers.json prompts.%s" % (lab, name)})
            break
    return out


# ------------------------------------------------------------------ 8. resolving items for one launch
def launch_items(rp, ctx, parallel=1, build=None, include=(REQ, REC), drop=()):
    """Resolve ${slot_ctx} / ${ctx} / rope YaRN for a launch at ctx with `parallel` slots.
    -> (argv list, errors list, notes list). Unsupported flags in `build` are errors (blockers)."""
    errs, notes, argv = [], [], []
    slot = ctx // max(1, parallel) if ctx else None
    native = rp.get("native_ctx")
    items = list(rp.get("items") or [])
    if ctx and native and ctx > native:
        y = rp.get("yarn")
        if y and y.get("factor"):
            for fl, v in zip(*[iter(rope_flags(y))] * 2):
                items.append(item(REQ, fl, v, rp.get("yarn_source"), "ctx %d exceeds the native window %d: the card's YaRN scaling" % (ctx, native)))
        else:
            errs.append("ctx %d exceeds the model's native window %d (%s) and the card documents no rope scaling for it"
                        % (ctx, native, rp.get("native_ctx_source")))
    for it in items:
        if it["class"] not in include or it["flag"].startswith("@") or it["flag"] in drop:
            continue
        v = it.get("value")
        if v is not None and v.startswith(">="):
            continue                     # a minimum: checked by missing_required, not emitted
        if v is not None:
            v = v.replace("${slot_ctx}", str(slot) if slot else "${slot_ctx}").replace("${ctx}", str(ctx) if ctx else "${ctx}")
        if build is not None:
            r = build["flags"].get(it["flag"])
            if r is None:
                errs.append("BLOCKER: %s (%s) is not a flag of llama.cpp %s" % (it["flag"], it["class"], build.get("name")))
                continue
        argv.append(it["flag"])
        if v is not None:
            argv.append(v)
    for it in items:
        if it["flag"].startswith("@") and it["class"] == REQ:
            notes.append("%s %s: %s (%s)" % (it["flag"][1:], it.get("value") or "", it["why_required"], it["source"]))
    return argv, errs, notes


def argv_values(argv, build=None):
    """{canonical flag: value or True} from a llama-server argv (last one wins)."""
    out, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("-") and not re.match(r"^-\d", a):
            c = canonical(a, build) if build else a
            r = (build or {}).get("flags", {}).get(a) if build else None
            n = r["nargs"] if r else (1 if i + 1 < len(argv) and not argv[i + 1].startswith("-") else 0)
            if n and i + 1 < len(argv):
                out[c] = argv[i + 1]
                i += 2
                continue
            out[c] = True
        i += 1
    return out


def missing_required(rp, argv, ctx, parallel=1, build=None, overrides=None):
    """REQUIRED items absent from argv (or with another value); RECOMMENDED ones too unless overridden.
    -> list of error strings ("" when fine)."""
    want, errs, _ = launch_items(rp, ctx, parallel, build)
    have = argv_values(argv, build)
    wantd = argv_values(want, build)
    cls = {}
    for it in rp.get("items") or []:
        cls[canonical(it["flag"], build) if build else it["flag"]] = it["class"]
    out = list(errs)
    for it in rp.get("items") or []:
        v = it.get("value") or ""
        if it["flag"].startswith("@") or not v.startswith(">=") or it["class"] not in (REQ, REC):
            continue
        k = canonical(it["flag"], build) if build else it["flag"]
        if (overrides or {}).get(k.lstrip("-")) or (overrides or {}).get(k):
            continue
        hv = have.get(k) if k != "--ctx-size" else (have.get(k) or ctx)
        try:
            if hv is None or float(hv) < float(v[2:]):
                out.append("%s %s must be %s (%s), is %s" % (it["class"], k, v, it["source"], hv))
        except ValueError:
            pass
    for k, v in wantd.items():
        c = cls.get(k, REQ)
        if (overrides or {}).get(k.lstrip("-")) or (overrides or {}).get(k):
            continue
        if k not in have:
            out.append("%s %s%s missing" % (c, k, "" if v is True else " " + str(v)))
        elif v is not True and str(have[k]) != str(v):
            if k in ("--ubatch-size", "--batch-size") and str(have[k]).isdigit() and str(v).isdigit() and int(have[k]) >= int(v):
                continue
            try:
                if float(have[k]) == float(v):
                    continue
            except (TypeError, ValueError):
                pass
            out.append("%s %s is %s, the card needs %s" % (c, k, have[k], v))
    return out
