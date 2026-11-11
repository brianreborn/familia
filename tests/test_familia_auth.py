import os, stat, sys, threading, json, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import familia_auth as FA
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_env_order_and_comma_list(tmp_path):
    f = tmp_path / "api-keys"; f.write_text("# c\nfilekey\n")
    assert FA.api_key(str(tmp_path), {"FAMILIA_API_KEY": "a", "LLAMA_API_KEY": "b"}) == "a"
    assert FA.api_key(str(tmp_path), {"LLAMA_API_KEY": "k1,k2"}) == "k1"
    assert FA.api_key(str(tmp_path), {"API_KEY_FILE": str(f)}) == "filekey"


def test_bootstrap_root_secrets(tmp_path):
    d = tmp_path / "code-bootstraps-llama.cpp" / ".secrets"; d.mkdir(parents=True)
    (d / "api-keys").write_text("# llama-server API key(s)\nrootkey\n")
    # Isolate from this machine's real instance key (~/.config/familia/instances/*/api-keys).
    assert FA.api_key(str(tmp_path), {"XDG_CONFIG_HOME": str(tmp_path / "cfg")}) == "rootkey"


def test_incoming_auth_passes_through():
    h = FA.auth_headers({"Content-Type": "x"}, key="mine", incoming={"Authorization": "Bearer caller"})
    assert h["Authorization"] == "Bearer caller"
    assert FA.auth_headers({}, key="mine")["Authorization"] == "Bearer mine"
    assert "Authorization" not in FA.auth_headers({}, key="")


class _Keyed(BaseHTTPRequestHandler):
    KEY = "s3cret"
    def do_GET(self):
        ok = self.headers.get("Authorization") == "Bearer " + self.KEY
        self.send_response(200 if ok else 401); self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "chat"}]} if ok else {"error": "Invalid API Key"}).encode())
    def log_message(self, *a):
        pass


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Keyed)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_open_url_against_keyed_server(monkeypatch):
    srv = _serve()
    try:
        monkeypatch.setenv("FAMILIA_API_KEY", "s3cret")
        with FA.open_url(f"http://127.0.0.1:{srv.server_port}/v1/models", timeout=3) as r:
            assert r.status == 200
    finally:
        srv.shutdown()


def _cli(*args, env):
    return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "familia_auth.py"), *args],
                          capture_output=True, text=True, env=env)


def test_cli_curl_config_writes_private_file_not_stdout(tmp_path):
    env = dict(os.environ, FAMILIA_API_KEY="zz", XDG_CONFIG_HOME=str(tmp_path / "cfg"))
    out = tmp_path / "curl.cfg"
    r = _cli("curl-config", "-o", str(out), env=env)
    assert r.returncode == 0 and "zz" not in r.stdout and "zz" not in r.stderr
    assert out.read_text() == 'header = "Authorization: Bearer zz"\n'
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(out).st_mode) == 0o600


def test_cli_curl_config_refuses_stdout_overwrite_symlink_and_no_key(tmp_path):
    env = dict(os.environ, FAMILIA_API_KEY="zz", XDG_CONFIG_HOME=str(tmp_path / "cfg"))
    r = _cli("curl-config", env=env)          # old stdout form is gone
    assert r.returncode == 2 and "zz" not in r.stdout + r.stderr
    existing = tmp_path / "exists"; existing.write_text("keep\n")
    r = _cli("curl-config", "-o", str(existing), env=env)
    assert r.returncode == 2 and existing.read_text() == "keep\n"
    if os.name != "nt":
        target = tmp_path / "victim"; link = tmp_path / "link"; os.symlink(target, link)
        r = _cli("curl-config", "-o", str(link), env=env)
        assert r.returncode == 2 and not target.exists()
    missing = tmp_path / "missing.cfg"
    assert FA.curl_config(["-o", str(missing)], "") == 1 and not missing.exists()


def test_fingerprint_is_salted_hmac_and_stable_per_instance(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(FA, "_process_salt", None)
    env = {"XDG_CONFIG_HOME": str(tmp_path), "FAMILIA_PORT": "9931"}
    d = os.path.dirname(FA.instance_key_file(env=env))
    # no instance dir: nothing is written, a per-process salt is used
    s0 = FA.fingerprint_salt(env=env)
    assert not os.path.exists(d) and s0 == FA.fingerprint_salt(env=env)
    os.makedirs(d)
    s1 = FA.fingerprint_salt(env=env)
    salt_file = os.path.join(d, FA.SALT_NAME)
    assert os.path.isfile(salt_file) and s1 == FA.fingerprint_salt(env=env) and s1 != s0
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(salt_file).st_mode) == 0o600
    fp = FA.fingerprint("abc", salt=s1)
    assert fp.startswith("hmac-sha256:") and len(fp) == len("hmac-sha256:") + 8
    assert fp == FA.fingerprint("abc", salt=s1) != FA.fingerprint("abc", salt=b"other")
    assert fp.split(":")[1] != hashlib.sha256(b"abc").hexdigest()[:8]   # not the old bare sha256
    assert FA.fingerprint("", salt=s1) == "none"


