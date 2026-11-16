"""scripts/swarm/bench_idle.py: run-when-idle trigger for scripts/swarm/bench.sh (stubbed here;
no real bench, model or llama-bench is ever started by these tests)."""
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "swarm", "bench_idle.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safe_temp  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "scripts", "swarm"))
import bench_idle as bi  # noqa: E402

IDLE = lambda: ((0.0, 0.0), 1 << 20, [])  # noqa: E731
STUB = """#!/bin/sh
env > "$STUB_OUT/env"
pwd > "$STUB_OUT/cwd"
python3 -c 'import os; print(os.nice(0))' > "$STUB_OUT/nice"
echo x > "$TMPDIR/scratch"
[ -n "${STUB_SLEEP:-}" ] && sleep "$STUB_SLEEP"
echo "| node | model | backend | threads | test | tok/s |"
echo "| n | m | CPU | 1 | tg128 | 1.0 |"
exit ${STUB_RC:-0}
"""


@pytest.fixture
def base():
    # User-owned and never under /tmp, /var/tmp or /dev/shm. The repo's
    # gitignored .cache is used when the checkout is outside those roots;
    # a /tmp checkout falls back to a real-home cache (see safe_temp).
    parent = safe_temp.safe_temp_parent()
    d = tempfile.mkdtemp(prefix="test-bench-idle-", dir=parent)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _setup(base, rc=0):
    out = os.path.join(base, "stub-out")
    os.mkdir(out)
    bench = os.path.join(base, "bench.sh")
    with open(bench, "w") as f:
        f.write(STUB)
    os.chmod(bench, 0o755)
    env = dict(os.environ, STUB_OUT=out, STUB_RC=str(rc), SWARM_BENCH_FORCE="1",
               SWARM_BENCH_IDLE_STATE=os.path.join(base, "state"))
    return bench, out, env


def _env_of(out):
    return dict(line.split("=", 1) for line in open(os.path.join(out, "env")).read().splitlines() if "=" in line)


def test_busy_reason_idle_vs_busy():
    assert bi.busy_reason((0.1, 0.2), 8000, [], 2.0, 4096) is None
    assert bi.busy_reason((0.1, 0.2), None, [], 2.0, 4096) is None  # RAM left to bench.sh's guard
    assert "load1" in bi.busy_reason((2.0, 0.1), 8000, [], 2.0, 4096)
    assert "load5" in bi.busy_reason((0.1, 3.0), 8000, [], 2.0, 4096)
    assert "MemAvailable" in bi.busy_reason((0.1, 0.1), 100, [], 2.0, 4096)
    assert "llama-server" in bi.busy_reason((0.0, 0.0), 8000, ["llama-server"], 2.0, 4096)
    assert bi.default_max_load(1) == 1.0 and bi.default_max_load(16) == 4.0


def test_busy_host_does_not_run_bench(base):
    bench, out, env = _setup(base)
    busy = lambda: ((50.0, 50.0), 1 << 20, [])  # noqa: E731
    assert bi.main(["--bench", bench], env=env, probe=busy) == 0
    assert not os.path.exists(os.path.join(out, "env"))
    assert not os.path.exists(os.path.join(base, "state", "stamp.json"))  # busy is not an attempt


def test_idle_runs_bench_without_force_low_priority_cpu_only(base):
    bench, out, env = _setup(base)
    assert bi.main(["--bench", bench], env=env, probe=IDLE) == 0
    e = _env_of(out)
    assert "SWARM_BENCH_FORCE" not in e  # inherited FORCE is stripped; bench.sh guards stay on
    assert e["CUDA_VISIBLE_DEVICES"] == "" and e["GGML_VK_VISIBLE_DEVICES"] == ""
    assert int(open(os.path.join(out, "nice")).read()) == 19
    for base_env in ({}, {"SWARM_BENCH_FORCE": "1"}, {"SWARM_BENCH_FORCE": "0"}):
        assert "SWARM_BENCH_FORCE" not in bi.bench_env(base_env, "/x")


def test_outputs_user_owned_private_not_tmp_and_tempdir_cleaned(base):
    bench, out, env = _setup(base)
    assert bi.main(["--bench", bench], env=env, probe=IDLE) == 0
    sd = os.path.join(base, "state")
    tmpdir = _env_of(out)["TMPDIR"]
    assert os.path.dirname(tmpdir) == sd and os.path.basename(tmpdir).startswith("run-")
    assert open(os.path.join(out, "cwd")).read().strip() == tmpdir
    assert not os.path.exists(tmpdir)  # private per-run temp dir removed
    assert not [n for n in os.listdir(sd) if n.startswith("run-")]
    for d in (sd, os.path.join(sd, "results")):
        st = os.stat(d)
        assert st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o700
    (res,) = os.listdir(os.path.join(sd, "results"))
    p = os.path.join(sd, "results", res)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600 and "tg128" in open(p).read()
    assert not bi._under_tmp(p)
    run = json.loads(open(os.path.join(sd, "runs.jsonl")).read().splitlines()[-1])
    assert run["status"] == "ok" and run["rc"] == 0 and run["result"] == p


@pytest.mark.parametrize("bad", ["/tmp/familia-bench", "/var/tmp/x", "/dev/shm/x"])
def test_refuses_shared_temp_state_dir(bad, base):
    bench, out, env = _setup(base)
    env["SWARM_BENCH_IDLE_STATE"] = bad
    assert bi.main(["--bench", bench], env=env, probe=IDLE) == 2
    assert not os.path.exists(os.path.join(out, "env"))


