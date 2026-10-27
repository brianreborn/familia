"""Machine-local hostname pin: resolve precedence and select_host integration."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hostname_pin  # noqa: E402
import start_graph  # noqa: E402


@pytest.fixture
def pin_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.delenv("FAMILIA_HOST", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    return {"XDG_STATE_HOME": str(state)}


def test_write_read_pin_roundtrip(pin_env):
    path = hostname_pin.write_pin("phone7", environ=pin_env)
    assert path == hostname_pin.pin_path(pin_env)
    assert path.read_text(encoding="utf-8") == "phone7\n"
    assert hostname_pin.read_pin(pin_env) == "phone7"


def test_resolve_candidate_precedence(pin_env):
    hostname_pin.write_pin("phone7", environ=pin_env)
    env = dict(pin_env, FAMILIA_HOST="miryam")
    assert hostname_pin.resolve_candidate(requested="angel", environ=env, hostname="localhost") == "angel"
    assert hostname_pin.resolve_candidate(requested=None, environ=env, hostname="localhost") == "miryam"
    env2 = dict(pin_env)
    assert hostname_pin.resolve_candidate(requested=None, environ=env2, hostname="localhost") == "phone7"
    empty = {"XDG_STATE_HOME": pin_env["XDG_STATE_HOME"] + "-empty"}
    os.makedirs(empty["XDG_STATE_HOME"], exist_ok=True)
    assert hostname_pin.resolve_candidate(requested=None, environ=empty, hostname="Box.local") == "Box"


def test_invalid_name_rejected(pin_env):
    with pytest.raises(SystemExit, match="invalid name"):
        hostname_pin.write_pin("Bad Name", environ=pin_env)
    with pytest.raises(SystemExit, match="invalid name"):
        hostname_pin.write_pin("", environ=pin_env)


def test_select_host_uses_pin_when_os_hostname_unknown(pin_env, monkeypatch):
    hostname_pin.write_pin("phone7", environ=pin_env)
    # Ensure process env matches (select_host defaults environ to os.environ).
    monkeypatch.setenv("XDG_STATE_HOME", pin_env["XDG_STATE_HOME"])
    monkeypatch.delenv("FAMILIA_HOST", raising=False)
    g = {
        "hosts": {
            "phone7": {"kind": "phone", "local_names": []},
            "box": {"kind": "desktop", "local_names": ["grok-bot-vm-x"]},
        }
    }
    assert start_graph.select_host(g, environ=pin_env, hostname="localhost") == "phone7"


def test_select_host_ignores_stale_pin_when_os_hostname_matches(pin_env, monkeypatch):
    """Pin says shalom but OS hostname is miryam → use miryam (not empty shalom topology)."""
    hostname_pin.write_pin("shalom", environ=pin_env)
    monkeypatch.setenv("XDG_STATE_HOME", pin_env["XDG_STATE_HOME"])
    monkeypatch.delenv("FAMILIA_HOST", raising=False)
    g = {
        "hosts": {
            "shalom": {"kind": "unknown", "local_names": ["shalom.local"]},
            "miryam": {"kind": "laptop", "local_names": ["miryam"]},
            "angel": {"kind": "desktop", "local_names": ["gabriel", "angel"]},
        }
    }
    assert start_graph.select_host(g, environ=pin_env, hostname="miryam") == "miryam"
    assert start_graph.select_host(g, environ=pin_env, hostname="angel") == "angel"
    # Explicit pin still wins when OS does not match any host
    assert start_graph.select_host(g, environ=pin_env, hostname="localhost") == "shalom"
    # FAMILIA_HOST / --host still beat OS
    env = dict(pin_env, FAMILIA_HOST="shalom")
    assert start_graph.select_host(g, environ=env, hostname="miryam") == "shalom"
    assert start_graph.select_host(g, requested="shalom", environ=pin_env, hostname="miryam") == "shalom"
