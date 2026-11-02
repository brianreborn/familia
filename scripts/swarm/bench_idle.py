#!/usr/bin/env python3
"""Run scripts/swarm/bench.sh automatically when this host is idle (opt-in, per host:user).

usage: python3 scripts/swarm/bench_idle.py [--dry-run] [--state-dir DIR] [--bench PATH]
           [--min-interval SEC] [--backoff SEC] [--max-load N] [--min-avail-mib MIB]
           [--timeout SEC]

One-shot: a scheduler (systemd --user timer or a user crontab line, see docs/swarm-bench.md)
calls it every few minutes. Each call:
  1. takes an flock on STATE/bench_idle.lock (non-blocking; a second trigger exits at once),
  2. honours STATE/disarmed, the min interval after a run, and the backoff after a skip,
  3. checks idleness: 1- and 5-min load < --max-load, MemAvailable >= --min-avail-mib,
     no llama-server / llama-cli / llama-bench / llama-run process
     (comma list override: SWARM_BENCH_IDLE_BUSY_PROCS),
  4. runs bench.sh at the lowest priority (nice 19, ionice idle class where available),
     CPU only (GPU devices hidden), with SWARM_BENCH_FORCE removed so bench.sh's own
     idle and RAM guards always apply,
  5. writes the markdown table to STATE/results/<UTC stamp>.md (0600) and one JSON line
     to STATE/runs.jsonl.
STATE = $SWARM_BENCH_IDLE_STATE, else $XDG_STATE_HOME/familia/bench, else
$HOME/.local/state/familia/bench. It is created 0700, must be owned by you, and must not be
under /tmp, /var/tmp or /dev/shm. Temp work uses one private mkdtemp() under STATE per run
(also exported as TMPDIR to bench.sh), removed when the run ends. Nothing listens on a socket.

Exit: 0 ran OK or skipped (busy, locked, too soon, disarmed, bench.sh 77/78), 1 bench failed,
2 bad arguments or unsafe state dir. Installs nothing; enabling a system-level unit, fstab or
rc.conf change needs the owner's explicit yes (docs/swarm-bench.md).

Example: python3 scripts/swarm/bench_idle.py --dry-run
"""
import argparse
import datetime
import errno
import fcntl
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BENCH = os.path.join(HERE, "bench.sh")
BUSY_PROCS = ("llama-server", "llama-cli", "llama-bench", "llama-run", "llama-mtmd-cli")
TMP_ROOTS = ("/tmp", "/var/tmp", "/dev/shm", "/private/tmp")
SKIP_RCS = (77, 78)
# Every GPU runtime llama.cpp can be built with: hide all devices so the idle bench is CPU only.
CPU_ONLY_ENV = {"CUDA_VISIBLE_DEVICES": "", "HIP_VISIBLE_DEVICES": "", "ROCR_VISIBLE_DEVICES": "",
                "GGML_VK_VISIBLE_DEVICES": "", "ONEAPI_DEVICE_SELECTOR": "opencl:none"}


class UnsafeStateDir(Exception):
    pass


def nproc():
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def default_max_load(n=None):
    """Stricter than bench.sh (nproc/2): a quarter of the cores, at least 1."""
    n = n or nproc()
    return max(1.0, n / 4.0)


def state_dir(env=None):
    env = os.environ if env is None else env
    if env.get("SWARM_BENCH_IDLE_STATE"):
        return os.path.abspath(os.path.expanduser(env["SWARM_BENCH_IDLE_STATE"]))
    xdg = (env.get("XDG_STATE_HOME") or "").strip()
    base = xdg if os.path.isabs(xdg) else os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "familia", "bench")


def _under_tmp(path):
    real = os.path.realpath(path)
    roots = set(TMP_ROOTS) | {os.path.realpath(r) for r in TMP_ROOTS}
    return any(real == r or real.startswith(r.rstrip("/") + "/") for r in roots)


def ensure_private_dir(path):
    """Create PATH 0700 (parents 0700 too if new); refuse /tmp, foreign owners, symlinks."""
    if _under_tmp(path):
        raise UnsafeStateDir(f"state dir under a shared temp root: {path}")
    old = os.umask(0o077)
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    finally:
        os.umask(old)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise UnsafeStateDir(f"state dir is not a plain directory: {path}")
    if st.st_uid != os.geteuid():
        raise UnsafeStateDir(f"state dir not owned by you: {path}")
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(path, 0o700)
    return path