def test_default_state_dir_is_xdg_or_home():
    assert bi.state_dir({"XDG_STATE_HOME": "/srv/st"}) == "/srv/st/familia/bench"
    assert bi.state_dir({"XDG_STATE_HOME": "relative"}).endswith("/.local/state/familia/bench")
    assert bi.state_dir({}) == os.path.join(os.path.expanduser("~"), ".local", "state", "familia", "bench")


def test_min_interval_respected(base):
    bench, out, env = _setup(base)
    t = 1_000_000.0
    assert bi.main(["--bench", bench, "--min-interval", "3600"], env=env, now=t, probe=IDLE) == 0
    os.remove(os.path.join(out, "env"))
    assert bi.main(["--bench", bench, "--min-interval", "3600"], env=env, now=t + 3599, probe=IDLE) == 0
    assert not os.path.exists(os.path.join(out, "env"))
    assert bi.main(["--bench", bench, "--min-interval", "3600"], env=env, now=t + 3600, probe=IDLE) == 0
    assert os.path.exists(os.path.join(out, "env"))


def test_backoff_after_bench_skip_doubles_and_caps():
    assert bi.too_soon({}, 100, 3600, 900) == 0
    assert bi.too_soon({"last_attempt": 100, "skips": 1}, 100, 3600, 900) == 900
    assert bi.too_soon({"last_attempt": 100, "skips": 2}, 100, 3600, 900) == 1800
    assert bi.too_soon({"last_attempt": 100, "skips": 9}, 100, 3600, 900) == 3600
    assert bi.too_soon({"last_attempt": 100, "skips": 0}, 100, 3600, 900) == 3600
    assert bi.too_soon({"last_attempt": 500, "skips": 0}, 100, 3600, 900) == 0  # clock went back


def test_bench_skip_is_recorded_with_backoff(base):
    bench, out, env = _setup(base, rc=78)
    assert bi.main(["--bench", bench], env=env, now=5000.0, probe=IDLE) == 0
    s = json.load(open(os.path.join(base, "state", "stamp.json")))
    assert s["status"] == "skipped" and s["skips"] == 1 and s["last_rc"] == 78


def test_bench_failure_exits_1(base):
    bench, out, env = _setup(base, rc=1)
    assert bi.main(["--bench", bench], env=env, probe=IDLE) == 1


def test_lock_held_skips_without_running(base):
    bench, out, env = _setup(base)
    sd = os.path.join(base, "state")
    os.makedirs(sd, mode=0o700)
    with open(os.path.join(sd, "bench_idle.lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        assert bi.main(["--bench", bench], env=env, probe=IDLE) == 0
    assert not os.path.exists(os.path.join(out, "env"))


def test_concurrent_triggers_do_not_overlap(base):
    bench, out, env = _setup(base)
    env.update(STUB_SLEEP="3", SWARM_BENCH_IDLE_MAX_LOAD="1e9", SWARM_BENCH_IDLE_MIN_AVAIL_MIB="0",
               SWARM_BENCH_IDLE_BUSY_PROCS="no-such-proc-bench-idle-test")
    cmd = [sys.executable, SCRIPT, "--bench", bench]
    p1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, text=True)
    deadline = time.time() + 20
    while not os.path.exists(os.path.join(out, "env")) and time.time() < deadline:
        time.sleep(0.05)
    p2 = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
    o1, _ = p1.communicate(timeout=30)
    assert p1.returncode == 0 and "ok (bench.sh exit 0)" in o1
    assert p2.returncode == 0 and "another trigger holds the lock" in p2.stdout


def test_disarmed_skips(base):
    bench, out, env = _setup(base)
    sd = os.path.join(base, "state")
    os.makedirs(sd, mode=0o700)
    open(os.path.join(sd, "disarmed"), "w").close()
    assert bi.main(["--bench", bench], env=env, probe=IDLE) == 0
    assert not os.path.exists(os.path.join(out, "env"))


def test_dry_run_never_runs(base):
    bench, out, env = _setup(base)
    assert bi.main(["--bench", bench, "--dry-run"], env=env, probe=IDLE) == 0
    assert not os.path.exists(os.path.join(out, "env"))


def test_no_listeners_and_installer_does_not_enable():
    src = open(SCRIPT).read()
    for bad in (".bind(", ".listen(", "socketserver", "http.server", "sudo", "/etc/"):
        assert bad not in src, bad
    for top in ("install", "install.sh", "build-automation.sh"):
        p = os.path.join(ROOT, top)
        files = [p] if os.path.isfile(p) else [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs]
        for f in files:
            t = open(f, encoding="utf-8", errors="ignore").read()
            assert "bench_idle" not in t and "familia-bench-idle" not in t, f


def test_example_units_are_user_level_and_low_priority():
    d = os.path.join(ROOT, "packaging", "systemd-user")
    raw = open(os.path.join(d, "familia-bench-idle.service")).read()
    svc = "\n".join(line for line in raw.splitlines() if not line.startswith("#"))
    tmr = open(os.path.join(d, "familia-bench-idle.timer")).read()
    assert "Nice=19" in svc and "IOSchedulingClass=idle" in svc and "bench_idle.py" in svc
    assert "SWARM_BENCH_FORCE" not in svc and "User=" not in svc and "sudo" not in svc
    assert "WantedBy=timers.target" in tmr and "OnUnitActiveSec=" in tmr
