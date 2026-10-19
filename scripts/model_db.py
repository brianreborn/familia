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
import llama_flags as lf  # noqa: E402
import model_params as mp  # noqa: E402

REPO_ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(REPO_ROOT, "registry", "models")
SCHEMA = 2      # 2: descriptor, card_commands (verbatim), required_params, blockers, github docs (#51)
PARAMS_BUILD = "b11374"   # flag table / EOG list the analysis is run against (code-bootstraps pin)
CONFIG_FILES = ("tokenizer.json", "config.json", "generation_config.json", "tokenizer_config.json", "config_sentence_transformers.json",
                "1_Pooling/config.json", "modules.json", "sentence_bert_config.json", "special_tokens_map.json")
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
           root=None, db_dir=None, write=True, fetch_base=True, refresh_github=False, weights=None):
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
    cur_ = (mp.load_curated().get(entry_id(repo, file)) or {})
    if not base and cur_.get("base_model"):
        base = cur_["base_model"]["value"]
        warnings.append("base_model %s from registry/model-params.yaml (%s)" % (base, cur_["base_model"]["source"]))
    if not base:   # "This is quantized version of [owner/repo](https://huggingface.co/owner/repo)" (QuantFactory)
        p_ = os.path.join(snap["dir"], "README.md")
        mm = re.search(r"(?i)quantized version of \[?([A-Za-z0-9][\w.-]*/[\w.-]+)\]?\(https://huggingface\.co/\1\)",
                       _read(p_)) if os.path.isfile(p_) else None
        if mm:
            base = mm.group(1)
            warnings.append("base_model from the card text (\"quantized version of %s\"); not in the front matter or GGUF" % base)
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
    commands = None   # filled verbatim by apply_params (model_params.extract_examples)
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
        "card_sampling_sets": sets or None, "card_commands": commands, "card_notes": notes or None,
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
    # weights: "absent (damp)" for a damp-run entry (validate_graph refuses to run it), "present (...)"
    # once a full run verified the file; kept from the old entry otherwise.
    w = weights or old.get("weights")
    if local_check and local_check.get("sha256_ok") and (w or "").startswith("absent"):
        w = "present (%s, sha256 checked %s)" % (local_check["host"], local_check.get("checked"))
    if w:
        entry["weights"] = w
    entry["gguf_meta"] = gguf_scalars(meta) or None
    try:
        apply_params(entry, snap, bsnap, meta, root=root, refresh_github=refresh_github)
    except hf.HFError as ex:
        warnings.append("model parameters: %s" % ex)
        entry["warnings"] = warnings
    if write:
        save(entry, db_dir)
    return entry


def gguf_scalars(meta):
    """Every GGUF header value except token arrays; the chat template as its sha256 and length."""
    out = {}
    for k, v in (meta or {}).items():
        if k == "tokenizer.chat_template" and isinstance(v, str):
            out[k] = {"sha256": hashlib.sha256(v.encode("utf-8")).hexdigest(), "chars": len(v)}
        elif isinstance(v, dict) and "array" in v:
            out[k] = {"array_len": v["array"]}
        elif isinstance(v, list) and len(v) > 64:
            out[k] = {"array_len": len(v)}
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ model parameters (#51)
def base_chain(base, bsnap, log_=log, depth=4):
    """[{repo, revision, via, card_data, pipeline_tag, safetensors, license_files}] from the base
    model up its own base_model links (API only beyond the first level)."""
    chain, seen = [], set()
    cur, info, via = base, bsnap, "card base_model"
    while cur and cur not in seen and len(chain) < depth:
        seen.add(cur)
        if info is None:
            try:
                ri = hf.repo_info(cur)
            except hf.HFError as ex:
                chain.append({"repo": cur, "via": via, "error": str(ex)})
                break
            info = {"repo": cur, "revision": ri["sha"], "card_data": ri.get("cardData"), "pipeline_tag": ri.get("pipeline_tag"),
                    "safetensors": ri.get("safetensors"), "api_id": ri.get("id"),
                    "files": {x["rfilename"]: {} for x in ri.get("siblings") or []}}
        cd = info.get("card_data") or {}
        chain.append({"repo": cur, "api_id": info.get("api_id"), "revision": info.get("revision"), "via": via,
                      "card_data": {k: cd.get(k) for k in ("license", "license_name", "license_link", "language", "base_model",
                                                           "pipeline_tag", "library_name") if cd.get(k) is not None},
                      "pipeline_tag": info.get("pipeline_tag"), "safetensors": info.get("safetensors"),
                      "license_files": [p for p in sorted(info.get("files") or {}) if re.match(r"(?i)^licen[cs]e", p)] or None})
        nb = cd.get("base_model")
        nb = nb[0] if isinstance(nb, list) and nb else nb
        cur, info, via = repo_from_url(nb) if isinstance(nb, str) else None, None, "%s card base_model" % cur
    return chain


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def snap_configs(s):
    out = {}
    for name in CONFIG_FILES:
        p = os.path.join(s["dir"], name)
        if os.path.isfile(p):
            try:
                out[name] = json.loads(_read(p))
            except ValueError:
                pass
    return out


def snap_template(s):
    p = os.path.join(s["dir"], "chat_template.jinja")
    if os.path.isfile(p):
        return {"text": _read(p), "file": "chat_template.jinja", "path": p}
    tok = read_snap_json(s, "tokenizer_config.json") or {}
    t = tok.get("chat_template")
    if isinstance(t, list):   # named templates: the default one
        t = next((x.get("template") for x in t if isinstance(x, dict) and x.get("name") == "default"), None)
    if isinstance(t, str):
        d = os.path.join(s["dir"], ".familia")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "chat_template.from-tokenizer_config.jinja")
        if not os.path.isfile(p) or _read(p) != t:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        return {"text": t, "file": "tokenizer_config.json:chat_template", "path": p}
    return None


