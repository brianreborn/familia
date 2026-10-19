#!/usr/bin/env python3
"""familia monitor probe: one read-only JSON snapshot of this host.

Stdlib only, no writes, no network except GET 127.0.0.1 health checks.
Designed to be piped over SSH:  ssh HOST python3 - --ports 9941,9951 < probe.py
Linux and Termux (Android). Windows uses probe.ps1.

Arguments (all optional):
  --ports P,P,...   local endpoints to health-check (graph node ports)
  --since EPOCH     only report OOM/earlyoom kills after this time (default now-3600)
  --logs G;G;...    log globs to tail (default: familia-perf.log, .cache/familia/*.log)
  --interval S      CPU sampling interval (default 0.25)
  --forced          take arguments from SSH_ORIGINAL_COMMAND (authorized_keys command=)
"""
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

VERSION = 1
FAMILIA_BINS = {"llama-server", "llama-cli", "llama-bench", "rpc-server", "llama-embedding", "llama-run"}
FAMILIA_SCRIPTS = {"hermes", "hermes_harness.py", "escalation_proxy.py", "escalate.py"}  # launchers (serve.sh, hermes.sh) are not tracked: their llama-server is
SECRET_FLAGS = {"--api-key", "--api-key-file", "--hf-token", "-hft", "--ssl-key-file"}
SECRET_RE = re.compile(r"(hf_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|(?i:bearer)\s+[A-Za-z0-9._~+/-]{8,}|(?i:(?:api[_-]?key|token|password|secret)\s*[=:]\s*)\S+)")
KEY_FLAGS = {
    "-m": "model", "--model": "model", "-hf": "hf_repo", "--hf-repo": "hf_repo", "-a": "alias", "--alias": "alias",
    "-c": "ctx", "--ctx-size": "ctx", "-ngl": "ngl", "--n-gpu-layers": "ngl", "--gpu-layers": "ngl",
    "-t": "threads", "--threads": "threads", "--port": "port", "--host": "bind", "-np": "parallel", "--parallel": "parallel",
    "-ctk": "kv_type", "--cache-type-k": "kv_type", "-cram": "cache_ram", "--cache-ram": "cache_ram",
    "-b": "batch", "--batch-size": "batch", "-ub": "ubatch", "--ubatch-size": "ubatch", "--pooling": "pooling",
    "--rope-scaling": "rope_scaling", "-fa": "flash_attn", "--flash-attn": "flash_attn", "-mmproj": "mmproj", "--mmproj": "mmproj",
    "-md": "draft", "--model-draft": "draft", "--log-file": "log_file",
}
BOOL_FLAGS = {"--embedding": "embeddings", "--embeddings": "embeddings", "--jinja": "jinja", "--mlock": "mlock", "--no-mmap": "no_mmap"}
REAL_FS = {"ext4", "ext3", "ext2", "xfs", "btrfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "zfs", "sdcardfs", "fuse"}


def redact(s):
    return SECRET_RE.sub("***", s)


def rd(path, default=None):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return default


def parse_args(argv):
    o = {"ports": [], "since": time.time() - 3600, "logs": None, "interval": 0.25}
    it = iter(argv)
    for a in it:
        try:
            if a == "--ports":
                o["ports"] = [int(p) for p in next(it).split(",") if p.strip().isdigit() and 0 < int(p) < 65536][:32]
            elif a == "--since":
                o["since"] = float(next(it))
            elif a == "--logs":
                o["logs"] = [g for g in next(it).split(";") if g][:16]
            elif a == "--interval":
                o["interval"] = min(max(float(next(it)), 0.05), 2.0)
        except (StopIteration, ValueError):
            pass
    return o


def forced_args():
    # Only whitelisted, validated tokens survive from SSH_ORIGINAL_COMMAND; --logs is dropped
    # so a restricted monitoring key can never choose which files are read.
    toks = os.environ.get("SSH_ORIGINAL_COMMAND", "").split()
    o = parse_args(toks)
    o["logs"] = None
    return o


# ---------- parsers (pure functions; unit-tested) ----------

def parse_meminfo(text):
    m = {}
    for line in (text or "").splitlines():
        k, _, v = line.partition(":")
        v = v.strip().split()
        if v and v[0].isdigit():
            m[k.strip()] = int(v[0]) // 1024  # MiB
    return {
        "total_mib": m.get("MemTotal"), "available_mib": m.get("MemAvailable", m.get("MemFree")),
        "swap_total_mib": m.get("SwapTotal"), "swap_free_mib": m.get("SwapFree"),
        "shmem_mib": m.get("Shmem"), "cached_mib": m.get("Cached"),
    }


def parse_stat_cpus(text):
    cpus = {}
    for line in (text or "").splitlines():
        if line.startswith("cpu"):
            f = line.split()
            vals = [int(x) for x in f[1:9] if x.isdigit()]
            if len(vals) >= 4:
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                cpus[f[0]] = (sum(vals), idle)
    return cpus


def cpu_percent(a, b):
    out = {}
    for k, (tot2, idle2) in b.items():
        if k in a:
            dt, di = tot2 - a[k][0], idle2 - a[k][1]
            out[k] = round(100.0 * (dt - di) / dt, 1) if dt > 0 else 0.0
    return out


def parse_pid_stat(text):
    """Return (comm, state, ppid, utime+stime ticks, starttime ticks) from /proc/PID/stat."""
    if not text:
        return None
    r = text.rfind(")")
    comm = text[text.find("(") + 1:r]
    f = text[r + 2:].split()
    try:
        return comm, f[0], int(f[1]), int(f[11]) + int(f[12]), int(f[19])
    except (IndexError, ValueError):
        return None


def parse_llama_cmdline(argv):
    flags = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        key, val = a, None
        if a.startswith("--") and "=" in a:
            key, val = a.split("=", 1)
        if key in SECRET_FLAGS:
            flags[key.lstrip("-").replace("-", "_")] = "***"
            i += 1 if val is not None else 2
            continue
        if key in KEY_FLAGS:
            if val is None and i + 1 < len(argv):
                val = argv[i + 1]
                i += 1
            if val is not None:
                name = KEY_FLAGS[key]
                if name in ("model", "draft", "mmproj", "log_file"):
                    val = os.path.basename(val)
                flags[name] = redact(val)
        elif key in BOOL_FLAGS:
            flags[BOOL_FLAGS[key]] = True
        i += 1
    return flags


def classify(argv, comm):
    if not argv:
        return None
    b0 = os.path.basename(argv[0])
    if b0 in FAMILIA_BINS or comm in FAMILIA_BINS:
        return b0 if b0 in FAMILIA_BINS else comm
    if b0 == "hermes":
        return "hermes"
    if re.match(r"^(python[0-9.]*|bash|sh|dash)$", b0):
        for a in argv[1:4]:
            if os.path.basename(a) in FAMILIA_SCRIPTS:
                return os.path.basename(a)
    return None


OOM_KERNEL_RE = re.compile(r"Killed process (\d+) \(([^)]*)\)(.*?anon-rss:(\d+)kB)?")
EARLYOOM_RE = re.compile(r"(?:sending|escalating to) (SIG\w+) to process (\d+)(?: uid \d+)? \"?([^\":]*)\"?(?::.*?VmRSS (\d+) MiB)?")


def parse_kill_lines(lines, source):
    out = []
    for line in lines:
        parts = line.split(None, 1)
        try:
            ts = float(parts[0])
        except (ValueError, IndexError):
            ts, parts = None, [None, line]
        rest = parts[1] if len(parts) > 1 else ""
        m = OOM_KERNEL_RE.search(rest)
        if m and source == "kernel":
            out.append({"ts": ts, "source": "cgroup-oom (memcap)" if "cgroup" in rest else "kernel-oom", "pid": int(m.group(1)), "name": m.group(2),
                        "rss_mib": int(m.group(4)) // 1024 if m.group(4) else None})
            continue
        m = EARLYOOM_RE.search(rest)
        if m and source == "earlyoom":
            out.append({"ts": ts, "source": "earlyoom", "signal": m.group(1), "pid": int(m.group(2)),
                        "name": m.group(3).strip(), "rss_mib": int(m.group(4)) if m.group(4) else None})
    return out


def tail(path, n=4, maxbytes=4096):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - maxbytes))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = [redact(l)[:200] for l in data.splitlines() if l.strip()]
    return lines[-n:]


# ---------- collectors ----------

def run(cmd, timeout=1.5):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def os_name():
    if os.environ.get("PREFIX", "").find("com.termux") >= 0 or os.path.isdir("/data/data/com.termux"):
        rel = run(["getprop", "ro.build.version.release"], 0.5)
        model = run(["getprop", "ro.product.model"], 0.5)
        return "android-%s (Termux%s)" % ((rel or "?").strip(), (", " + model.strip()) if model else "")
    t = rd("/etc/os-release", "")
    m = re.search(r'^PRETTY_NAME="?([^"\n]*)', t, re.M)
    u = os.uname()
    return "%s; %s %s" % (m.group(1) if m else u.sysname, u.sysname, u.release)


def zram():
    out = []
    for d in sorted(glob.glob("/sys/block/zram*")):
        mm = (rd(d + "/mm_stat") or "").split()
        size = rd(d + "/disksize")
        if size and size.strip() != "0":
            out.append({"dev": os.path.basename(d), "disksize_mib": int(size) // 1048576,
                        "orig_mib": int(mm[0]) // 1048576 if mm else None, "compr_mib": int(mm[1]) // 1048576 if len(mm) > 1 else None})
    return out


def swaps():
    out = []
    for line in (rd("/proc/swaps") or "").splitlines()[1:]:
        f = line.split()
        if len(f) >= 5:
            out.append({"dev": f[0], "size_mib": int(f[2]) // 1024, "used_mib": int(f[3]) // 1024, "prio": int(f[4])})
    return out


def disks():
    paths, seen, out = ["/", os.path.expanduser("~"), "/tmp"], set(), []
    if os.environ.get("PREFIX"):
        paths.append(os.environ["PREFIX"])
    for line in (rd("/proc/mounts") or "").splitlines():
        f = line.split()
        if len(f) > 2 and f[2] in REAL_FS and not f[1].startswith(("/snap", "/proc", "/sys", "/run/user", "/boot")):
            paths.append(f[1].replace("\\040", " "))
    for p in paths:
        try:
            st = os.stat(p)
            if st.st_dev in seen:
                continue
            v = os.statvfs(p)
        except OSError:
            continue
        seen.add(st.st_dev)
        if v.f_blocks == 0:
            continue
        out.append({"mount": p, "free_mib": v.f_bavail * v.f_frsize // 1048576, "total_mib": v.f_blocks * v.f_frsize // 1048576})
        if len(out) >= 6:
            break
    return out


def temps():
    out = []
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*"))[:16]:
        t = rd(z + "/temp")
        if t and t.strip().lstrip("-").isdigit():
            v = int(t) / (1000.0 if abs(int(t)) > 200 else 1.0)
            if -40 < v < 150:
                out.append({"name": (rd(z + "/type") or "zone").strip(), "c": round(v, 1)})
    for h in sorted(glob.glob("/sys/class/hwmon/hwmon*"))[:8]:
        name = (rd(h + "/name") or "hwmon").strip()
        for t in sorted(glob.glob(h + "/temp*_input"))[:4]:
            v = rd(t)
            if v and v.strip().isdigit():
                out.append({"name": name, "c": round(int(v) / 1000.0, 1)})
    return out[:16]


def gpus():
    out = []
    smi = shutil.which("nvidia-smi")
    if smi:
        txt = run([smi, "--query-gpu=name,driver_version,temperature.gpu,utilization.gpu,memory.used,memory.total",
                   "--format=csv,noheader,nounits"], 1.5)
        for line in (txt or "").splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) >= 6:
                out.append({"source": "nvidia-smi", "name": f[0], "driver": f[1], "temp_c": f[2], "util_pct": f[3],
                            "mem_used_mib": f[4], "mem_total_mib": f[5]})
    vendors = {"0x8086": "intel", "0x10de": "nvidia", "0x1002": "amd"}
    for c in sorted(glob.glob("/sys/class/drm/card[0-9]")):
        dev = c + "/device"
        g = {"source": "drm", "card": os.path.basename(c), "vendor": vendors.get((rd(dev + "/vendor") or "").strip(), (rd(dev + "/vendor") or "?").strip())}
        try:
            g["driver"] = os.path.basename(os.readlink(dev + "/driver"))
        except OSError:
            pass
        for key, path in (("util_pct", dev + "/gpu_busy_percent"), ("cur_mhz", c + "/gt_cur_freq_mhz"),
                          ("vram_used", dev + "/mem_info_vram_used"), ("vram_total", dev + "/mem_info_vram_total")):
            v = rd(path)
            if v and v.strip().isdigit():
                g[key] = int(v) // 1048576 if key.startswith("vram") else int(v)
        out.append(g)
    for path, key in (("/sys/kernel/gpu/gpu_busy", "util_pct"), ("/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage", "util_pct")):
        v = rd(path)
        if v:
            out.append({"source": path, key: v.strip().rstrip("%").split()[0] if v.strip() else None,
                        "name": (rd("/sys/kernel/gpu/gpu_model") or "").strip() or None})
            break
    return out


def battery():
    for b in glob.glob("/sys/class/power_supply/*"):
        if (rd(b + "/type") or "").strip() == "Battery":
            cap = rd(b + "/capacity")
            return {"pct": int(cap) if cap and cap.strip().isdigit() else None, "status": (rd(b + "/status") or "").strip() or None}
    return None


def health(port, out):
    import urllib.request
    r = {"port": port}
    for path, key in (("/health", "health"), ("/v1/models", "models")):
        t0 = time.time()
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=0.6) as resp:
                body = resp.read(65536).decode("utf-8", "replace")
                r[key] = resp.status
                if key == "models":
                    try:
                        r["model_ids"] = [m.get("id") for m in json.loads(body).get("data", [])][:4]
                    except (ValueError, AttributeError):
                        pass
        except Exception as e:  # noqa: BLE001 - any failure is "down"
            code = getattr(e, "code", None)
            r[key] = code if code else "down"
            if not code:
                r["ms"] = int((time.time() - t0) * 1000)
                break  # nothing listening: skip /v1/models
        r["ms"] = int((time.time() - t0) * 1000)
    out.append(r)


def kills(since, out):
    jc = shutil.which("journalctl")
    since_s = "@%d" % int(since)
    if jc:
        k = run([jc, "-k", "-q", "--no-pager", "-o", "short-unix", "--since", since_s, "-n", "200",
                 "-g", "Killed process|Out of memory"], 2.0)
        out.extend(parse_kill_lines((k or "").splitlines(), "kernel"))
        e = run([jc, "-u", "earlyoom", "-q", "--no-pager", "-o", "short-unix", "--since", since_s, "-n", "200",
                 "-g", "sending|escalating"], 2.0)
        out.extend(parse_kill_lines((e or "").splitlines(), "earlyoom"))
    else:
        d = run(["dmesg"], 0.5)  # usually denied on Android; harmless
        out.extend(parse_kill_lines([l for l in (d or "").splitlines() if "Killed process" in l], "kernel"))


def procs_snapshot():
    """Read every /proc/PID once: returns {pid: dict} with ticks for CPU% deltas."""
    snap = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        st = parse_pid_stat(rd("/proc/%s/stat" % d))
        statm = (rd("/proc/%s/statm" % d) or "").split()
        if not st:
            continue
        snap[int(d)] = {"comm": st[0], "state": st[1], "ppid": st[2], "ticks": st[3], "start": st[4],
                        "rss_pages": int(statm[1]) if len(statm) > 1 else 0}
    return snap


def system_agent_state():
    """Last phone-assistant probe (scripts/termux/system_agent.py probe); reading only, never runs rish."""
    try:
        with open(os.path.expanduser("~/.cache/familia/system-agent.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    out = {k: d.get(k) for k in ("shizuku", "providers", "sdk") if k in d}
    if isinstance(d.get("time"), (int, float)):
        out["age_s"] = int(time.time() - d["time"])
    return out


def collect(o):
    t0, c0 = time.time(), time.process_time()
    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    stat1, procs1 = parse_stat_cpus(rd("/proc/stat")), procs_snapshot()
    t1 = time.time()
    hres, kres, threads = [], [], []
    for p in o["ports"]:
        threads.append(threading.Thread(target=health, args=(p, hres), daemon=True))
    threads.append(threading.Thread(target=kills, args=(o["since"], kres), daemon=True))
    for t in threads:
        t.start()
    uptime = float((rd("/proc/uptime") or "0").split()[0])
    load = (rd("/proc/loadavg") or "").split()[:3]
    mem = parse_meminfo(rd("/proc/meminfo"))
    rest = {"disks": disks(), "temps": temps(), "gpus": gpus(), "battery": battery(),
            "zram": zram(), "swaps": swaps(), "os": os_name()}
    time.sleep(max(0.0, o["interval"] - (time.time() - t1)))
    stat2, procs2 = parse_stat_cpus(rd("/proc/stat")), procs_snapshot()
    dt = max(time.time() - t1, 0.01)
    cpu = cpu_percent(stat1, stat2)
    boot = time.time() - uptime
    me = os.getpid()
    top, fam = [], []
    for pid, p in procs2.items():
        rss = p["rss_pages"] * page // 1048576
        prev = procs1.get(pid)
        cpu_p = round(100.0 * (p["ticks"] - prev["ticks"]) / hz / dt, 1) if prev and prev["start"] == p["start"] else None
        top.append((rss, pid, p["comm"], cpu_p))
        if pid == me:
            continue
        raw = rd("/proc/%d/cmdline" % pid)
        if not raw:
            continue
        argv = [a for a in raw.split("\0") if a]
        kind = classify(argv, p["comm"])
        if not kind:
            continue
        f = parse_llama_cmdline(argv) if kind in FAMILIA_BINS else {}
        if kind == "llama-server" and "port" not in f:
            f["port"] = "8080"
        env = rd("/proc/%d/environ" % pid) if kind in FAMILIA_BINS else None
        if env is not None:
            vk = [e for e in env.split("\0") if e.startswith("GGML_VK_VISIBLE_DEVICES=")]
            f["vk_visible"] = vk[0].split("=", 1)[1] if vk else None
        fam.append({"pid": pid, "kind": kind, "start": p["start"], "state": p["state"], "rss_mib": rss, "cpu_pct": cpu_p,
                    "uptime_s": int(uptime - p["start"] / float(hz)), "flags": f,
                    "cmd": redact(" ".join(os.path.basename(argv[0:1][0]) if i == 0 else a for i, a in enumerate(argv)))[:300]})
    top.sort(reverse=True)
    for t in threads:
        t.join(2.5)
    logs = {}
    globs = o["logs"] or ["~/familia-perf.log", "~/.cache/familia/*.log", "~/.cache/familia/logs/*.log*", "~/repositories/familia*/.cache/familia/*.log",
                          "~/familia/.cache/familia/*.log", "~/repositories/familia*/.cache/server.log"]
    files = []
    for g in globs:
        files.extend(glob.glob(os.path.expanduser(g)))
    files = sorted(set(files), key=lambda p: -os.path.getmtime(p))[:6]
    for p in files:
        logs[p.replace(os.path.expanduser("~"), "~", 1)] = {"mtime": int(os.path.getmtime(p)), "tail": tail(p)}
    res = {"v": VERSION, "ok": True, "platform": "termux" if "com.termux" in os.environ.get("PREFIX", "") else "linux",
           "hostname": socket.gethostname(), "time": round(time.time(), 1), "boot_time": int(boot), "uptime_s": int(uptime),
           "load": [float(x) for x in load], "ncpu": os.cpu_count(), "cpu_pct": cpu, "mem": mem,
           "top": [{"pid": p, "comm": c, "rss_mib": r, "cpu_pct": cp} for r, p, c, cp in top[:8]],
           "familia": sorted(fam, key=lambda x: x["pid"]), "health": sorted(hres, key=lambda x: x["port"]),
           "kills": [k for k in kres if k.get("ts") is None or k["ts"] >= o["since"]][-20:], "logs": logs}
    res.update(rest)
    sa = system_agent_state()
    if sa:
        res["system_agents"] = sa
    try:
        import resource
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        maxrss = None
    res["probe"] = {"elapsed_ms": int((time.time() - t0) * 1000), "cpu_ms": int((time.process_time() - c0) * 1000),
                    "maxrss_kib": maxrss, "pid": me}
    return res


def main(argv):
    o = forced_args() if "--forced" in argv else parse_args(argv)
    try:
        res = collect(o)
    except Exception as e:  # never print a traceback with paths/env; report the class only
        res = {"v": VERSION, "ok": False, "error": "%s: %s" % (type(e).__name__, redact(str(e))[:200]),
               "hostname": socket.gethostname(), "time": time.time()}
    sys.stdout.write(json.dumps(res, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
