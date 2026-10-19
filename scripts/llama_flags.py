#!/usr/bin/env python3
"""llama_flags.py: which llama.cpp flags and architectures a pinned build really has (#51).

The table is read from the llama.cpp SOURCE at the build's tag or commit (common/arg.cpp,
src/llama-arch.cpp, src/llama-vocab.cpp), not from memory, and saved as
registry/llama-builds/<name>.json:
  flags   every option: aliases, number of values, the tools (examples) it applies to
  archs   GGUF general.architecture values the build can load
  eog     token texts the build always treats as end of generation
A build whose source is not public (e.g. a distro package) can be described from its
`llama-server --help` text instead (--help-file); then archs/eog stay unknown.

  llama_flags.py fetch NAME REPO REF [--out DIR]      e.g. fetch b11374 ggml-org/llama.cpp b11374
  llama_flags.py help NAME FILE [--commit SHA]         from a --help dump
  llama_flags.py show NAME FLAG...
Stdlib only (urllib); GITHUB_TOKEN is used when set and never printed."""
import json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "registry", "llama-builds")
SERVER = "LLAMA_EXAMPLE_SERVER"


def _get(url, accept=None):
    h = {"User-Agent": "familia-llama-flags/1"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and url.startswith("https://api.github.com/"):
        h["Authorization"] = "Bearer " + tok
    if accept:
        h["Accept"] = accept
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # retried: connections drop
            last = e
            if getattr(e, "code", None) in (401, 403, 404):
                break
            time.sleep(2 * (i + 1))
    raise RuntimeError("%s: %s" % (url.split("?")[0], last))


def _strings(s):
    return re.findall(r'"((?:[^"\\]|\\.)*)"', s)


def parse_arg_cpp(text):
    """{flag: {"aliases", "nargs", "neg", "examples", "env"}} from common/arg.cpp."""
    out = {}
    text = re.sub(r"(?m)^[ \t]*//.*$", "", text)     # whole-line comments may quote flags ("-mmdev" must sort ...)
    for m in re.finditer(r"add_opt\(common_arg\(", text):
        i, depth = m.end(), 2
        while i < len(text) and depth:     # the whole add_opt(common_arg( ... ).set_...()) call
            c = text[i]
            if c == '"':
                i += 1
                while i < len(text) and text[i] != '"':
                    i += 2 if text[i] == "\\" else 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        call = text[m.end():i]
        groups = re.match(r"\s*(\{[^{}]*\})\s*,\s*(?:(\{[^{}]*\})\s*,)?", call)
        if not groups:
            continue
        pos = [x for x in _strings(groups.group(1)) if x.startswith("-")]
        neg = [x for x in _strings(groups.group(2) or "") if x.startswith("-")]
        if not pos:
            continue
        lam = re.search(r"\[\]\s*\(\s*common_params\s*&\s*\w*\s*((?:,[^)]*)?)\)", call)
        params = [p for p in (lam.group(1) if lam else "").split(",") if p.strip()]
        boolean = len(params) == 1 and re.search(r"\bbool\b", params[0]) is not None
        nargs = 0 if (not params or boolean) else len(params)
        ex = re.search(r"\.set_examples\(\{([^}]*)\}\)", call)
        examples = re.findall(r"LLAMA_EXAMPLE_\w+", ex.group(1)) if ex else ["LLAMA_EXAMPLE_COMMON"]
        exc = re.search(r"\.set_excludes\(\{([^}]*)\}\)", call)
        env = re.search(r'\.set_env\("([^"]+)"\)', call)
        rec = {"aliases": pos + neg, "nargs": nargs, "bool": boolean, "neg": neg or None, "examples": examples,
               "excludes": re.findall(r"LLAMA_EXAMPLE_\w+", exc.group(1)) if exc else None,
               "env": env.group(1) if env else None}
        for a in pos + neg:
            out[a] = rec
    return out


def parse_arch(text):
    m = re.search(r"LLM_ARCH_NAMES\s*=\s*\{(.*?)\n\};", text, re.S)
    return sorted(set(re.findall(r'\{\s*LLM_ARCH_\w+\s*,\s*"([^"]+)"\s*\}', m.group(1) if m else "")))


def parse_eog(text):
    """Token texts in the 'for (const auto & t : token_to_id)' EOG list of llama-vocab.cpp."""
    best = []
    for m in re.finditer(r"for \(const auto & t : token_to_id\)\s*\{\s*auto & attr[^\n]*\n\s*if \(false(.*?)\)\s*\{\s*special_eog_ids\.insert", text, re.S):
        best = re.findall(r't\.first == "((?:[^"\\]|\\.)*)"', m.group(1))
    return best


def parse_help(text):
    """{flag: {...}} from `llama-server --help` (aliases on one line, a value hint after)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^((?:-{1,2}[\w.-]+(?:,\s*)?)+)\s*(\S*)", line.strip())
        if not m or not line.lstrip().startswith("-"):
            continue
        al = [a.strip() for a in m.group(1).split(",") if a.strip()]
        hint = m.group(2)
        nargs = 1 if hint and (hint.isupper() or hint.startswith(("{", "<", "["))) and not hint.startswith("--") else 0
        rec = {"aliases": al, "nargs": nargs, "bool": False, "neg": None, "examples": [SERVER], "excludes": None, "env": None}
        for a in al:
            out[a] = rec
    return out


def build_record(name, repo, ref, out=DB):
    info = json.loads(_get("https://api.github.com/repos/%s/commits/%s" % (repo, ref)))
    sha = info["sha"]
    raw = "https://raw.githubusercontent.com/%s/%s/" % (repo, sha)
    flags = parse_arg_cpp(_get(raw + "common/arg.cpp"))
    archs = parse_arch(_get(raw + "src/llama-arch.cpp"))
    eog = parse_eog(_get(raw + "src/llama-vocab.cpp"))
    rec = {"name": name, "repo": repo, "ref": ref, "commit": sha, "source": "common/arg.cpp, src/llama-arch.cpp, src/llama-vocab.cpp @ " + sha,
           "flags": flags, "archs": archs, "eog": eog, "fetched": time.strftime("%Y-%m-%d")}
    save(rec, out)
    return rec


def save(rec, out=DB):
    os.makedirs(out, exist_ok=True)
    if isinstance(rec.get("flags"), dict):     # stored once per option, indexed again on load
        seen, opts = set(), []
        for r in rec["flags"].values():
            if id(r) not in seen:
                seen.add(id(r))
                opts.append({k: v for k, v in r.items() if v is not None and v is not False})
        rec = dict(rec, flags=sorted(opts, key=lambda r: r["aliases"][0]))
    p = os.path.join(out, rec["name"] + ".json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(p + ".tmp", p)
    return p


_cache = {}


def load(name, db=DB):
    if (name, db) not in _cache:
        p = os.path.join(db, name + ".json")
        rec = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None
        if rec and isinstance(rec.get("flags"), list):
            for r in rec["flags"]:
                r.setdefault("nargs", 0)
            rec["flags"] = {a: r for r in rec["flags"] for a in r["aliases"]}
        _cache[(name, db)] = rec
    return _cache[(name, db)]


def supports(build, flag, tool=SERVER):
    """True / False, or None when the build is not described."""
    if build is None:
        return None
    r = build["flags"].get(flag)
    if r is None:
        return False
    ex = r.get("examples") or ["LLAMA_EXAMPLE_COMMON"]
    if tool in (r.get("excludes") or []):
        return False
    return "LLAMA_EXAMPLE_COMMON" in ex or tool in ex


def build_for_runtime(rt):
    """Build table name for a graph runtime: its 'build' tag (bNNNNN), else None."""
    if not rt:
        return None
    m = re.search(r"\bb(\d{4,6})\b", str(rt.get("build", "")))
    return "b" + m.group(1) if m else (rt.get("flags_table") or None)


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[1] == "fetch":
        r = build_record(argv[2], argv[3], argv[4])
        print("%s: %d flags, %d archs, %d EOG texts @ %s" % (r["name"], len(r["flags"]), len(r["archs"]), len(r["eog"]), r["commit"][:10]))
        return 0
    if argv[1] == "help":
        text = open(argv[3], encoding="utf-8", errors="replace").read()
        commit = argv[argv.index("--commit") + 1] if "--commit" in argv else None
        rec = {"name": argv[2], "repo": None, "ref": None, "commit": commit, "source": "llama-server --help (%s)" % os.path.basename(argv[3]),
               "flags": parse_help(text), "archs": None, "eog": None, "fetched": time.strftime("%Y-%m-%d")}
        save(rec)
        print("%s: %d flags from --help" % (rec["name"], len(rec["flags"])))
        return 0
    if argv[1] == "show":
        b = load(argv[2])
        for f in argv[3:]:
            print(f, supports(b, f), (b["flags"].get(f) or {}).get("aliases"))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