def template_path(sha, root=None):
    """Path of a stored repo chat template with this sha256 (any snapshot under the meta root), or None."""
    r = root or hf.meta_root()
    for p in glob.glob(os.path.join(r, "*", "*", "chat_template.jinja")) + glob.glob(os.path.join(r, "*", "*", ".familia", "*.jinja")):
        with open(p, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() == sha:
                return p
    return None


def apply_params(entry, snap, bsnap, meta, root=None, curated=None, refresh_github=False, build=None):
    """Fill descriptor / card_commands / required_params / template / stop / blockers of an entry."""
    cur_all = curated if curated is not None else mp.load_curated()
    cur = cur_all.get(entry["id"]) or {}
    chain = base_chain(entry.get("base_model"), bsnap) if entry.get("base_model") else []
    docs, doc_meta, cfgs, tmpls = {}, [], {}, {}
    for lab, s_, kind in [(entry["repo"], snap, "card")] + ([(entry["base_model"], bsnap, "base-card")] if bsnap else []):
        p = os.path.join(s_["dir"], "README.md")
        if os.path.isfile(p):
            docs.setdefault(lab, {})["README.md"] = _read(p)
            doc_meta.append({"label": lab, "file": "README.md", "kind": kind, "sha": s_["revision"]})
        cfgs[lab] = snap_configs(s_)
        t = snap_template(s_)
        if t:
            tmpls[lab] = t
    links = []
    for lab in list(docs):
        links += hf.github_links(docs[lab]["README.md"])
    kept, dropped = hf.official_github(links, [entry["repo"]] + [c["repo"] for c in chain])
    extra = {}
    for g in cur.get("github") or []:
        if g["repo"] not in kept:
            kept.append(g["repo"])
        extra.setdefault(g["repo"], []).extend(g.get("paths") or [])
    gh = []
    kept = list(dict.fromkeys(kept))
    for g in kept:
        if refresh_github:
            import shutil
            shutil.rmtree(os.path.join(root or hf.meta_root(), "github", g.replace("/", "--")), ignore_errors=True)
        rec = hf.github_snapshot(g, root=root, log=log, extra=tuple(extra.get(g, ())))
        if rec.get("error"):
            gh.append({"repo": g, "error": rec["error"]})
            continue
        lab = "github.com/%s" % g
        files = [("README.md" if rec["files"].get("readme", {}).get("path") else None, rec["files"].get("readme", {}).get("path"))]
        files += [(x, x) for x in (rec["files"].get("extra") or {})]
        for shown, path in files:
            if not path:
                continue
            fp = os.path.join(rec["dir"], path)
            if os.path.isfile(fp):
                docs.setdefault(lab, {})[path] = _read(fp)
                doc_meta.append({"label": lab, "file": path, "kind": "github", "sha": rec["sha"],
                                 "license_spdx": rec.get("license_spdx") if path == rec["files"].get("readme", {}).get("path") else None,
                                 "license_file": (rec["files"].get("license") or {}).get("path") if path == rec["files"].get("readme", {}).get("path") else None})
        gh.append({"repo": g, "resolved": rec["repo"], "sha": rec["sha"], "renamed": rec["repo"].lower() != g.lower() or None,
                   "description": rec.get("description"), "license_spdx": rec.get("license_spdx"),
                   "files": {k: {"path": v["path"], "sha256": v["sha256"], "bytes": v["bytes"]} for k, v in rec["files"].items() if k in ("readme", "license")},
                   "extra": {k: {"sha256": v["sha256"], "bytes": v["bytes"]} for k, v in (rec["files"].get("extra") or {}).items()} or None,
                   "snapshot": "github/%s/%s" % (g.replace("/", "--"), rec["sha"])})
    if build is None:
        build = lf.load(PARAMS_BUILD)
    latest = None
    try:
        li = hf.repo_info(entry["repo"], "main")
        latest = li["sha"] if li["sha"] != entry["revision"] else None
    except hf.HFError:
        pass
    res = mp.analyze({"repo": entry["repo"], "revision": entry["revision"], "file": entry["file"], "entry": entry, "meta": meta,
                      "docs": docs, "doc_meta": doc_meta, "snap": snap, "bsnap": bsnap, "configs": cfgs, "chain": chain,
                      "templates": tmpls, "build": build, "curated": cur, "latest_revision": latest})
    entry["base_chain"] = chain or None
    entry["github"] = gh or None
    entry["github_dropped"] = [{"repo": g, "why": w} for g, w in dropped] or None
    entry["descriptor"] = res["descriptor"]
    entry["card_commands"] = res["card_commands"] or None
    entry["required_params"] = res["required_params"]
    if res["template"]:
        t = dict(entry.get("chat_template") or {})
        t.update({k: v for k, v in res["template"].items() if k != "repo_path"})
        entry["chat_template"] = t
    entry["stop"] = dict(entry.get("stop") or {}, analysis=res["stop"]) if res["stop"] else entry.get("stop")
    entry["blockers"] = res["blockers"]
    entry["params_problems"] = res["problems"]
    entry["params_build"] = PARAMS_BUILD
    d = res["descriptor"]
    if (d.get("ctx") or {}).get("effective"):
        entry["native_ctx"], entry["native_ctx_source"] = res["required_params"]["native_ctx"], res["required_params"]["native_ctx_source"]
    if cur.get("role"):
        entry["roles"] = sorted(set([cur["role"]] + [r for r in entry.get("roles") or [] if r not in (cur.get("not_roles") or [])]))
    for r in cur.get("not_roles") or []:
        entry["roles"] = [x for x in entry.get("roles") or [] if x != r]
    if cur.get("license"):
        entry["license"], entry["license_source"] = cur["license"]["value"], cur["license"]["source"]
    entry["license_info"] = license_info(entry, snap, bsnap, cur)
    return entry


LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "License.txt", "license.txt", "LICENCE", "COPYING",
                 "LICENSE-MIT", "LICENSE-APACHE", "NOTICE", "NOTICE.md", "USE_POLICY.md", "Responsible_AI_License.md")
