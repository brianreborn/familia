#!/usr/bin/env python3
"""hf_cache.py: cache-coherent, resumable, verified HTTP file fetch (stdlib only).

Used by hf_fetch.download for Hugging Face artifacts. Per target file DEST:
  DEST.meta.json       sidecar: url, etag, last_modified, size, sha256 of the finished file
  DEST.part            in-progress bytes (same folder, so the final os.replace is atomic)
  DEST.part.meta.json  validators the .part was fetched under (for If-Range)
  DEST.lock            exclusive lock; .part is only read, resumed or taken over while held

Rules:
  * revalidate with If-None-Match / If-Modified-Since; 304, or a 200 whose ETag and size
    match the sidecar while the local sha256 is still good, skips the download;
  * resume with Range + If-Range (strong ETag, else Last-Modified; never resume without one);
    a 200 means upstream changed: truncate and restart, never splice; a 206 must have a
    Content-Range starting at the current offset;
  * an ETag or size change re-downloads;
  * sha256 is checked BEFORE the rename (expected value, else an LFS ETag that is a sha256);
    then fsync file, os.replace, fsync directory. Readers never see a half-written DEST.
All temp names live in the target folder (atomic rename needs the same filesystem), not /tmp.
"""
import hashlib, json, os, re, urllib.error, urllib.request

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

CHUNK = 1 << 20
HEX64 = re.compile(r"[0-9a-f]{64}")


class FetchError(Exception):
    pass


def _norm_etag(v):
    if not v:
        return None
    v = v.strip()
    weak = v.startswith("W/")
    if weak:
        v = v[2:]
    v = v.strip('"')
    return ("W/" + v) if weak else v


