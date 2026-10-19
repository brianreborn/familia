#!/usr/bin/env python3
"""add_model.py: register a model (a Hugging Face snapshot directory, explicit
flags, or a lone GGUF) in code-bootstraps-llama.cpp/config/models-manifest.json
and models-preset.ini.

First ingestion piece of the model database (REQUIREMENTS.md "Model database",
familia #51). Stdlib only (no pip dependencies): runs on ~15-year-old devices.
No network unless --fetch is given. Never invents values: anything it cannot
find stays null / "unknown" and is reported.

Usage (wrapper: scripts/add-model.sh):
  add-model.sh DIR                      HF snapshot dir (README.md, config.json, *.gguf, ...)
  add-model.sh FILE.gguf                a lone GGUF (+ --card/--config/... if you have them)
  add-model.sh ROLE FILE.gguf           legacy form, still works
  add-model.sh --repo ORG/NAME --revision SHA --file FILE.gguf [--card README.md] ...
  add-model.sh --fetch ORG/NAME[@REV] --quant Q4_K_M   download (stdlib HTTPS, pinned), then add
Run with --help for every flag.
"""
import argparse, hashlib, json, os, re, shutil, struct, subprocess, sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUX_KINDS = ("draft", "mmproj", "embed", "reranker", "tokenizer", "vocoder", "mtp", "lora")
BASE_ROLES = ("general", "coder", "decision", "embed")
CARD_FILES = ("README.md", "config.json", "generation_config.json", "tokenizer_config.json",
              "chat_template.jinja", "chat_template.json", "special_tokens_map.json", "LICENSE",
              "LICENSE.md", "LICENSE.txt", "NOTICE", "decision_config.json", "params.json")
# Keys of manifest entries written as ONE compact JSON line: the launchers read the
# manifest with scripts/lib/manifest.awk, which only understands flat "key": value lines.
NESTED_KEYS = ("base_model", "card_defaults", "card_defaults_source", "card_sampling_modes",
               "card_commands", "card_notes", "chat_template", "stop", "rope", "files", "aux",
               "parts", "inferred", "unknown", "deviations", "override_reasons", "repo_files", "base_repo_files",
               "required", "blockers")
FTYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K",
          11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S",
          17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS",
          23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S",
          29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16", 36: "TQ1_0", 37: "TQ2_0", 38: "MXFP4_MOE"}
QUANT_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(UD-)?(IQ\d_[A-Z]+|Q\d_K(?:_[SMLX]+)?|Q\d_\d|TQ\d_\d|MXFP4(?:_MOE)?|BF16|F16|F32)(?![A-Za-z0-9])")
EMBED_ARCHS = ("bert", "nomic-bert", "nomic-bert-moe", "jina-bert-v2", "jina-bert-v3", "gemma-embedding", "neo-bert", "t5encoder")


class UsageError(Exception):
    pass


