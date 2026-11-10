"""hermes_harness.check_toolchain: python floor from the pin file; opt-in installed-vs-pin check."""
import os, sys, types
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh
import hermes_pin as hp

BANNER = "Hermes Agent {v} (2026.9.24) · stable · local {c}\n"


def fake_run(pyver="3.14", banner=None):
    def run(cmd, **kw):
        out = banner if cmd[-1] == "--version" else pyver + "\n"
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
    return run


@pytest.fixture(autouse=True)
def no_channel_py(monkeypatch):
    monkeypatch.setattr(hp, "channel_module", lambda path=None: None)


def test_old_python_warns(capsys):
    w = hh.check_toolchain("/v/bin/hermes", "/v/bin/python", run=fake_run("3.12"), environ={})
    assert w and "needs >= 3.14" in w[0]
    assert "warning" in capsys.readouterr().err


def test_python_314_is_quiet():
    assert hh.check_toolchain("/v/bin/hermes", "/v/bin/python", run=fake_run("3.14"), environ={}) == []


def test_snap_python_not_probed():
    assert hh.check_toolchain(hh.SNAP_BIN, hh.SNAP_PY, run=fake_run("3.12"), environ={}) == []


def test_check_can_be_disabled():
    assert hh.check_toolchain("/v/bin/hermes", "/v/py", run=fake_run("3.11"),
                              environ={"FAMILIA_HERMES_TOOLCHAIN_CHECK": "0"}) == []


def test_pin_check_opt_in_matches_bleeding():
    pin = hp.load_pins()["channels"]["bleeding"]
    run = fake_run(banner=BANNER.format(v=pin["ref"], c=pin["commit"][:12]))
    assert hh.check_toolchain("/v/bin/hermes", "/v/py", run=run, environ={"FAMILIA_HERMES_PIN_CHECK": "1"}) == []


def test_pin_check_follows_channel_and_strict_refuses():
    pin = hp.load_pins()["channels"]["bleeding"]
    run = fake_run(banner=BANNER.format(v=pin["ref"], c=pin["commit"][:12]))
    env = {"FAMILIA_HERMES_PIN_CHECK": "1", "FAMILIA_CHANNEL": "stable"}
    w = hh.check_toolchain("/v/bin/hermes", "/v/py", run=run, environ=env)
    assert w and "stable pin" in w[0]
    with pytest.raises(SystemExit):
        hh.check_toolchain("/v/bin/hermes", "/v/py", run=run, environ=dict(env, FAMILIA_HERMES_PIN_CHECK="strict"))
