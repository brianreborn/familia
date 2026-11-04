#!/usr/bin/env python3
"""hf_fetch.py: stdlib-only Hugging Face Hub client for the model database (#51).

Plain HTTPS through urllib: no pip dependencies, so it runs on ~15-year-old devices.
  * file list:  https://huggingface.co/api/models/ORG/NAME/revision/REV?blobs=true
  * downloads:  https://huggingface.co/ORG/NAME/resolve/REV/FILE
HF_TOKEN is sent when set (never printed, and dropped when a download redirects to
another host). Every fetch is pinned to a commit SHA; "main" is resolved first.

Snapshots go to  $FAMILIA_HF_META or $GGUF_HOME/hf-meta or ~/.local/share/gguf/hf-meta
as  ORG--NAME/REV/<files>  plus  snapshot.json  (every repo file with size and
LFS sha256 / git blob id, which were fetched and verified, which were skipped and why).
Large weight files (> --max-bytes, default 50 MB) are listed, never downloaded.
"""
import hashlib, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
WEIGHT_EXT = (".gguf", ".safetensors", ".bin", ".onnx", ".pt", ".pth", ".ckpt", ".h5", ".msgpack",
              ".tflite", ".mlmodel", ".npz", ".pte", ".nemo", ".model.bin", ".data")
DEFAULT_MAX = 50 * 1000 * 1000
UA = "familia-model-db/1 (stdlib urllib)"


class HFError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def meta_root():
    r = os.environ.get("FAMILIA_HF_META")
    if r:
        return os.path.expanduser(r)
    gh = os.environ.get("GGUF_HOME") or os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "gguf")
    return os.path.join(os.path.expanduser(gh), "hf-meta")


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects but drop the Authorization header when the host changes."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            for h in list(new.headers):
                if h.lower() == "authorization":
                    del new.headers[h]
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_opener = urllib.request.build_opener(_NoAuthRedirect)


