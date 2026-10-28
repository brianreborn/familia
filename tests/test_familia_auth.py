import os, sys, threading, json, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import familia_auth as FA

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
