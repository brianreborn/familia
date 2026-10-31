"""Tests for the SSH monitoring console (scripts/monitor.py, scripts/monitor/probe.py)."""
import io
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "monitor"))
import monitor  # noqa: E402
import probe  # noqa: E402


def test_parse_meminfo():
    m = probe.parse_meminfo("MemTotal: 7464960 kB\nMemFree: 100000 kB\nMemAvailable: 2097152 kB\nSwapTotal: 1048576 kB\nSwapFree: 524288 kB\n")
    assert m["total_mib"] == 7290 and m["available_mib"] == 2048 and m["swap_free_mib"] == 512


def test_cpu_percent():
    a = probe.parse_stat_cpus("cpu  100 0 100 800 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0\n")
    b = probe.parse_stat_cpus("cpu  150 0 150 900 0 0 0 0\ncpu0 100 0 50 450 0 0 0 0\n")
    p = probe.cpu_percent(a, b)
    assert p["cpu"] == 50.0 and p["cpu0"] == 50.0


def test_parse_pid_stat_with_spaces_in_comm():
    st = "123 (Web Content) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 99999 20"
    comm, state, ppid, ticks, start = probe.parse_pid_stat(st)
    assert comm == "Web Content" and state == "S" and ppid == 1 and ticks == 11 + 12 and start == 99999


def test_llama_flags_and_redaction():
    f = probe.parse_llama_cmdline(["/opt/llama-server", "-m", "/m/Qwen3.5-2B-Q4_K_M.gguf", "-c", "65536", "-ngl", "0", "-t", "2",
                                   "--port=9941", "--api-key", "sekrit123", "--embeddings", "--log-file", "/home/u/.cache/familia/logs/serve-coder.log"])
    assert f["model"] == "Qwen3.5-2B-Q4_K_M.gguf" and f["ctx"] == "65536" and f["ngl"] == "0" and f["threads"] == "2"
    assert f["port"] == "9941" and f["api_key"] == "***" and f["embeddings"] is True and f["log_file"] == "serve-coder.log"
    assert "sekrit" not in json.dumps(f)
    assert probe.redact("Authorization: Bearer abcdefghijkl token=xyz hf_ABCDEFGHIJ") .count("***") == 3


def test_classify():
    assert probe.classify(["/x/llama-server", "-m", "a"], "llama-server") == "llama-server"
    assert probe.classify(["python3", "/r/scripts/escalation_proxy.py"], "python3") == "escalation_proxy.py"
    assert probe.classify(["bash", "scripts/serve.sh", "coder"], "bash") is None
    assert probe.classify(["vim", "llama-server.txt"], "vim") is None


def test_parse_kill_lines():
    k = probe.parse_kill_lines(["1792400000.5 miryam kernel: Out of memory: Killed process 4242 (llama-server) total-vm:1kB, anon-rss:2097152kB, file-rss:0kB"], "kernel")
    assert k == [{"ts": 1792400000.5, "source": "kernel-oom", "pid": 4242, "name": "llama-server", "rss_mib": 2048}]
    c = probe.parse_kill_lines(["1792400002 miryam kernel: Memory cgroup out of memory: Killed process 77 (llama-server) total-vm:9kB, anon-rss:1024kB"], "kernel")
    assert c[0]["source"] == "cgroup-oom (memcap)" and c[0]["pid"] == 77
    e = probe.parse_kill_lines(['1792400001.0 miryam earlyoom[1411]: sending SIGTERM to process 4243 uid 1000 "llama-server": oom_score 700, VmRSS 1800 MiB, cmdline "/x/llama-server"'], "earlyoom")
    assert e[0]["pid"] == 4243 and e[0]["signal"] == "SIGTERM" and e[0]["rss_mib"] == 1800 and e[0]["name"] == "llama-server"
    assert probe.parse_kill_lines(["1792400001.0 miryam earlyoom[1411]: mem avail: 3963 of 5765 MiB"], "earlyoom") == []


def test_forced_args_drop_logs(monkeypatch):
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "python3 - --ports 9941,abc,70000 --since 5 --logs /etc/shadow; rm -rf /")
    o = probe.forced_args()
    assert o["ports"] == [9941] and o["logs"] is None and o["since"] == 5.0


def test_probe_runs_locally_fast():
    t0 = time.time()
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "monitor", "probe.py"), "--ports", "1"],
                         stdout=subprocess.PIPE, timeout=20).stdout
    d = json.loads(out)
    assert d["ok"] and d["mem"]["total_mib"] > 0 and d["health"][0]["health"] == "down"
    assert time.time() - t0 < 10