def log(msg=""):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- GGUF header
def gguf_header(path, max_str_array=256):
    """Read only the GGUF header key/values (v2/v3). Numeric arrays and long string
    arrays (token lists) are skipped with seeks and returned as {"array": n}."""
    fmt = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
    out = {}
    with open(path, "rb") as f:
        def rd(n):
            b = f.read(n)
            if len(b) != n:
                raise ValueError("truncated GGUF header")
            return b
        if rd(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        ver, = struct.unpack("<I", rd(4))
        if ver < 2:
            raise ValueError("unsupported GGUF version %d" % ver)
        n_tensors, n_kv = struct.unpack("<QQ", rd(16))
        if n_kv > 100000:
            raise ValueError("implausible GGUF kv count %d" % n_kv)
        def rstr():
            n, = struct.unpack("<Q", rd(8))
            return rd(n).decode("utf-8", "replace")
        def skipstr():
            n, = struct.unpack("<Q", rd(8))
            f.seek(n, 1)
        def rval(t):
            if t == 8:
                return rstr()
            if t == 9:
                et, n = struct.unpack("<IQ", rd(12))
                if et in fmt:
                    f.seek(struct.calcsize(fmt[et]) * n, 1)
                    return {"array": n}
                if et == 8:
                    if n <= max_str_array:
                        return [rstr() for _ in range(n)]
                    for _ in range(n):
                        skipstr()
                    return {"array": n}
                return {"array": n, "items": [rval(et) for _ in range(n)]}
            if t not in fmt:
                raise ValueError("unknown GGUF value type %d" % t)
            s = fmt[t]
            return struct.unpack(s, rd(struct.calcsize(s)))[0]
        for _ in range(n_kv):
            k = rstr()
            t, = struct.unpack("<I", rd(4))
            out[k] = rval(t)
    out["_gguf_version"] = ver
    out["_n_tensors"] = n_tensors
    return out


def sha256_file(path, progress=False):
    h = hashlib.sha256()
    size = os.path.getsize(path)
    done = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress and size > (256 << 20) and done % (256 << 20) < (1 << 20):
                log("  sha256 %s: %d%%" % (os.path.basename(path), done * 100 // size))
    return h.hexdigest()


# ---------------------------------------------------------------- model card
def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if v in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d*", v):
        return float(v)
    return v


def parse_front_matter_text(text):
    """Tiny YAML subset for card front matter: top-level `key: value`, `key: [a, b]`
    and `key:` followed by `- item` lines. Nested mappings are kept as raw text."""
    data, key = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                data[key] = [_scalar(x) for x in val[1:-1].split(",") if x.strip()]
            elif val in ("", "|", ">"):
                data[key] = None
            else:
                data[key] = _scalar(val)
            continue
        m = re.match(r"^\s*-\s+(.*)$", line)
        if m and key is not None:
            if not isinstance(data.get(key), list):
                data[key] = [] if data.get(key) is None else [data[key]]
            data[key].append(_scalar(m.group(1)))
            continue
        if key is not None and line.startswith((" ", "\t")):
            prev = data.get(key)
            if prev is None or isinstance(prev, str):
                data[key] = ((prev + "\n") if prev else "") + line.strip()
    return data


def split_card(text):
    """(front matter dict, body text, body first line number)."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_text = "\n".join(lines[1:i])
                try:
                    import yaml  # optional, better fidelity when present
                    fm = yaml.safe_load(fm_text) or {}
                    if not isinstance(fm, dict):
                        fm = parse_front_matter_text(fm_text)
                except Exception:
                    fm = parse_front_matter_text(fm_text)
                return fm, "\n".join(lines[i + 1:]), i + 2
    return {}, text, 1


PARAM_RE = re.compile(
    r"(?i)(?<![\w])(?:--)?(temperature|temp|top[_ -]?p|top[_ -]?k|min[_ -]?p|presence[_ -]?penalty|"
    r"repetition[_ -]?penalty|repeat[_ -]?penalty|frequency[_ -]?penalty)\b[`*\"']*\s*(?:=|:|\s)\s*[`*\"']*(-?\d+(?:\.\d+)?)(?![\d.]*%)")
PARAM_NAMES = {"temperature": "temp", "temp": "temp", "topp": "top-p", "topk": "top-k", "minp": "min-p",
               "presencepenalty": "presence-penalty", "repetitionpenalty": "repeat-penalty",
               "repeatpenalty": "repeat-penalty", "frequencypenalty": "frequency-penalty"}
CMD_RE = re.compile(r"^(?:\S*/)?(llama-server|llama-cli|llama-mtmd-cli|llama-run|llama-embedding|"
                    r"llama-simple|main|server|ollama|vllm|hf|huggingface-cli|sglang|python3?)\b")
NOTE_RE = re.compile(r"(?i)(enable_thinking|/no_think|/think\b|thinking mode|non-thinking|reasoning[ _-]budget|"
                     r"--reasoning|--jinja|chat[ _-]template|system prompt|context length|yarn|rope[ _-]scaling|"
                     r"stop token|presence[_ ]penalty|do not use greedy|greedy decoding)")


def _norm_param(name):
    return PARAM_NAMES.get(re.sub(r"[_ -]", "", name.lower()))


def _num(s):
    return int(s) if re.fullmatch(r"-?\d+", s) else float(s)


def _mode_of(text):
    t = text.lower()
    if re.search(r"non[- ]?thinking|no[_ -]think|instruct(ion)? mode|enable_thinking\s*=\s*false", t):
        return "non-thinking"
    if re.search(r"\bthinking\b|reasoning mode|enable_thinking\s*=\s*true", t):
        return "thinking"
    return None


BENCH_RE = re.compile(r"(?i)experimental setting|benchmark|evaluat|were used|we used|adopted|leaderboard|for reproduc")
DEFAULT_MODE_RE = re.compile(r"(?i)(?:operates?|runs?|works?) in (non-thinking|thinking|instruct|reasoning) mode by default|"
                             r"defaults? to (non-thinking|thinking|instruct|reasoning) mode|"
                             r"(non-thinking|thinking) mode is (?:the )?default|"
                             r"(thinking) mode is enabled by default|"
                             r"by default,? [^.]{0,40}?has (thinking) capabilities enabled")
RECOMMEND_RE = re.compile(r"(?i)recommend|suggest|best practice|generation (?:parameters|settings)|sampling (?:parameters|settings)|"
                          r"推奨|おすすめ|推荐|建议")
CTX_RE = re.compile(r"(?i)context (?:length|window)\W{0,6}(?:full\s+|of\s+|up to\s+)?(\d[\d,]*(?:\.\d+)?)\s*([km])?\b")


def _clean_label(t):
    t = re.sub(r"[`*_>#|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -:;,.()")
    return t[:160]


def _card_ctx(lines, first_line, src):
    for i, line in enumerate(lines):
        m = CTX_RE.search(line)
        if m:
            v = float(m.group(1).replace(",", ""))
            if m.group(2):
                v *= 1024 if m.group(2).lower() == "k" else 1024 * 1024
            if v >= 256:
                return int(v), "%s:L%d" % (src, first_line + i)
    return None, None


def scan_card_body(body, first_line, src="README.md"):
    """Everything the card body states, without interpretation:
    sets      sampling parameter sets, one per labelled line / list / code example:
              {label, kind: recommended|example|benchmark|mention, mode, params, source, conflicts}
    commands  llama.cpp / vllm / hf command lines from code blocks
    notes     lines about thinking modes, templates, context, penalties
    ctx       (context length the card states, source)
    default_mode  (mode the card says is the default, source)"""
    lines = body.splitlines()
    sets, commands, notes = [], [], []
    heading, prose, in_code, code_buf, code_start = "", "", False, [], 0
    cur, cur_last = None, -10
    for i, line in enumerate(lines):
        ln = first_line + i
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                commands.extend(_commands_in_block(code_buf, code_start, src))
                code_buf = []
            else:
                code_start = ln + 1
            in_code = not in_code
            cur = None
            continue
        if in_code:
            code_buf.append(line)
        found = [(m.start(), _norm_param(m.group(1)), _num(m.group(2))) for m in PARAM_RE.finditer(line) if _norm_param(m.group(1))]
        if found:
            prefix = _clean_label(line[:found[0][0]])
            labelled = len(re.findall(r"[^\W\d_]", prefix)) >= 3 and not in_code
            gap = 4 if in_code else 1
            if cur is None or labelled or i - cur_last > gap:
                label = prefix if labelled else (_clean_label(prose) or _clean_label(heading) or "unlabelled")
                ctx = " ".join([heading, prose, label])
                if BENCH_RE.search(label) or BENCH_RE.search(line):
                    kind = "benchmark"
                elif in_code and not RECOMMEND_RE.search(label):
                    kind = "example"
                else:
                    kind = "recommended"
                cur = {"label": label, "kind": kind, "mode": _mode_of(label) or _mode_of(line) or _mode_of(heading),
                       "params": {}, "source": "%s:L%d" % (src, ln)}
                sets.append(cur)
            for _, p, v in found:
                if p in cur["params"] and cur["params"][p] != v:
                    cur.setdefault("conflicts", []).append({"param": p, "also": v, "source": "%s:L%d" % (src, ln)})
                else:
                    cur["params"].setdefault(p, v)
            cur_last = i
        elif s and not in_code:
            if s.startswith("#"):
                heading, prose = s, ""
            elif len(re.findall(r"[A-Za-z]", s)) >= 3 and not s.startswith("|") and not s.startswith("<"):
                prose = s
            if i - cur_last > 1:
                cur = None
        if not in_code and NOTE_RE.search(s) and len(notes) < 20:
            notes.append({"text": s[:300], "source": "%s:L%d" % (src, ln)})
    for x in sets:   # one value in passing ("temperature 0" in an example answer) is not a recommended set
        if x["kind"] == "recommended" and len(x["params"]) < 2:
            x["kind"] = "mention"
    ctx, ctx_src = _card_ctx(lines, first_line, src)
    dm, dm_src = None, None
    for i, line in enumerate(lines):
        m = DEFAULT_MODE_RE.search(line)
        if m:
            w = next(g for g in m.groups() if g).lower()
            dm, dm_src = {"instruct": "non-thinking", "reasoning": "thinking"}.get(w, w), "%s:L%d" % (src, first_line + i)
            break
    return {"sets": sets, "commands": commands[:20], "notes": notes, "ctx": ctx, "ctx_source": ctx_src,
            "default_mode": dm, "default_mode_source": dm_src}


GEN_KEYS = (("temperature", "temp"), ("top_p", "top-p"), ("top_k", "top-k"), ("min_p", "min-p"),
            ("repetition_penalty", "repeat-penalty"), ("presence_penalty", "presence-penalty"))


def gen_config_params(gen):
    out = {}
    if not isinstance(gen, dict) or gen.get("do_sample") is False:
        return out
    for gk, p in GEN_KEYS:
        v = gen.get(gk)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[p] = v
    return out


def choose_card_defaults(scans, gens):
    """scans: [(label, scan)] strongest card first (base model card, then the GGUF repo
    card); gens: [(label, generation_config dict)]. Returns
    (defaults, sources, default_set_label, modes, how) without inventing values:
      1. the card's recommended sets: one set -> it; several -> those of the mode the
         card calls the default, then the text/general one of those; still several -> none
      2. else generation_config.json sampling values
      3. else a single distinct code-example set (flagged as an example)."""
    for label, sc in scans:
        rec, seen = [], set()
        for x in sc["sets"]:      # cards often repeat their table further down: keep the first
            key = json.dumps(x["params"], sort_keys=True)
            if x["kind"] == "recommended" and x["params"] and key not in seen:
                seen.add(key)
                rec.append(x)
        if not rec:
            continue
        modes = {x["label"]: x["params"] for x in rec}
        pick = rec
        how = "the card's only recommended set"
        dm = [x for x in pick if sc.get("default_mode") and x.get("mode") == sc["default_mode"]]
        if len(pick) > 1 and dm:
            pick = dm
            how = "recommended set for the card's default mode (%s, %s)" % (sc["default_mode"], sc.get("default_mode_source"))
        if len(pick) > 1:
            tx = [x for x in pick if re.search(r"(?i)\btext\b|\bgeneral\b", x["label"])]
            if len(tx) == 1:
                pick, how = tx, how + ", text/general task set"
        if len(pick) > 1:      # the repo's generation_config.json is the default the card's authors ship
            for glabel, gen in gens:
                gp = gen_config_params(gen)
                hit = [x for x in pick if gp and all(x["params"].get(k) == v for k, v in gp.items())]
                if len(hit) == 1:
                    pick, how = hit, "recommended set matching %s generation_config.json" % glabel
                    break
        if len(pick) == 1:
            x = pick[0]
            return dict(x["params"]), {k: "%s %s" % (label, x["source"]) for k in x["params"]}, x["label"], modes, how
        return None, {}, None, modes, "ambiguous: %d recommended sets and no single default" % len(rec)
    for label, gen in gens:
        gp = gen_config_params(gen)
        if gp:
            return gp, {k: "%s generation_config.json" % label for k in gp}, "generation_config.json", None, "generation_config.json"
    for label, sc in scans:
        ex = [x for x in sc["sets"] if x["kind"] == "example" and x["params"]]
        uniq = {json.dumps(x["params"], sort_keys=True): x for x in ex}
        if len(uniq) == 1:
            x = next(iter(uniq.values()))
            return dict(x["params"]), {k: "%s %s (code example)" % (label, x["source"]) for k in x["params"]}, \
                "example: " + x["label"], None, "the card's only code example with sampling values"
    return None, {}, None, None, "the card and generation_config.json state no sampling values"


def _commands_in_block(buf, start, src):
    out, cur, cur_ln = [], "", None
    for j, raw in enumerate(buf):
        s = raw.strip()
        if s.startswith(("$ ", "> ")):
            s = s[2:]
        if not cur:
            if not s or s.startswith("#"):
                continue
            cur_ln = start + j
        cur += (" " if cur else "") + s.rstrip("\\").strip()
        if s.endswith("\\"):
            continue
        m = CMD_RE.match(cur)
        if m and (m.group(1) != "python3" and m.group(1) != "python" or "llama" in cur or "vllm" in cur):
            tool = m.group(1)
            if tool not in ("main", "server") or "-m " in cur or "--model" in cur:
                out.append({"tool": tool, "command": cur[:1000], "source": "%s:L%d" % (src, cur_ln)})
        cur = ""
    return out


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log("warning: cannot read %s: %s" % (path, e))
        return None


# ---------------------------------------------------------------- environment
class Env:
    def __init__(self, bootstraps=None, manifest=None, preset=None):
        self.bootstraps = os.path.abspath(bootstraps or os.environ.get("CODE_BOOTSTRAPS")
                                          or os.path.join(REPO_ROOT, "code-bootstraps-llama.cpp"))
        self.manifest = os.path.abspath(manifest or os.path.join(self.bootstraps, "config", "models-manifest.json"))
        self.preset = os.path.abspath(preset or os.path.join(self.bootstraps, "config", "models-preset.ini"))
        self.data = None
        if os.path.isfile(self.manifest):
            with open(self.manifest, encoding="utf-8") as f:
                self.raw = f.read()
            self.data = json.loads(self.raw)

    def roles(self):
        r = list(BASE_ROLES)
        for c in (self.data or {}).get("candidates", []):
            if c.get("role") and c["role"] not in r:
                r.append(c["role"])
        for sec in preset_sections(self.preset):
            if sec != "*" and not sec.startswith("locale.") and sec not in r:
                r.append(sec)
        return r


def preset_sections(path):
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\[([^\]]+)\]\s*$", line.strip())
            if m:
                out.append(m.group(1))
    return out


# ---------------------------------------------------------------- sources
def hf_snapshot_info(d):
    """(repo, revision, {file: lfs sha256}, source) from HF cache layouts, if any."""
    p = os.path.realpath(d)
    m = re.search(r"[/\\]models--([^/\\]+?)--([^/\\]+)[/\\]snapshots[/\\]([0-9a-f]{40})(?:[/\\]|$)", p + os.sep)
    oids = {}
    if m:
        return m.group(1) + "/" + m.group(2), m.group(3), oids, "HF hub cache path (%s)" % p
    sj = os.path.join(d, "snapshot.json")      # scripts/hf_fetch.py layout: hf-meta/ORG--NAME/REV/
    if os.path.isfile(sj):
        try:
            with open(sj, encoding="utf-8") as f:
                snap = json.load(f)
            oids = {k: v["sha256"] for k, v in snap.get("files", {}).items() if v.get("sha256")}
            return snap.get("repo"), snap.get("revision"), oids, "hf-meta snapshot.json"
        except (OSError, ValueError):
            pass
    md = os.path.join(d, ".cache", "huggingface", "download")
    rev = None
    if os.path.isdir(md):
        for root, _, files in os.walk(md):
            for fn in files:
                if not fn.endswith(".metadata"):
                    continue
                try:
                    with open(os.path.join(root, fn), encoding="utf-8") as f:
                        ls = f.read().split("\n")
                except OSError:
                    continue
                rel = os.path.relpath(os.path.join(root, fn[:-len(".metadata")]), md)
                if ls and re.fullmatch(r"[0-9a-f]{40}", ls[0].strip()):
                    rev = rev or ls[0].strip()
                if len(ls) > 1 and re.fullmatch(r"[0-9a-f]{64}", ls[1].strip()):
                    oids[rel] = ls[1].strip()
        if rev:
            return None, rev, oids, ".cache/huggingface/download/*.metadata"
    return None, None, oids, None


def classify_gguf_name(fn):
    n = fn.lower()
    if "mmproj" in n or "vision-proj" in n or n.startswith("clip"):
        return "mmproj"
    if re.search(r"(^|[-_.])(draft|dflash|eagle\d*)([-_.]|$)", n):
        return "draft"
    if re.search(r"(^|[-_.])mtp([-_.]|$)", n):
        return "mtp"
    if "vocoder" in n or "wavtokenizer" in n:
        return "vocoder"
    if "lora" in n:
        return "lora"
    return None


SPLIT_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$")


def ggufs_in(d):
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith(".gguf") and os.path.isfile(os.path.join(d, fn)):
            out.append(fn)
    for sub in sorted(os.listdir(d)):    # snapshots often keep quants in sub-folders (Q4_K_M/...)
        sp = os.path.join(d, sub)
        if os.path.isdir(sp) and not sub.startswith("."):
            for fn in sorted(os.listdir(sp)):
                if fn.lower().endswith(".gguf") and os.path.isfile(os.path.join(sp, fn)):
                    out.append(os.path.join(sub, fn))
    return out


def quant_of(fn):
    m = QUANT_RE.search(os.path.basename(fn))
    return m.group(2).upper() if m else None


# ---------------------------------------------------------------- role inference
class Evidence:
    def __init__(self):
        self.items = []

    def add(self, role, weight, source, why, generic=False):
        self.items.append({"role": role, "weight": weight, "source": source, "why": why, "generic": generic})

    def decide(self, roles):
        """Sum the weights per role. Generic "it is a chat model" hints count once in
        total, so a plain card + config + GGUF does not outvote one specific signal."""
        score, generic = {}, set()
        for e in self.items:
            if e["generic"]:
                if e["role"] in generic:
                    continue
                generic.add(e["role"])
            score[e["role"]] = score.get(e["role"], 0) + e["weight"]
        ranked = sorted(score.items(), key=lambda kv: -kv[1])
        known = [(r, s) for r, s in ranked if r in roles]
        if not known:
            return None, ranked
        if len(known) > 1 and known[0][1] == known[1][1]:
            return None, ranked
        return known[0][0], ranked


def infer_from_card(ev, fm, title):
    pt = str(fm.get("pipeline_tag") or "").lower()
    tags = fm.get("tags") or []
    tags = [str(t).lower() for t in (tags if isinstance(tags, list) else [tags])]
    lib = str(fm.get("library_name") or "").lower()
    base = fm.get("base_model")
    base = " ".join(map(str, base)) if isinstance(base, list) else str(base or "")
    src = "card front matter"
    if pt in ("feature-extraction", "sentence-similarity"):
        ev.add("embed", 5, src, "pipeline_tag: %s" % pt)
    elif pt == "text-ranking":
        ev.add("reranker", 5, src, "pipeline_tag: text-ranking")
    elif pt == "translation":
        ev.add("language", 5, src, "pipeline_tag: translation")
    elif pt in ("text-classification", "zero-shot-classification"):
        ev.add("decision", 3, src, "pipeline_tag: %s" % pt)
    elif pt in ("text-generation", "image-text-to-text", "text2text-generation", "any-to-any"):
        ev.add("general", 1, src, "pipeline_tag: %s (generic chat model)" % pt, generic=True)
    if lib == "sentence-transformers" or any(t in ("sentence-transformers", "embedding", "embeddings", "text-embedding") for t in tags):
        ev.add("embed", 5, src, "library_name/tags say sentence-transformers/embedding")
    if any("rerank" in t for t in tags):
        ev.add("reranker", 5, src, "tags mention rerank")
    if any(t.startswith("decision") or t in ("router", "routing", "jev", "systemone") for t in tags):
        ev.add("decision", 5, src, "tags: %s" % ", ".join(t for t in tags if t.startswith("decision") or t in ("router", "routing", "jev", "systemone")))
    codey = [t for t in tags if re.search(r"(^|-)(code|coder|coding)(-|$)", t)]
    if codey:
        ev.add("coder", 5, src, "tags: %s" % ", ".join(codey))
    if re.search(r"(?i)coder", base):
        ev.add("coder", 4, src, "base_model %s" % base)
    if title and re.search(r"(?i)\bcoder\b", title):
        ev.add("coder", 4, "card title", title)
    if title and re.search(r"(?i)\bembed(ding)?\b", title):
        ev.add("embed", 4, "card title", title)
    if any(t == "translation" for t in tags):
        ev.add("language", 4, src, "tags: translation")


def infer_from_config(ev, cfg, have_decision_cfg):
    archs = cfg.get("architectures") or []
    mt = str(cfg.get("model_type") or "")
    src = "config.json"
    if have_decision_cfg:
        ev.add("decision", 4, "decision_config.json", "repo ships a decision head config")
    for a in archs:
        if a.endswith("ForCausalLM") or a.endswith("ForConditionalGeneration"):
            ev.add("general", 1, src, "architectures: %s (generative)" % a, generic=True)
        elif a.endswith("ForSequenceClassification"):
            ev.add("decision", 2, src, "architectures: %s" % a)
        elif re.search(r"(?i)embed|bert|Model$", a):
            ev.add("embed", 2, src, "architectures: %s (encoder)" % a)
    if re.search(r"(?i)coder", str(cfg.get("_name_or_path") or "")):
        ev.add("coder", 3, src, "_name_or_path %s" % cfg.get("_name_or_path"))
    if mt and re.search(r"(?i)embedding", mt):
        ev.add("embed", 3, src, "model_type %s" % mt)


def infer_from_gguf(ev, meta, fn):
    arch = meta.get("general.architecture")
    src = "GGUF metadata"
    if any(k.startswith("decision.") for k in meta):
        ev.add("decision", 5, src, "decision.* keys present")
    if arch and "%s.pooling_type" % arch in meta:
        ev.add("embed", 3, src, "%s.pooling_type = %s" % (arch, meta["%s.pooling_type" % arch]))
    if arch in EMBED_ARCHS:
        ev.add("embed", 2, src, "general.architecture %s (encoder)" % arch)
    name = " ".join(str(meta.get(k) or "") for k in ("general.name", "general.basename", "general.finetune"))
    if re.search(r"(?i)coder", name):
        ev.add("coder", 3, src, "general.name %s" % name.strip())
    if re.search(r"(?i)embed", name):
        ev.add("embed", 3, src, "general.name %s" % name.strip())
    tags = meta.get("general.tags")
    if isinstance(tags, list):
        tl = [t.lower() for t in tags]
        if any(t in ("embedding", "sentence-transformers", "feature-extraction") for t in tl):
            ev.add("embed", 3, src, "general.tags")
        if any(re.search(r"(^|-)(code|coder)(-|$)", t) for t in tl):
            ev.add("coder", 3, src, "general.tags")
    if arch and arch not in EMBED_ARCHS and "%s.pooling_type" % arch not in meta and not any(k.startswith("decision.") for k in meta):
        ev.add("general", 1, src, "general.architecture %s (generative)" % arch, generic=True)


def infer_from_filename(ev, fn):
    n = os.path.basename(fn).lower()
    if re.search(r"embed", n):
        ev.add("embed", 2, "filename", n)
    if re.search(r"rerank", n):
        ev.add("reranker", 2, "filename", n)
    if re.search(r"coder|(^|[-_])code([-_]|$)", n):
        ev.add("coder", 2, "filename", n)


def infer_from_layout(ev, path, roles):
    parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
    if parent in roles:
        ev.add(parent, 3, "directory layout", "file sits in models/%s/" % parent)


def manifest_matches(env, file, sha):
    out = []
    for i, c in enumerate((env.data or {}).get("candidates", [])):
        if sha and c.get("sha256") == sha:
            out.append((i, c))
        elif not sha and c.get("file") == file:
            out.append((i, c))
    return out


# ---------------------------------------------------------------- building the entry
def first(*vals):
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return None


def build(args, env, interactive):
    """Return (entry, report, preset_model_path)."""
    report = {"inferred": [], "unknown": [], "warnings": []}
    d = args.dir
    files = {}                               # card-file name -> path
    if d:
        for fn in CARD_FILES:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                files[fn] = p
    for flag, fn in (("card", "README.md"), ("config", "config.json"), ("generation_config", "generation_config.json"),
                     ("tokenizer_config", "tokenizer_config.json"), ("chat_template", "chat_template.jinja"),
                     ("license_file", "LICENSE")):
        v = getattr(args, flag, None)
        if v:
            if not os.path.isfile(v):
                raise UsageError("--%s %s: file not found" % (flag.replace("_", "-"), v))
            files[fn] = os.path.abspath(v)

    # ---- choose the main GGUF and the aux files found in the directory
    aux = []
    main = None
    if args.file and os.path.isfile(args.file):
        main = os.path.abspath(args.file)
    elif d:
        found = ggufs_in(d)
        if not args.file and getattr(args, "_fetch_main", None):
            args.file = args._fetch_main
        if args.file:
            sel = [f for f in found if f == args.file or os.path.basename(f) == args.file]
            if not sel:
                raise UsageError("--file %s is not in %s (GGUFs there: %s)" % (args.file, d, ", ".join(found) or "none"))
            mains = sel
        else:
            mains = [f for f in found if not classify_gguf_name(f)]
        for f in found:
            k = classify_gguf_name(f)
            if k and f not in mains:
                aux.append({"kind": k, "path": os.path.join(d, f), "source": "detected in directory (filename)"})
        if args.quant and not args.file:
            mains = [f for f in mains if (quant_of(f) or "").upper() == args.quant.upper()]
        # split GGUFs: keep the first part, record the rest as parts
        groups = {}
        for f in mains:
            m = SPLIT_RE.match(os.path.basename(f))
            key = os.path.join(os.path.dirname(f), m.group(1)) if m else f
            groups.setdefault(key, []).append(f)
        if not groups:
            raise UsageError("no main .gguf in %s%s. This tool registers GGUF models for llama.cpp; "
                             "fetch the -GGUF repo or pass --file." % (d, " for --quant %s" % args.quant if args.quant else ""))
        if len(groups) > 1:
            names = sorted(groups)
            if interactive:
                for i, n in enumerate(names, 1):
                    log("  %d) %s" % (i, n))
                ans = input("Several GGUFs in %s; which one is the main model? [1-%d] " % (d, len(names))).strip()
                if not ans.isdigit() or not 1 <= int(ans) <= len(names):
                    raise UsageError("no GGUF chosen")
                key = names[int(ans) - 1]
            else:
                raise UsageError("several main GGUFs in %s: %s. Choose one with --file NAME or --quant QUANT."
                                 % (d, ", ".join(names)))
        else:
            key = next(iter(groups))
        parts = sorted(groups[key])
        main = os.path.join(d, parts[0])
        args._parts = [os.path.join(d, p) for p in parts] if len(parts) > 1 else []
    elif args.file:
        raise UsageError("--file %s: file not found (give a path, or a name inside DIR)" % args.file)
    else:
        raise UsageError("nothing to add: give DIR, FILE.gguf, ROLE FILE.gguf or --file")
    parts = getattr(args, "_parts", [])

    for spec in args.aux or []:
        if "=" not in spec:
            raise UsageError("--aux needs KIND=PATH, got %r" % spec)
        k, p = spec.split("=", 1)
        if k not in AUX_KINDS:
            raise UsageError("--aux kind %r is not one of %s" % (k, ", ".join(AUX_KINDS)))
        if not os.path.isfile(p):
            raise UsageError("--aux %s: file not found" % spec)
        p = os.path.abspath(p)
        aux = [a for a in aux if os.path.abspath(a["path"]) != p]
        aux.append({"kind": k, "path": p, "source": "--aux"})

    # ---- read everything
    meta = {}
    try:
        meta = gguf_header(main)
    except Exception as e:
        report["warnings"].append("GGUF header of %s unreadable: %s" % (main, e))
    fm, body, body_ln, title = {}, "", 1, None
    if "README.md" in files:
        with open(files["README.md"], encoding="utf-8", errors="replace") as f:
            fm, body, body_ln = split_card(f.read())
        m = re.search(r"(?m)^#\s+(.+)$", body)
        title = m.group(1).strip() if m else None
    cfg = read_json(files["config.json"]) if "config.json" in files else None
    gen = read_json(files["generation_config.json"]) if "generation_config.json" in files else None
    tok = read_json(files["tokenizer_config.json"]) if "tokenizer_config.json" in files else None
    cfg, gen, tok = cfg or {}, gen or {}, tok or {}
    text_cfg = cfg.get("text_config") if isinstance(cfg.get("text_config"), dict) else {}

    log("hashing %s ..." % os.path.basename(main))
    sha = sha256_file(main, progress=True)
    size = os.path.getsize(main)
    fname = os.path.basename(main)

    # ---- repo / revision
    hf_repo, hf_rev, oids, hf_src = hf_snapshot_info(d) if d else (None, None, {}, None)
    matches = manifest_matches(env, fname, sha)
    m_entry = matches[0][1] if matches else {}
    repo = first(args.repo, hf_repo, m_entry.get("repo"))
    revision = first(args.revision, hf_rev, m_entry.get("revision"))
    for name, val, srcs in (("repo", repo, [("--repo", args.repo), (hf_src, hf_repo), ("existing manifest entry", m_entry.get("repo"))]),
                            ("revision", revision, [("--revision", args.revision), (hf_src, hf_rev), ("existing manifest entry", m_entry.get("revision"))])):
        src = next((s for s, v in srcs if v), None)
        if val:
            report["inferred"].append("%s = %s (from %s)" % (name, val, src))
        else:
            report["unknown"].append(name)
    rel_main = os.path.relpath(main, d) if d else fname
    if rel_main in oids:
        report["inferred"].append("sha256 %s HF LFS oid in .cache/huggingface" % ("matches" if oids[rel_main] == sha else "DIFFERS FROM"))
        if oids[rel_main] != sha:
            report["warnings"].append("sha256 of %s differs from the HF LFS oid %s" % (fname, oids[rel_main]))

    # ---- role
    roles = env.roles()
    ev = Evidence()
    explicit = args.role
    if explicit:
        role, ranked = explicit, []
        report["inferred"].append("role = %s (given with --role/--type)" % role)
    else:
        infer_from_card(ev, fm, title)
        infer_from_config(ev, cfg, "decision_config.json" in files)
        if meta:
            infer_from_gguf(ev, meta, fname)
        infer_from_filename(ev, fname)
        infer_from_layout(ev, main, roles)
        mroles = sorted({c.get("role") for _, c in matches if c.get("role")})
        for r in mroles:
            ev.add(r, 6 if len(mroles) == 1 else 2, "existing manifest entry",
                   "same %s already registered as role %s" % ("sha256" if sha else "file", r))
        role, ranked = ev.decide(roles)
        for e in ev.items:
            log("  evidence: %-9s +%d%s  %s: %s" % (e["role"], e["weight"], " (generic, counted once)" if e["generic"] else "",
                                                  e["source"], e["why"]))
        if role is None:
            why = ("candidates " + ", ".join("%s=%d" % kv for kv in ranked)) if ranked else "no evidence"
            if interactive:
                log("role is ambiguous (%s); known roles: %s" % (why, ", ".join(roles)))
                ans = input("Role for %s: " % fname).strip()
                if not ans:
                    raise UsageError("no role chosen")
                role = ans
                report["inferred"].append("role = %s (chosen interactively; %s)" % (role, why))
            else:
                raise UsageError("cannot infer the role of %s (%s). Pass --role ROLE (known roles: %s)."
                                 % (fname, why, ", ".join(roles)))
        else:
            top = [e for e in ev.items if e["role"] == role]
            report["inferred"].append("role = %s (score %d: %s)" % (role, dict(ranked)[role],
                                      "; ".join("%s: %s" % (e["source"], e["why"]) for e in top)))
    if role not in roles:
        report["warnings"].append("role %r is new: no manifest entry or preset section has it yet" % role)

    # ---- facts
    arch = meta.get("general.architecture")
    quant, qsrc = quant_of(fname), "filename"
    if not quant and isinstance(meta.get("general.file_type"), int):
        quant, qsrc = FTYPES.get(meta["general.file_type"]), "GGUF general.file_type"
    if not quant:
        quant, qsrc = "unknown", None
    lic, lsrc = None, None
    for v, s in ((args.license, "--license"), (fm.get("license_name") if fm.get("license") == "other" else None, "card license_name"),
                 (fm.get("license"), "card front matter"), (meta.get("general.license"), "GGUF general.license"),
                 (m_entry.get("license"), "existing manifest entry")):
        if v:
            lic, lsrc = str(v), s
            break
    if lic and fm.get("license_link") and lsrc == "card license_name":
        lic += " (%s)" % fm["license_link"]
    if not lic and any(k.startswith("LICENSE") for k in files):
        lic, lsrc = "see %s (not identified)" % next(k for k in files if k.startswith("LICENSE")), "license file"
    ctx, csrc = None, None
    for v, s in ((args.ctx, "--ctx"), (meta.get("%s.context_length" % arch) if arch else None, "GGUF %s.context_length" % arch),
                 (cfg.get("max_position_embeddings"), "config.json max_position_embeddings"),
                 (text_cfg.get("max_position_embeddings"), "config.json text_config.max_position_embeddings")):
        if isinstance(v, int) and v > 0:
            ctx, csrc = v, s
            break
    base_model = first(fm.get("base_model"), meta.get("general.base_model.0.repo_url"), meta.get("general.base_model.0.name"))
    rope = {}
    if arch:
        for k in ("rope.scaling.type", "rope.scaling.factor", "rope.scaling.original_context_length", "rope.freq_base"):
            if "%s.%s" % (arch, k) in meta:
                rope[k] = meta["%s.%s" % (arch, k)]
        if rope:
            rope["source"] = "GGUF metadata"
    rs = cfg.get("rope_scaling") or text_cfg.get("rope_scaling") or cfg.get("rope_parameters") or text_cfg.get("rope_parameters")
    if isinstance(rs, dict):
        rope["config"] = rs
        rope.setdefault("source", "config.json")

    # ---- sampling + commands from the card and generation_config
    sc = scan_card_body(body, body_ln) if body else scan_card_body("", 1)
    commands, notes = sc["commands"], sc["notes"]
    defaults, dsrc, dset, modes, dhow = choose_card_defaults([("", sc)] if body else [], [("", gen)])
    dsrc = {k: v.strip() for k, v in dsrc.items()}
    if gen and gen.get("do_sample") is False:
        notes.append({"text": "generation_config.json: do_sample=false (greedy)", "source": "generation_config.json"})
    conflicts = [dict(c, set=x["label"]) for x in sc["sets"] for c in x.get("conflicts", [])]

    tmpl = {}
    gt = meta.get("tokenizer.chat_template")
    if isinstance(gt, str):
        tmpl["gguf_sha256"] = hashlib.sha256(gt.encode("utf-8")).hexdigest()
    for fn in ("chat_template.jinja",):
        if fn in files:
            with open(files[fn], "rb") as f:
                tmpl["repo_file"], tmpl["repo_sha256"] = fn, hashlib.sha256(f.read()).hexdigest()
    if "repo_file" not in tmpl and isinstance(tok.get("chat_template"), str):
        tmpl["repo_file"], tmpl["repo_sha256"] = "tokenizer_config.json:chat_template", hashlib.sha256(tok["chat_template"].encode("utf-8")).hexdigest()
    if "gguf_sha256" in tmpl and "repo_sha256" in tmpl:
        tmpl["same"] = tmpl["gguf_sha256"] == tmpl["repo_sha256"]
    stop = {}
    eos = tok.get("eos_token")
    if isinstance(eos, dict):
        eos = eos.get("content")
    if eos:
        stop["eos_token"], stop["eos_token_source"] = eos, "tokenizer_config.json"
    if gen.get("eos_token_id") is not None:
        stop["eos_token_id"], stop["eos_token_id_source"] = gen["eos_token_id"], "generation_config.json"
    elif isinstance(meta.get("tokenizer.ggml.eos_token_id"), int):
        stop["eos_token_id"], stop["eos_token_id_source"] = meta["tokenizer.ggml.eos_token_id"], "GGUF tokenizer.ggml.eos_token_id"

    # draft models referenced on the card
    for c in commands:
        for mm in re.finditer(r"(?:-md|--model-draft)\s+(\S+\.gguf)", c["command"]):
            ref = mm.group(1)
            local = os.path.join(d, os.path.basename(ref)) if d else None
            if not any(os.path.basename(a["path"] or "") == os.path.basename(ref) for a in aux):
                aux.append({"kind": "draft", "path": local if local and os.path.isfile(local) else None,
                            "ref": ref, "source": c["source"]})
        for mm in re.finditer(r"(?:-hfd|-hfrd|--hf-repo-draft)\s+(\S+)", c["command"]):
            aux.append({"kind": "draft", "path": None, "ref": mm.group(1), "source": c["source"]})

    aux_out = []
    for a in aux:
        rec = {"kind": a["kind"], "file": os.path.basename(a["path"]) if a.get("path") else None}
        if a.get("ref"):
            rec["ref"] = a["ref"]
        if a.get("path"):
            rec["bytes"] = os.path.getsize(a["path"])
            if a["path"].lower().endswith(".gguf"):
                rec["quant"] = quant_of(a["path"]) or "unknown"
                try:
                    am = gguf_header(a["path"])
                    rec["arch"] = am.get("general.architecture")
                except Exception as e:
                    report["warnings"].append("aux %s: GGUF header unreadable: %s" % (a["path"], e))
            log("hashing aux %s ..." % rec["file"])
            rec["sha256"] = sha256_file(a["path"], progress=True)
        else:
            report["unknown"].append("aux %s %s: not on disk" % (a["kind"], a.get("ref")))
        rec["source"] = a["source"]
        rec["linked_to"] = fname
        aux_out.append(rec)

    file_shas = {}
    for fn, p in sorted(files.items()):
        with open(p, "rb") as f:
            file_shas[fn] = hashlib.sha256(f.read()).hexdigest()

    entry = {"role": role, "pick": first(args.pick, m_entry.get("pick"), "local"), "repo": repo, "revision": revision,
             "file": fname, "quant": quant, "bytes": size, "sha256": sha, "license": lic or "unknown", "ctx": ctx,
             "tested": m_entry.get("tested", False)}
    if args.dir_field:
        entry["dir"] = args.dir_field
    if arch:
        entry["arch"] = arch
    if base_model:
        entry["base_model"] = base_model
    if parts:
        entry["parts"] = [{"file": os.path.basename(p), "bytes": os.path.getsize(p), "sha256": sha256_file(p) if p != main else sha} for p in parts]
    entry["card_defaults"] = defaults or None
    entry["card_default_set"] = dset
    if modes:
        entry["card_sampling_modes"] = modes
    entry["card_defaults_source"] = dsrc or None
    if sc["ctx"]:
        entry["card_ctx"], entry["card_ctx_source"] = sc["ctx"], sc["ctx_source"]
    if sc["default_mode"]:
        entry["card_default_mode"] = sc["default_mode"]
    entry["card_commands"] = commands or None
    if notes:
        entry["card_notes"] = notes[:20]
    if conflicts:
        report["warnings"].append("card gives conflicting values: %s" % "; ".join(
            "%s: %s also %s (%s)" % (c["set"], c["param"], c["also"], c["source"]) for c in conflicts))
    if tmpl:
        entry["chat_template"] = tmpl
    if stop:
        entry["stop"] = stop
    if rope:
        entry["rope"] = rope
    entry["files"] = file_shas or None
    if aux_out:
        entry["aux"] = aux_out
    entry["inferred"] = {"role": "--role" if explicit else [{"role": e["role"], "weight": e["weight"], "source": e["source"]} for e in ev.items if e["role"] == role],
                         "quant": qsrc, "license": lsrc, "ctx": csrc, "by": "scripts/add_model.py"}
    for k in ("license", "ctx"):
        if entry[k] in (None, "unknown"):
            report["unknown"].append(k)
    if quant == "unknown":
        report["unknown"].append("quant")
    if not files.get("README.md"):
        report["unknown"].append("model card (README.md): no card, so no card defaults/commands")
    elif not defaults:
        report["unknown"].append("card_defaults: %s" % dhow)
    if not files.get("config.json"):
        report["unknown"].append("config.json")
    unknown = [u for u in report["unknown"]]
    entry["unknown"] = unknown or None
    if "note" not in m_entry and args.note:
        entry["note"] = args.note
    return entry, report, main, matches


# ---------------------------------------------------------------- writing
def dump_manifest(data):
    """indent=4 like the existing file; NESTED_KEYS of candidates on one line (manifest.awk)."""
    holders = {}
    def mark(c):
        c2 = {}
        for k, v in c.items():
            if k in NESTED_KEYS and isinstance(v, (dict, list)):
                tok = "@@ADD_MODEL_%d@@" % len(holders)
                holders[tok] = json.dumps(v, ensure_ascii=True, separators=(", ", ": "))
                c2[k] = tok
            else:
                c2[k] = v
        return c2
    d2 = dict(data)
    d2["candidates"] = [mark(c) for c in data.get("candidates", [])]
    out = json.dumps(d2, indent=4, ensure_ascii=True)
    for tok, js in holders.items():
        out = out.replace('"%s"' % tok, js)
    return out


CURATED = ("license", "pick", "tested", "dir", "note", "notice", "parser", "decision_type", "languages", "locale", "roles")
KEEP_NULL = ("repo", "revision", "ctx")


def merge_entry(old, new, warnings):
    """Update in place. Hand-curated fields (license text, pick, tested, note, notice, ...)
    keep their value; a differing card value is reported. Known values are never
    replaced by null/unknown. Changed facts (ctx, sha256, ...) are reported."""
    out = dict(old)
    for k, v in new.items():
        ov = old.get(k)
        if v in (None, "unknown") and ov not in (None, "unknown"):
            continue
        if k in CURATED and ov not in (None, "unknown") and ov != v:
            if k == "license":
                warnings.append("license: card/GGUF says %r, manifest keeps %r" % (v, ov))
                if isinstance(new.get("inferred"), dict):
                    new["inferred"]["license"] = "existing manifest entry (kept; %s says %r)" % (new["inferred"].get("license"), v)
            continue
        if k not in NESTED_KEYS and k != "unknown" and ov is not None and ov != v:
            warnings.append("%s changes %r -> %r" % (k, ov, v))
        out[k] = v
    return {k: v for k, v in out.items() if v is not None or k in KEEP_NULL}


def upsert(data, entry, explicit_role=False, warnings=None):
    """Same repo+file as an existing entry: update it (the one with the same role first).
    A different explicit --role for the same file adds a second entry, like the
    manifest's Qwen3.5-0.8B coder/language-small pair."""
    warnings = [] if warnings is None else warnings
    cands = data.setdefault("candidates", [])
    same = [i for i, c in enumerate(cands) if c.get("file") == entry["file"] and c.get("repo") == entry["repo"]]
    hit = [i for i in same if cands[i].get("role") == entry["role"]]
    if not hit and same and not explicit_role:
        hit = same[:1]
    if hit:
        i = hit[0]
        cands[i] = merge_entry(cands[i], entry, warnings)
        return "updated", i
    cands.append({k: v for k, v in entry.items() if v is not None or k in KEEP_NULL})
    return "added", len(cands) - 1


def preset_get(lines, section):
    out, sec = {}, None
    for line in lines:
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            sec = m.group(1)
            continue
        if sec == section:
            m = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*$", line)
            if m:
                out.setdefault(m.group(1), m.group(2))
    return out


def preset_set(lines, section, kv):
    """Set keys in [section], keeping comments, order and every section header.
    Missing keys go after the section's last key/comment; a missing section is appended."""
    lines = list(lines)
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*\[%s\]\s*$" % re.escape(section), line):
            start = i
            break
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "[%s]" % section, "; added by scripts/add-model.sh", ""]
        start = len(lines) - 3
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*\[[^\]]+\]\s*$", lines[j]):
            end = j
            break
    width = max([len(k) for k in kv] + [0])
    for k, v in kv.items():
        done = False
        for j in range(start + 1, end):
            m = re.match(r"^(\s*)%s(\s*)=" % re.escape(k), lines[j])
            if m:
                lines[j] = "%s%s%s= %s" % (m.group(1), k, m.group(2) or " ", v)
                done = True
                break
        if not done:
            ins = end
            while ins - 1 > start and not lines[ins - 1].strip():
                ins -= 1
            lines.insert(ins, "%s = %s" % (k.ljust(width), v))
            end += 1
    return lines


def preset_model_value(env, main, role=None):
    """models/<role>/FILE when the file sits in a models layout (serve.sh resolves it in
    GGUF_HOME / MODELS_DIR / the checkout); a checkout-relative path inside the
    checkout; otherwise the absolute path."""
    root = env.bootstraps
    p = os.path.abspath(main)
    sub, top = os.path.basename(os.path.dirname(p)), os.path.basename(os.path.dirname(os.path.dirname(p)))
    if role and sub == role and top in ("models", "models-optional", "models-inactive"):
        return "%s/%s/%s" % (top, role, os.path.basename(p))
    try:
        rel = os.path.relpath(p, root)
    except ValueError:
        rel = None
    if rel and not rel.startswith(".."):
        return rel.replace(os.sep, "/")
    return p


def atomic_write(path, text):
    tmp = path + ".add-model.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def choose_mode(entry, preset_kv, args):
    """(label, how) of the card set chosen with --card-set (case-insensitive substring)."""
    modes = entry.get("card_sampling_modes") or {}
    if not args.card_set:
        return None, None
    hits = [l for l in modes if args.card_set.lower() in l.lower()]
    if len(hits) != 1:
        raise UsageError("--card-set %r matches %d of the card's sets: %s" % (args.card_set, len(hits), "; ".join(modes) or "none"))
    return hits[0], "--card-set"


# ---------------------------------------------------------------- fetch
def hf_max(args):
    import hf_fetch as hf
    return hf.max_bytes_of(args)


def fetch(spec, args):
    """--fetch ORG/NAME[@REV]: stdlib HTTPS (scripts/hf_fetch.py, no pip). Fetches every
    small repo file into the shared hf-meta snapshot (pinned to the commit SHA) plus the
    chosen GGUF, verified against its LFS sha256. Returns the snapshot directory."""
    import hf_fetch as hf
    repo, _, rev = spec.partition("@")
    try:
        info = hf.repo_info(repo, rev or "main")
    except hf.HFError as e:
        raise UsageError("--fetch %s: %s" % (spec, e))
    sha = info["sha"]
    ggufs = [s for s in info.get("siblings", []) if s["rfilename"].lower().endswith(".gguf")]
    if args.file:
        sel = [s for s in ggufs if s["rfilename"] == args.file or os.path.basename(s["rfilename"]) == os.path.basename(args.file)]
    elif args.quant:
        sel = [s for s in ggufs if not classify_gguf_name(s["rfilename"]) and (quant_of(s["rfilename"]) or "").upper() == args.quant.upper()]
    else:
        sel = [s for s in ggufs if not classify_gguf_name(s["rfilename"])]
    sel = [s for s in sel if not SPLIT_RE.match(os.path.basename(s["rfilename"])) or "-00001-of-" in s["rfilename"]]
    if len(sel) != 1:
        listing = ", ".join("%s (%d MB)" % (s["rfilename"], (s.get("size") or 0) // 1000000) for s in ggufs) or "none"
        raise UsageError("--fetch %s@%s: choose one GGUF with --quant or --file (repo GGUFs: %s)" % (repo, sha[:10], listing))
    main_sib = sel[0]
    root = hf.meta_root()
    d = os.path.join(root, repo.replace("/", "--"), sha)
    mb = hf.max_bytes_of(args)
    log("fetch %s@%s: small files -> %s; %s (%d MB)" % (repo, sha[:10], d, main_sib["rfilename"], (main_sib.get("size") or 0) // 1000000))
    dest = os.path.join(d, main_sib["rfilename"])
    have = os.path.isfile(dest) and os.path.getsize(dest) == main_sib.get("size")
    if args.dry_run:
        info.setdefault("id", repo)
        hf.print_plan(repo, sha, hf.plan_rows(info, (), mb, want=() if have else (main_sib["rfilename"],)), sys.stderr, "dry run: ")
        lic = (info.get("cardData") or {}).get("license")
        log("dry run: card license %s%s; a full run shows the license summary and asks you to accept it before the "
            "%d MB download" % (lic or "not stated in this repo's card", " (gated)" if info.get("gated") else "",
                                (main_sib.get("size") or 0) // 1000000))
        if not have:
            raise SystemExit(0)
    else:
        try:
            hf.snapshot(repo, sha, max_bytes=mb, log=log)
            if not have:
                import model_db, model_license
                e0 = model_db.ingest(repo, sha, main_sib["rfilename"], found_in=["add-model.sh --fetch"], max_bytes=mb, write=False)
                rc = model_license.gate([e0], yes=getattr(args, "accept_licenses", False),
                                        what="download %s (%d MB)" % (main_sib["rfilename"], (main_sib.get("size") or 0) // 1000000))
                if rc != 0:
                    raise UsageError("--fetch %s: license not accepted; %s was not downloaded (--damp-run fetches the metadata only)"
                                     % (spec, main_sib["rfilename"]))
                log("downloading %s ..." % main_sib["rfilename"])
                hf.download(repo, sha, main_sib, dest)
        except hf.HFError as e:
            raise UsageError("--fetch %s: %s" % (spec, e))
    args.repo = args.repo or repo
    args.revision = args.revision or sha
    args.file = None           # the main GGUF is picked inside the snapshot directory
    args._fetched = (repo, sha, main_sib["rfilename"])
    args._fetch_main = main_sib["rfilename"]
    return d


# ---------------------------------------------------------------- CLI
HELP_EPILOG = """\
inputs (pick one):
  DIR                     a Hugging Face snapshot directory: README.md (model card with YAML front
                          matter), config.json, generation_config.json, tokenizer_config.json,
                          chat_template.jinja, LICENSE, *.gguf. HF cache paths
                          (.../models--ORG--NAME/snapshots/REV) and hf --local-dir metadata
                          (.cache/huggingface/download) give the repo id / revision.
  FILE.gguf               a lone GGUF; add --card/--config/... for the repo files you have.
  ROLE FILE.gguf          legacy form (same as FILE.gguf --role ROLE).
  --fetch ORG/NAME[@REV]  download over plain HTTPS (stdlib, HF_TOKEN honoured): every small repo file
                          into $GGUF_HOME/hf-meta/ORG--NAME/REV/ plus the --quant/--file GGUF, all
                          verified against the LFS sha256; also writes registry/models/<id>.json.

role / type:
  optional. Inferred, strongest first, from the card front matter (pipeline_tag, tags,
  library_name, base_model), config.json (architectures, model_type), GGUF metadata
  (decision.* keys, <arch>.pooling_type, general.name), the filename, the models/<role>/
  directory and an existing manifest entry with the same sha256. Every piece of evidence is
  printed. Still ambiguous: asks on a TTY, otherwise exits 2 asking for --role.

auxiliary models:
  --aux KIND=PATH (repeatable; KIND: %s). mmproj-*, *draft*,
  *mtp* GGUFs in DIR and -md/--model-draft/-hfd references in the card's commands are found
  automatically. They are recorded in the entry's "aux" list, linked to the main file.

writes:
  code-bootstraps-llama.cpp/config/models-manifest.json (entry added, or updated in place when
  the same repo+file is already there) and models-preset.ini ([ROLE] model = PATH; with
  --apply-card-defaults also the card's sampling keys). --dry-run prints and writes nothing.

run modes (with --fetch):
  (default)     small repo files, then the license summary; after you accept it (prompt, or
                --accept-licenses / --yes) the GGUF is downloaded and the model registered
  --dry-run     prints every repo file with size, sha and status (present / fetch / skip-weight /
                weight-wanted) and the card license; downloads and writes nothing
  --damp-run    fetches only the missing small files (up to --max-file-mb, default 50) and writes
                registry/models/<id>.json with weights: absent (damp); prints the license (nothing
                to accept: no weights are fetched); manifest and preset are not changed
  --max-file-mb N  small-file limit

exit status: 0 ok, 1 error, 2 usage / role ambiguous / fetch failed / license not accepted.
""" % ", ".join(AUX_KINDS)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="add-model.sh", description="Register a model (a Hugging Face snapshot directory, explicit flags, or a lone GGUF) in the code-bootstraps-llama.cpp model manifest and preset.",
                                 epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", metavar="DIR|FILE.gguf|ROLE FILE.gguf")
    ap.add_argument("--role", "--type", dest="role", help="familia role (coder, general, decision, embed, ...); optional")
    ap.add_argument("--repo", help="Hugging Face repo id ORG/NAME of the GGUF")
    ap.add_argument("--revision", help="Hugging Face commit SHA the files come from")
    ap.add_argument("--file", help="main GGUF: a path, or a file name inside DIR")
    ap.add_argument("--quant", help="pick the main GGUF in DIR by quant (Q4_K_M, Q8_0, ...)")
    ap.add_argument("--card", help="model card README.md (when there is no DIR)")
    ap.add_argument("--config", help="config.json")
    ap.add_argument("--generation-config", dest="generation_config", help="generation_config.json")
    ap.add_argument("--tokenizer-config", dest="tokenizer_config", help="tokenizer_config.json")
    ap.add_argument("--chat-template", dest="chat_template", help="chat_template.jinja")
    ap.add_argument("--license-file", dest="license_file", help="LICENSE file")
    ap.add_argument("--license", help="license string (overrides the card)")
    ap.add_argument("--ctx", type=int, help="context length (overrides GGUF/config)")
    ap.add_argument("--aux", action="append", metavar="KIND=PATH", help="auxiliary model file (repeatable)")
    ap.add_argument("--pick", help="manifest pick (default: the existing entry's, else 'local'; "
                    "pick=default entries are fetched by fetch-models.sh)")
    ap.add_argument("--dir-field", dest="dir_field", metavar="DIR", help="manifest 'dir' (models-optional/...)")
    ap.add_argument("--note", help="free-text note for a new entry")
    ap.add_argument("--no-preset", action="store_true", help="do not touch models-preset.ini")
    ap.add_argument("--apply-card-defaults", action="store_true", help="write the card's sampling keys into [ROLE]")
    ap.add_argument("--card-set", metavar="LABEL", help="use this recommended card set (substring of its label) instead of card_defaults")
    ap.add_argument("--fetch", metavar="ORG/NAME[@REV]", help="download the repo's small files + one GGUF first (opt-in network)")
    ap.add_argument("--bootstraps", help="code-bootstraps-llama.cpp checkout (default: $CODE_BOOTSTRAPS, else code-bootstraps-llama.cpp in the familia checkout)")
    ap.add_argument("--manifest", help="manifest path (default: BOOTSTRAPS/config/models-manifest.json)")
    ap.add_argument("--preset", help="preset path (default: BOOTSTRAPS/config/models-preset.ini)")
    import hf_fetch as hf
    hf.add_mode_args(ap, "print the plan, the entry and the preset change; write nothing (with --fetch: every repo file, "
                         "size, sha and status, and the license; no download)")
    ap.add_argument("--accept-licenses", "--yes", dest="accept_licenses", action="store_true",
                    help="accept the model's license without a prompt (the summary is still printed); also FAMILIA_ACCEPT_LICENSES=yes")
    ap.add_argument("--json", action="store_true", help="print only the entry as JSON on stdout")
    return ap.parse_args(argv)


def resolve_inputs(args, roles_hint):
    args.dir = None
    ins = list(args.inputs)
    if len(ins) == 2 and not os.path.exists(ins[0]) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", ins[0]):
        if not os.path.isfile(os.path.expanduser(ins[1])):
            raise UsageError("legacy form ROLE FILE.gguf: %s: file not found" % ins[1])
        if args.role and args.role != ins[0]:
            raise UsageError("legacy ROLE %s conflicts with --role %s" % (ins[0], args.role))
        args.role = ins[0]
        ins = [ins[1]]
    if len(ins) > 1:
        raise UsageError("expected one DIR or FILE.gguf (or ROLE FILE.gguf), got: %s" % " ".join(ins))
    if ins:
        p = os.path.expanduser(ins[0])
        if os.path.isdir(p):
            args.dir = os.path.abspath(p)
        elif os.path.isfile(p):
            if args.file:
                raise UsageError("give the GGUF either as an argument or with --file, not both")
            args.file = os.path.abspath(p)
            if os.path.isfile(os.path.join(os.path.dirname(p), "README.md")) and not args.card:
                log("note: %s has a README.md next to it; pass its directory to use the whole repo" % p)
        else:
            raise UsageError("%s: no such file or directory" % ins[0])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    interactive = sys.stdin.isatty() and sys.stderr.isatty()
    try:
        # flag combinations are checked before anything touches the environment (manifest, terminal)
        if args.damp_run and not args.fetch:
            raise UsageError("--damp-run needs --fetch ORG/NAME[@REV] (a local DIR has nothing to fetch)")
        if not argv:
            if not interactive:
                raise UsageError("no arguments. Usage: add-model.sh DIR | FILE.gguf | ROLE FILE.gguf | --fetch ORG/NAME (see --help)")
            p = input("Path to a Hugging Face model directory or .gguf file: ").strip()
            if not p:
                raise UsageError("nothing given")
            r = input("Role (empty = infer): ").strip()
            args.inputs = [p]
            args.role = r or None
        env = Env(args.bootstraps, args.manifest, args.preset)
        if env.data is None and not args.dry_run:
            raise UsageError("manifest %s not found (run scripts/configure.sh, or pass --bootstraps/--manifest)" % env.manifest)
        if args.damp_run:
            import model_db
            r = model_db.damp(args.fetch, file=args.file, quant=args.quant, role=args.role,
                              found_in=["add-model.sh --fetch --damp-run"], max_bytes=hf_max(args))
            e = r.get("entry")
            print(json.dumps({"repo": r["repo"], "revision": r["revision"], "id": e and e["id"], "roles": e and e.get("roles"),
                              "weights": e and e.get("weights"), "license": e and (e.get("license_info") or {}).get("id"),
                              "fetched_bytes": r.get("fetched_bytes"), "skipped": r.get("plan_totals"), "why": r.get("why")}, indent=1))
            print("damp run: database entry only (weights absent); the manifest and preset are not changed. "
                  "Run again without --damp-run to download the weights and register the model.")
            return 0
        if args.fetch:
            args.inputs = [fetch(args.fetch, args)]
        resolve_inputs(args, env.roles())
        entry, report, main_path, matches = build(args, env, interactive)
    except UsageError as e:
        log("add-model: %s" % e)
        return 2
    except (OSError, ValueError) as e:
        log("add-model: error: %s" % e)
        return 1

    data = env.data or {"candidates": []}
    action, idx = upsert(data, entry, explicit_role=bool(args.role), warnings=report["warnings"])
    final = data["candidates"][idx]
    if args.pick:
        final["pick"] = args.pick
    preset_lines = None
    preset_changes = {}
    if os.path.isfile(env.preset):
        with open(env.preset, encoding="utf-8") as f:
            text = f.read()
        preset_lines = text.split("\n")
        cur = preset_get(preset_lines, final["role"])
        try:
            mode, msrc = choose_mode(final, cur, args)
        except UsageError as e:
            log("add-model: %s" % e)
            return 2
        card = dict(final["card_sampling_modes"][mode]) if mode else dict(final.get("card_defaults") or {})
        star = preset_get(preset_lines, "*")
        for k, v in sorted(card.items()):
            have = cur.get(k, star.get(k))
            same = have is not None and _num_or(have) == v
            log("  card %-17s %-8s preset [%s] %s%s" % (k, v, final["role"], have if have is not None else "(unset)",
                                                     "" if same else "   <- differs" if have is not None else ""))
        if mode:
            log("  (card set %r, chosen by %s)" % (mode, msrc))
        elif final.get("card_sampling_modes") and len(final["card_sampling_modes"]) > 1:
            log("  card sets: %s (default: %s; another with --card-set)" % ("; ".join(final["card_sampling_modes"]), final.get("card_default_set")))
        if not args.no_preset and final["role"] not in preset_sections(env.preset):
            report["warnings"].append("preset has no [%s] section; not adding one, because the router would serve it "
                                      "as a new model (add it by hand, then re-run)" % final["role"])
        elif not args.no_preset:
            preset_changes["model"] = preset_model_value(env, main_path, final["role"])
            if args.apply_card_defaults:
                for k, v in card.items():
                    preset_changes[k] = repr(v) if isinstance(v, float) else str(v)
    elif not args.no_preset:
        report["warnings"].append("preset %s not found; not updated" % env.preset)

    if args.json:
        print(json.dumps(final, indent=2, ensure_ascii=False))
    else:
        print("== %s manifest entry #%d (role %s, pick %s)" % (("would be " if args.dry_run else "") + action, idx, final["role"], final["pick"]))
        print(json.dumps(final, indent=2, ensure_ascii=False))
        for s in report["inferred"]:
            print("inferred: " + s)
        for s in report["unknown"]:
            print("unknown:  " + s)
        for s in report["warnings"]:
            print("warning:  " + s)
        if preset_changes:
            print("preset [%s]: %s" % (final["role"], ", ".join("%s = %s" % kv for kv in preset_changes.items())))
    if args.dry_run:
        (log if args.json else print)("dry run: nothing written (%s, %s)" % (env.manifest, env.preset))
        return 0
    atomic_write(env.manifest, dump_manifest(data))
    (log if args.json else print)("%s %s" % ("Updated" if action == "updated" else "Added entry to", env.manifest))
    if getattr(args, "_fetched", None):
        try:
            import model_db
            repo, sha, fn = args._fetched
            e = model_db.ingest(repo, sha, fn, local=main_path, role=final["role"], found_in=["add-model.sh --fetch"])
            (log if args.json else print)("Model database entry registry/models/%s.json" % e["id"])
        except Exception as ex:  # the manifest is already written; the entry can be rebuilt with model_db.py ingest
            log("warning: model database entry not written: %s (run scripts/model_db.py ingest %s@%s %s)" % (ex, *args._fetched))
    if preset_changes and preset_lines is not None:
        out = "\n".join(preset_set(preset_lines, final["role"], preset_changes))
        atomic_write(env.preset, out if out.endswith("\n") or not text.endswith("\n") else out + "\n")
        (log if args.json else print)("Updated %s" % env.preset)
    return 0


def _num_or(s):
    try:
        return _num(s)
    except ValueError:
        return s


if __name__ == "__main__":
    sys.exit(main())
