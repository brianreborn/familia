"""#96: per-host cache for hermes-agent env_probe "Python toolchain:" line."""
import importlib
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY = os.path.join(ROOT, "scripts", "hermes_env_probe_cache")
sys.path.insert(0, OVERLAY)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import familia_env_probe_cache as fepc  # noqa: E402
import hermes_harness as hh  # noqa: E402


def test_cache_path_uses_xdg_and_hostname(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("HOME", raising=False)
    p = fepc.cache_path(hostname="angel.local", environ=os.environ)
    assert p == str(tmp_path / "xdg" / "familia" / "hermes-env-probe" / "angel.local")


def test_cache_path_falls_back_to_home_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    p = fepc.cache_path(hostname="box", environ=dict(os.environ))
    assert p.endswith(os.path.join(".cache", "familia", "hermes-env-probe", "box"))


def test_hostname_key_strips_separators():
    assert "/" not in fepc.hostname_key("a/b\\c")
    assert fepc.hostname_key("") == "unknown"


def test_cached_build_stores_first_and_ignores_later_builds(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(fepc.REFRESH_ENV, raising=False)
    path = fepc.cache_path(hostname="host1", environ=os.environ)
    calls = {"n": 0}
    lines = [
        "Python toolchain: python3=3.14.4 (no pip module), pip=missing.",
        "Python toolchain: python3=3.14.4, pip→python3.14.",
    ]

    def build():
        i = calls["n"]
        calls["n"] += 1
        return lines[min(i, len(lines) - 1)]

    first = fepc.cached_build(build, hostname="host1", environ=os.environ)
    second = fepc.cached_build(build, hostname="host1", environ=os.environ)
    assert first == lines[0]
    assert second == lines[0]
    assert calls["n"] == 1
    assert fepc.read_cache(path) == lines[0]


def test_cached_build_stores_empty_clean_line(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(fepc.REFRESH_ENV, raising=False)
    out = fepc.cached_build(lambda: "", hostname="clean", environ=os.environ)
    assert out == ""
    assert fepc.read_cache(fepc.cache_path(hostname="clean", environ=os.environ)) == ""
    # Second call must not re-build
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return "SHOULD_NOT_SEE"

    assert fepc.cached_build(build, hostname="clean", environ=os.environ) == ""
    assert calls["n"] == 0


def test_refresh_env_forces_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(fepc.REFRESH_ENV, raising=False)
    fepc.cached_build(lambda: "line-a", hostname="r", environ=os.environ)
    monkeypatch.setenv(fepc.REFRESH_ENV, "1")
    out = fepc.cached_build(lambda: "line-b", hostname="r", environ=os.environ)
    assert out == "line-b"
    assert fepc.read_cache(fepc.cache_path(hostname="r", environ=os.environ)) == "line-b"


def test_wrap_env_probe_module_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(fepc.REFRESH_ENV, raising=False)
    calls = {"n": 0}

    def orig():
        calls["n"] += 1
        return f"line-{calls['n']}"

    mod = types.ModuleType("tools.env_probe")
    mod._build_probe_line = orig
    assert fepc.wrap_env_probe_module(mod) is True
    assert fepc.wrap_env_probe_module(mod) is False
    assert mod._build_probe_line() == "line-1"
    assert mod._build_probe_line() == "line-1"
    assert calls["n"] == 1


def test_hermes_child_env_prepends_overlay(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/other")
    env = hh.hermes_child_env({"HERMES_HOME": "/tmp/h"})
    assert env["HERMES_HOME"] == "/tmp/h"
    parts = env["PYTHONPATH"].split(os.pathsep)
    assert parts[0] == hh.ENV_PROBE_CACHE_OVERLAY
    assert "/other" in parts
    # idempotent prepend
    env2 = hh.hermes_child_env(environ=env)
    assert env2["PYTHONPATH"].split(os.pathsep).count(hh.ENV_PROBE_CACHE_OVERLAY) == 1


def test_unstable_lines_kept_for_defense_in_depth():
    assert "Python toolchain:" in hh.UNSTABLE_LINES


def test_sitecustomize_hook_wraps_on_import(tmp_path, monkeypatch):
    """Simulate two process builds: first writes cache; second import sees same line."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(fepc.REFRESH_ENV, raising=False)
    # Fake tools package + env_probe as a real importable module
    tools = types.ModuleType("tools")
    tools.__path__ = []  # package
    sys.modules["tools"] = tools

    probe = types.ModuleType("tools.env_probe")
    builds = {"n": 0, "lines": ["first-probe", "second-probe"]}

    def _build():
        i = builds["n"]
        builds["n"] += 1
        return builds["lines"][min(i, 1)]

    probe._build_probe_line = _build
    # Install hook, then present module as if freshly imported via finder path:
    # wrap directly (finder path covered by wrap_env_probe_module).
    fepc.install_import_hook()
    assert fepc.wrap_env_probe_module(probe) is True
    assert probe._build_probe_line() == "first-probe"

    # "Second process": new module object, same host cache file
    probe2 = types.ModuleType("tools.env_probe")
    builds2 = {"n": 0}

    def _build2():
        builds2["n"] += 1
        return "second-probe"

    probe2._build_probe_line = _build2
    # Clear wrap attr namespace — new module
    assert fepc.wrap_env_probe_module(probe2) is True
    assert probe2._build_probe_line() == "first-probe"
    assert builds2["n"] == 0

    # cleanup hook / modules
    if fepc._FINDER in sys.meta_path:
        sys.meta_path.remove(fepc._FINDER)
    fepc._FINDER = None
    sys.modules.pop("tools.env_probe", None)
    sys.modules.pop("tools", None)
