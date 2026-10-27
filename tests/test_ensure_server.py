"""ensure_server: no daemon spawn; adopt only with n_ctx (+ tools when graph asks)."""
import io
import json
import os
import sys
import urllib.error

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh


def _node(**kw):
    n = {"ctx": 65536, "parallel": 1, "bind": "127.0.0.1", "port": 18200}
    n.update(kw)
    return n


def test_tools_live_ok(monkeypatch):
    class R:
        status = 200
        def read(self, n=-1):
            return b'{"tools":[]}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(hh.urllib.request, "urlopen", lambda *a, **k: R())
    assert hh.tools_live(_node()) is True


def test_tools_live_403(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.HTTPError("http://x/tools", 403, "Forbidden", hdrs=None, fp=io.BytesIO(b'{"error":{"message":"feature_disabled"}}'))

    monkeypatch.setattr(hh.urllib.request, "urlopen", boom)
    assert hh.tools_live(_node()) is False


def test_ensure_server_cold_refuses_spawn(monkeypatch):
    monkeypatch.setattr(hh, "props", lambda n: None)
    spawned = []
    monkeypatch.setattr(hh.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    with pytest.raises(SystemExit) as e:
        hh.ensure_server({}, "angel-coder", _node(server_tools="all"))
    assert e.value.code == 1
    assert spawned == []


def test_ensure_server_adopts_when_ctx_ok_no_tools_required(monkeypatch):
    monkeypatch.setattr(hh, "props", lambda n: {"default_generation_settings": {"n_ctx": 65536}})
    monkeypatch.setattr(hh, "tools_live", lambda n: False)  # must not be consulted
    assert hh.ensure_server({}, "coder", _node()) == 65536


def test_ensure_server_rejects_up_without_tools(monkeypatch):
    monkeypatch.setattr(hh, "props", lambda n: {"default_generation_settings": {"n_ctx": 65536}})
    monkeypatch.setattr(hh, "tools_live", lambda n: False)
    with pytest.raises(SystemExit) as e:
        hh.ensure_server({}, "angel-coder", _node(server_tools="all"))
    assert e.value.code == 1


def test_ensure_server_accepts_up_with_tools(monkeypatch):
    monkeypatch.setattr(hh, "props", lambda n: {"default_generation_settings": {"n_ctx": 65536}})
    monkeypatch.setattr(hh, "tools_live", lambda n: True)
    assert hh.ensure_server({}, "angel-coder", _node(server_tools="all")) == 65536


def test_ensure_server_ctx_mismatch(monkeypatch):
    monkeypatch.setattr(hh, "props", lambda n: {"default_generation_settings": {"n_ctx": 8192}})
    with pytest.raises(SystemExit):
        hh.ensure_server({}, "angel-coder", _node(server_tools="all"))


def test_warm_prompt_skips_low_mem(monkeypatch):
    monkeypatch.setenv("FAMILIA_WARM_MIN_AVAIL_MIB", "4096")
    monkeypatch.setattr(hh, "mem_available_mib", lambda: 1000)
    called = []
    monkeypatch.setattr(hh, "hermes_prefix", lambda home: called.append("prefix") or {})
    assert hh.warm_prompt({}, "angel-coder", _node(slot_save=True), "/tmp") is None
    assert called == []


def test_warm_prompt_passes_timeout(monkeypatch):
    monkeypatch.delenv("FAMILIA_WARM_MIN_AVAIL_MIB", raising=False)
    monkeypatch.setenv("FAMILIA_WARM_TIMEOUT", "123")
    monkeypatch.setattr(hh, "mem_available_mib", lambda: 99999)
    monkeypatch.setattr(hh, "hermes_prefix", lambda home: {"system": "s", "tools": [], "volatile": ""})
    import prompt_cache as pc
    seen = {}

    def fake_stable(*a, **k):
        return "PREFIX"

    def fake_tokens(*a, **k):
        return [1, 2, 3]

    def fake_warm(base, tokens, tag="", slot=0, timeout=7200, log=None):
        seen["timeout"] = timeout
        seen["tag"] = tag
        return ("restored", 0.1)

    monkeypatch.setattr(pc, "stable_prefix", fake_stable)
    monkeypatch.setattr(pc, "prefix_tokens", fake_tokens)
    monkeypatch.setattr(pc, "warm", fake_warm)
    # warm_prompt imports prompt_cache inside — patch sys.modules path used after import
    import importlib
    monkeypatch.setitem(sys.modules, "prompt_cache", pc)
    assert hh.warm_prompt({}, "angel-coder", _node(slot_save=True), "/tmp") == "restored"
    assert seen["timeout"] == 123