def test_no_bare_9931_callers():
    """Every script that names :9931 must go through familia_auth (no keyless probes)."""
    import re
    bad = []
    for dp, _dn, fns in os.walk(os.path.join(ROOT, "scripts")):
        for fn in fns:
            if not fn.endswith((".sh", ".py")) or fn == "familia_auth.py":
                continue
            p = os.path.join(dp, fn)
            for i, line in enumerate(open(p, errors="replace"), 1):
                if re.search(r"curl[^\n]*:9931", line) and "familia_auth" not in line:
                    bad.append(f"{p}:{i}")
    assert not bad, bad


def test_load_or_create_persists_0600(tmp_path):
    p = str(tmp_path / ".secrets" / "api-keys")
    k1 = FA.load_or_create_key_file(p)
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    assert FA.load_or_create_key_file(p) == k1          # never regenerated
    assert [f for f in os.listdir(os.path.dirname(p)) if f.startswith(".api-keys.")] == []


def test_concurrent_first_start_one_key(tmp_path):
    p = str(tmp_path / "api-keys")
    out = []
    ts = [threading.Thread(target=lambda: out.append(FA.load_or_create_key_file(p))) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(set(out)) == 1


def test_fail_closed_and_fingerprint():
    import pytest
    with pytest.raises(FA.MissingKey):
        FA.auth_headers({}, key="", required=True)
    fp = FA.fingerprint("abc", salt=b"test-salt")   # no write into the real instance dir
    assert fp.startswith("hmac-sha256:") and "abc" not in fp
    assert FA.keys_match("k", "k") and not FA.keys_match("k", "kk") and not FA.keys_match("", "")


# --- per-instance key + authenticated probe (code-bootstraps-llama.cpp docs/api-key-design.md) ---
import http.server as _hs
import socket as _socket
import threading as _th


def test_instance_key_file_per_port(tmp_path, monkeypatch):
    import familia_auth as fa
    env = {"XDG_CONFIG_HOME": str(tmp_path), "PORT": "9940"}
    assert fa.instance_key_file(env=env) == str(tmp_path / "familia" / "instances" / "9940" / "api-keys")
    assert fa.instance_key_file(port=9931, env=env).endswith("/instances/9931/api-keys")
    assert fa.candidate_key_files(env=env)[0] == fa.instance_key_file(env=env)


def _serve_probe(code):
    class H(_hs.BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.headers.get("Authorization") == "Bearer good"
            self.send_response(200 if (ok and code == 200) else 401)
            self.end_headers(); self.wfile.write(b"{}")
        def log_message(self, *a):
            pass
    srv = _hs.HTTPServer(("127.0.0.1", 0), H)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_probe_up_rejected_down(monkeypatch):
    import familia_auth as fa
    monkeypatch.setenv("FAMILIA_API_KEY", "good")
    s = _serve_probe(200)
    assert fa.probe("http://127.0.0.1:%d" % s.server_port) == fa.UP
    s.shutdown()
    monkeypatch.setenv("FAMILIA_API_KEY", "wrong")
    s = _serve_probe(200)
    # a 401 is a misconfiguration, never "no server"
    assert fa.probe("http://127.0.0.1:%d" % s.server_port) == fa.AUTH_REJECTED
    s.shutdown()
    sock = _socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    assert fa.probe("http://127.0.0.1:%d" % port) == fa.DOWN


def test_key_for_url_uses_the_urls_port(tmp_path):
    """A server start.sh moved to another port: --url alone must find its key (no FAMILIA_PORT)."""
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    for port, key in (("9931", "k-default"), ("45109", "k-moved")):
        d = tmp_path / "familia" / "instances" / port
        d.mkdir(parents=True)
        (d / "api-keys").write_text("# one key per line, never rotated (see docs)\n" + key + "\n")
    assert FA.key_for_url("http://127.0.0.1:45109/v1/models", env=env) == "k-moved"
    assert FA.key_for_url("http://localhost:9931", env=env) == "k-default"
    env["FAMILIA_API_KEY"] = "explicit"
    assert FA.key_for_url("http://127.0.0.1:45109", env=env) == "explicit"


# --- combined key fix: persistence across restart + nested forwarding -------------------------

def _clean_env(tmp_path, **extra):
    e = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "HOME": str(tmp_path / "home"), "FAMILIA_PORT": "9931"}
    e.update(extra)
    return e






def test_harness2_chat_sends_key_and_fails_closed(tmp_path, monkeypatch):
    import sys, json
    sys.path.insert(0, os.path.join(FA.ROOT, "scripts"))
    import harness2_local as L
    seen = []

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_open(req, timeout=None):
        seen.append(req.get_header("Authorization"))
        return R()
    monkeypatch.setattr(L.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(L.json, "load", lambda r: json.loads(r.read()))
    monkeypatch.setenv("FAMILIA_API_KEY", "nested-k")
    chat = L.make_chat("http://127.0.0.1:9931/v1", "m")
    for _ in range(3):  # recursive engine calls chat() repeatedly
        assert chat([{"role": "user", "content": "x"}])[0] == "ok"
    assert seen == ["Bearer nested-k"] * 3
    for n in ("FAMILIA_API_KEY", "LLAMA_API_KEY", "API_KEY_FILE"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr(FA, "candidate_key_files", lambda *a, **k: [])
    monkeypatch.setattr(FA, "instance_key_file", lambda *a, **k: str(tmp_path / "none"))
    with pytest.raises(FA.MissingKey):
        chat([{"role": "user", "content": "x"}])


def test_instance_key_persists_0600_across_restart(tmp_path):
    """existing load_or_create_key_file: created once, 0600, same key after a restart."""
    import importlib, stat
    env = _clean_env(tmp_path)
    path = FA.instance_key_file(env=env)
    k1 = FA.load_or_create_key_file(path)
    assert k1 and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    importlib.reload(FA)
    assert FA.load_or_create_key_file(path) == k1 and FA.api_key(str(tmp_path), env) == k1


def test_nested_children_inherit_key_via_env(tmp_path):
    """plain env inheritance: parent -> child -> grandchild all resolve the same API_KEY_FILE key."""
    f = tmp_path / "k"; f.write_text("# c\nnestedkey\n")
    env = {k: v for k, v in os.environ.items() if k not in ("FAMILIA_API_KEY", "LLAMA_API_KEY")}
    env.update(API_KEY_FILE=str(f), HOME=str(tmp_path))
    scripts = os.path.join(FA.ROOT, "scripts")
    code = ("import sys,subprocess; sys.path.insert(0,%r); import familia_auth as F;"
            "d=int(sys.argv[1]); assert F.api_key()=='nestedkey', d;"
            "sys.exit(subprocess.call([sys.executable,'-c',sys.argv[2],str(d-1),sys.argv[2]]) if d else 0)") % scripts
    assert subprocess.run([sys.executable, "-c", code, "3", code], env=env).returncode == 0


def test_with_fleet_hermes_has_key_precheck():
    src = open(os.path.join(FA.ROOT, "with-fleet.sh")).read()
    assert src.index("familia_auth.py\" has-key") < src.index('scripts/hermes.sh" --agent')



def test_familia_api_key_file_accepted(tmp_path):
    import familia_auth as fa
    f = tmp_path / "installer.key"
    f.write_bytes(b"from-familia-env\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "FAMILIA_API_KEY_FILE": str(f)}
    assert fa.candidate_key_files(env=env)[0] == str(f)
    assert fa.api_key(str(tmp_path), env) == "from-familia-env"
    # both names accepted; API_KEY_FILE wins if both are set
    g = tmp_path / "api-env.key"
    g.write_bytes(b"from-api-env\n")
    env["API_KEY_FILE"] = str(g)
    assert fa.candidate_key_files(env=env)[0] == str(g)
    assert fa.api_key(str(tmp_path), env) == "from-api-env"


def test_installer_key_file_is_a_fallback(tmp_path):
    import familia_auth as fa
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    inst = fa.installer_key_file(env=env)
    assert inst == str(tmp_path / "familia" / "api.key")
    cands = fa.candidate_key_files(env=env)
    assert cands[0] == fa.instance_key_file(env=env)
    assert inst in cands and cands.index(inst) > 0


def test_load_or_create_writes_lf_no_bom(tmp_path):
    import familia_auth as fa
    pth = str(tmp_path / "api-keys")
    fa.load_or_create_key_file(pth)
    data = open(pth, "rb").read()
    assert not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data
    assert data.startswith(b"#") and data.endswith(b"\n")


def test_publish_falls_back_when_link_is_denied(tmp_path, monkeypatch):
    """Termux SELinux denies link(2) with EACCES; still no-clobber create."""
    import errno
    import familia_auth as fa
    def boom(src, dst):
        raise OSError(errno.EACCES, "selinux denies link")
    monkeypatch.setattr(fa.os, "link", boom)
    pth = str(tmp_path / "api-keys")
    k1 = fa.load_or_create_key_file(pth)
    assert k1 and open(pth, "rb").read().count(k1.encode()) == 1
    assert fa.load_or_create_key_file(pth) == k1
