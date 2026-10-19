#!/usr/bin/env python3
"""model_db.py: the familia model database (#51, docs/model-database.md).

One JSON file per model file in registry/models/<id>.json, built from the model's
FULL Hugging Face repo pinned to a commit (small files fetched and sha-verified,
large weights listed with size + LFS sha256) plus its base model repo, where the
recommended sampling settings usually live. Card values are copied, never invented.

  model_db.py ingest ORG/NAME[@REV] FILE [--local PATH] [--role ROLE]
  model_db.py backfill [--dry-run] [--only SUBSTR] [--skip-search]
  model_db.py show ID
  model_db.py list

backfill finds every model already in use: code-bootstraps manifest candidates, graph.yaml
models, registry records and GGUFs in the local model dirs / HF cache. It writes the
entries, links graph models (models.<m>.db) and registry records (model.db_id,
model.revision), and copies the card fields into the matching manifest candidates.
Stdlib only; network only for ingest/backfill (urllib, HF_TOKEN honoured, never printed).
"""
import argparse, glob, hashlib, json, os, re, socket, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import add_model as am  # noqa: E402
import hf_fetch as hf   # noqa: E402

REPO_ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(REPO_ROOT, "registry", "models")
SCHEMA = 1
LLAMA_DEFAULTS = {"temp": 0.8, "top-p": 0.95, "top-k": 40, "min-p": 0.05, "repeat-penalty": 1.0,
                  "presence-penalty": 0.0, "frequency-penalty": 0.0}   # llama.cpp b11374 common/common.h
SAMPLING_FLAGS = {"temp": "--temp", "top-p": "--top-p", "top-k": "--top-k", "min-p": "--min-p",
                  "repeat-penalty": "--repeat-penalty", "presence-penalty": "--presence-penalty",
                  "frequency-penalty": "--frequency-penalty"}
MANIFEST_KEYS = ("db_id", "base_model", "base_revision", "card_defaults", "card_default_set", "card_defaults_source",
                 "card_sampling_modes", "card_default_mode", "card_ctx", "card_ctx_source")


def log(m):
    print(m, file=sys.stderr)


def entry_id(repo, file):
    stem = re.sub(r"\.(gguf|bin)$", "", os.path.basename(file))
    return re.sub(r"[^A-Za-z0-9._-]+", "-", "%s--%s" % (repo.replace("/", "--"), stem))


def db_path(eid, db_dir=None):
    return os.path.join(db_dir or DB_DIR, eid + ".json")


def load(eid, db_dir=None):
    p = db_path(eid, db_dir)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_all(db_dir=None):
    out = {}
    for p in sorted(glob.glob(os.path.join(db_dir or DB_DIR, "*.json"))):
        with open(p, encoding="utf-8") as f:
            e = json.load(f)
        out[e["id"]] = e
    return out


def save(entry, db_dir=None):
    d = db_dir or DB_DIR
    os.makedirs(d, exist_ok=True)
    p = db_path(entry["id"], d)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entry, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)
    return p


# ------------------------------------------------------------------ helpers
def repo_from_url(u):
    if not isinstance(u, str):
        return None
    m = re.match(r"^(?:https?://huggingface\.co/)?([A-Za-z0-9][\w.-]*/[\w.-]+?)/?$", u.strip())
    return m.group(1) if m else None


def files_record(snap):
    return {p: {k: v for k, v in r.items() if k in ("size", "sha256", "blob", "fetched", "skipped", "verified", "error")}
            for p, r in sorted(snap["files"].items())}


def read_snap_json(snap, name):
    p = os.path.join(snap["dir"], name)
    return am.read_json(p) if os.path.isfile(p) else None


def card_of(snap, label):
    p = os.path.join(snap["dir"], "README.md")
    if not os.path.isfile(p):
        return {}, None
    with open(p, encoding="utf-8", errors="replace") as f:
        fm, body, ln = am.split_card(f.read())
    if not fm and isinstance(snap.get("card_data"), dict):
        fm = snap["card_data"]
    sc = am.scan_card_body(body, ln, "README.md")
    for x in sc["sets"]:
        x["source"] = "%s %s" % (label, x["source"])
    for c in sc["commands"] + sc["notes"]:
        c["source"] = "%s %s" % (label, c["source"])
    if sc["ctx_source"]:
        sc["ctx_source"] = "%s %s" % (label, sc["ctx_source"])
    if sc["default_mode_source"]:
        sc["default_mode_source"] = "%s %s" % (label, sc["default_mode_source"])
    return fm, sc