def _request(url, headers=None, timeout=60, retries=3):
    h = {"User-Agent": UA}
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if tok and url.startswith(ENDPOINT):
        h["Authorization"] = "Bearer " + tok
    h.update(headers or {})
    last = None
    for i in range(retries):
        try:
            return _opener.open(urllib.request.Request(url, headers=h), timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 410, 416):
                body = ""
                try:
                    body = e.read(300).decode("utf-8", "replace")
                except Exception:
                    pass
                why = {401: "unauthorized (gated or private; set HF_TOKEN)", 403: "forbidden (gated: accept the license on huggingface.co, set HF_TOKEN)",
                       404: "not found (renamed, deleted or wrong revision)", 410: "gone", 416: "range not satisfiable"}[e.code]
                raise HFError("%s: HTTP %d %s %s" % (_safe(url), e.code, why, body.strip()[:160]), e.code)
            last = e
        except (urllib.error.URLError, OSError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise HFError("%s: %s" % (_safe(url), last))


def _safe(url):
    return url.split("?")[0]


def repo_info(repo, revision="main"):
    url = "%s/api/models/%s/revision/%s?blobs=true" % (ENDPOINT, repo, urllib.parse.quote(revision or "main", safe=""))
    with _request(url) as r:
        info = json.load(r)
    if not re.fullmatch(r"[0-9a-f]{40}", info.get("sha") or ""):
        raise HFError("%s@%s: API returned no commit sha" % (repo, revision))
    return info


def resolve_url(repo, rev, path):
    return "%s/%s/resolve/%s/%s" % (ENDPOINT, repo, rev, urllib.parse.quote(path))


def git_blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch_range(repo, rev, path, nbytes):
    with _request(resolve_url(repo, rev, path), headers={"Range": "bytes=0-%d" % (nbytes - 1)}, timeout=120) as r:
        return r.read(nbytes)


def download(repo, rev, sib, dest):
    """Download one sibling to dest via hf_cache (sidecar revalidation, Range/If-Range resume,
    sha256 before an atomic rename) and verify LFS sha256 / git blob sha1."""
    import hf_cache
    path = sib["rfilename"]
    size = sib.get("size")
    lfs = sib.get("lfs") or {}
    h = {"User-Agent": UA}
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    url = resolve_url(repo, rev, path)
    if tok and url.startswith(ENDPOINT):
        h["Authorization"] = "Bearer " + tok
    try:
        res = hf_cache.fetch(url, dest, sha256=lfs.get("sha256"), size=size, headers=h, opener=_opener)
    except hf_cache.FetchError as e:
        raise HFError("%s: %s" % (path, e))
    sha, n = res["sha256"], res["size"]
    verified = "lfs-sha256" if lfs.get("sha256") else None
    if not lfs and sib.get("blobId") and size is not None:
        s1 = hashlib.sha1(b"blob %d\0" % size)
        hf_cache.sha256_file(dest, s1)
        if s1.hexdigest() != sib["blobId"]:
            for p in (dest, dest + ".meta.json"):
                if os.path.exists(p):
                    os.unlink(p)
            raise HFError("%s: git blob sha1 %s != %s" % (path, s1.hexdigest(), sib["blobId"]))
        verified = "git-blob-sha1"
    return sha, n, verified


def is_weight(path):
    p = path.lower()
    return p.endswith(WEIGHT_EXT) or re.search(r"\.(gguf|safetensors|bin)\.part\d+$", p) is not None


def plan(info, keep=(), max_bytes=DEFAULT_MAX):
    """(fetch, skip): every file up to max_bytes is fetched (small weights such as a
    tokenizer .bin too); anything larger (other quants, safetensors, big mmproj) is
    skipped but still listed with its size and LFS sha256 in snapshot.json."""
    fetch, skip = [], []
    for s in info.get("siblings", []):
        p = s["rfilename"]
        size = s.get("size") or (s.get("lfs") or {}).get("size") or 0
        if p in keep and size <= max_bytes:
            fetch.append(s)
        elif p.lower().endswith((".gguf", ".safetensors", ".pt", ".pth", ".onnx")) or re.search(r"\.(gguf|safetensors)\.part\d+$", p.lower()):
            # model weights, however small: only a full run downloads them, after the license is accepted
            skip.append((s, "weight file, fetched only by a full run (%d MB)" % (size // 1000000)))
        elif size > max_bytes:
            skip.append((s, ("weight file not used here (%d MB)" if is_weight(p) else "larger than the limit (%d MB)")
                         % (size // 1000000)))
        else:
            fetch.append(s)
    return fetch, skip


def sibling_record(s):
    lfs = s.get("lfs") or {}
    return {"size": s.get("size") if s.get("size") is not None else lfs.get("size"),
            "sha256": lfs.get("sha256"), "blob": s.get("blobId"), "lfs": bool(lfs)}


def snapshot(repo, revision=None, keep=(), max_bytes=DEFAULT_MAX, root=None, log=None, dry_run=False):
    """Fetch the small files of repo@revision. Returns the snapshot dict (also written
    as snapshot.json). Existing verified files are not downloaded again."""
    log = log or (lambda m: print(m, file=sys.stderr))
    info = repo_info(repo, revision or "main")
    rev = info["sha"]
    d = os.path.join(root or meta_root(), repo.replace("/", "--"), rev)
    snap_path = os.path.join(d, "snapshot.json")
    old = {}
    if os.path.isfile(snap_path):
        try:
            with open(snap_path, encoding="utf-8") as f:
                old = json.load(f).get("files", {})
        except (OSError, ValueError):
            old = {}
    fetch, skip = plan(info, keep, max_bytes)
    files, errors, total = {}, [], 0
    for s in info.get("siblings", []):
        files[s["rfilename"]] = sibling_record(s)
    for s, why in skip:
        files[s["rfilename"]].update({"fetched": False, "skipped": why})
    for s in fetch:
        p = s["rfilename"]
        rec = files[p]
        dest = os.path.join(d, p)
        o = old.get(p) or {}
        if o.get("fetched") and os.path.isfile(dest) and os.path.getsize(dest) == rec["size"]:
            rec.update({k: o[k] for k in ("local_sha256", "verified") if k in o})
            rec["fetched"] = True
            total += rec["size"] or 0
            continue
        if dry_run:
            rec.update({"fetched": False, "skipped": "dry run"})
            continue
        try:
            sha, n, ver = download(repo, rev, s, dest)
            rec.update({"fetched": True, "local_sha256": sha, "verified": ver})
            total += n
        except HFError as e:
            rec.update({"fetched": False, "error": str(e)})
            errors.append(str(e))
            log("  ! %s" % e)
    snap = {"repo": repo, "revision": rev, "requested": revision or "main", "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "dir": d, "gated": info.get("gated", False), "private": info.get("private", False),
            "card_data": info.get("cardData"), "pipeline_tag": info.get("pipeline_tag"), "tags": info.get("tags"),
            "library_name": info.get("library_name"), "fetched_bytes": total,
            "api_id": info.get("id"), "author": info.get("author"), "last_modified": info.get("lastModified"),
            "safetensors": info.get("safetensors"), "gguf": _gguf_info(info.get("gguf")),
            "files": files, "errors": errors}
    if not dry_run:
        os.makedirs(d, exist_ok=True)
        tmp = snap_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=1, sort_keys=True)
        os.replace(tmp, snap_path)
    return snap


def _gguf_info(g):
    """The API's gguf block without the template text (its sha256 instead)."""
    if not isinstance(g, dict):
        return None
    out = {k: v for k, v in g.items() if k != "chat_template"}
    if isinstance(g.get("chat_template"), str):
        out["chat_template_sha256"] = hashlib.sha256(g["chat_template"].encode("utf-8")).hexdigest()
    return out


def gguf_remote_header(repo, rev, path, parse, start=4 << 20, limit=64 << 20):
    """GGUF header KVs of a remote file via HTTP Range (no weights): grows the range
    until parse() stops raising 'truncated'. parse takes a file path."""
    import tempfile
    n = start
    while True:
        data = fetch_range(repo, rev, path, n)
        with tempfile.NamedTemporaryFile(suffix=".gguf-header", delete=False) as t:
            t.write(data)
        try:
            return parse(t.name)
        except ValueError as e:
            if "truncated" not in str(e) or n >= limit or len(data) < n:
                raise
            n *= 4
        finally:
            os.unlink(t.name)


# ------------------------------------------------------------------ GitHub READMEs a card links (#51)
GH_API = "https://api.github.com"
GH_TOOL_REPOS = {  # inference / training tools: their READMEs say nothing about one model
    "ggml-org/llama.cpp", "ggerganov/llama.cpp", "vllm-project/vllm", "sgl-project/sglang", "huggingface/transformers",
    "huggingface/trl", "huggingface/text-generation-inference", "huggingface/lighteval", "huggingface/nanotron",
    "huggingface/alignment-handbook", "huggingface/transformers.js", "huggingface/huggingface_hub", "ollama/ollama",
    "ml-explore/mlx", "ml-explore/mlx-examples", "ml-explore/mlx-lm", "unslothai/unsloth", "unslothai/notebooks",
    "kvcache-ai/ktransformers", "QwenLM/Qwen-Agent", "QwenLM/qwen-code", "lm-sys/FastChat", "arcee-ai/mergekit",
    "UKPLab/sentence-transformers", "huggingface/sentence-transformers", "nomic-ai/gpt4all", "LostRuins/koboldcpp",
    "mudler/LocalAI", "lmstudio-ai/lms", "turboderp/exllamav2", "intel/neural-compressor", "openvinotoolkit/openvino",
    "ggml-org/convert", "NVIDIA/TensorRT-LLM", "microsoft/onnxruntime", "pytorch/executorch", "google-ai-edge/LiteRT", "embodiedreasoning/ERQA",
}


def github_links(text):
    """owner/repo of every github.com link in text, in order, without duplicates."""
    out = []
    for m in re.finditer(r"https?://github\.com/([A-Za-z0-9][\w.-]*)/([\w.-]+?)(?:\.git)?(?=[/#?)\s\]'\">`]|$)", text):
        r = "%s/%s" % (m.group(1), m.group(2))
        if r.lower() not in [x.lower() for x in out] and m.group(1).lower() not in ("orgs", "settings", "sponsors", "features"):
            out.append(r)
    return out


def official_github(links, hf_repos):
    """Keep the links that belong to the model: the GitHub owner matches an HF org of the
    model or its base (one a prefix of the other, case-insensitive), or the repo name shares
    a 4+ character word with a model name. Tool repos are dropped. -> (kept, dropped-with-reason)."""
    orgs = {r.split("/")[0].lower() for r in hf_repos if r}
    words = set()
    for r in hf_repos:
        if r:
            words |= {w for w in re.split(r"[^a-z0-9]+", r.split("/")[-1].lower().replace("gguf", "")) if len(w) >= 4}
    kept, dropped = [], []
    for g in links:
        own, name = g.split("/")
        if g.lower() in {x.lower() for x in GH_TOOL_REPOS} or name.lower() in ("llama.cpp", "ollama", "vllm", "sglang"):
            dropped.append((g, "inference/training tool repo"))
            continue
        if own.lower() == "huggingface":
            dropped.append((g, "Hugging Face tool repo"))
            continue
        nw = {w for w in re.split(r"[^a-z0-9]+", name.lower()) if len(w) >= 4}
        if any(own.lower().startswith(o) or o.startswith(own.lower()) for o in orgs if len(o) >= 3) or (nw & words):
            kept.append(g)
        else:
            dropped.append((g, "owner and name unrelated to the model's Hugging Face repos"))
    return kept, dropped


def _gh_json(path):
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(GH_API + path, headers=h)
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 451):
                return None
            last = e
            if e.code in (401, 403):
                break
        except (urllib.error.URLError, OSError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise HFError("GitHub %s: %s" % (path, last))


def github_snapshot(repo, root=None, ref=None, log=None, extra=()):
    """README (and LICENSE, plus `extra` paths) of a GitHub repo at one commit, stored under
    <meta_root>/github/<owner>--<repo>/<sha>/ with github.json. A stored snapshot is reused
    (refresh=True in the caller removes it first)."""
    log = log or (lambda m: print(m, file=sys.stderr))
    base = os.path.join(root or meta_root(), "github", repo.replace("/", "--"))
    if ref is None and os.path.isdir(base):
        for sha in sorted(os.listdir(base)):
            p = os.path.join(base, sha, "github.json")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    rec = json.load(f)
                missing = [x for x in extra if x not in rec["files"].get("extra", {})]
                for x in missing:
                    _gh_extra(rec, x, log)
                if missing:
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(rec, f, indent=1, sort_keys=True)
                rec["dir"] = os.path.join(base, sha)
                return rec
    info = _gh_json("/repos/%s" % repo)
    if info is None:
        return {"repo": repo, "error": "not found"}
    commit = _gh_json("/repos/%s/commits/%s" % (repo, urllib.parse.quote(ref or info["default_branch"], safe="")))
    sha = commit["sha"]
    d = os.path.join(base, sha)
    os.makedirs(d, exist_ok=True)
    rec = {"repo": info["full_name"], "requested": repo, "sha": sha, "ref": ref or info["default_branch"], "dir": d,
           "description": info.get("description"), "license_spdx": (info.get("license") or {}).get("spdx_id"),
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": {}}
    for kind, path in (("readme", "/repos/%s/readme?ref=%s" % (repo, sha)), ("license", "/repos/%s/license?ref=%s" % (repo, sha))):
        meta = _gh_json(path)
        if not meta or not meta.get("download_url"):
            continue
        name = meta.get("path") or meta.get("name")
        raw = "https://raw.githubusercontent.com/%s/%s/%s" % (info["full_name"], sha, urllib.parse.quote(name))
        with _request(raw) as r:
            data = r.read()
        dest = os.path.join(d, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        rec["files"][kind] = {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": raw}
        log("  github %s@%s %s (%d bytes)" % (repo, sha[:10], name, len(data)))
    for x in extra:
        _gh_extra(rec, x, log)
    with open(os.path.join(d, "github.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
    return rec


def _gh_extra(rec, path, log):
    raw = "https://raw.githubusercontent.com/%s/%s/%s" % (rec["repo"], rec["sha"], urllib.parse.quote(path))
    try:
        with _request(raw) as r:
            data = r.read()
    except HFError as e:
        rec["files"].setdefault("extra_errors", {})[path] = str(e)
        return
    dest = os.path.join(rec["dir"], path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    rec["files"].setdefault("extra", {})[path] = {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": raw}
    log("  github %s@%s %s (%d bytes)" % (rec["repo"], rec["sha"][:10], path, len(data)))


# ------------------------------------------------------------------ run modes (shared by the model scripts)
MODES_HELP = """run modes (every model script):
  (default)        full run: small files, and the weights the command is for
  --dry-run        no file writes, no network writes: prints the plan (every file, size,
                   sha, and whether it is present, would be fetched, or is skipped as large)
  --damp-run       fetches only the missing small files (card, config, generation_config,
                   tokenizer*, chat templates, license, small json/txt: up to --max-file-mb);
                   weights and large files are skipped but recorded with size and LFS sha256,
                   and the database entry is marked weights: absent (damp)
  --max-file-mb N  the small-file limit (default 50)"""


def add_mode_args(ap, dry_help=None):
    """--dry-run / --damp-run / --max-file-mb on an argparse parser (mutually exclusive modes)."""
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help=dry_help or "print the plan; write nothing (no file or network writes)")
    g.add_argument("--damp-run", action="store_true", help="fetch only the missing small files; record weights (size, sha256) without downloading them")
    ap.add_argument("--max-file-mb", type=float, default=DEFAULT_MAX / 1e6, metavar="N",
                    help="small-file limit for snapshots and damp runs, in MB (default %(default)g)")
    return ap


def max_bytes_of(args):
    return int(float(getattr(args, "max_file_mb", None) or DEFAULT_MAX / 1e6) * 1000 * 1000)


def plan_rows(info, keep=(), max_bytes=DEFAULT_MAX, root=None, want=()):
    """[{path, size, sha256, blob, status}] for repo info: status is present / fetch / skip-large /
    skip-weight; files in `want` (the weights a full run downloads) are 'weight-wanted'."""
    rev = info["sha"]
    d = os.path.join(root or meta_root(), info.get("id", "").replace("/", "--") if info.get("id") else "", rev)
    old = {}
    sp = os.path.join(d, "snapshot.json")
    if os.path.isfile(sp):
        try:
            with open(sp, encoding="utf-8") as f:
                old = json.load(f).get("files", {})
        except (OSError, ValueError):
            old = {}
    fetch, skip = plan(info, keep, max_bytes)
    fset = {s["rfilename"] for s in fetch}
    rows = []
    for s in info.get("siblings", []):
        p = s["rfilename"]
        r = sibling_record(s)
        o = old.get(p) or {}
        present = o.get("fetched") and os.path.isfile(os.path.join(d, p)) and os.path.getsize(os.path.join(d, p)) == r["size"]
        if present:
            st = "present"
        elif p in want:
            st = "weight-wanted"
        elif p in fset:
            st = "fetch"
        else:
            st = "skip-weight" if is_weight(p) else "skip-large"
        rows.append({"path": p, "size": r["size"], "sha256": r["sha256"], "blob": r["blob"], "status": st})
    return rows


def print_plan(repo, rev, rows, out=None, header=""):
    out = out or sys.stderr
    tot = {}
    for r in rows:
        tot[r["status"]] = tot.get(r["status"], 0) + (r["size"] or 0)
    out.write("%splan for %s@%s (%d files):\n" % (header, repo, rev[:10], len(rows)))
    for r in rows:
        out.write("  %-13s %12s  %s  %s\n" % (r["status"], "{:,}".format(r["size"] or 0), (r["sha256"] or ("blob " + str(r["blob"])))[:20], r["path"]))
    out.write("  totals: " + ", ".join("%s %.1f MB" % (k, v / 1e6) for k, v in sorted(tot.items())) + "\n")
    return tot


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Fetch the small files of a Hugging Face repo, pinned to a commit. "
                                 "This script never downloads weights, so a normal run and --damp-run are the same.",
                                 epilog=MODES_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="ORG/NAME[@REV]")
    ap.add_argument("--keep", action="append", default=[], help="also fetch this file even if it is a weight")
    ap.add_argument("--max-bytes", type=int, default=None, help="small-file limit in bytes (overrides --max-file-mb)")
    add_mode_args(ap)
    a = ap.parse_args()
    r, _, v = a.repo.partition("@")
    mb = a.max_bytes or max_bytes_of(a)
    try:
        if a.dry_run:
            info = repo_info(r, v or "main")
            info.setdefault("id", r)
            print_plan(r, info["sha"], plan_rows(info, a.keep, mb), sys.stdout, "dry run: ")
            sys.exit(0)
        s = snapshot(r, v or None, a.keep, mb)
    except HFError as e:
        print("hf_fetch: %s" % e, file=sys.stderr)
        sys.exit(1)
    print(json.dumps({k: s[k] for k in ("repo", "revision", "dir", "fetched_bytes", "errors")}, indent=1))