def load_avg():
    try:
        return os.getloadavg()[:2]
    except OSError:
        return None


def mem_available_mib(paths=("/proc/meminfo", "/compat/linux/proc/meminfo")):
    for p in paths:
        try:
            with open(p, encoding="ascii", errors="ignore") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            continue
    return None  # bench.sh's own RAM guard then decides (exit 77 = guard unavailable)


def running_procs(names=BUSY_PROCS):
    """Names from NAMES that are running now (pgrep -x, else /proc/*/comm)."""
    found = []
    pg = shutil.which("pgrep")
    for n in names:
        if pg:
            if subprocess.run([pg, "-x", n], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                found.append(n)
            continue
        try:
            for pid in os.listdir("/proc"):
                if pid.isdigit():
                    try:
                        with open(f"/proc/{pid}/comm") as f:
                            if f.read().strip() == n:
                                found.append(n)
                                break
                    except OSError:
                        pass
        except OSError:
            break
    return found


def busy_reason(load, avail_mib, procs, max_load, min_avail_mib):
    """None when idle, else a short reason. Pure: tests drive it directly."""
    if procs:
        return "running: " + ",".join(procs)
    if load is not None:
        l1, l5 = load
        if l1 >= max_load:
            return f"load1 {l1:.2f} >= {max_load:g}"
        if l5 >= max_load:
            return f"load5 {l5:.2f} >= {max_load:g}"
    if avail_mib is not None and avail_mib < min_avail_mib:
        return f"MemAvailable {avail_mib}MiB < {min_avail_mib}MiB"
    return None


def read_stamp(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_private(path, text):
    """Atomic 0600 write inside a directory we own."""
    tmp = f"{path}.{os.getpid()}.part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def too_soon(stamp, now, min_interval, backoff):
    """Seconds still to wait, or 0. After a run: MIN_INTERVAL. After N bench skips in a row:
    BACKOFF * 2**(N-1), capped at MIN_INTERVAL."""
    last = float(stamp.get("last_attempt") or 0)
    if not last or now < last:  # never ran, or the clock went backwards
        return 0
    skips = int(stamp.get("skips") or 0)
    wait = min(min_interval, backoff * (2 ** (skips - 1))) if skips else min_interval
    return max(0, int(last + wait - now))


def priority_argv():
    argv = []
    if shutil.which("nice"):
        argv += ["nice", "-n", "19"]
    if shutil.which("ionice"):  # Linux (util-linux); absent on FreeBSD/macOS
        argv += ["ionice", "-c3"]
    return argv


def bench_env(base, tmpdir):
    env = {k: v for k, v in base.items() if k != "SWARM_BENCH_FORCE"}
    env.update(CPU_ONLY_ENV)
    env["TMPDIR"] = tmpdir
    env["SWARM_BENCH_IDLE"] = "1"
    return env


def _lower_self():
    try:
        os.nice(19)  # no-op cap at 19 if already niced
    except OSError:
        pass


def run_bench(bench, env, timeout):
    argv = priority_argv() + ["sh", bench]
    p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True,
                         preexec_fn=_lower_self, cwd=env["TMPDIR"])
    old = signal.signal(signal.SIGTERM, lambda *_: _killgrp(p, signal.SIGTERM))
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        _killgrp(p, signal.SIGTERM)
        try:
            out, err = p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            _killgrp(p, signal.SIGKILL)
            out, err = p.communicate()
        return 124, out, (err or "") + f"\nbench_idle: timeout {timeout}s\n"
    finally:
        signal.signal(signal.SIGTERM, old)


def _killgrp(p, sig):
    try:
        os.killpg(p.pid, sig)
    except OSError:
        pass


def log(msg):
    print("bench_idle: " + msg, flush=True)


def main(argv=None, env=None, now=None, probe=None):
    env = dict(os.environ if env is None else env)
    ap = argparse.ArgumentParser(prog="bench_idle.py", description=__doc__.split("\n")[0],
                                 epilog="Example: python3 scripts/swarm/bench_idle.py --dry-run")
    ap.add_argument("--dry-run", action="store_true", help="decide and print; never run bench.sh")
    ap.add_argument("--state-dir", default=None, help="results/lock/stamp dir (default: see module doc)")
    ap.add_argument("--bench", default=env.get("SWARM_BENCH_IDLE_BENCH", DEFAULT_BENCH))
    ap.add_argument("--min-interval", type=int, default=int(env.get("SWARM_BENCH_IDLE_INTERVAL", 6 * 3600)),
                    help="seconds between runs (default 21600)")
    ap.add_argument("--backoff", type=int, default=int(env.get("SWARM_BENCH_IDLE_BACKOFF", 900)),
                    help="first wait after bench.sh skipped (doubles, capped at --min-interval; default 900)")
    ap.add_argument("--max-load", type=float, default=float(env.get("SWARM_BENCH_IDLE_MAX_LOAD") or default_max_load()))
    ap.add_argument("--min-avail-mib", type=int, default=int(env.get("SWARM_BENCH_IDLE_MIN_AVAIL_MIB", 4096)))
    ap.add_argument("--timeout", type=int, default=int(env.get("SWARM_BENCH_IDLE_TIMEOUT", 4 * 3600)),
                    help="whole bench.sh run cap in seconds (default 14400)")
    a = ap.parse_args(argv)
    if a.min_interval < 0 or a.backoff < 1 or a.timeout < 1 or a.max_load <= 0:
        log("bad interval/backoff/timeout/max-load")
        return 2
    now = time.time() if now is None else now
    sd = os.path.abspath(os.path.expanduser(a.state_dir)) if a.state_dir else state_dir(env)
    try:
        ensure_private_dir(sd)
        results = ensure_private_dir(os.path.join(sd, "results"))
    except (UnsafeStateDir, OSError) as e:
        log(f"refusing: {e}")
        return 2

    lock_fd = os.open(os.path.join(sd, "bench_idle.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                log("skip: another trigger holds the lock")
                return 0
            raise
        return _locked(a, env, sd, results, now, probe)
    finally:
        os.close(lock_fd)  # releases the flock


def _locked(a, env, sd, results, now, probe):
    if os.path.exists(os.path.join(sd, "disarmed")):
        log(f"skip: disarmed ({os.path.join(sd, 'disarmed')})")
        return 0
    stamp_path = os.path.join(sd, "stamp.json")
    stamp = read_stamp(stamp_path)
    wait = too_soon(stamp, now, a.min_interval, a.backoff)
    if wait:
        log(f"skip: next attempt in {wait}s")
        return 0
    names = tuple(n for n in (env.get("SWARM_BENCH_IDLE_BUSY_PROCS") or ",".join(BUSY_PROCS)).split(",") if n)
    load, avail, procs = probe() if probe else (load_avg(), mem_available_mib(), running_procs(names))
    why = busy_reason(load, avail, procs, a.max_load, a.min_avail_mib)
    if why:
        log("skip: busy: " + why)  # cheap check; no stamp, the next tick re-checks
        return 0
    if a.dry_run:
        log(f"idle: would run {a.bench} (nice 19, CPU only, guards on); results -> {results}")
        return 0
    if not os.path.isfile(a.bench):
        log(f"bench not found: {a.bench}")
        return 2

    tmp = tempfile.mkdtemp(prefix="run-", dir=sd)
    try:
        t0 = time.time()
        rc, out, err = run_bench(a.bench, bench_env(env, tmp), a.timeout)
        ts = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        res = os.path.join(results, ts + ".md")
        write_private(res, out + ("\n<!-- stderr\n" + err.strip() + "\n-->\n" if err.strip() else ""))
        status = "skipped" if rc in SKIP_RCS else ("ok" if rc == 0 else "failed")
        skips = int(stamp.get("skips") or 0) + 1 if status == "skipped" else 0
        write_private(stamp_path, json.dumps({"last_attempt": now, "last_rc": rc, "status": status,
                                              "skips": skips}) + "\n")
        line = json.dumps({"ts": ts, "host": socket.gethostname().split(".")[0], "rc": rc,
                           "status": status, "secs": round(time.time() - t0, 1), "result": res})
        fd = os.open(os.path.join(sd, "runs.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        log(f"{status} (bench.sh exit {rc}); results -> {res}")
        return 0 if status in ("ok", "skipped") else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
