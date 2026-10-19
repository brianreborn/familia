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
    """Download one sibling to dest (atomic) and verify LFS sha256 / git blob sha1."""
    path = sib["rfilename"]
    tmp = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    h = hashlib.sha256()
    s1 = hashlib.sha1()
    size = sib.get("size")
    if size is not None and not sib.get("lfs"):
        s1.update(b"blob %d\0" % size)
    n = 0
    with _request(resolve_url(repo, rev, path), timeout=300) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            h.update(b)
            s1.update(b)
            n += len(b)
    sha = h.hexdigest()
    lfs = sib.get("lfs") or {}
    if size is not None and n != size:
        os.unlink(tmp)
        raise HFError("%s: size %d != listed %d" % (path, n, size))
    if lfs.get("sha256") and lfs["sha256"] != sha:
        os.unlink(tmp)
        raise HFError("%s: sha256 %s != LFS %s" % (path, sha, lfs["sha256"]))
    verified = "lfs-sha256" if lfs.get("sha256") else None
    if not lfs and sib.get("blobId") and size is not None:
        if s1.hexdigest() != sib["blobId"]:
            os.unlink(tmp)
            raise HFError("%s: git blob sha1 %s != %s" % (path, s1.hexdigest(), sib["blobId"]))
        verified = "git-blob-sha1"
    os.replace(tmp, dest)
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
            "files": files, "errors": errors}
    if not dry_run:
        os.makedirs(d, exist_ok=True)
        tmp = snap_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=1, sort_keys=True)
        os.replace(tmp, snap_path)
    return snap


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


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Fetch the small files of a Hugging Face repo, pinned to a commit.")
    ap.add_argument("repo", help="ORG/NAME[@REV]")
    ap.add_argument("--keep", action="append", default=[], help="also fetch this file even if it is a weight")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    r, _, v = a.repo.partition("@")
    try:
        s = snapshot(r, v or None, a.keep, a.max_bytes, dry_run=a.dry_run)
    except HFError as e:
        print("hf_fetch: %s" % e, file=sys.stderr)
        sys.exit(1)
    print(json.dumps({k: s[k] for k in ("repo", "revision", "dir", "fetched_bytes", "errors")}, indent=1))
