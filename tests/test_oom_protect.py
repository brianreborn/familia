"""#112: launch children first-to-kill, protected processes flagged P0. Fixtures only; never causes OOM."""
import os, subprocess, sys
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(R, "scripts"))
import oom_adj  # noqa: E402
FX = os.path.join(R, "tests", "fixtures", "oom112")


def test_clamp():
    assert oom_adj.clamp(0) == 500 and oom_adj.clamp(2000) == 1000 and oom_adj.clamp(900) == 900


def test_child_gets_adj():
    out = subprocess.run(["cat", "/proc/self/oom_score_adj"], capture_output=True, text=True,
                         preexec_fn=oom_adj.preexec(910)).stdout.strip()
    assert out == "910"
    out = subprocess.run([os.path.join(R, "scripts", "oom-adj"), "700", "cat", "/proc/self/oom_score_adj"],
                         capture_output=True, text=True).stdout.strip()
    assert out == "700"


def test_launchers_wired():
    for f in ("launch_matrix.py", "harness2.py"):
        assert "preexec_fn=oom_adj.preexec()" in open(os.path.join(R, "scripts", f)).read(), f
    # hermes no longer Popen's llama-server (#957cd32); still marks hermes child + self (#112)
    hh = open(os.path.join(R, "scripts", "hermes_harness.py")).read()
    assert "preexec_fn=oom_adj.preexec()" in hh or "oom_adj.set_self()" in hh
    assert "preexec_fn=oom_adj.preexec()" in hh  # escalate path still spawns hermes as child
    assert "scripts/oom-adj" in open(os.path.join(R, "scripts", "perf", "bench_capped.sh")).read()
    assert "oom_score_adj" in open(os.path.join(R, "scripts", "serve.sh")).read()
    assert "MemorySwapMax=0" not in open(os.path.join(R, "scripts", "perf", "spec_bench.py")).read()
    assert "oom-adj" in open(os.path.join(R, "scripts", "perf", "spec_bench.py")).read()


def test_kill_watch_flags_protected(tmp_path):
    log = tmp_path / "kills.log"
    env = dict(os.environ, KILL_WATCH_INPUT=os.path.join(FX, "journal-kills.log"),
               FAMILIA_KILL_LOG=str(log), KILL_WATCH_SNAP="true")
    subprocess.run(["sh", os.path.join(R, "scripts", "watchdog", "kill-watch.sh")], env=env, check=True, timeout=30)
    lines = log.read_text().splitlines()
    assert len(lines) == 5
    prot = (tmp_path / "protected-kills.log").read_text().splitlines()
    assert len(prot) == 3
    assert any("grok-bot" in l and "kernel-oom" in l for l in prot)
    assert any("loop.sh" in l and "earlyoom" in l for l in prot)
    assert any("familia-kill-watch" in l and "systemd-oomd" in l for l in prot)
    assert not any("llama" in l for l in prot)
    assert any("P0-PROTECTED" not in l and "cgroup-memmax" in l and "llama-server" in l for l in lines)


def test_earlyoom_args_idempotent(tmp_path):
    eo = tmp_path / "earlyoom"
    eo.write_text(open(os.path.join(FX, "earlyoom.default")).read())
    src = open(os.path.join(R, "scripts", "tune", "linux-memory.sh")).read().splitlines()
    i = next(n for n, l in enumerate(src) if "s/ --avoid" in l)
    body = "\n".join(src[i:i + 3]).replace("; systemctl try-restart earlyoom", "")
    pre = "\n".join(l for l in src if l.startswith(("AVOID=", "PREFER=")))
    for _ in range(2):
        subprocess.run(["sh", "-c", pre + "\nEO=%s\n" % eo + body], check=True)
    t = eo.read_text()
    assert t.count("--avoid") == 1 and t.count("--prefer") == 1 and "-m 3,2 -s 5,3" in t
    assert "grok-bot" in t and "loop.sh" in t and "kill-watch.sh" in t and "^(llama-.*|llama)$" in t
    assert "'" not in t.split("EARLYOOM_ARGS=")[1]


def test_units_restart_always(tmp_path):
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path), NO_SYSTEMCTL="1")
    subprocess.run(["sh", os.path.join(R, "scripts", "dogfood", "install-loop-unit.sh")], env=env, check=True)
    u = (tmp_path / "systemd/user/familia-dogfood.service").read_text()
    assert "Restart=always" in u and "loop.sh" in u
    assert "Restart=always" in open(os.path.join(R, "scripts", "watchdog", "install-kill-watch.sh")).read()