def template_sha(snap):
    if not snap:
        return None, None
    p = os.path.join(snap["dir"], "chat_template.jinja")
    if os.path.isfile(p):
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest(), "chat_template.jinja"
    tok = read_snap_json(snap, "tokenizer_config.json") or {}
    if isinstance(tok.get("chat_template"), str):
        return hashlib.sha256(tok["chat_template"].encode("utf-8")).hexdigest(), "tokenizer_config.json:chat_template"
    return None, None


# ------------------------------------------------------------------ ingest
def ingest(repo, revision, file, local=None, role=None, found_in=None, match=None, max_bytes=hf.DEFAULT_MAX,
           root=None, db_dir=None, write=True, fetch_base=True):
    """Build (and save) the database entry for repo@revision/file. Raises hf.HFError."""
    unknown, warnings = [], []
    snap = hf.snapshot(repo, revision, max_bytes=max_bytes, root=root, log=log)
    rev = snap["revision"]
    sib = snap["files"].get(file)
    if sib is None:
        raise hf.HFError("%s@%s has no file %s (renamed or removed upstream)" % (repo, rev[:10], file), 404)
    eid = entry_id(repo, file)
    old = load(eid, db_dir) or {}
    local_check = None
    if local and os.path.isfile(local):
        if os.path.getsize(local) != sib["size"]:
            warnings.append("local %s: size %d != repo %d" % (local, os.path.getsize(local), sib["size"]))
            local_check = {"host": socket.gethostname(), "size_ok": False}
        else:
            log("  hashing local %s ..." % local)
            ok = am.sha256_file(local) == sib.get("sha256")
            local_check = {"host": socket.gethostname(), "sha256_ok": ok, "checked": time.strftime("%Y-%m-%d")}
            if not ok:
                warnings.append("local %s: sha256 differs from the repo's LFS sha256" % local)
    meta = {}
    if file.endswith(".gguf"):
        try:
            if local and os.path.isfile(local):
                meta = am.gguf_header(local)
            else:
                meta = hf.gguf_remote_header(repo, rev, file, am.gguf_header)
        except (hf.HFError, ValueError, OSError) as e:
            warnings.append("GGUF header unreadable: %s" % e)
    fm, sc = card_of(snap, repo)
    # ---- base model (where the sampling recommendations usually live)
    bm = fm.get("base_model") if isinstance(fm, dict) else None
    bm = bm[0] if isinstance(bm, list) and bm else bm
    base = repo_from_url(bm) or repo_from_url(meta.get("general.base_model.0.repo_url")) \
        or repo_from_url(meta.get("general.base_model.0.organization", "") + "/" + meta.get("general.base_model.0.name", "")
                         if meta.get("general.base_model.0.organization") else None)
    bsnap, bfm, bsc = None, {}, None
    if base and base != repo and fetch_base:
        try:
            bsnap = hf.snapshot(base, old.get("base_revision") if old.get("base_model") == base else None,
                                max_bytes=max_bytes, root=root, log=log)
            bfm, bsc = card_of(bsnap, base)
        except hf.HFError as e:
            warnings.append("base model %s: %s" % (base, e))
    elif not base:
        unknown.append("base_model (not in the card front matter or GGUF metadata)")
    scans = [(l, s) for l, s in ((base, bsc), (repo, sc)) if s]
    gens = [(l, g) for l, g in ((base, read_snap_json(bsnap, "generation_config.json") if bsnap else None),
                                (repo, read_snap_json(snap, "generation_config.json"))) if g]
    defaults, dsrc, dset, modes, how = am.choose_card_defaults(scans, gens)
    cfg = (read_snap_json(bsnap, "config.json") if bsnap else None) or read_snap_json(snap, "config.json") or {}
    tcfg = cfg.get("text_config") if isinstance(cfg.get("text_config"), dict) else {}
    arch = meta.get("general.architecture")
    ctx, ctx_src = None, None
    if arch and isinstance(meta.get("%s.context_length" % arch), int):
        ctx, ctx_src = meta["%s.context_length" % arch], "GGUF %s.context_length" % arch
    elif isinstance(cfg.get("max_position_embeddings") or tcfg.get("max_position_embeddings"), int):
        ctx, ctx_src = cfg.get("max_position_embeddings") or tcfg.get("max_position_embeddings"), "config.json max_position_embeddings"
    card_ctx, card_ctx_src = None, None
    for _, s in scans:
        if s.get("ctx"):
            card_ctx, card_ctx_src = s["ctx"], s["ctx_source"]
            break
    if card_ctx and ctx and card_ctx != ctx:
        warnings.append("card states context %d (%s) but %s is %d" % (card_ctx, card_ctx_src, ctx_src, ctx))
    dmode = next(((s["default_mode"], s["default_mode_source"]) for _, s in scans if s.get("default_mode")), (None, None))
    lic, lic_src = None, None
    for f_, l in ((fm, repo), (bfm, base)):
        if isinstance(f_, dict) and f_.get("license"):
            lic, lic_src = str(f_["license"]), "%s card license" % l
            if lic == "other" and f_.get("license_name"):
                lic = "%s (%s)" % (f_["license_name"], f_.get("license_link") or "no link")
            break
    if not lic and meta.get("general.license"):
        lic, lic_src = meta["general.license"], "GGUF general.license"
    if not lic:
        unknown.append("license")
    quant = am.quant_of(file) or (am.FTYPES.get(meta.get("general.file_type")) if isinstance(meta.get("general.file_type"), int) else None)
    # chat template / stop
    tmpl = {}
    if isinstance(meta.get("tokenizer.chat_template"), str):
        tmpl["gguf_sha256"] = hashlib.sha256(meta["tokenizer.chat_template"].encode("utf-8")).hexdigest()
    for l, s_ in ((base, bsnap), (repo, snap)):
        h, src = template_sha(s_)
        if h:
            tmpl["repo_sha256"], tmpl["repo_file"] = h, "%s %s" % (l, src)
            break
    if "gguf_sha256" in tmpl and "repo_sha256" in tmpl:
        tmpl["same"] = tmpl["gguf_sha256"] == tmpl["repo_sha256"]
    stop = {}
    tok = (read_snap_json(bsnap, "tokenizer_config.json") if bsnap else None) or read_snap_json(snap, "tokenizer_config.json") or {}
    eos = tok.get("eos_token")
    eos = eos.get("content") if isinstance(eos, dict) else eos
    if eos:
        stop["eos_token"] = eos
    gen0 = gens[0][1] if gens else {}
    if gen0.get("eos_token_id") is not None:
        stop["eos_token_id"], stop["eos_token_id_source"] = gen0["eos_token_id"], "%s generation_config.json" % gens[0][0]
    elif isinstance(meta.get("tokenizer.ggml.eos_token_id"), int):
        stop["eos_token_id"], stop["eos_token_id_source"] = meta["tokenizer.ggml.eos_token_id"], "GGUF"
    rope = {k: meta["%s.%s" % (arch, k)] for k in ("rope.freq_base", "rope.scaling.type", "rope.scaling.factor",
                                                   "rope.scaling.original_context_length") if arch and "%s.%s" % (arch, k) in meta}
    rs = cfg.get("rope_scaling") or tcfg.get("rope_scaling") or cfg.get("rope_parameters") or tcfg.get("rope_parameters")
    if isinstance(rs, dict):
        rope["config"] = rs
    # aux files of the repo (mmproj / draft / mtp), fetched only when small
    aux = []
    for p, r in sorted(snap["files"].items()):
        k = am.classify_gguf_name(p) if p.endswith(".gguf") and p != file else None
        if k:
            aux.append({"kind": k, "file": p, "size": r.get("size"), "sha256": r.get("sha256"), "fetched": bool(r.get("fetched")),
                        "source": "%s repo file" % repo})
    for c in (sc or {}).get("commands", []) + ((bsc or {}).get("commands", [])):
        for mm in re.finditer(r"(?:--mmproj|-mm|-md|--model-draft)\s+(\S+\.gguf)", c["command"]):
            if not any(a["file"] == os.path.basename(mm.group(1)) for a in aux):
                aux.append({"kind": "mmproj" if "mm" in c["command"][mm.start():mm.start() + 8] else "draft",
                            "ref": mm.group(1), "source": c["source"]})
    commands = ((bsc or {}).get("commands", []) + (sc or {}).get("commands", []))[:30]
    notes = ((bsc or {}).get("notes", []) + (sc or {}).get("notes", []))[:30]
    sets = [x for _, s in scans for x in s["sets"]]
    if not defaults:
        unknown.append("card_defaults: %s" % how)
    if not quant:
        unknown.append("quant")
    if not ctx:
        unknown.append("ctx")
    entry = {
        "schema": SCHEMA, "id": eid, "repo": repo, "revision": rev, "file": file,
        "sha256": sib.get("sha256"), "bytes": sib.get("size"), "quant": quant, "arch": arch,
        "roles": sorted(set((old.get("roles") or []) + ([role] if role else []))),
        "license": lic or "unknown", "license_source": lic_src,
        "ctx": ctx, "ctx_source": ctx_src, "card_ctx": card_ctx, "card_ctx_source": card_ctx_src,
        "base_model": base if bsnap or base else None, "base_revision": bsnap["revision"] if bsnap else None,
        "card_defaults": defaults, "card_defaults_source": dsrc or None, "card_default_set": dset, "card_defaults_how": how,
        "card_sampling_modes": modes, "card_default_mode": dmode[0], "card_default_mode_source": dmode[1],
        "card_sampling_sets": sets or None, "card_commands": commands or None, "card_notes": notes or None,
        "chat_template": tmpl or None, "stop": stop or None, "rope": rope or None, "aux": aux or None,
        "gguf": {k: meta.get(k) for k in ("general.architecture", "general.name", "general.file_type", "general.quantization_version",
                                         "_gguf_version") if k in meta} or None,
        "snapshot": {"path": "%s/%s" % (repo.replace("/", "--"), rev), "fetched_bytes": snap["fetched_bytes"],
                     "errors": snap["errors"] or None, "gated": snap.get("gated")},
        "base_snapshot": ({"path": "%s/%s" % (base.replace("/", "--"), bsnap["revision"]), "fetched_bytes": bsnap["fetched_bytes"],
                           "errors": bsnap["errors"] or None, "gated": bsnap.get("gated")} if bsnap else None),
        "repo_files": files_record(snap), "base_repo_files": files_record(bsnap) if bsnap else None,
        "found_in": sorted(set((old.get("found_in") or []) + (found_in or []))),
        "match": match or old.get("match"), "local_check": local_check or old.get("local_check"),
        "unknown": unknown or None, "warnings": warnings or None,
        "updated": time.strftime("%Y-%m-%d"), "by": "scripts/model_db.py",
    }
    if write:
        save(entry, db_dir)
    return entry