SPEC = {"name": "miryam", "os": "posix", "transport": "ssh", "dest": "x", "ssh_opts": [],
        "nodes": {"coder": {"port": 9941, "status": "active", "model": "q"}}}


def sample(t, procs, kills=(), boot=1000, health=200, mem_av=4000, logs=None):
    return {"ok": True, "time": t, "boot_time": boot, "uptime_s": t - boot, "load": [0.1, 0, 0], "cpu_pct": {"cpu": 5.0},
            "mem": {"total_mib": 7289, "available_mib": mem_av, "swap_total_mib": 1000, "swap_free_mib": 900},
            "familia": list(procs), "kills": list(kills), "health": [{"port": 9941, "health": health}],
            "temps": [], "disks": [], "logs": logs or {}, "probe": {"elapsed_ms": 300}}


LS = {"pid": 4242, "start": 777, "kind": "llama-server", "rss_mib": 1800, "uptime_s": 60, "flags": {"port": "9941", "model": "q.gguf"}}


def test_death_detection_simulated_pid_disappearance():
    prev = sample(2000, [LS])
    cur = sample(2003, [], health="down", logs={"~/.cache/familia/logs/serve-coder.log": {"mtime": 2002, "tail": ["ggml: alloc failed"]}})
    ev = monitor.diff_samples(SPEC, prev, cur)
    deaths = [e for e in ev if e["type"] == "death"]
    assert len(deaths) == 1 and deaths[0]["node"] == "coder" and deaths[0]["severity"] == "critical"
    assert deaths[0]["log"].endswith("serve-coder.log") and deaths[0]["log_tail"] == ["ggml: alloc failed"]
    assert not any(e["type"] == "unhealthy" for e in ev)  # folded into the death
    alive = monitor.diff_samples(SPEC, sample(2000, [LS]), sample(2003, [LS], health="down"))
    assert [e["type"] for e in alive] == ["unhealthy"]


def test_death_with_earlyoom_cause_not_double_reported():
    k = {"ts": 2001, "source": "earlyoom", "signal": "SIGTERM", "pid": 4242, "name": "llama-server", "rss_mib": 1800}
    ev = monitor.diff_samples(SPEC, sample(2000, [LS]), sample(2003, [], kills=[k], health="down"), set())
    assert [e["type"] for e in ev] == ["death"]  # no separate oom-kill or unhealthy event for the same process
    assert ev[0]["cause"][0].startswith("OOM: earlyoom sent SIGTERM")


def test_pid_reuse_counts_as_death_and_reboot_hint():
    reused = dict(LS, start=999)
    ev = monitor.diff_samples(SPEC, sample(2000, [LS]), sample(2003, [reused]))
    assert [e["type"] for e in ev] == ["death", "started"]
    ev = monitor.diff_samples(SPEC, sample(2000, [LS]), sample(2600, [], boot=2500))
    assert ev[0]["cause"] == ["host rebooted (boot time moved)"]


def test_oneshot_exit_is_info_and_first_sample_silent():
    bench = dict(LS, kind="llama-bench", flags={})
    ev = monitor.diff_samples(SPEC, sample(2000, [bench]), sample(2003, []))
    assert [e["type"] for e in ev] == ["exited"]
    assert monitor.diff_samples(SPEC, None, sample(2003, [LS], kills=[{"ts": 1, "source": "kernel-oom", "pid": 9}])) == []


def test_unrelated_oom_kill_reported_once():
    seen = set()
    k = {"ts": 2001, "source": "kernel-oom", "pid": 55, "name": "firefox"}
    ev = monitor.diff_samples(SPEC, sample(2000, []), sample(2003, [], kills=[k]), seen)
    assert [e["type"] for e in ev] == ["oom-kill"]
    assert monitor.diff_samples(SPEC, sample(2003, []), sample(2006, [], kills=[k]), seen) == []


def mon_with(states):
    m = monitor.Monitor({n: dict(SPEC, name=n) for n in states}, interval=3, persist=False)
    for n, (smp, err, last_ok) in states.items():
        st = m.states[n]
        st.sample, st.err, st.last_ok, st.wall_ms = smp, err, last_ok, 500
    return m


