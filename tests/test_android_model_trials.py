"""Tests for scripts/android-model-trials.py (PR #757 review fixes)."""
import importlib.util
import json
import re
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "android-model-trials.py"
TERMUX_HOME = "/data/data/com.termux/files/home"
REAL_SLEEP = time.sleep


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
        self.owner = "ours"
        FakeDevice.instances.append(self)

    def shell(self, command, timeout=None):
        self.commands.append(command)
        if "api.key" in command and "cat " in command:
            return "k" * 64
        if "socket:" in command:
            return self.owner
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
    term = stop.index("kill -TERM")
    assert term < stop.index("sleep 1", term) < stop.index("kill -9")


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


def test_keep_best_leaves_forward_in_place(mod, monkeypatch):
    monkeypatch.setattr(mod, "health", lambda *a, **k: True)
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse())
    assert mod.main(ARGS + ["--keep-best"]) == 0
    dev = FakeDevice.instances[-1]
    assert dev.forwarded == [18102] and dev.unforwarded == []
    assert not any(c.startswith("touch") and "/final.stop" in c for c in dev.commands)


class Run:
    def __init__(self, stdout=""):
        self.stdout = stdout


def fake_adb(monkeypatch, mod, listing):
    calls = []

    def run(argv, **k):
        calls.append(argv)
        return Run(listing if argv[-1] == "--list" else "")

    monkeypatch.setattr(mod.subprocess, "run", run)
    real = load().Device
    dev = real.__new__(real)
    dev.adb, dev.serial = "adb", "OURS"
    return dev, calls


def test_forward_clears_only_our_own_stale_forward(mod, monkeypatch):
    dev, calls = fake_adb(monkeypatch, mod, "OURS tcp:18102 tcp:18102\nOTHER tcp:18200 tcp:18102\n")
    dev.forward(18102)
    assert [c[-2:] for c in calls[1:]] == [["--remove", "tcp:18102"], ["tcp:18102", "tcp:18102"]]
    assert all("-s" in c and "OURS" in c for c in calls[1:])


def test_forward_refuses_port_held_by_another_device(mod, monkeypatch):
    dev, calls = fake_adb(monkeypatch, mod, "OTHER tcp:18102 tcp:18102\n")
    with pytest.raises(RuntimeError, match="another device"):
        dev.forward(18102)
    assert not any("--remove" in c for c in calls)


def test_forward_with_no_existing_forward_removes_nothing(mod, monkeypatch):
    dev, calls = fake_adb(monkeypatch, mod, "")
    dev.forward(18102)
    assert not any("--remove" in c for c in calls)


def test_trial_fails_when_another_process_owns_the_port(mod, monkeypatch):
    seen = []
    monkeypatch.setattr(mod, "health", lambda *a, **k: True)  # a foreign server answers 200
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout=None: seen.append(req) or FakeResponse())
    real_init = FakeDevice.__init__

    def init(self, *a, **k):
        real_init(self, *a, **k)
        self.owner = "other"

    monkeypatch.setattr(FakeDevice, "__init__", init)
    assert mod.main(ARGS + ["--startup-timeout", "1"]) == 1
    assert seen == []
    assert "PORT_OWNED_BY_OTHER" in next(Path(".").glob("android-model-trials-*.jsonl")).read_text()


