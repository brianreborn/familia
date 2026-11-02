"""hf_cache: revalidation, resume, If-Range restart, no validators, sha256, concurrency."""
import hashlib, http.server, os, sys, threading, time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import hf_cache  # noqa: E402

LM = "Wed, 21 Oct 2026 07:28:00 GMT"


class Srv:
    def __init__(self, data, etag="auto", lm=LM, delay=0.0):
        self.set(data, etag, lm)
        self.delay, self.log, self.ignore_if_range, self.bad_offset = delay, [], False, False
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                d, et, lm = srv.data, srv.etag, srv.lm
                inm, ims = self.headers.get("If-None-Match"), self.headers.get("If-Modified-Since")
                rng, ir = self.headers.get("Range"), self.headers.get("If-Range")
                if (inm and et and inm.strip('"') == et) or (not inm and ims and lm and ims == lm):
                    srv.log.append(304); self.send_response(304); self.end_headers(); return
                start = 0
                if rng and (srv.ignore_if_range or not ir or ir.strip('"') in (et, lm)):
                    start = int(rng.split("=")[1].split("-")[0])
                if start:
                    s = start + 1 if srv.bad_offset else start
                    srv.log.append(206); self.send_response(206)
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (s, len(d) - 1, len(d)))
                    body = d[s:]
                else:
                    srv.log.append(200); self.send_response(200); body = d
                if et:
                    self.send_header("ETag", '"%s"' % et)
                if lm:
                    self.send_header("Last-Modified", lm)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                for i in range(0, len(body), 4096):
                    self.wfile.write(body[i:i + 4096])
                    if srv.delay:
                        time.sleep(srv.delay)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/f.gguf" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def set(self, data, etag="auto", lm=LM):
        self.data = data
        self.etag = hashlib.sha256(data).hexdigest() if etag == "auto" else etag
        self.lm = lm


A = os.urandom(100_000)
B = os.urandom(100_000)
sha = lambda b: hashlib.sha256(b).hexdigest()


@pytest.fixture
def srv():
    s = Srv(A)
    yield s
    s.httpd.shutdown()


def _part(dest, data, etag):
    open(dest + ".part", "wb").write(data)
    hf_cache._write_json(dest + ".part.meta.json", {"url": None, "etag": etag, "last_modified": LM, "sha256": None})


def test_unchanged_304_skips(srv, tmp_path):
    d = str(tmp_path / "f.gguf")
    assert hf_cache.fetch(srv.url, d)["status"] == "downloaded"
    assert hf_cache.fetch(srv.url, d)["status"] == "unchanged"
    assert srv.log == [200, 304] and open(d, "rb").read() == A


def test_partial_resume_206(srv, tmp_path):
    d = str(tmp_path / "f.gguf")
    _part(d, A[:40_000], sha(A))
    hf_cache._write_json(d + ".part.meta.json", {"url": srv.url, "etag": sha(A), "last_modified": LM, "sha256": None})
    r = hf_cache.fetch(srv.url, d, sha256=sha(A))
    assert r["status"] == "resumed" and srv.log == [206] and open(d, "rb").read() == A
    assert not os.path.exists(d + ".part")


def test_upstream_changed_mid_resume_restarts_clean(srv, tmp_path):
    d = str(tmp_path / "f.gguf")
    hf_cache._write_json(d + ".part.meta.json", {"url": srv.url, "etag": sha(A), "last_modified": "x", "sha256": None})
    open(d + ".part", "wb").write(A[:40_000])
    srv.set(B, lm="Thu, 29 Oct 2026 07:28:00 GMT")
    r = hf_cache.fetch(srv.url, d)
    assert r["status"] == "downloaded" and srv.log == [200]
    assert open(d, "rb").read() == B  # no splice of A's head onto B


def test_bad_content_range_never_spliced(srv, tmp_path):
    d = str(tmp_path / "f.gguf")
    hf_cache._write_json(d + ".part.meta.json", {"url": srv.url, "etag": sha(A), "last_modified": LM, "sha256": None})
    open(d + ".part", "wb").write(A[:40_000])
    srv.bad_offset = True
    assert hf_cache.fetch(srv.url, d)["status"] == "downloaded"
    assert srv.log == [206, 200] and open(d, "rb").read() == A


def test_no_validators_full_download_and_sha_check(tmp_path):
    s = Srv(A, etag=None, lm=None)
    try:
        d = str(tmp_path / "f.gguf")
        open(d + ".part", "wb").write(b"junk")  # no part meta: must not resume
        assert hf_cache.fetch(s.url, d, sha256=sha(A))["status"] == "downloaded"
        assert hf_cache.fetch(s.url, d, sha256=sha(A))["status"] == "downloaded"  # nothing to revalidate with
        assert s.log == [200, 200] and open(d, "rb").read() == A
    finally:
        s.httpd.shutdown()


def test_etag_or_size_change_forces_redownload(srv, tmp_path):
    d = str(tmp_path / "f.gguf")
    hf_cache.fetch(srv.url, d)
    srv.set(B)
    assert hf_cache.fetch(srv.url, d)["status"] == "downloaded" and open(d, "rb").read() == B
    C = B + b"x"
    srv.set(C, etag="same-etag")
    hf_cache.fetch(srv.url, d)
    srv.set(C + b"y", etag="same-etag")
    assert hf_cache.fetch(srv.url, d, size=len(C) + 1)["status"] == "downloaded"
    assert open(d, "rb").read() == C + b"y"


def test_sha256_mismatch_rejected_and_target_untouched(srv, tmp_path):
    d = str(tmp_path / "f.gguf")
    open(d, "wb").write(b"old")
    with pytest.raises(hf_cache.FetchError, match="sha256"):
        hf_cache.fetch(srv.url, d, sha256="0" * 64)
    assert open(d, "rb").read() == b"old" and not os.path.exists(d + ".part")
    srv.set(A, etag=sha(B))  # LFS-style ETag that is a sha256 and disagrees with the body
    with pytest.raises(hf_cache.FetchError, match="sha256"):
        hf_cache.fetch(srv.url, str(tmp_path / "g.gguf"))


def test_two_fetchers_same_file(tmp_path):
    s = Srv(A, delay=0.002)
    try:
        d = str(tmp_path / "f.gguf")
        out, errs = [], []

        def go():
            try:
                out.append(hf_cache.fetch(s.url, d, sha256=sha(A))["status"])
            except Exception as e:  # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert not errs and sorted(out) == ["downloaded", "unchanged"]
        assert s.log == [200, 304] and open(d, "rb").read() == A
        assert [n for n in os.listdir(tmp_path) if n.endswith((".part", ".tmp"))] == []
    finally:
        s.httpd.shutdown()