# lines that carry an obligation or a limit (quoted, never paraphrased)
OBLIGATION_RE = re.compile(r"(?i)(attribution|acceptable use|prohibited|use policy|non-?commercial|not (be )?valid in|"
                           r"does not apply in|monthly active|commercial (use|purposes)|you (must|shall) (not )?|must (retain|include|give|display|cause)|"
                           r"built with|powered by|notice file|export control|territory|indemnif|gated|agree to share)")


SPDX_LINKS = {"apache-2.0": "https://spdx.org/licenses/Apache-2.0.html", "mit": "https://spdx.org/licenses/MIT.html",
              "cc-by-nc-4.0": "https://spdx.org/licenses/CC-BY-NC-4.0.html", "cc-by-4.0": "https://spdx.org/licenses/CC-BY-4.0.html",
              "bsd-3-clause": "https://spdx.org/licenses/BSD-3-Clause.html", "gpl-3.0": "https://spdx.org/licenses/GPL-3.0-only.html",
              "cc-by-sa-4.0": "https://spdx.org/licenses/CC-BY-SA-4.0.html", "openrail": "https://huggingface.co/blog/open_rail"}


def _url_of(repo, rev, path):
    return "https://huggingface.co/%s/blob/%s/%s" % (repo, rev, path)


def license_info(entry, snap, bsnap, cur=None, max_quotes=8):
    """{id, name, source, texts: [{file, path, sha256, bytes, what}], link, obligations: [{quote, source}],
    gated, unknown}: the exact license of an entry, where its full text is, and the lines that oblige
    or limit, quoted with file:line. Nothing is inferred: no id stays "unknown"."""
    cur = cur or {}
    d = entry.get("descriptor") or {}
    def eff(k):
        return (d.get(k) or {}).get("effective"), (d.get(k) or {}).get("source")
    fm_id, fm_src = None, None
    for s_, lab in ((snap, entry["repo"]), (bsnap, entry.get("base_model"))):
        cd = (s_ or {}).get("card_data") or {}
        if cd.get("license"):
            fm_id, fm_src = cd["license"], "%s card front matter license" % lab
            if fm_id == "other" and cd.get("license_name"):
                fm_id, fm_src = cd["license_name"], "%s card front matter license_name" % lab
            break
    lid, lsrc = fm_id, fm_src
    if not lid and entry.get("license") not in (None, "unknown") and re.search(r"card license|GGUF", str(entry.get("license_source"))):
        lid, lsrc = entry["license"], entry["license_source"]      # the card front matter as ingest parsed it
    if not lid:
        g = (entry.get("gguf_meta") or {}).get("general.license")
        if g:
            lid, lsrc = g, "GGUF general.license"
    cl = cur.get("license") or {}
    if cl.get("id"):
        lid, lsrc = cl["id"], cl.get("source")
    texts, quotes = [], []
    for s_, lab in ((snap, entry["repo"]), (bsnap, entry.get("base_model"))):
        if not s_:
            continue
        for n in LICENSE_NAMES:
            fp = os.path.join(s_["dir"], n)
            if os.path.isfile(fp):
                b = open(fp, "rb").read()
                texts.append({"file": "%s@%s/%s" % (lab, s_["revision"][:12], n), "path": fp, "url": _url_of(lab, s_["revision"], n),
                              "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b), "what": "model"})
        for n in [x for x in LICENSE_NAMES if os.path.isfile(os.path.join(s_["dir"], x))] + ["README.md"]:
            fp = os.path.join(s_["dir"], n)
            if not os.path.isfile(fp):
                continue
            body = _read(fp).split("\n")
            start = 0
            if n == "README.md" and body and body[0].strip() == "---":   # skip the front matter
                start = next((i for i in range(1, len(body)) if body[i].strip() == "---"), 0) + 1
            for i in range(start, len(body)):
                t = " ".join(body[i].split())
                if 20 < len(t) and OBLIGATION_RE.search(t):
                    quotes.append({"quote": t[:300] + ("..." if len(t) > 300 else ""), "source": "%s %s:L%d" % (lab, n, i + 1)})
                    if sum(1 for q in quotes if q["source"].startswith("%s %s:" % (lab, n))) >= max_quotes:
                        break
    for g in entry.get("github") or []:
        lfile = ((g.get("files") or {}).get("license") or {})
        if lfile.get("path"):
            fp = os.path.join(hf.meta_root(), g["snapshot"], lfile["path"])
            texts.append({"file": "github.com/%s@%s/%s" % (g["resolved"], g["sha"][:12], lfile["path"]),
                          "path": fp if os.path.isfile(fp) else None,
                          "url": "https://github.com/%s/blob/%s/%s" % (g["resolved"], g["sha"], lfile["path"]),
                          "sha256": lfile.get("sha256"), "bytes": lfile.get("bytes"),
                          "what": "code (GitHub %s, spdx %s)" % (g["resolved"], g.get("license_spdx"))})
    link, link_src = eff("license_link")
    if link and not re.match(r"https?://", str(link)):
        base_lab = entry["repo"]
        link = _url_of(base_lab, entry["revision"], link)
    if not link:
        mt = [t for t in texts if t["what"] == "model"]
        link = mt[0]["url"] if mt else None
        link_src = "license file in the repo" if mt else None
    if not link and lid and SPDX_LINKS.get(str(lid).lower()):
        link, link_src = SPDX_LINKS[str(lid).lower()], "SPDX license list (standard text of %s)" % lid
    gated = bool((snap or {}).get("gated")) or bool((bsnap or {}).get("gated"))
    if gated:
        quotes.insert(0, {"quote": "gated repo: Hugging Face asks you to accept its terms before download", "source": "HF API gated"})
    out = {"id": lid or "unknown", "id_source": lsrc, "name": eff("license_name")[0] or (cl.get("value") if cl else None),
           "summary": entry.get("license"), "summary_source": entry.get("license_source"),
           "link": link, "link_source": link_src, "texts": texts or None, "obligations": quotes or None,
           "gated": gated, "unknown": not lid,
           # every license statement seen up the base chain; a base model's license is NOT the fine-tune's
           "seen": [v for v in ((d.get("license") or {}).get("values") or [d.get("license")] if d.get("license") else [])] or None}
    return out


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
            try:
                info = hf.repo_info(repo, t["revision"] or "main")
                info.setdefault("id", repo)
                hf.print_plan(repo, info["sha"], hf.plan_rows(info, (), args.max_bytes), sys.stderr, "dry run: ")
            except hf.HFError as ex:
                log("  dry run: %s" % ex)
            continue
        try:
            e = ingest(repo, t["revision"], file, local=t["local"], found_in=sorted(set(t["found_in"])), match=t["match"],
                       max_bytes=args.max_bytes, db_dir=args.db_dir)
            e["roles"] = sorted(set(e["roles"] + [r for r in t["roles"] if r]))
            save(e, args.db_dir)
            import model_license          # metadata only: printed, no acceptance needed (no weights fetched)
            model_license.summary(e)
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


PROJECTED = ("db_id", "base_model", "base_revision", "card_defaults", "card_default_set", "card_defaults_source",
             "card_sampling_modes", "card_default_mode", "card_ctx", "card_ctx_source", "bytes", "license", "ctx",
             "native_ctx", "native_ctx_source", "required", "chat_template_repo", "chat_template_revision",
             "chat_template_path", "chat_template_sha256", "blockers", "weights")


def chat_template_file(e):
    """{repo, revision, file, sha256} of the repo template a launch must pass with --chat-template-file,
    or None when the GGUF's own template is used. file "X.json:key" means: take X.json's key."""
    t = e.get("chat_template") or {}
    if t.get("use") != "repo" or not t.get("repo_sha256"):
        return None
    lab = t.get("repo_label") or e["repo"]
    rev = e.get("base_revision") if lab == e.get("base_model") else e["revision"]
    return {"repo": lab, "revision": rev, "file": t.get("repo_file"), "sha256": t["repo_sha256"]}


def required_compact(e):
    """REQUIRED server items as "flag value" strings (client-side ones as "@x value")."""
    out = []
    for it in (e.get("required_params") or {}).get("items") or []:
        if it["class"] == mp.REQ:
            out.append(it["flag"] + ("" if it.get("value") is None else " " + str(it["value"])))
    return out or None


def manifest_projection(e):
    """The entry's fields carried into the code-bootstraps manifest candidate. A key whose entry value
    is None is listed with None, so project_manifest removes a stale copy."""
    return {"db_id": e["id"], "base_model": e.get("base_model"), "base_revision": e.get("base_revision"),
            "card_defaults": e.get("card_defaults"), "card_default_set": e.get("card_default_set"),
            "card_defaults_source": e.get("card_defaults_source"), "card_sampling_modes": e.get("card_sampling_modes"),
            "card_default_mode": e.get("card_default_mode"), "card_ctx": e.get("card_ctx"), "card_ctx_source": e.get("card_ctx_source"),
            "bytes": e.get("bytes"), "license": e.get("license"), "ctx": e.get("ctx"),
            "native_ctx": e.get("native_ctx"), "native_ctx_source": e.get("native_ctx_source"),
            "required": required_compact(e),
            # flat, so the launchers' manifest.awk can read them
            "chat_template_repo": (chat_template_file(e) or {}).get("repo"),
            "chat_template_revision": (chat_template_file(e) or {}).get("revision"),
            "chat_template_path": (chat_template_file(e) or {}).get("file"),
            "chat_template_sha256": (chat_template_file(e) or {}).get("sha256"),
            "blockers": [b["what"] if isinstance(b, dict) else b for b in e.get("blockers") or []] or None,
            "weights": e.get("weights") if e.get("weights", "").startswith("absent") else None}


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
            if k == "license" and c.get("license") and (v == "unknown" or str(c["license"]).split()[0] == str(v).split()[0]):
                continue                # the manifest's longer wording (notice, code license) of the same license
            if v is None:
                c.pop(k, None)          # stale copy of a value the entry no longer has
            else:
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


OVERRIDE_ALIASES = {"ctx": "ctx-size", "ctx-size": "ctx", "parallel": "np"}


def _ovr(reasons, flag):
    k = flag.lstrip("-")
    return reasons.get(k) or reasons.get(OVERRIDE_ALIASES.get(k, "")) or None


def runtime_build(graph, node):
    rt = (graph.get("runtimes") or {}).get(node.get("runtime")) or {}
    name = lf.build_for_runtime(rt)
    return name, (lf.load(name) if name else None)


def node_params(graph, name, entry):
    """Model parameters a node must launch with (#51): (argv, errors, notes).
    argv holds the REQUIRED and RECOMMENDED items resolved for the node's ctx / slots, the
    node's sampling overrides applied; RECOMMENDED items with node.override_reasons.<flag>
    are left out. errors: blockers, unsupported flags, ctx past the native window, missing
    template files, undecided template mismatches."""
    n = graph["nodes"][name]
    rp = entry.get("required_params")
    if not rp:
        return [], ["model database entry %s has no required_params (scripts/model_db.py refresh)" % entry["id"]], []
    reasons = n.get("override_reasons") or {}
    bname, build = runtime_build(graph, n)
    ctx, par = n.get("ctx"), n.get("parallel") or 1
    drop = []
    for it in rp["items"]:
        if it["class"] == mp.REC and _ovr(reasons, it["flag"]):
            drop.append(it["flag"])
    samp = launch_sampling(entry, n) if rp.get("kind") == "chat" else {}
    for k in samp:
        drop.append(SAMPLING_FLAGS[k])
    argv, errs, notes = mp.launch_items(rp, ctx, par, build, drop=tuple(drop))
    if str(entry.get("weights") or "").startswith("absent"):
        errs.insert(0, "not runnable yet: %s has weights: %s (metadata only); fetch %s first: scripts/add-model.sh --fetch %s@%s --file %s"
                    % (entry["id"], entry["weights"], entry["file"], entry["repo"], entry["revision"], entry["file"]))
    for k, v in samp.items():
        argv += [SAMPLING_FLAGS[k], str(v)]
    out, i = [], 0
    while i < len(argv):          # resolve ${template:<sha>} to this host's stored template
        a = argv[i]
        if i + 1 < len(argv) and argv[i + 1].startswith("${template:"):
            sha = argv[i + 1][len("${template:"):-1]
            pth = template_path(sha)
            if pth is None:
                errs.append("%s needs the chat template %s (%s) but it is not under %s on this host (scripts/model_db.py refresh fetches it)"
                            % (a, sha[:12], entry["id"], hf.meta_root()))
                i += 2
                continue
            out += [a, pth]
            i += 2
            continue
        out.append(a)
        i += 1
    for b in entry.get("blockers") or []:
        errs.append("BLOCKER (%s): %s" % (b.get("source") or "model database", b["what"]))
    for pr in entry.get("params_problems") or []:
        if pr.startswith("chat template:") or pr.startswith("curated"):
            errs.append(pr)
    arch = entry.get("arch")
    if build and build.get("archs") is not None and arch and arch not in build["archs"]:
        errs.append("BLOCKER: llama.cpp %s cannot load architecture %r (not in its src/llama-arch.cpp)" % (bname, arch))
    if build is None and (graph.get("runtimes") or {}).get(n.get("runtime"), {}).get("kind") == "llama-server":
        notes.append("runtime %s: no flag table (registry/llama-builds), flag support is unverified" % n.get("runtime"))
    for it in rp["items"]:
        if it["flag"] == "@runtime" and it["class"] == mp.REQ:
            if not (build and build.get("archs") and arch in build["archs"]):
                errs.append("BLOCKER: %s needs %s (%s)" % (entry["id"], it["value"], it["source"]))
    return out, errs, notes


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
        kind = (e.get("required_params") or {}).get("kind")
        if n.get("embeddings") and kind not in (None, "embed"):
            errs.append("%s: embeddings: true but %s is a %s model" % (w, e["id"], kind))
        if kind == "embed" and not n.get("embeddings"):
            errs.append("%s: %s is an embedding model; set embeddings: true" % (w, e["id"]))
        if (graph.get("runtimes") or {}).get(n.get("runtime"), {}).get("kind", "llama-server") == "llama-server":
            try:
                pargv, perrs, pnotes = node_params(graph, name, e)
            except Exception as ex:   # never let a bad entry pass silently
                perrs, pnotes = ["model parameters: %s" % ex], []
            for x in perrs:
                if n.get("status") == "planned":   # not launched yet: reported, not fatal
                    warns.append("%s (planned): %s" % (w, x))
                else:
                    errs.append("%s: %s" % (w, x))
            for x in pnotes:
                if x.startswith("runtime "):     # client-side requirements are listed by --explain
                    warns.append("%s: %s" % (w, x))
            rp = e.get("required_params") or {}
            for it in rp.get("items") or []:
                if it["class"] == mp.REC and _ovr(reasons, it["flag"]):
                    needed.add(it["flag"].lstrip("-"))
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
            if k not in needed and OVERRIDE_ALIASES.get(k) not in needed:
                warns.append("%s.override_reasons.%s: nothing overrides the card here (stale reason?)" % (w, k))
    return errs, warns


ROLE_FALLBACK = ("general", "coder", "decision", "embed", "language", "reranker", "jev")
GGUF_PREF = ("Q4_K_M", "Q4_K_S", "Q5_K_M", "Q8_0", "Q4_0", "Q6_K", "IQ4_XS", "Q3_K_M", "F16", "BF16")


def pick_main(info, file=None, quant=None):
    """The file an entry is about: --file, else the GGUF of --quant, else the first GGUF in GGUF_PREF
    order (first part of a split), else the main safetensors. -> (path, how) or (None, why)."""
    sib = {s["rfilename"]: s for s in info.get("siblings", [])}
    if file:
        hit = [p for p in sib if p == file or os.path.basename(p) == os.path.basename(file)]
        return (hit[0], "--file") if len(hit) == 1 else (None, "--file %s: %d matches" % (file, len(hit)))
    ggufs = [p for p in sib if p.lower().endswith(".gguf") and not am.classify_gguf_name(p)
             and (not am.SPLIT_RE.match(os.path.basename(p)) or "-00001-of-" in p)]
    if quant:
        hit = [p for p in ggufs if (am.quant_of(p) or "").upper() == quant.upper()]
        return (hit[0], "--quant %s" % quant) if len(hit) == 1 else (None, "--quant %s: %d GGUFs" % (quant, len(hit)))
    for q in GGUF_PREF:
        hit = [p for p in ggufs if (am.quant_of(p) or "").upper() == q]
        if hit:
            return sorted(hit)[0], "GGUF %s (preference %s)" % (q, "/".join(GGUF_PREF[:4]))
    if ggufs:
        return sorted(ggufs)[0], "only GGUF(s): %s" % ", ".join(sorted(ggufs)[:3])
    st = sorted(p for p in sib if p.endswith(".safetensors"))
    if st:
        main = next((p for p in st if os.path.basename(p) == "model.safetensors"), None) or next((p for p in st if "-00001-of-" in p), st[0])
        return main, "no GGUF; main safetensors"
    return None, "no GGUF or safetensors weights in the repo"


def infer_role(e, snap, roles=ROLE_FALLBACK):
    """add_model's evidence rules on what a damp run has: card front matter, config.json, the GGUF
    header (read remotely) and the file name. -> (role or None, [evidence lines])."""
    ev = am.Evidence()
    fm = (snap or {}).get("card_data") or {}
    title = None
    p = os.path.join(snap["dir"], "README.md") if snap else None
    if p and os.path.isfile(p):
        fm2, body, _ = am.split_card(_read(p))
        fm = dict(fm2 or {}, **{k: v for k, v in fm.items() if v})
        title = next((l.lstrip("# ").strip() for l in body.split("\n") if l.startswith("# ")), None)
    am.infer_from_card(ev, fm, title)
    cfg = read_snap_json(snap, "config.json") or {} if snap else {}
    am.infer_from_config(ev, cfg, bool(snap and os.path.isfile(os.path.join(snap["dir"], "decision_config.json"))))
    meta = dict(e.get("gguf_meta") or {})
    if meta:
        am.infer_from_gguf(ev, meta, e["file"])
    am.infer_from_filename(ev, e["file"])
    rp = (e.get("required_params") or {}).get("kind")
    if rp == "embed":
        ev.add("embed", 3, "model_params", "required_params kind embed")
    elif rp == "decision":
        ev.add("decision", 3, "model_params", "required_params kind decision")
    role, ranked = ev.decide(list(roles))
    lines = ["%s +%d (%s: %s)" % (x["role"], x["weight"], x["source"], x["why"]) for x in ev.items]
    # a speech / audio / image model is "generative" too, but it is not a familia text role
    pt = str(fm.get("pipeline_tag") or "")
    arch = str(meta.get("general.architecture") or "")
    why = None
    if pt in NON_TEXT_PIPELINES:
        why = "card pipeline_tag %s" % pt
    elif re.match(NON_TEXT_ARCH, arch):
        why = "GGUF general.architecture %s" % arch
    if why and role in ("general", None):
        return None, lines + ["no familia role: %s is not a text-generation model; classify by hand" % why]
    return role, lines + (["ranked: %s" % ranked] if not role else [])


NON_TEXT_PIPELINES = {"automatic-speech-recognition", "audio-classification", "audio-to-audio", "text-to-speech",
                      "text-to-audio", "voice-activity-detection", "text-to-image", "image-to-image",
                      "unconditional-image-generation", "text-to-video", "image-to-video", "image-classification",
                      "object-detection", "image-segmentation", "depth-estimation"}
NON_TEXT_ARCH = r"(sortformer|parakeet|audiocpp|whisper|wav2vec|moshi|qwen_image|flux|sd\d|stable.?diffusion|clip$|siglip)"


def damp(spec, file=None, quant=None, role=None, found_in=None, dry_run=False, max_bytes=hf.DEFAULT_MAX,
         db_dir=None, show_license=True):
    """Damp run of one HF repo: small files into hf-meta, weights listed (size, LFS sha256) but not
    downloaded, a database entry with weights: absent (damp) and an inferred role. Never downloads
    weights, so no license acceptance is needed; the license is printed. --dry-run prints the plan.
    -> {"repo", "revision", "entry" or None, "plan_totals", "why"}."""
    repo, _, rev = spec.partition("@")
    info = hf.repo_info(repo, rev or "main")
    info.setdefault("id", repo)
    main, how = pick_main(info, file, quant)
    rows = hf.plan_rows(info, (), max_bytes)
    tot = {}
    for r in rows:
        tot[r["status"]] = tot.get(r["status"], 0) + (r["size"] or 0)
    out = {"repo": repo, "revision": info["sha"], "main": main, "main_how": how, "gated": info.get("gated"),
           "repo_bytes": sum(r["size"] or 0 for r in rows), "plan_totals": tot, "entry": None,
           "license_card": ((info.get("cardData") or {}).get("license"))}
    if dry_run:
        hf.print_plan(repo, info["sha"], rows, sys.stderr, "dry run: ")
        log("dry run: main file %s (%s); card license %s; nothing written" % (main, how, out["license_card"]))
        return out
    if not main:
        snap = hf.snapshot(repo, info["sha"], max_bytes=max_bytes, log=log)
        out["fetched_bytes"] = snap["fetched_bytes"]
        out["why"] = how
        log("damp %s: %s; snapshot only, no database entry" % (repo, how))
        return out
    e = ingest(repo, info["sha"], main, role=role, found_in=found_in or ["model_db.py damp"], max_bytes=max_bytes,
               db_dir=db_dir, write=False, weights="absent (damp)")
    old = load(e["id"], db_dir)
    if old and not str(old.get("weights") or "").startswith("absent"):
        # an entry that already exists for weights in use is refreshed, never downgraded to damp
        if old.get("weights"):
            e["weights"] = old["weights"]
        else:
            e.pop("weights", None)
        out["existing"] = True
    if not role:
        r_, ev = infer_role(e, _snap_of(e.get("snapshot")))
        e["role_inference"] = {"role": r_, "evidence": ev}
        if r_:
            e["roles"] = sorted(set((e.get("roles") or []) + [r_]))
    e["repo_bytes"] = out["repo_bytes"]
    save(e, db_dir)
    out["entry"] = e
    out["fetched_bytes"] = (e.get("snapshot") or {}).get("fetched_bytes", 0) + ((e.get("base_snapshot") or {}).get("fetched_bytes") or 0)
    if show_license:
        import model_license
        model_license.summary(e)
    return out


def _snap_of(rec):
    if not rec:
        return None
    d = os.path.join(hf.meta_root(), rec["path"])
    try:
        with open(os.path.join(d, "snapshot.json"), encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return None
    j["dir"] = d
    return j


def refresh(db_dir=None, only=None, refresh_github=False, max_bytes=hf.DEFAULT_MAX):
    """Re-ingest every entry at its pinned revision (the local weights file when found)."""
    done, failures = [], []
    for eid, e in sorted(load_all(db_dir).items()):
        if only and only.lower() not in eid.lower():
            continue
        log("== refresh %s" % eid)
        try:
            n = ingest(e["repo"], e["revision"], e["file"], local=find_local(e["file"]), found_in=e.get("found_in"),
                       match=e.get("match"), max_bytes=max_bytes, db_dir=db_dir, refresh_github=refresh_github)
            done.append(n["id"])
        except hf.HFError as ex:
            failures.append({"what": eid, "why": str(ex)})
            log("  FAILED: %s" % ex)
    return done, failures


def _cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def params_doc(db_dir=None):
    """docs/model-params.md: per model, what a launch must pass and where each value comes from."""
    allents = load_all(db_dir)
    ents = {k: v for k, v in allents.items() if not str(v.get("weights") or "").startswith("absent")}
    damped = sorted(k for k in allents if k not in ents)
    out = ["# Model parameters (#51)", "",
           "Generated by `python3 scripts/model_db.py params-doc` from registry/models (do not edit by hand).",
           "Every value cites the card / config / GGUF / GitHub line it comes from; registry/model-params.yaml holds",
           "the curated decisions (each with a verified quote). REQUIRED items are enforced by `validate_graph.py --args`",
           "(and so scripts/serve.sh and the hermes harness): a node missing one does not start. RECOMMENDED items are",
           "added unless the node gives an override reason. Client items (`@...`) are for the caller, not llama-server.", "",
           "| model | kind | native ctx | REQUIRED (server) | client REQUIRED | RECOMMENDED | chat template | blockers |",
           "|---|---|---|---|---|---|---|---|"]
    for eid, e in sorted(ents.items()):
        rp = e.get("required_params") or {}
        its = rp.get("items") or []
        srv = [it["flag"] + ("" if it.get("value") is None else " " + str(it["value"])) for it in its if it["class"] == mp.REQ and not it.get("client")]
        cli = [it["flag"] + ("" if it.get("value") is None else " " + str(it["value"])[:40]) for it in its if it["class"] == mp.REQ and it.get("client")]
        rec = [it["flag"] + ("" if it.get("value") is None else " " + str(it["value"])) for it in its if it["class"] == mp.REC]
        t = e.get("chat_template") or {}
        tm = "repo %s (%s)" % (t.get("repo_sha256", "")[:12], t.get("repo_label")) if t.get("use") == "repo" else \
             ("GGUF %s" % t.get("gguf_sha256", "")[:12] if t.get("gguf_sha256") else "-")
        bl = "; ".join((b["what"] if isinstance(b, dict) else b) for b in e.get("blockers") or []) or "-"
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            "`%s`" % eid, rp.get("kind", "?"), "%s (%s)" % (rp.get("native_ctx"), rp.get("native_ctx_source")),
            "<br>".join("`%s`" % _cell(x) for x in srv) or "-", "<br>".join("`%s`" % _cell(x) for x in cli) or "-",
            "<br>".join("`%s`" % _cell(x) for x in rec) or "-", _cell(tm), _cell(bl)))
    for eid, e in sorted(ents.items()):
        rp = e.get("required_params") or {}
        out += ["", "## %s" % eid, "",
                "%s@%s `%s`, %s bytes, license %s" % (e["repo"], e["revision"][:10], e["file"], e.get("bytes"), e.get("license")), ""]
        for it in rp.get("items") or []:
            out.append("- **%s** `%s%s`%s - %s (%s)" % (it["class"], it["flag"], "" if it.get("value") is None else " " + str(it["value"]),
                       " (client)" if it.get("client") else "", _cell(it.get("why_required", "")), _cell(it.get("source", ""))))
        cmds = [c for c in e.get("card_commands") or [] if c.get("kind") != "inline"]
        if cmds:
            out += ["", "Card / GitHub examples (verbatim in the entry's `card_commands`):", ""]
            for c in cmds:
                out.append("- %s `%s` (%s)%s" % (c["source"], c.get("tool") or c.get("lang") or "?", c.get("scope", "model"),
                           " - translated" if c.get("translation") else ""))
        for p_ in e.get("params_problems") or []:
            out.append("- problem: %s" % _cell(p_))
    if damped:
        out += ["", "## Damp-run entries (metadata only, not runnable)", "",
                "Recorded by `model_db.py damp` with `weights: absent (damp)`; classify them and run a full fetch before",
                "their parameters are listed here (`registry/models/<id>.json` has what is known).", ""]
        out += ["- `%s`" % x for x in damped]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-dir", default=None, help="database directory (default registry/models)")
    ap.add_argument("--max-bytes", type=int, default=None, help="skip repo files larger than this (overrides --max-file-mb)")
    ap.add_argument("--max-file-mb", type=float, default=hf.DEFAULT_MAX / 1e6, metavar="N", help="small-file limit in MB (default %(default)g)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    dm = sp.add_parser("damp", help="damp-run repos: small files + a database entry with weights: absent (damp)",
                       epilog=hf.MODES_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    dm.add_argument("repos", nargs="+", metavar="ORG/NAME[@REV]")
    dm.add_argument("--file")
    dm.add_argument("--quant")
    dm.add_argument("--role")
    dm.add_argument("--found-in", action="append", help="where the repo was found (e.g. 'familia #53')")
    dm.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    dm.add_argument("--json", action="store_true", help="print the results as JSON")
    i = sp.add_parser("ingest")
    i.add_argument("repo")
    i.add_argument("file")
    i.add_argument("--local")
    i.add_argument("--role")
    b = sp.add_parser("backfill")
    b.add_argument("--dry-run", action="store_true", help="print each target's plan; write nothing")
    b.add_argument("--damp-run", action="store_true", help="the default for backfill: it never downloads weights")
    b.add_argument("--only")
    b.add_argument("--skip-search", action="store_true")
    b.add_argument("--no-manifest", action="store_true")
    b.add_argument("--no-graph", action="store_true")
    b.add_argument("--no-registry", action="store_true")
    b.add_argument("--bootstraps")
    r = sp.add_parser("refresh", help="re-ingest every entry at its pinned revision")
    r.add_argument("--only")
    r.add_argument("--refresh-github", action="store_true")
    pd = sp.add_parser("params-doc", help="write docs/model-params.md")
    pd.add_argument("--out", default=os.path.join(REPO_ROOT, "docs", "model-params.md"))
    s = sp.add_parser("show")
    s.add_argument("id")
    sp.add_parser("list")
    a = ap.parse_args(argv)
    a.max_bytes = a.max_bytes or int(a.max_file_mb * 1e6)
    if a.cmd == "damp":
        res, rc = [], 0
        for spec in a.repos:
            try:
                r = damp(spec, a.file, a.quant, a.role, a.found_in, a.dry_run, a.max_bytes, a.db_dir)
            except hf.HFError as ex:
                log("model_db: damp %s: %s" % (spec, ex))
                r, rc = {"repo": spec, "error": str(ex), "status": getattr(ex, "status", None)}, 1
            e = r.pop("entry", None)
            if e:
                r.update({"id": e["id"], "roles": e.get("roles"), "license": (e.get("license_info") or {}).get("id"),
                          "weights": e.get("weights"), "bytes": e.get("bytes"), "role_inference": e.get("role_inference")})
            res.append(r)
        print(json.dumps(res, indent=1, ensure_ascii=False) if a.json else "\n".join(
            "%s: %s" % (x["repo"], x.get("error") or ("dry run" if a.dry_run else x.get("id") or x.get("why"))) for x in res))
        return rc
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
    if a.cmd == "refresh":
        done, failures = refresh(a.db_dir, a.only, a.refresh_github, a.max_bytes)
        print(json.dumps({"refreshed": len(done), "failures": failures}, indent=1))
        return 1 if failures else 0
    if a.cmd == "params-doc":
        am.atomic_write(a.out, params_doc(a.db_dir))
        log("wrote %s" % a.out)
        return 0
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