# ------------------------------------------------------------------ backfill discovery
def model_dirs():
    home = os.path.expanduser("~")
    gh = os.environ.get("GGUF_HOME") or os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "gguf")
    return [os.path.join(home, "code-bootstraps-llama.cpp"), os.path.join(REPO_ROOT, "code-bootstraps-llama.cpp"), gh]


def find_local(file, extra=()):
    for root in model_dirs():
        for sub in ("models", "models-optional", "models-inactive"):
            for p in glob.glob(os.path.join(root, sub, "**", file), recursive=True):
                if os.path.isfile(p):
                    return os.path.realpath(p)
    for p in extra:
        if p and os.path.isfile(os.path.expanduser(p)):
            return os.path.realpath(os.path.expanduser(p))
    for p in glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--*/snapshots/*/%s" % file)):
        return os.path.realpath(p)
    return None


def hf_cache_targets():
    out = []
    for p in glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--*/snapshots/*/*.gguf")):
        repo, rev, _, _ = am.hf_snapshot_info(os.path.dirname(p))
        if repo:
            out.append({"repo": repo, "revision": rev, "file": os.path.basename(p), "local": os.path.realpath(p),
                        "found_in": ["hf-cache"]})
    return out


def search_repo_for(file, sha=None, size_mib=None, hints=()):
    """Find the HF repo holding `file`: exact LFS sha256 match first, else a unique
    filename (+ approximate size) match. Returns (repo, revision, match note) or None."""
    stem = re.sub(r"[.-](?:UD-)?(IQ\d_\w+|Q\d_K(?:_[SMLX]+)?|Q\d_\d|F16|BF16|F32)$", "", re.sub(r"\.gguf$", "", file))
    repos = [h for h in hints if h]
    try:
        url = "%s/api/models?search=%s&limit=40" % (hf.ENDPOINT, hf.urllib.parse.quote(stem))
        with hf._request(url) as r:
            repos += [m["id"] for m in json.load(r) if "gguf" in m["id"].lower() or "gguf" in (m.get("tags") or [])]
    except hf.HFError as e:
        log("  search %s: %s" % (stem, e))
    seen, by_name = set(), []
    for repo in repos:
        if repo in seen:
            continue
        seen.add(repo)
        try:
            info = hf.repo_info(repo)
        except hf.HFError:
            continue
        for s in info.get("siblings", []):
            lfs = s.get("lfs") or {}
            if sha and lfs.get("sha256") == sha:
                same = [x["rfilename"] for x in info["siblings"] if (x.get("lfs") or {}).get("sha256") == sha]
                pick = s["rfilename"] if s["rfilename"] == file else (file if file in same else s["rfilename"])
                return repo, info["sha"], pick, "LFS sha256 match"
            if os.path.basename(s["rfilename"]) == file:
                by_name.append((repo, info["sha"], s["rfilename"], s.get("size") or lfs.get("size")))
    if size_mib:
        by_name = [b for b in by_name if b[3] and abs(b[3] / 1048576.0 - size_mib) < 0.6]
    if len(by_name) == 1:
        return by_name[0][0], by_name[0][1], by_name[0][2], "unique filename%s match (sha256 not measured)" % (" + size" if size_mib else "")
    return None


def load_graph():
    import yaml
    with open(os.path.join(REPO_ROOT, "graph.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_records():
    p = os.path.join(REPO_ROOT, "registry", "records.jsonl")
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def backfill(args):
    env = am.Env(args.bootstraps)
    targets, failures = {}, []

    def add(t):
        k = (t["repo"], t["file"])
        cur = targets.setdefault(k, {"repo": t["repo"], "revision": None, "file": t["file"], "local": None,
                                     "found_in": [], "roles": [], "match": None, "graph_models": []})
        cur["revision"] = cur["revision"] or t.get("revision")
        cur["local"] = cur["local"] or t.get("local")
        cur["found_in"] += t.get("found_in", [])
        cur["roles"] += [r for r in t.get("roles", []) if r]
        cur["match"] = cur["match"] or t.get("match")
        cur["graph_models"] += t.get("graph_models", [])

    for c in (env.data or {}).get("candidates", []):
        if c.get("repo") and c.get("file") and "/" in c["repo"]:
            add({"repo": c["repo"], "revision": c.get("revision"), "file": c["file"], "local": find_local(c["file"]),
                 "found_in": ["manifest %s/%s" % (c.get("role"), c.get("pick"))], "roles": [c.get("role")]})
    for t in hf_cache_targets():
        add(t)
    g = load_graph()
    recs = load_records()
    by_sha = {(t["file"]): t for t in targets.values()}
    for name, m in (g.get("models") or {}).items():
        file = os.path.basename(m["gguf"])
        sha = m.get("sha256") if re.fullmatch(r"[0-9a-f]{64}", str(m.get("sha256"))) else None
        hit = None
        for t in targets.values():          # already known (manifest): match by sha or file
            e = load(entry_id(t["repo"], t["file"]), args.db_dir)
            if t["file"] == file and (not sha or not e or e.get("sha256") == sha):
                hit = t
                break
        if hit:
            hit["graph_models"].append(name)
            hit["roles"].append(m.get("role"))
            continue
        hints = []
        size = None
        for r in recs:
            rm = r.get("model") or {}
            if rm.get("file") == file or (sha and rm.get("sha256") == sha):
                rp = (rm.get("repo") or "").split(" ")[0]
                if "/" in rp:
                    hints.append(rp)
                size = size or rm.get("size_mib")
        if args.skip_search:
            failures.append({"what": "graph model %s (%s)" % (name, file), "why": "search skipped"})
            continue
        log("searching HF for %s (graph model %s) ..." % (file, name))
        found = search_repo_for(file, sha, size if not sha else None, hints)
        if not found:
            failures.append({"what": "graph model %s (%s)" % (name, file),
                             "why": "no HF repo with this %s" % ("LFS sha256" if sha else "unique filename/size")})
            continue
        repo, rev, rfile, note = found
        add({"repo": repo, "revision": rev, "file": rfile, "local": find_local(file, [m["gguf"]]),
             "found_in": ["graph.yaml models.%s" % name], "roles": [m.get("role")], "match": note, "graph_models": [name]})
    built = {}
    for (repo, file), t in sorted(targets.items()):
        if args.only and args.only.lower() not in (repo + "/" + file).lower():
            continue
        log("== %s@%s %s%s" % (repo, (t["revision"] or "main")[:10], file, " (local)" if t["local"] else ""))
        if args.dry_run:
            continue
        try:
            e = ingest(repo, t["revision"], file, local=t["local"], found_in=sorted(set(t["found_in"])), match=t["match"],
                       max_bytes=args.max_bytes, db_dir=args.db_dir)
            e["roles"] = sorted(set(e["roles"] + [r for r in t["roles"] if r]))
            save(e, args.db_dir)
            built[e["id"]] = (e, t)
        except hf.HFError as ex:
            failures.append({"what": "%s %s" % (repo, file), "why": str(ex)})
            log("  FAILED: %s" % ex)
    if args.dry_run:
        return targets, failures, {}
    changes = {"manifest": 0, "graph": 0, "records": 0}
    if not args.no_manifest and env.data:
        changes["manifest"] = project_manifest(env, built)
    if not args.no_graph:
        changes["graph"] = link_graph(built)
    if not args.no_registry:
        changes["records"], notes = link_records(load_all(args.db_dir), load_graph())
        for n in notes:
            log("  registry: " + n)
    log("changes: %s" % changes)
    return targets, failures, built


def manifest_projection(e):
    p = {"db_id": e["id"], "base_model": e.get("base_model"), "base_revision": e.get("base_revision"),
         "card_defaults": e.get("card_defaults"), "card_default_set": e.get("card_default_set"),
         "card_defaults_source": e.get("card_defaults_source"), "card_sampling_modes": e.get("card_sampling_modes"),
         "card_default_mode": e.get("card_default_mode"), "card_ctx": e.get("card_ctx"), "card_ctx_source": e.get("card_ctx_source")}
    return {k: v for k, v in p.items() if v is not None}


def project_manifest(env, built):
    n = 0
    for c in env.data.get("candidates", []):
        e = next((x for x, _ in built.values() if x["repo"] == c.get("repo") and x["file"] == c.get("file")), None)
        if not e:
            continue
        if c.get("revision") and c["revision"] != e["revision"]:
            log("  manifest %s: revision %s kept (entry %s)" % (c["file"], c["revision"], e["revision"]))
            continue
        for k, v in manifest_projection(e).items():
            c[k] = v
        if not c.get("revision"):
            c["revision"] = e["revision"]
        if c.get("sha256") != e["sha256"]:
            log("  manifest %s: sha256 %s != repo LFS %s" % (c["file"], c.get("sha256"), e["sha256"]))
        n += 1
    am.atomic_write(env.manifest, am.dump_manifest(env.data))
    return n


def link_graph(built, path=None):
    """Set models.<m>.db: <id> in graph.yaml with a line edit (keeps comments)."""
    p = path or os.path.join(REPO_ROOT, "graph.yaml")
    with open(p, encoding="utf-8") as f:
        lines = f.read().split("\n")
    want = {}
    for e, t in built.values():
        for gm in t.get("graph_models", []):
            want[gm] = e["id"]
    n, sec, cur = 0, None, None
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^([A-Za-z_]+):\s*(#.*)?$", line)
        if m:
            sec = m.group(1)
        mm = re.match(r"^  ([A-Za-z0-9_.-]+):\s*(#.*)?$", line)
        out.append(line)
        if sec == "models" and mm and mm.group(1) in want:
            name = mm.group(1)
            j = i + 1
            block = []
            while j < len(lines) and (lines[j].startswith("    ") or not lines[j].strip()):
                block.append(lines[j])
                j += 1
            block = [b for b in block if not re.match(r"^    db:", b)]
            ins = len(block)
            while ins > 0 and not block[ins - 1].strip():
                ins -= 1
            block.insert(ins, "    db: %s" % want[name])
            out += block
            n += 1
            i = j
            continue
        i += 1
    am.atomic_write(p, "\n".join(out))
    return n


def norm_name(s):
    s = (s or "").split(" (")[0].lower()
    s = s.split("/")[-1] if "/" in s else s.split(" ")[-1]
    return re.sub(r"[^a-z0-9.]+", "-", re.sub(r"-gguf$", "", s)).strip("-")


def record_match(r, entries, graph):
    """Unambiguous db entry for a registry record, or (None, why)."""
    rm = r.get("model") or {}
    if not isinstance(rm, dict) or not rm:
        return None, "record has no model"
    if rm.get("sha256"):
        hits = [e for e in entries.values() if e.get("sha256") == rm["sha256"]]
        hits = [e for e in hits if not rm.get("file") or e["file"] == rm["file"]] or hits
        uniq = {e["id"] for e in hits}
        if len(uniq) == 1:
            return hits[0], "sha256"
        if len(uniq) > 1:
            same = [e for e in hits if rm.get("quant") and e.get("quant") == rm.get("quant") and rm["quant"].lower() in e["file"].lower()]
            if len({e["id"] for e in same}) == 1:
                return same[0], "sha256 + quant"
            return None, "sha256 matches %d entries" % len(uniq)
    name, quant = norm_name(rm.get("repo")), (rm.get("quant") or "").upper()
    if not name or not quant:
        return None, "no repo/quant to match"
    cands = [e for e in entries.values() if (e.get("quant") or "").upper() == quant and
             (name in norm_name(e["repo"]) or name == norm_name(e.get("base_model")) or name in e["file"].lower())]
    if rm.get("file"):
        cands = [e for e in cands if e["file"] == rm["file"]] or ([] if cands else cands)
    host = r.get("host")
    if len({e["id"] for e in cands}) > 1 and host:   # narrow by the graph models placed on that host
        on_host = {(graph["models"][n["model"]].get("db")) for n in graph["nodes"].values() if n.get("host") == host}
        cands = [e for e in cands if e["id"] in on_host] or cands
    ids = {e["id"] for e in cands}
    if len(ids) == 1:
        return cands[0], "repo name + quant%s" % (" + file" if rm.get("file") else "")
    return None, ("no entry for %s %s" % (rm.get("repo"), quant)) if not ids else "ambiguous: %s" % ", ".join(sorted(ids))


def link_records(entries, graph=None, path=None):
    """Add model.db_id / model.revision / model.db_match to registry records with an
    unambiguous match; others get db_id null and a db_note saying why."""
    p = path or os.path.join(REPO_ROOT, "registry", "records.jsonl")
    with open(p, encoding="utf-8") as f:
        raw = [l for l in f.read().split("\n") if l.strip()]
    graph = graph or load_graph()
    n, notes, out = 0, [], []
    for i, l in enumerate(raw):
        r = json.loads(l)
        rm = r.get("model")
        if isinstance(rm, dict) and rm:
            e, why = record_match(r, entries, graph)
            if e:
                if rm.get("db_id") != e["id"] or rm.get("revision") != e["revision"] or rm.get("db_match") != why:
                    rm["db_id"], rm["revision"], rm["db_match"] = e["id"], e["revision"], why
                    rm.pop("db_note", None)
                    n += 1
            else:
                if rm.get("db_id") is None or rm.get("db_note") != "unlinked: %s" % why:
                    rm["db_id"], rm["revision"], rm["db_note"] = None, None, "unlinked: %s" % why
                    rm.pop("db_match", None)
                    n += 1
                notes.append("record %d (%s %s): %s" % (i + 1, rm.get("repo"), rm.get("quant"), why))
            out.append(json.dumps(r, sort_keys=True))
        else:
            out.append(l)
    am.atomic_write(p, "\n".join(out) + "\n")
    return n, notes


# ------------------------------------------------------------------ graph checks / launch defaults
def pick_label(labels, want):
    """Card set labels matching want: an exact label, else a unique prefix, else substrings."""
    w = want.lower().strip()
    for test in (lambda l: l.lower().strip() == w, lambda l: l.lower().startswith(w), lambda l: w in l.lower()):
        hits = [l for l in labels if test(l)]
        if hits:
            return hits
    return []


def node_card(entry, node):
    """(params, set label, how) the node should launch with, from the card. Raises
    ValueError when the card has several sets and none is the default or chosen."""
    modes = entry.get("card_sampling_modes") or {}
    want = node.get("card_set")
    if want:
        hits = pick_label(modes, want)
        if len(hits) != 1:
            raise ValueError("card_set %r matches %d of the card's sets (%s)" % (want, len(hits), "; ".join(modes) or "none"))
        return dict(modes[hits[0]]), hits[0], "card_set"
    if entry.get("card_defaults"):
        return dict(entry["card_defaults"]), entry.get("card_default_set"), "card default"
    if len(modes) > 1:
        raise ValueError("the card recommends %d sampling sets and none is the default (%s); set card_set"
                         % (len(modes), "; ".join(modes)))
    return {}, None, "card states no sampling values"


def launch_sampling(entry, node):
    """Effective sampling for a node: card values, then node.sampling overrides."""
    params, label, _ = node_card(entry, node)
    params.update(node.get("sampling") or {})
    return params


def check_graph(graph, db_dir=None):
    """Errors / warnings for graph models and nodes against the model database."""
    errs, warns = [], []
    entries = {}
    used = {n.get("model") for n in (graph.get("nodes") or {}).values()}
    for mname, m in (graph.get("models") or {}).items():
        w = "models.%s" % mname
        eid = m.get("db")
        if not eid:
            if mname in used:
                errs.append("%s: no model database entry (set models.%s.db; scripts/model_db.py backfill)" % (w, mname))
            continue
        e = load(eid, db_dir)
        if e is None:
            errs.append("%s.db: no entry %s in registry/models/" % (w, eid))
            continue
        entries[mname] = e
        if not re.fullmatch(r"[0-9a-f]{40}", str(e.get("revision") or "")):
            errs.append("%s.db: entry %s has no pinned revision (commit SHA)" % (w, eid))
        if re.fullmatch(r"[0-9a-f]{64}", str(m.get("sha256"))) and e.get("sha256") and m["sha256"] != e["sha256"]:
            errs.append("%s: sha256 %s differs from the database entry %s (%s)" % (w, m["sha256"][:12], eid, e["sha256"][:12]))
        if isinstance(e.get("ctx"), int) and m.get("trained_ctx") != e["ctx"]:
            errs.append("%s: trained_ctx %s but the database entry says %d (%s)" % (w, m.get("trained_ctx"), e["ctx"], e.get("ctx_source")))
        if e.get("arch") and m.get("arch") != e["arch"]:
            errs.append("%s: arch %r but the database entry says %r" % (w, m.get("arch"), e["arch"]))
    for name, n in (graph.get("nodes") or {}).items():
        e = entries.get(n.get("model"))
        if e is None:
            continue
        w = "nodes.%s" % name
        reasons = n.get("override_reasons") or {}
        for k, v in reasons.items():
            if not isinstance(v, str) or len(v.strip()) < 10:
                errs.append("%s.override_reasons.%s: needs a real reason (a sentence), got %r" % (w, k, v))
        needed = set()
        card_ctx = e.get("card_ctx") or e.get("ctx")
        if isinstance(card_ctx, int) and n.get("ctx") != card_ctx:
            needed.add("ctx")
            if "ctx" not in reasons:
                errs.append("%s: ctx %s differs from the model card's %d (%s) without override_reasons.ctx"
                            % (w, n.get("ctx"), card_ctx, e.get("card_ctx_source") or e.get("ctx_source")))
        if n.get("embeddings"):
            continue
        try:
            card, label, how = node_card(e, n)
        except ValueError as ex:
            errs.append("%s: %s" % (w, ex))
            continue
        if n.get("card_set") and label != e.get("card_default_set"):
            needed.add("card_set")
            if "card_set" not in reasons:
                errs.append("%s: card_set %r is not the card's default (%r) without override_reasons.card_set"
                            % (w, label, e.get("card_default_set")))
        for k, v in (n.get("sampling") or {}).items():
            if k not in SAMPLING_FLAGS:
                errs.append("%s.sampling.%s: unknown key (known: %s)" % (w, k, ", ".join(SAMPLING_FLAGS)))
                continue
            if k in card and card[k] != v:
                needed.add(k)
                if k not in reasons:
                    errs.append("%s.sampling.%s = %s contradicts the model card (%s: %s) without override_reasons.%s"
                                % (w, k, v, label, card[k], k))
        for k in reasons:
            if k not in needed:
                warns.append("%s.override_reasons.%s: nothing overrides the card here (stale reason?)" % (w, k))
    return errs, warns


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-dir", default=None, help="database directory (default registry/models)")
    ap.add_argument("--max-bytes", type=int, default=hf.DEFAULT_MAX, help="skip repo files larger than this (default 50 MB)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("ingest")
    i.add_argument("repo")
    i.add_argument("file")
    i.add_argument("--local")
    i.add_argument("--role")
    b = sp.add_parser("backfill")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--only")
    b.add_argument("--skip-search", action="store_true")
    b.add_argument("--no-manifest", action="store_true")
    b.add_argument("--no-graph", action="store_true")
    b.add_argument("--no-registry", action="store_true")
    b.add_argument("--bootstraps")
    s = sp.add_parser("show")
    s.add_argument("id")
    sp.add_parser("list")
    a = ap.parse_args(argv)
    if a.cmd == "ingest":
        repo, _, rev = a.repo.partition("@")
        try:
            e = ingest(repo, rev or None, a.file, a.local, a.role, found_in=["model_db.py ingest"], db_dir=a.db_dir)
        except hf.HFError as ex:
            log("model_db: %s" % ex)
            return 1
        print(json.dumps({k: e[k] for k in ("id", "repo", "revision", "card_defaults", "card_default_set", "ctx", "card_ctx", "unknown")}, indent=1))
        return 0
    if a.cmd == "backfill":
        targets, failures, built = backfill(a)
        print(json.dumps({"targets": len(targets), "built": sorted(built), "failures": failures}, indent=1))
        return 1 if failures else 0
    if a.cmd == "show":
        e = load(a.id, a.db_dir)
        if not e:
            log("no entry %s" % a.id)
            return 1
        print(json.dumps(e, indent=1, ensure_ascii=False))
        return 0
    for eid, e in load_all(a.db_dir).items():
        print("%-60s %s %-8s ctx %-7s card %s" % (eid, e["revision"][:10], e.get("quant"), e.get("ctx"), e.get("card_defaults")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