def _etag_of(headers):
    # HF puts the LFS sha256 in X-Linked-Etag on the resolve hop; the CDN's ETag is the same.
    return _norm_etag(headers.get("X-Linked-Etag") or headers.get("ETag"))


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _fsync_dir(d):
    if os.name == "nt":
        return
    fd = os.open(d or ".", os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json(path, obj):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(os.path.dirname(path))


def _rm(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def sha256_file(path, h=None):
    h = h or hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h


class _Lock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.f = open(self.path, "a+b")
        if fcntl:
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        else:
            self.f.seek(0)
            while True:
                try:
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    pass
        return self

    def __exit__(self, *a):
        try:
            if fcntl:
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
            else:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.f.close()


_default_opener = urllib.request.build_opener()


def _open(opener, url, headers, timeout):
    """Return (status, response or None). 304 comes back as a status, not an exception."""
    try:
        r = opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)
        return r.status, r
    except urllib.error.HTTPError as e:
        if e.code == 304:
            e.close()
            return 304, None
        if e.code == 416:
            e.close()
            return 416, None
        raise FetchError("%s: HTTP %d" % (url.split("?")[0], e.code))


def fetch(url, dest, sha256=None, size=None, headers=None, opener=None, timeout=300):
    """Fetch url to dest. Returns dict(status=unchanged|downloaded|resumed, sha256, size)."""
    opener = opener or _default_opener
    headers = dict(headers or {})
    sha256 = sha256.lower() if sha256 else None
    d = os.path.dirname(os.path.abspath(dest))
    os.makedirs(d, exist_ok=True)
    meta_p, part, part_meta_p = dest + ".meta.json", dest + ".part", dest + ".part.meta.json"
    with _Lock(dest + ".lock"):
        meta = _load(meta_p) if os.path.exists(dest) else None
        if meta and (meta.get("url") != url or (sha256 and meta.get("sha256") != sha256)
                     or (size is not None and meta.get("size") != size)
                     or os.path.getsize(dest) != meta.get("size")):
            meta = None  # expectation or local file changed: full re-download
        if meta:
            h = dict(headers)
            if meta.get("etag"):
                h["If-None-Match"] = '"%s"' % meta["etag"] if not meta["etag"].startswith("W/") else 'W/"%s"' % meta["etag"][2:]
            if meta.get("last_modified"):
                h["If-Modified-Since"] = meta["last_modified"]
            if len(h) > len(headers):
                st, r = _open(opener, url, h, timeout)
                if st == 304:
                    return {"status": "unchanged", "sha256": meta["sha256"], "size": meta["size"]}
                same = (r is not None and _etag_of(r.headers) == meta.get("etag")
                        and r.headers.get("Content-Length") not in (None, "")
                        and int(r.headers["Content-Length"]) == meta["size"])
                if same and sha256_file(dest).hexdigest() == meta["sha256"]:
                    r.close()
                    return {"status": "unchanged", "sha256": meta["sha256"], "size": meta["size"]}
                return _finish(r, url, dest, part, part_meta_p, meta_p, sha256, size, 0, hashlib.sha256(), headers, opener, timeout)
        # resume a .part only under the lock, and only with a strong validator
        off, h0 = 0, hashlib.sha256()
        pm = _load(part_meta_p) if os.path.exists(part) else None
        if pm and pm.get("url") == url and (not sha256 or pm.get("sha256") in (None, sha256)):
            ir = pm.get("etag") if pm.get("etag") and not pm["etag"].startswith("W/") else pm.get("last_modified")
            off = os.path.getsize(part)
            if ir and off > 0:
                sha256_file(part, h0)
                st, r = _open(opener, url, dict(headers, Range="bytes=%d-" % off, **{"If-Range": ('"%s"' % ir) if ir == pm.get("etag") else ir}), timeout)
                if st == 206:
                    m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", r.headers.get("Content-Range", ""))
                    if m and int(m.group(1)) == off and _etag_of(r.headers) in (None, pm.get("etag")):
                        return _finish(r, url, dest, part, part_meta_p, meta_p, sha256, size, off, h0, headers, opener, timeout, pm)
                    r.close()  # wrong offset or validator: never splice
                elif st == 200:
                    return _finish(r, url, dest, part, part_meta_p, meta_p, sha256, size, 0, hashlib.sha256(), headers, opener, timeout)
        _rm(part, part_meta_p)
        st, r = _open(opener, url, headers, timeout)
        if st != 200:
            raise FetchError("%s: unexpected HTTP %d" % (url, st))
        return _finish(r, url, dest, part, part_meta_p, meta_p, sha256, size, 0, hashlib.sha256(), headers, opener, timeout)


def _finish(r, url, dest, part, part_meta_p, meta_p, sha256, size, off, h, headers, opener, timeout, pm=None):
    with r:
        if r.status not in (200, 206):
            raise FetchError("%s: unexpected HTTP %d" % (url, r.status))
        etag, lm = _etag_of(r.headers), r.headers.get("Last-Modified")
        if pm is None:
            pm = {"url": url, "etag": etag, "last_modified": lm, "sha256": sha256}
            _write_json(part_meta_p, pm)
        with open(part, "r+b" if off else "wb") as f:
            f.seek(off)
            f.truncate()
            n = off
            for b in iter(lambda: r.read(CHUNK), b""):
                f.write(b)
                h.update(b)
                n += len(b)
            f.flush()
            os.fsync(f.fileno())
    got = h.hexdigest()
    want = sha256 or (etag if etag and HEX64.fullmatch(etag) else None)
    if size is not None and n != size:
        _rm(part, part_meta_p)
        raise FetchError("%s: size %d != expected %d" % (dest, n, size))
    if want and got != want:
        _rm(part, part_meta_p)
        raise FetchError("%s: sha256 %s != expected %s" % (dest, got, want))
    os.replace(part, dest)
    _fsync_dir(os.path.dirname(os.path.abspath(dest)))
    _write_json(meta_p, {"url": url, "etag": pm.get("etag") or etag, "last_modified": pm.get("last_modified") or lm,
                         "size": n, "sha256": got})
    _rm(part_meta_p)
    return {"status": "resumed" if off else "downloaded", "sha256": got, "size": n}
