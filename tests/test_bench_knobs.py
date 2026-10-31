"""scripts/swarm/bench.sh: tuning knobs pass through to llama-bench; idle guard skips with 78."""
import os
import subprocess

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
             SWARM_BENCH_MODELS="r/x/m.gguf", **env)
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
    if not os.path.exists("/proc/meminfo"):
        return
    p, a = _run(tmp_path, SWARM_BENCH_MAX_LOAD="100000", SWARM_BENCH_RESERVE_MIB="100000000")
    assert p.returncode == 78 and "MemAvailable" in p.stdout and a == ""