def test_interrupt_cleanup_waits_for_port_and_always_unforwards(mod, monkeypatch):
    monkeypatch.setattr(mod, "health", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        mod.main(ARGS)
    dev = FakeDevice.instances[-1]
    stop = max(i for i, c in enumerate(dev.commands) if c.startswith("touch") and "/cpu.stop" in c)
    assert any("/proc/net/tcp" in c and "socket:" not in c for c in dev.commands[stop + 1:])
    assert dev.unforwarded == [18102]


def test_second_interrupt_during_stop_still_unforwards(mod, monkeypatch):
    monkeypatch.setattr(mod, "health", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    real_shell = FakeDevice.shell

    def shell(self, command, timeout=None):
        if command.startswith("touch") and ".stop" in command:
            raise KeyboardInterrupt
        return real_shell(self, command, timeout)

    monkeypatch.setattr(FakeDevice, "shell", shell)
    with pytest.raises(KeyboardInterrupt):
        mod.main(ARGS)
    assert FakeDevice.instances[-1].unforwarded == [18102]


# ---- runtime tests: run the real phone-side shell locally ----

class LocalDevice:
    def __init__(self, stubs):
        self.env = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}")

    def shell(self, command, timeout=None):
        return subprocess.run(["sh", "-c", command], env=self.env, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout or 60).stdout.strip()


def stub(directory, name, body):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z" if Path(f"/proc/{pid}").exists() else True


@pytest.fixture
def phone(mod, monkeypatch, tmp_path):
    if not shutil.which("setsid"):
        pytest.skip("needs setsid")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    monkeypatch.setattr(mod.time, "sleep", REAL_SLEEP)  # runtime tests need real time
    monkeypatch.setattr(mod, "PHONE_SH", "/bin/sh")
    monkeypatch.setattr(mod, "WATCHDOG_TICK_SECONDS", 0.05)
    monkeypatch.setattr(mod, "HEALTH_PROBE_SECONDS", 0.05)
    monkeypatch.setattr(mod, "STOP_GRACE_SECONDS", 1)
    return stubs, LocalDevice(stubs), tmp_path


def test_runtime_busy_during_failed_probe_does_not_kill_request(mod, phone):
    stubs, dev, tmp = phone
    base = str(tmp / "cpu")
    count = tmp / "probes"
    stub(stubs, "llama-server", "exec sleep 60\n")
    # /health always fails; the 3rd probe (failures already 2) sees the request start mid-probe
    stub(stubs, "python3", f"n=$(( $(cat {count} 2>/dev/null || echo 0) + 1 )); echo $n > {count}\n"
                           f"[ $n -ge 3 ] && touch {base}.busy\nexit 1\n")
    mod.start_watchdog(dev, base, "/m.gguf", 0, 18102, 8192, 4, "/k")
    assert wait_for(lambda: Path(base + ".pid").exists() and Path(base + ".pid").read_text().strip())
    pid = int(Path(base + ".pid").read_text())
    Path(base + ".ready").touch()
    assert wait_for(lambda: count.exists() and int(count.read_text() or 0) >= 3)
    time.sleep(0.5)  # many ticks with failures==2 and a request in flight
    assert Path(base + ".state").read_text().strip() == "RUNNING" and alive(pid)
    Path(base + ".busy").unlink()  # request finished; failing probes now count again
    stub(stubs, "python3", "exit 1\n")
    assert wait_for(lambda: Path(base + ".state").read_text().strip() == "UNHEALTHY")
    assert wait_for(lambda: not alive(pid))


def test_runtime_stop_trial_kills_server_and_watchdog_even_if_term_ignored(mod, phone):
    stubs, dev, tmp = phone
    base = str(tmp / "cpu")
    stub(stubs, "llama-server", "trap '' TERM\nwhile :; do sleep 0.2; done\n")
    stub(stubs, "python3", "exit 0\n")
    mod.start_watchdog(dev, base, "/m.gguf", 0, 18102, 8192, 4, "/k")
    assert wait_for(lambda: all(Path(base + s).exists() and Path(base + s).read_text().strip()
                                for s in (".pid", ".wpid")))
    pid, wpid = int(Path(base + ".pid").read_text()), int(Path(base + ".wpid").read_text())
    Path(base + ".stop").write_text("")  # watchdog would only TERM the server, which ignores it
    mod.stop_trial(dev, base)
    assert not alive(pid) and not alive(wpid)


def test_runtime_stop_trial_waits_for_late_pidfile(mod, phone):
    stubs, dev, tmp = phone
    base = tmp / "cpu"
    Path(str(base) + ".watchdog.sh").write_text("")
    # detached (reparented) like the real watchdog, so a killed pid is reaped, not a zombie of pytest
    subprocess.run(["sh", "-c", f"nohup sh -c 'sleep 0.5; echo $$ > {base}.pid; echo $$ > {base}.wpid; "
                                "exec sleep 30' >/dev/null 2>&1 &"], check=True)
    mod.stop_trial(dev, str(base))
    pid = int(Path(f"{base}.pid").read_text())
    assert wait_for(lambda: not alive(pid), 3)


def test_runtime_port_owner_checks_the_pidfile_pid(mod, phone):
    _, dev, tmp = phone
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    pidfile = tmp / "srv.pid"
    pidfile.write_text(str(os.getpid()))
    assert mod.port_owner(dev, port, str(pidfile)) == "none"
    sock.listen()
    assert mod.port_owner(dev, port, str(pidfile)) == "ours"
    pidfile.write_text("1")
    assert mod.port_owner(dev, port, str(pidfile)) == "other"
    sock.close()
    assert mod.port_owner(dev, port, str(pidfile)) == "none"
