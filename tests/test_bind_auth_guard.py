"""serve.sh / launcher auth guard: API key required on every bind, loopback included."""
import os, stat, sys, textwrap
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bind_auth_guard as g  # noqa: E402


def _key(tmp_path, name="api-keys", content="k" * 32, mode=0o600):
    k = tmp_path / name
    k.write_bytes(content.encode())
    k.chmod(mode)
    return str(k)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0", "192.168.1.8"])
def test_refuses_any_bind_without_key(host):
    ok, msg = g.check(["llama-server", "--host", host, "--port", "9941"])
    assert ok is False and "required on every bind" in msg


def test_accepts_loopback_and_lan_with_0600_key_file(tmp_path):
    kf = _key(tmp_path)
    for host in ("127.0.0.1", "0.0.0.0"):
        ok, msg = g.check(["llama-server", "--host", host, "--api-key-file", kf])
        assert ok is True, (host, msg)


def test_last_host_and_equals_form(tmp_path):
    kf = _key(tmp_path)
    ok, msg = g.check(["bin", "--host", "127.0.0.1", "--host=0.0.0.0", "--api-key-file=" + kf])
    assert ok is True, msg
    host, key_file, api_key = g.parse_host_and_key(["bin", "--host", "127.0.0.1", "--host=0.0.0.0"])
    assert host == "0.0.0.0" and key_file is None and api_key is None


def test_refuses_bad_mode_symlink_empty_missing(tmp_path):
    kf = _key(tmp_path, mode=0o644)
    ok, msg = g.check(["bin", "--api-key-file", kf])
    assert ok is False and "0600" in msg
    missing = str(tmp_path / "nope")
    ok, msg = g.check(["bin", "--api-key-file", missing])
    assert ok is False and "missing" in msg
    real = _key(tmp_path, "real")
    link = tmp_path / "link"
    link.symlink_to(real)
    ok, msg = g.check(["bin", "--api-key-file", str(link)])
    assert ok is False and "symlink" in msg
    empty = _key(tmp_path, "empty", content="")
    ok, msg = g.check(["bin", "--api-key-file", empty])
    assert ok is False and "empty" in msg


def test_ensure_creates_missing_0600_file(tmp_path):
    kf = str(tmp_path / "instances" / "9941" / "api-keys")
    ok, msg = g.check(["bin", "--host", "127.0.0.1", "--api-key-file", kf], ensure=True)
    assert ok is True, msg
    st = os.stat(kf)
    assert stat.S_IMODE(st.st_mode) == 0o600
    first = open(kf).read()
    ok, msg = g.check(["bin", "--api-key-file", kf], ensure=True)
    assert ok is True and open(kf).read() == first  # never rotated


def test_inline_api_key_satisfies_rule(tmp_path):
    ok, msg = g.check(["bin", "--host", "0.0.0.0", "--api-key", "secret-token"])
    assert ok is True, msg
    ok, msg = g.check(["bin", "--host", "0.0.0.0", "--api-key="])
    assert ok is False


def test_main_exits_2_on_refuse(tmp_path, capsys):
    assert g.main(["--", "llama-server", "--host", "0.0.0.0"]) == 2
    err = capsys.readouterr().err
    assert "familia-auth-guard:" in err and "refusing" in err


def test_serve_sh_wires_guard():
    src = open(os.path.join(ROOT, "scripts/serve.sh")).read()
    assert "bind_auth_guard.py" in src
    assert src.count('auth_guard "$@"') == 3
    assert "auth_guard() {" in src


def test_launch_auth_argv_always_adds_key_path(tmp_path, monkeypatch):
    import validate_graph as v
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("API_KEY_FILE", raising=False)
    n = {"port": 18120, "bind": "127.0.0.1"}
    path = v.tool_key_path(n)
    assert path.startswith(str(tmp_path)) and "18120" in path
    assert not os.path.exists(path)  # path only; not created here
    assert v.launch_auth_argv({"nodes": {"n": n}}, "n") == ["--api-key-file", path]
    src = __import__("inspect").getsource(v.server_args)
    assert "launch_tools_argv(graph, name) or launch_auth_argv(graph, name)" in src