def test_stale_host_rendered_not_crashing():
    now = 10000.0
    m = mon_with({"miryam": (sample(now - 1, [LS]), None, now - 1), "phone7": (sample(now - 600, []), "ssh: connect to host 192.168.1.9 port 8022: timed out", now - 600),
                  "qodesh": (None, "Connection timed out", None)})
    m.states["qodesh"].next_try = now + 8
    txt = monitor.render_text(m, now=now, details={"phone7"})
    assert "STALE" in txt and "last seen 10m ago" in txt and "never reached" in txt and "retry in 8s" in txt
    assert monitor.host_level(m.states["phone7"], now, 3)[0] == "stale"
    assert monitor.host_level(m.states["miryam"], now, 3)[0] == "ok"
    j = monitor.to_json(m, now=now)
    assert j["hosts"]["phone7"]["stale"] and j["hosts"]["qodesh"]["level"] == "stale"


def test_scrub_hides_addresses():
    assert monitor.scrub(["ssh: connect to host 192.168.1.7 port 8022: Connection timed out"]) == ["ssh: connect to host <addr> port <p>: Connection timed out"]


def test_plain_renderer_shows_death_banner():
    m = mon_with({"miryam": (sample(2003, []), None, 2003)})
    m.record(monitor.diff_samples(SPEC, sample(2000, [LS]), sample(2003, [])))
    txt = monitor.render_text(m, now=2004)
    assert "!! DEATH miryam: coder llama-server pid 4242 port 9941" in txt.splitlines()[1]


def test_build_hosts_never_uses_graph_addr_by_default():
    g = {"hosts": {"miryam": {"os": "linux"}, "phone7": {"os": "android-16", "addr": "10.0.0.7", "user": "u", "port": 8022}, "qodesh": {"os": "windows"}},
         "nodes": {"coder": {"host": "miryam", "port": 9941, "status": "active"}}}
    h = monitor.build_hosts(g, {"hosts": {"qodesh": {"ssh": "q"}}}, alias_check=lambda n: False, local_name="miryam")
    assert h["miryam"]["transport"] == "local" and h["miryam"]["nodes"]["coder"]["port"] == 9941
    assert h["phone7"]["transport"] is None and h["qodesh"]["transport"] == "ssh" and h["qodesh"]["os"] == "windows"
    h = monitor.build_hosts(g, {"allow_graph_addr": True}, alias_check=lambda n: n == "qodesh", local_name="x")
    assert h["phone7"]["transport"] == "ssh-graph" and h["qodesh"]["dest"] == "qodesh"


def test_ssh_command_is_batch_and_multiplexed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = monitor.ssh_base({"dest": "phone7", "ssh_opts": []})
    assert "BatchMode=yes" in c and "ControlMaster=auto" in c and c[-1] == "phone7"
    remote, data = monitor.probe_command(dict(SPEC, os="windows"), 5)
    assert "$" not in remote and data.startswith(b"$FamiliaPorts=@(9941)")
    remote, data = monitor.probe_command(SPEC, 5)
    assert remote.startswith("command -v python3") and b"def collect" in data


def test_backoff_caps():
    assert [monitor.backoff(i) for i in (1, 2, 3, 10)] == [2, 4, 8, 60]


def test_mini_graph_fallback(tmp_path):
    p = tmp_path / "g.yaml"
    p.write_text("version: 2\nhosts:\n  miryam:\n    os: linux   # c\nnodes:\n  coder:\n    host: miryam\n    port: 9941\n    status: active\n")
    g = monitor.mini_graph(str(p))
    assert g["hosts"]["miryam"]["os"] == "linux" and g["nodes"]["coder"]["port"] == 9941


def test_cli_once_local_only(tmp_path):
    cfg = tmp_path / "m.json"
    cfg.write_text(json.dumps({"hosts": {"miryam": {"local": True}}}))
    env = dict(os.environ, XDG_STATE_HOME=str(tmp_path / "st"))
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "monitor.py"), "--config", str(cfg), "--json", "miryam"],
                       stdout=subprocess.PIPE, env=env, timeout=60)
    d = json.loads(p.stdout)
    assert d["hosts"]["miryam"]["transport"] == "local" and d["hosts"]["miryam"]["sample"]["ok"]


def test_parse_bsd_mem():
    m = probe.parse_bsd_mem("25629380608\n4096\n416268\n4037176\n",
                            "Device:       1kB-blocks      Used:\n/dev/ada1      156290904    1091368\n")
    assert m["total_mib"] == 24442 and m["available_mib"] == (416268 + 4037176) * 4096 // 1048576
    assert m["swap_total_mib"] == 156290904 // 1024 and m["swap_free_mib"] == (156290904 - 1091368) // 1024
    assert probe.parse_bsd_mem("") is None
