"""scripts/swarm/bench.sh: tuning knobs pass through to llama-bench; idle guard skips with 78."""
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "scripts", "swarm", "bench.sh")
CSV = 'n_threads,n_prompt,n_gen,avg_ts,stddev_ts,backends\n"4","0","128","20.0","0.1","CPU"\n'


def _run(tmp_path, **env):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "m.gguf").write_bytes(b"x" * 1024)
    args = tmp_path / "args"
    fake = tmp_path / "llama-bench"
    fake.write_text("#!/bin/sh\necho \"$@\" > %s\nprintf '%%s' '%s'\n" % (args, CSV))
    fake.chmod(0o755)
    e = dict(os.environ, SWARM_BENCH_CACHE=str(cache), LLAMA_BENCH=str(fake),
             SWARM_BENCH_MODELS="r/x/m.gguf")
    e.update(env)
    p = subprocess.run(["sh", BENCH], env=e, capture_output=True, text=True, timeout=60)
    return p, (args.read_text() if args.exists() else "")


def test_knobs_reach_llama_bench(tmp_path):
    p, a = _run(tmp_path, SWARM_BENCH_FORCE="1", SWARM_BENCH_THREADS="2,4",
                SWARM_BENCH_UB="64,512", SWARM_BENCH_LM="mmap,none", SWARM_BENCH_REPS="3")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "-r 3 -t 2,4 -ub 64,512 -lm mmap,none" in a
    assert "| 20.0 ± 0.1 |" in p.stdout


def test_defaults_unchanged(tmp_path):
    _, a = _run(tmp_path, SWARM_BENCH_FORCE="1")
    assert "-r 2 -o csv" in a and "-t " not in a


def test_busy_host_is_skipped(tmp_path):
    p, a = _run(tmp_path, SWARM_BENCH_MAX_LOAD="0")
    assert p.returncode == 78 and "SKIP" in p.stdout and a == ""


def test_low_memory_is_skipped(tmp_path):
    mi = tmp_path / "meminfo"
    mi.write_text("MemTotal: 1000 kB\nMemAvailable: 2048 kB\n")
    p, a = _run(tmp_path, SWARM_BENCH_MAX_LOAD="100000", SWARM_BENCH_RESERVE_MIB="100000000",
                SWARM_BENCH_MEMINFO=str(mi))
    assert p.returncode == 78 and "MemAvailable" in p.stdout and a == ""


def test_bad_knob_rejected(tmp_path):
    p, a = _run(tmp_path, SWARM_BENCH_FORCE="1", SWARM_BENCH_THREADS="2 *")
    assert p.returncode == 2 and a == ""



def test_timeout_labelled(tmp_path):
    slow = tmp_path / "slow-bench"
    slow.write_text("#!/bin/sh\nexec sleep 5\n")
    slow.chmod(0o755)
    p, _ = _run(tmp_path, SWARM_BENCH_FORCE="1", SWARM_BENCH_TIMEOUT="1", LLAMA_BENCH=str(slow))
    assert p.returncode == 1 and "timeout 1s" in p.stdout, p.stdout


def test_one_cpu_host_not_always_skipped(tmp_path):
    mi = tmp_path / "meminfo"
    mi.write_text("MemAvailable: 99999999 kB\n")
    # nproc=1 -> default max load floors at 1; load 0.50 must run (was: max 0, always skip)
    p, a = _run(tmp_path, SWARM_BENCH_NPROC="1", SWARM_BENCH_LOAD1="0.50",
                SWARM_BENCH_MEMINFO=str(mi), SWARM_BENCH_RESERVE_MIB="0")
    assert p.returncode == 0 and a, p.stdout + p.stderr
    p, a = _run(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
                SWARM_BENCH_NPROC="1", SWARM_BENCH_LOAD1="1.00", SWARM_BENCH_MEMINFO=str(mi))
    assert p.returncode == 78 and "load 1.00" in p.stdout


def test_missing_meminfo_is_not_silent_pass(tmp_path):
    p, a = _run(tmp_path, SWARM_BENCH_MAX_LOAD="100000",
                SWARM_BENCH_MEMINFO=str(tmp_path / "nope1") + " " + str(tmp_path / "nope2"))
    assert p.returncode == 77 and a == "", p.stdout
    assert "RAM guard unavailable: mount procfs+linprocfs (see fstab)" in p.stderr


def test_missing_meminfo_force_overrides(tmp_path):
    p, a = _run(tmp_path, SWARM_BENCH_FORCE="1", SWARM_BENCH_MEMINFO=str(tmp_path / "nope"))
    assert p.returncode == 0 and a

