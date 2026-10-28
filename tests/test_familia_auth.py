import os, sys, threading, json, subprocess
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
    assert FA.api_key(str(tmp_path), {}) == "rootkey"


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


def test_cli_curl_config(monkeypatch):
    env = dict(os.environ, FAMILIA_API_KEY="zz")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "familia_auth.py"), "curl-config"],
                         capture_output=True, text=True, env=env).stdout
    assert out.strip() == 'header = "Authorization: Bearer zz"'


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
    fp = FA.fingerprint("abc")
    assert fp.startswith("sha256:") and "abc" not in fp
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


def test_ensure_instance_key_persists_0600_across_restart(tmp_path):
    import importlib, stat
    env = _clean_env(tmp_path)
    k1 = FA.ensure_instance_key(env=env)
    path = FA.instance_key_file(env=env)
    assert k1 and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    importlib.reload(FA)  # "restart": fresh module state, same disk
    assert FA.ensure_instance_key(env=env) == k1
    assert FA.api_key(str(tmp_path), env) == k1


def test_child_env_forwards_file_not_value(tmp_path):
    env = _clean_env(tmp_path)
    k = FA.ensure_instance_key(env=env)
    c = FA.child_env({"X": "1"}, env=env)
    assert c["API_KEY_FILE"] == FA.instance_key_file(env=env) and c["FAMILIA_PORT"] == "9931"
    assert k not in "".join(c.values()) and c["X"] == "1"


def test_child_env_required_fails_closed(tmp_path):
    with pytest.raises(FA.MissingKey):
        FA.child_env(env=_clean_env(tmp_path), required=True)


def test_nested_forwarding_three_levels(tmp_path):
    """parent -> child -> grandchild python processes each resolve the same key via child_env."""
    import subprocess, sys
    env = _clean_env(tmp_path, PATH=os.environ.get("PATH", ""))
    k = FA.ensure_instance_key(env=env)
    scripts = os.path.join(FA.ROOT, "scripts")
    code = ("import os,sys,subprocess; sys.path.insert(0,%r); import familia_auth as F;"
            "d=int(sys.argv[1]); assert F.api_key()==%r, d;"
            "e=F.child_env(env={k:v for k,v in os.environ.items() if k!='XDG_CONFIG_HOME'}, required=True);"
            "sys.exit(subprocess.call([sys.executable,'-c',sys.argv[2],str(d-1),sys.argv[2]],env=e) if d else 0)")
    code = code % (scripts, k)
    root_env = FA.child_env(env=env, required=True)
    root_env.pop("XDG_CONFIG_HOME")  # grandchildren must rely on forwarded API_KEY_FILE only
    r = subprocess.run([sys.executable, "-c", code, "3", code], env=root_env)
    assert r.returncode == 0


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


def test_dogfood_loops_forward_key_file(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, os.path.join(FA.ROOT, "scripts", "dogfood"))
    import harness2_loop as H2, hermes_loop as HL
    for n in ("FAMILIA_API_KEY", "LLAMA_API_KEY"):
        monkeypatch.delenv(n, raising=False)
    f = tmp_path / "k"; f.write_text("filek\n")
    monkeypatch.setenv("API_KEY_FILE", str(f))
    got = {}
    def sh(cmd, cwd=None, timeout=None, env=None):
        got.setdefault("envs", []).append(env); return 0, "dry-run: ok"
    H2.run_propose("t", sh=sh, smoke=True)
    HL.run_render("single", "coder", sh=sh)
    for e in got["envs"]:
        assert e["API_KEY_FILE"] == str(f) and "filek" not in "".join(map(str, e.values()))


def test_with_fleet_helper_cli_ensure_then_child_env(tmp_path):
    """with-fleet.sh: `ensure` creates once, `child-env` exports the file path only (sh-evalable)."""
    env = dict(os.environ, **_clean_env(tmp_path))
    for n in ("FAMILIA_API_KEY", "LLAMA_API_KEY", "API_KEY_FILE"):
        env.pop(n, None)
    cli = os.path.join(FA.ROOT, "scripts", "familia_auth.py")
    fp1 = subprocess.run([sys.executable, cli, "ensure"], env=env, capture_output=True, text=True).stdout
    fp2 = subprocess.run([sys.executable, cli, "ensure"], env=env, capture_output=True, text=True).stdout
    assert fp1 == fp2 and fp1.startswith("sha256:")
    out = subprocess.run([sys.executable, cli, "child-env"], env=env, capture_output=True, text=True).stdout
    key = FA._read(FA.instance_key_file(env=env))
    assert "export API_KEY_FILE=" in out and key not in out
    assert "familia_key_for_children" in open(os.path.join(FA.ROOT, "with-fleet.sh")).read()
