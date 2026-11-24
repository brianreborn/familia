"""Tests for scripts/android-model-trials.py (PR #757 review fixes)."""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "android-model-trials.py"
TERMUX_HOME = "/data/data/com.termux/files/home"


def load():
    spec = importlib.util.spec_from_file_location("android_model_trials", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDevice:
    instances = []

    def __init__(self, *args, **kwargs):
        self.commands, self.forwarded, self.unforwarded = [], [], []
        self.port_states = []
        FakeDevice.instances.append(self)

    def shell(self, command, timeout=None):
        self.commands.append(command)
        if "api.key" in command and "cat " in command:
            return "k" * 64
        if "/proc/net/tcp" in command:
            return self.port_states.pop(0) if self.port_states else "free"
        if command.startswith("cat ") and ".state" in command:
            return "RUNNING"
        return ""

    def forward(self, port):
        self.forwarded.append(port)

    def unforward(self, port):
        self.unforwarded.append(port)


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps({"content": "def f(n): ...", "timings": {"predicted_per_second": 5.0}}).encode()


@pytest.fixture
def mod(monkeypatch, tmp_path):
    m = load()
    FakeDevice.instances.clear()
    monkeypatch.setattr(m, "Device", FakeDevice)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    return m


ARGS = ["--serial", "SERIAL123", "--ctx", "8192"]


def test_server_binds_with_api_key_and_requests_send_bearer(mod, monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req)
        return FakeResponse()

    monkeypatch.setattr(mod, "health", lambda *a, **k: True)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.main(ARGS) == 0
    dev = FakeDevice.instances[-1]
    key_file = f"{TERMUX_HOME}/.config/familia/api.key"
    keygen = next(c for c in dev.commands if "api.key" in c and "chmod 600" in c)
    assert "umask 077" in keygen
    starts = [c for c in dev.commands if "llama-server --model" in c]
    assert starts and all(f"--api-key-file {key_file}" in c for c in starts)
    assert seen and all(r.get_header("Authorization") == "Bearer " + "k" * 64 for r in seen)


def test_watchdog_script_is_valid_sh(mod):
    dev = FakeDevice()
    mod.start_watchdog(dev, "/x/trials/r/cpu", "/x/m.gguf", 0, 18102, 8192, 4, "/x/api.key")
    body = re.search(r"<<'WATCHDOG_SCRIPT'\n(.*)WATCHDOG_SCRIPT", dev.commands[-1], re.S).group(1)
    sh = shutil.which("dash") or shutil.which("sh")
    subprocess.run([sh, "-n"], input=body, text=True, check=True)
    assert "--api-key-file /x/api.key" in body


def test_default_home_is_host_neutral(mod, monkeypatch):
    monkeypatch.setattr(mod, "health", lambda *a, **k: True)
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse())
    mod.main(ARGS)
    dev = FakeDevice.instances[-1]
    assert any(f"{TERMUX_HOME}/familia/trials/" in c for c in dev.commands)
    assert "note9" not in SCRIPT.read_text().lower()
    journals = list(Path(".").glob("android-model-trials-*.jsonl"))
    assert journals and "SERIAL123" not in journals[0].name and "SERIAL123" not in journals[0].read_text()


def test_interrupt_stops_active_server_and_watchdog(mod, monkeypatch):
    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(mod, "health", boom)
    with pytest.raises(KeyboardInterrupt):
        mod.main(ARGS)
    dev = FakeDevice.instances[-1]
    stops = [c for c in dev.commands if "/cpu.stop" in c]
    assert stops, "interrupt must touch the active trial's stop file"
    assert "kill" in stops[-1] and "kill -9" in stops[-1]
    assert dev.unforwarded == [18102]


def test_sigterm_is_turned_into_interrupt(mod):
    with pytest.raises(KeyboardInterrupt):
        mod._raise_interrupt(15, None)


def test_partial_failure_exit_code(mod, monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("vulkan trial failed")
        return FakeResponse()

    monkeypatch.setattr(mod, "health", lambda *a, **k: True)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.main(ARGS) == 3


def test_teardown_waits_for_shared_port_before_next_trial(mod, monkeypatch):
    monkeypatch.setattr(mod, "health", lambda *a, **k: True)
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse())
    assert mod.main(ARGS) == 0
    cmds = FakeDevice.instances[-1].commands
    starts = [i for i, c in enumerate(cmds) if "llama-server --model" in c]
    stops = [i for i, c in enumerate(cmds) if c.startswith("touch") and "/cpu.stop" in c]
    checks = [i for i, c in enumerate(cmds) if "/proc/net/tcp" in c]
    assert len(starts) == 2
    # every server start is preceded by a port check, and the cpu stop (TERM, wait, KILL) and a
    # port check both land before the vulkan server starts
    assert all(any(c < s for c in checks) for s in starts)
    assert stops and stops[0] < starts[1]
    assert any(stops[0] < c < starts[1] for c in checks)
    stop = cmds[stops[0]]
    assert stop.index('kill "$p"') < stop.index("sleep 1") < stop.index("kill -9")


def test_stop_trial_waits_until_port_is_free(mod):
    dev = FakeDevice()
    dev.port_states = ["busy", "busy", "free"]
    mod.stop_trial(dev, "/x/cpu", port=18102)
    assert dev.port_states == []


def test_leftover_server_on_port_blocks_next_trial(mod, monkeypatch):
    monkeypatch.setattr(mod, "STOP_GRACE_SECONDS", 0)
    dev = FakeDevice()
    dev.port_states = ["busy"] * 50
    with pytest.raises(RuntimeError, match="still in use"):
        mod.wait_port_free(dev, 18102, seconds=0)


def test_watchdog_skips_health_kill_during_inflight_request(mod):
    dev = FakeDevice()
    mod.start_watchdog(dev, "/x/cpu", "/x/m.gguf", 0, 18102, 8192, 4, "/x/api.key")
    body = dev.commands[-1]
    assert "if [ -e /x/cpu.busy ]; then\n    failures=0" in body


def test_keep_best_leaves_forward_in_place(mod, monkeypatch):
    monkeypatch.setattr(mod, "health", lambda *a, **k: True)
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse())
    assert mod.main(ARGS + ["--keep-best"]) == 0
    dev = FakeDevice.instances[-1]
    assert dev.forwarded == [18102] and dev.unforwarded == []
    assert not any(c.startswith("touch") and "/final.stop" in c for c in dev.commands)


def test_forward_clears_stale_forward_first(mod, monkeypatch):
    calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda argv, **k: calls.append(argv))
    real = load().Device
    dev = real.__new__(real)
    dev.adb, dev.serial = "adb", "S"
    dev.forward(18102)
    assert calls[0][-2:] == ["--remove", "tcp:18102"]
    assert calls[1][-2:] == ["tcp:18102", "tcp:18102"]
