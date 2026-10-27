"""#142: hermes --client cli|desktop|webapp routing (frontend clients)."""
import os
import sys
import tempfile

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh  # noqa: E402
import hermes_modes as hm  # noqa: E402


def test_client_argv_cli_passthrough():
    assert hh.client_argv("cli", ["--tui"]) == ["--tui"]
    assert hh.client_argv("cli", []) == []


def test_client_argv_desktop_and_webapp_prefix():
    assert hh.client_argv("desktop", []) == ["desktop"]
    assert hh.client_argv("desktop", ["--cwd", "/tmp"]) == ["desktop", "--cwd", "/tmp"]
    assert hh.client_argv("webapp", ["--no-open"]) == ["webapp", "--no-open"]


def test_client_argv_rejects_unknown():
    with pytest.raises(SystemExit):
        hh.client_argv("electron", [])


def test_modes_parse_client_default_cli():
    o = hm.parse([])
    assert o["client"] == "cli"


def test_modes_parse_client_desktop():
    o = hm.parse(["--client", "desktop", "--model", "coder"])
    assert o["client"] == "desktop"
    assert o["mode"] == "single"
    assert o["model"] == "coder"


def test_modes_parse_client_webapp():
    o = hm.parse(["--graph-mode", "--client", "webapp"])
    assert o["client"] == "webapp"
    assert o["mode"] == "graph"


def test_modes_parse_bad_client():
    with pytest.raises(SystemExit) as ei:
        hm.parse(["--client", "panel"])
    assert ei.value.code == 2


def test_modes_client_rejected_with_render_only():
    with pytest.raises(SystemExit) as ei:
        hm.parse(["--client", "desktop", "--render-only"])
    assert ei.value.code == 2


def test_harness_parse_argv_client():
    agent, graph, mode, light, swap, client, rest = hh.parse_argv(
        ["--agent", "hermes", "--client", "desktop", "--", "--cwd", "/x"]
    )
    assert client == "desktop"
    assert rest == ["--cwd", "/x"]
    assert mode == "run"


def test_harness_parse_rejects_client_on_render():
    with pytest.raises(SystemExit) as ei:
        hh.parse_argv(["--client", "webapp", "--render-only"])
    assert ei.value.code == 2


def test_ensure_webapp_enabled_sets_flag(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    cfg = home / "config.yaml"
    cfg.write_text("model:\n  default: x\n")
    assert hh.ensure_webapp_enabled(str(home)) is True
    data = yaml.safe_load(cfg.read_text())
    assert data["webapp"]["enabled"] is True
    assert data["model"]["default"] == "x"
    # idempotent
    assert hh.ensure_webapp_enabled(str(home)) is False


def test_require_client_probe_finds_token(monkeypatch):
    monkeypatch.delenv("FAMILIA_HERMES_CLIENT_PROBE", raising=False)

    def fake_run(cmd, **kwargs):
        class R:
            stdout = "Commands:\n  desktop  Launch the GUI\n  webapp   Browser workspace\n"
            stderr = ""
            returncode = 0
        return R()

    hh.require_client_subcommand("/fake/hermes", "desktop", run=fake_run)


def test_require_client_probe_dies_without_token(monkeypatch):
    monkeypatch.delenv("FAMILIA_HERMES_CLIENT_PROBE", raising=False)

    def fake_run(cmd, **kwargs):
        class R:
            stdout = "usage: hermes chat\n"
            stderr = ""
            returncode = 0
        return R()

    with pytest.raises(SystemExit):
        hh.require_client_subcommand("/fake/hermes", "desktop", run=fake_run)


def test_require_client_probe_skippable(monkeypatch):
    monkeypatch.setenv("FAMILIA_HERMES_CLIENT_PROBE", "0")

    def boom(*a, **k):
        raise AssertionError("probe should be skipped")

    hh.require_client_subcommand("/fake/hermes", "webapp", run=boom)


def test_prepare_client_launch_webapp(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILIA_HERMES_CLIENT_PROBE", "0")
    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text("model: {}\n")
    argv = hh.prepare_client_launch(str(home), "webapp", ["--no-open"], bin_path="/fake/hermes")
    assert argv == ["webapp", "--no-open"]
    assert yaml.safe_load((home / "config.yaml").read_text())["webapp"]["enabled"] is True
