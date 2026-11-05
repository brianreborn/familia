"""Guardian weight gate for Hermes: configurable path, pinned sha256, fail closed."""
import hashlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import guardian_load as gl  # noqa: E402
import hermes_harness as hh  # noqa: E402

REAL = "/workspace/models/guardian/" + gl.GGUF_NAME


def _g(path=None, sha=gl.EXPECTED_SHA256):
    m = {"sha256": sha, "role": "pentest"}
    if path:
        m["gguf"] = path
    return {"models": {gl.MODEL_KEY: m, "chat": {"role": "chat"}}}


NODE = {"model": gl.MODEL_KEY, "role": "guardian"}


def test_default_path_follows_models_dir_convention():
    assert gl.resolve_path({}, env={}) == os.path.expanduser(gl.DEFAULT_GGUF)
    assert "/gguf/models/pentest/" in gl.resolve_path({}, env={})


def test_env_overrides_graph(tmp_path):
    assert gl.resolve_path(_g("/a.gguf"), env={gl.ENV_PATH: "/b.gguf"}) == "/b.gguf"
    assert gl.resolve_path(_g("/a.gguf"), env={}) == "/a.gguf"


def test_missing_refuses(tmp_path):
    with pytest.raises(gl.GuardianRefused, match="missing"):
        gl.require(_g(), NODE, env={gl.ENV_PATH: str(tmp_path / "nope.gguf")})


def test_mismatch_refuses(tmp_path):
    f = tmp_path / "x.gguf"; f.write_bytes(b"not the guardian")
    with pytest.raises(gl.GuardianRefused, match="mismatch"):
        gl.require(_g(), NODE, env={gl.ENV_PATH: str(f)})


def test_graph_sha_disagreeing_with_pin_refuses(tmp_path):
    with pytest.raises(gl.GuardianRefused, match="pinned"):
        gl.expected_sha(_g(sha="0" * 64))


def test_match_passes(tmp_path, monkeypatch):
    f = tmp_path / "x.gguf"; f.write_bytes(b"ok")
    monkeypatch.setattr(gl, "EXPECTED_SHA256", hashlib.sha256(b"ok").hexdigest())
    assert gl.require({"models": {}}, NODE, env={gl.ENV_PATH: str(f)}) == str(f)


def test_non_guardian_node_untouched():
    assert gl.require(_g(), {"model": "chat"}, env={gl.ENV_PATH: "/nope"}) is None


def test_role_from_model_catalog():
    assert gl.is_guardian_node(_g(), {"model": gl.MODEL_KEY})


def test_hermes_ensure_server_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv(gl.ENV_PATH, str(tmp_path / "nope.gguf"))
    monkeypatch.setattr(hh, "props", lambda n: pytest.fail("adopted node despite bad weights"))
    with pytest.raises(SystemExit):
        hh.ensure_server(_g(), "miryam-pentest", dict(NODE, ctx=8192, parallel=1, port=1))


@pytest.mark.skipif(not os.path.isfile(REAL), reason="real guardian weights not on this host")
def test_real_weights_verify():
    assert gl.verify(REAL) == gl.EXPECTED_SHA256
