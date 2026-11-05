"""Phone/Termux: Hermes uses ~/.config/familia/api.key; config.yaml is 0600."""
from __future__ import annotations

import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import familia_auth as fa  # noqa: E402
import hermes_harness as hh  # noqa: E402


def _minimal_graph(port: int):
    return {
        "hosts": {"phone": {"kind": "phone", "ram_mib": 7570}},
        "models": {"m": {"gguf": "x.gguf", "sha256": "a" * 64, "arch": "llama", "trained_ctx": 8192, "role": "chat"}},
        "nodes": {
            "phone-chat": {
                "model": "m",
                "role": "chat",
                "host": "phone",
                "runtime": "cbl",
                "ctx": 4096,
                "parallel": 1,
                "kv_type": "q8_0",
                "flash_attn": True,
                "offload": {"backend": "cpu", "ngl": 0, "split": "none", "main_gpu": 0},
                "bind": "127.0.0.1",
                "port": port,
                "cache_ram_mib": 64,
                "status": "active",
            }
        },
        "aliases": {"phone-chat": {"node": "phone-chat"}},
        "agents": {
            "hermes": {
                "kind": "hermes-agent",
                "host": "phone",
                "min_ctx": 2048,
                "context_length": 4096,
                "aliases": {"main": "phone-chat", "auxiliary": "phone-chat"},
            }
        },
    }


def test_termux_api_key_in_candidate_files(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    key = cfg / "familia" / "api.key"
    key.parent.mkdir(parents=True)
    key.write_text("phone-secret-key\n", encoding="utf-8")
    os.chmod(key, 0o600)
    env = {"XDG_CONFIG_HOME": str(cfg), "TERMUX_VERSION": "0.118"}
    assert fa.is_termux(env=env)
    assert fa.termux_api_key_file(env=env) == str(key)
    assert fa.api_key(env=env) == "phone-secret-key"
    assert str(key) in fa.candidate_key_files(env=env)


def test_desktop_does_not_prefer_api_key(tmp_path):
    """R-3: Linux/desktop keeps previous resolution — api.key is not preferred."""
    cfg = tmp_path / "cfg"
    key = cfg / "familia" / "api.key"
    inst = cfg / "familia" / "instances" / "9931" / "api-keys"  # default port
    key.parent.mkdir(parents=True)
    inst.parent.mkdir(parents=True)
    key.write_text("phone-only-key\n", encoding="utf-8")
    inst.write_text("desktop-instance-key\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(cfg)}  # no TERMUX_VERSION
    assert not fa.is_termux(env=env)
    cands = fa.candidate_key_files(env=env)
    assert str(key) not in cands
    assert str(inst) in cands
    assert fa.api_key(env=env) == "desktop-instance-key"


def test_render_writes_0600_and_uses_termux_key(tmp_path, monkeypatch):
    cfg_home = tmp_path / "cfg"
    key = cfg_home / "familia" / "api.key"
    key.parent.mkdir(parents=True)
    key.write_text("e2e-phone-key\n", encoding="utf-8")
    os.chmod(key, 0o600)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_home))
    monkeypatch.setenv("TERMUX_VERSION", "0.118")  # phone path
    # Isolate HERMES_HOME under tmp
    cache = tmp_path / "cache"
    monkeypatch.setenv("HOME", str(tmp_path))
    # hermes harness expands ~/.cache from HOME
    g = _minimal_graph(19941)
    monkeypatch.setenv("FAMILIA_CTX", "4096")
    monkeypatch.setenv("FAMILIA_HERMES_BASE_URL", "http://127.0.0.1:19941/v1")
    # Avoid needing real ~/.hermes user config
    user = tmp_path / "none.yaml"
    user.write_text("{}\n", encoding="utf-8")
    home, base, n, name = hh.render(g, "hermes", user_cfg_path=str(user))
    cfg_path = Path(home) / "config.yaml"
    assert cfg_path.is_file()
    mode = stat.S_IMODE(cfg_path.stat().st_mode)
    assert mode == 0o600, oct(mode)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert cfg["model"]["api_key"] == "e2e-phone-key"
    assert cfg["model"]["context_length"] == 4096
    assert "19941" in cfg["model"]["base_url"]
    # child env carries the key for Hermes process
    env = hh.hermes_child_env({"HERMES_HOME": home})
    assert env.get("FAMILIA_API_KEY") == "e2e-phone-key"


def test_hermes_auth_headers_authorized_against_mock_server(tmp_path, monkeypatch):
    """End-to-end: a request built with familia_auth is accepted by a server using api.key."""
    cfg_home = tmp_path / "cfg"
    key = cfg_home / "familia" / "api.key"
    key.parent.mkdir(parents=True)
    secret = "authorized-phone-key-xyz"
    key.write_text(secret + "\n", encoding="utf-8")
    os.chmod(key, 0o600)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_home))
    monkeypatch.setenv("TERMUX_VERSION", "0.118")
    monkeypatch.delenv("FAMILIA_API_KEY", raising=False)
    monkeypatch.delenv("LLAMA_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY_FILE", raising=False)

    got = {"auth": None, "ok": False}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            got["auth"] = self.headers.get("Authorization")
            if got["auth"] == "Bearer " + secret:
                got["ok"] = True
                body = json.dumps({"object": "list", "data": [{"id": "ok"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(401)
                self.end_headers()

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.handle_request, daemon=True)
    th.start()
    url = f"http://127.0.0.1:{port}/v1/models"
    with fa.open_url(url, timeout=3) as resp:
        data = json.load(resp)
    th.join(timeout=3)
    httpd.server_close()
    assert got["ok"] is True
    assert got["auth"] == "Bearer " + secret
    assert data["data"][0]["id"] == "ok"
