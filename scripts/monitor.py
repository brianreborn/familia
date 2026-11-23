#!/usr/bin/env python3
"""familia monitor: SSH-transported fleet console (read-only).

  monitor.py                 live TUI (curses; plain text when there is no TTY)
  monitor.py --once          one snapshot as text, then exit
  monitor.py --json          one snapshot as JSON, then exit
  monitor.py HOST [HOST..]   only these hosts (with --once: full detail)
  monitor.py --watch-deaths  alert loop: one line per process death / OOM kill / host change
  --on-death CMD             run CMD (sh) for each familia process death (off by default)

Hosts come from graph.yaml; how to reach them comes from a private, never-committed
override file (~/.config/familia/monitor.json) or ~/.ssh/config aliases named like the host.
Every probe runs over `ssh -T -o BatchMode=yes` with ControlMaster reuse; the probe script
is sent on stdin, so nothing is installed remotely. See docs/monitoring.md.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROBE_PY = os.path.join(HERE, "monitor", "probe.py")
PROBE_PS1 = os.path.join(HERE, "monitor", "probe.ps1")
PINNED = "~/.local/share/familia/monitor-probe.py"
STATE_DIR = os.path.expanduser(os.environ.get("XDG_STATE_HOME", "~/.local/state")) + "/familia"
CONFIG = os.path.expanduser(os.environ.get("FAMILIA_MONITOR_CONFIG", "~/.config/familia/monitor.json"))

try:
    sys.path.insert(0, HERE)
    import hosts_overlay
except Exception:  # pragma: no cover
    hosts_overlay = None


# ---------------------------------------------------------------- graph + config

def load_graph(path):
    try:
        import familia_yaml  # DUP-01
        return familia_yaml.load(path) or {}
    except ImportError:
        return mini_graph(path)
    except OSError:
        return {}


def mini_graph(path):
    """PyYAML-free fallback (e.g. a bare Termux): host names/os/kind and node host/port/status/model."""
    g, sec, cur = {"hosts": {}, "nodes": {}}, None, None
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return g
    for line in lines:
        s = line.split("#", 1)[0].rstrip()
        if not s.strip():
            continue
        ind = len(s) - len(s.lstrip())
        if ind == 0:
            sec = s.rstrip(":") if s.endswith(":") else None
            cur = None
        elif sec in g and ind == 2 and s.strip().endswith(":"):
            cur = s.strip()[:-1]
            g[sec][cur] = {}
        elif sec in g and cur and ind == 4 and ":" in s:
            k, v = [x.strip() for x in s.strip().split(":", 1)]
            if k in ("os", "kind", "host", "port", "status", "model", "addr", "user") and v:
                g[sec][cur][k] = int(v) if v.isdigit() else v.strip("'\"")
    return g


def load_config(path=CONFIG):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ssh_alias_exists(name):
    """True when ~/.ssh/config maps NAME to some other HostName (an alias the user set up)."""
    try:
        out = subprocess.run(["ssh", "-G", name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3).stdout.decode()
    except (OSError, subprocess.SubprocessError):
        return False
    m = re.search(r"^hostname (\S+)", out, re.M)
    return bool(m and m.group(1).lower() != name.lower())


def build_hosts(graph, cfg, only=None, alias_check=ssh_alias_exists, local_name=None):
    """Return {name: host-spec}. Specs never carry addresses into output; `dest` stays internal."""
    local_name = (local_name or socket.gethostname()).split(".")[0].lower()
    # Merge #104 hosts.local.yaml so allow_graph_addr can resolve dest without tracked IPs.
    if hosts_overlay is not None:
        try:
            hosts_overlay.merge_connection_overlay(graph, graph_path=graph.get("_path"))
        except Exception:
            pass
    over = cfg.get("hosts", {})
    names = list((graph.get("hosts") or {}).keys()) + [n for n in over if n not in (graph.get("hosts") or {})]
    nodes = graph.get("nodes") or {}
    hosts = {}
    for n in names:
        gh = (graph.get("hosts") or {}).get(n) or {}
        o = over.get(n, {})
        if only and n not in only:
            continue
        if o.get("enabled") is False:
            continue
        osname = str(o.get("os") or gh.get("os") or "linux")
        spec = {"name": n, "os": "windows" if osname.startswith("windows") else "posix", "kind": gh.get("kind", o.get("kind")),
                "nodes": {}, "probe": o.get("probe", "stdin"), "ssh_opts": list(o.get("ssh_opts", []))}
        if o.get("known_hosts"):
            spec["ssh_opts"] += ["-o", "UserKnownHostsFile=" + os.path.expanduser(o["known_hosts"])]
        for nn, nd in nodes.items():
            if isinstance(nd, dict) and nd.get("host") == n and nd.get("port"):
                spec["nodes"][nn] = {"port": int(nd["port"]), "status": nd.get("status"), "model": nd.get("model")}
        if o.get("local") or (not o.get("ssh") and n.lower() == local_name):
            spec["transport"] = "local"
        elif o.get("ssh"):
            spec["transport"], spec["dest"] = "ssh", o["ssh"]
        elif alias_check(n):
            spec["transport"], spec["dest"] = "ssh", n
        elif gh.get("addr") and not (hosts_overlay and hosts_overlay.is_placeholder(gh.get("addr"))) and o.get("allow_graph_addr", cfg.get("allow_graph_addr", False)):
            user = gh.get("user")
            if hosts_overlay and hosts_overlay.is_placeholder(user):
                user = None
            spec["transport"], spec["dest"] = "ssh-graph", "%s@%s" % (user, gh["addr"]) if user else gh["addr"]
            if gh.get("port") and not (hosts_overlay and hosts_overlay.is_placeholder(gh.get("port"))):
                spec["ssh_opts"] += ["-p", str(gh["port"])]
        else:
            spec["transport"] = None
        hosts[n] = spec
    return hosts


# ---------------------------------------------------------------- transport

def ssh_base(spec, connect_timeout=5):
    cmd = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % connect_timeout,
           "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2", "-o", "LogLevel=ERROR"]
    if os.name != "nt":  # Win32-OpenSSH has no ControlMaster
        cm = os.path.expanduser("~/.cache/familia")
        os.makedirs(cm, mode=0o700, exist_ok=True)
        cmd += ["-o", "ControlMaster=auto", "-o", "ControlPath=%s/cm-%%C" % cm, "-o", "ControlPersist=120"]
    return cmd + spec.get("ssh_opts", []) + [spec["dest"]]


def probe_command(spec, since):
    ports = ",".join(str(v["port"]) for v in spec["nodes"].values()) or "0"
    args = "--ports %s --since %d" % (ports, since)
    if spec["os"] == "windows":
        head = "$FamiliaPorts=@(%s); $FamiliaSince=%d\n" % (ports, since)
        return ('powershell -NoProfile -NonInteractive -Command "[Console]::In.ReadToEnd() | Invoke-Expression"',
                (head + open(PROBE_PS1).read()).encode())
    if spec.get("probe") == "pinned":
        return "python3 %s %s" % (PINNED, args), b""
    return ("command -v python3 >/dev/null 2>&1 && exec python3 - %s || exec python - %s" % (args, args),
            open(PROBE_PY, "rb").read())


def run_probe(spec, since, timeout=20):
    """Return (sample|None, error|None, wall_ms)."""
    t0 = time.time()
    try:
        if spec["transport"] == "local":
            if spec["os"] == "windows":
                cmd, data = ["powershell", "-NoProfile", "-NonInteractive", "-Command", "[Console]::In.ReadToEnd() | Invoke-Expression"], probe_command(spec, since)[1]
            else:
                ports = ",".join(str(v["port"]) for v in spec["nodes"].values()) or "0"
                cmd, data = [sys.executable, PROBE_PY, "--ports", ports, "--since", str(int(since))], b""
        else:
            remote, data = probe_command(spec, since)
            cmd = ssh_base(spec) + [remote]
        p = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "probe timed out after %ds" % timeout, int((time.time() - t0) * 1000)
    except OSError as e:
        return None, "cannot run %s: %s" % ("probe" if spec["transport"] == "local" else "ssh", e.strerror), int((time.time() - t0) * 1000)
    wall = int((time.time() - t0) * 1000)
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    for line in reversed(out):
        if line.startswith("{"):
            try:
                return json.loads(line), None, wall
            except ValueError:
                break
    err = scrub(p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["exit %d, no output" % p.returncode])[0]
    return None, err, wall


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){3,7}\b", re.I)


def scrub(lines):
    """No addresses in output (ssh errors like 'connect to host 10.0.0.5 port 22')."""
    return [IP_RE.sub("<addr>", re.sub(r"port \d+", "port <p>", l))[:160] for l in lines]


# ---------------------------------------------------------------- state + death detection

class HostState:
    def __init__(self, spec):
        self.spec, self.sample, self.prev = spec, None, None
        self.last_ok = self.last_try = None
        self.err, self.fails, self.next_try, self.wall_ms = None, 0, 0.0, None

    def stale(self, now, interval):
        if self.sample is None:
            return True
        return self.err is not None or now - self.last_ok > 3 * interval + 10

    def as_json(self, now, interval):
        return {"transport": self.spec["transport"], "stale": self.stale(now, interval), "error": self.err,
                "last_ok": self.last_ok, "fails": self.fails, "probe_wall_ms": self.wall_ms, "sample": self.sample}


def backoff(fails, base=2.0, cap=60.0):
    return min(cap, base * (2 ** max(0, fails - 1)))


def proc_key(p):
    return "%s:%s" % (p.get("pid"), p.get("start"))


def node_for(spec, proc):
    port = str((proc.get("flags") or {}).get("port") or "")
    for nn, nd in spec.get("nodes", {}).items():
        if str(nd["port"]) == port:
            return nn
    return None


def death_hints(proc, cur, prev):
    hints = []
    for k in (cur or {}).get("kills", []):
        if k.get("pid") == proc.get("pid"):
            if k["source"] == "earlyoom":
                hints.append("OOM: earlyoom sent %s (VmRSS %s MiB)" % (k.get("signal"), k.get("rss_mib")))
            else:
                hints.append("OOM: %s killed it (anon-rss %s MiB)" % (k["source"], k.get("rss_mib")))
    if not hints and prev:
        m = prev.get("mem") or {}
        if m.get("total_mib") and m.get("available_mib") is not None and m["available_mib"] < 0.1 * m["total_mib"]:
            hints.append("memory was low at last sample (%s/%s MiB available)" % (m["available_mib"], m["total_mib"]))
    if not hints:
        hints.append("no OOM record; exit code not visible to the monitor (not its child), see log")
    return hints


def related_log(proc, node, sample):
    logs = (sample or {}).get("logs") or {}
    want = [x for x in ((proc.get("flags") or {}).get("log_file"), node and "serve-%s.log" % node) if x]
    for path, v in logs.items():
        if any(path.endswith(w) or os.path.basename(path).startswith(w) for w in want):
            return path, v.get("tail") or []
    if logs:
        path, v = max(logs.items(), key=lambda kv: kv[1].get("mtime", 0))
        return path, v.get("tail") or []
    return None, []


ONESHOT = {"llama-bench", "llama-cli", "llama-run", "llama-embedding", "escalate.py"}  # exiting is normal unless OOM-killed


def diff_samples(spec, prev, cur, seen_kills=None):
    """Compare two probe samples of one host. Returns events (pure; unit-tested)."""
    events, host = [], spec["name"]
    if not cur or not cur.get("ok"):
        return events
    seen = seen_kills if seen_kills is not None else set()
    fam_pids = {p["pid"] for p in (prev or {}).get("familia", [])}
    if prev and prev.get("ok"):
        rebooted = cur.get("boot_time", 0) > prev.get("boot_time", 0) + 30
        cur_keys = {proc_key(p) for p in cur.get("familia", [])}
        for p in prev.get("familia", []):
            if proc_key(p) in cur_keys:
                continue
            node = node_for(spec, p)
            oneshot = p.get("kind") in ONESHOT
            hints = ["host rebooted (boot time moved)"] if rebooted else death_hints(p, cur, prev)
            logp, tail = related_log(p, node, cur)
            oom = any(h.startswith("OOM") for h in hints)
            if oneshot and not oom and not rebooted:
                events.append({"type": "exited", "severity": "info", "host": host, "kind": p.get("kind"), "pid": p.get("pid"),
                               "node": node, "detected": cur.get("time")})
                continue
            events.append({"type": "death", "severity": "critical", "host": host, "node": node, "kind": p.get("kind"),
                           "pid": p.get("pid"), "port": (p.get("flags") or {}).get("port"), "model": (p.get("flags") or {}).get("model"),
                           "rss_mib": p.get("rss_mib"), "uptime_s": p.get("uptime_s"), "last_seen": prev.get("time"),
                           "detected": cur.get("time"), "cause": hints, "log": logp, "log_tail": tail})
        prev_h = {h["port"]: h for h in prev.get("health", [])}
        for h in cur.get("health", []):
            ph = prev_h.get(h["port"])
            dead_ports = {str(e.get("port")) for e in events if e["type"] == "death"}
            if ph and ph.get("health") == 200 and h.get("health") != 200 and str(h["port"]) not in dead_ports:
                events.append({"type": "unhealthy", "severity": "warning", "host": host, "port": h["port"],
                               "node": next((n for n, d in spec["nodes"].items() if d["port"] == h["port"]), None),
                               "detected": cur.get("time"), "cause": ["/health now %s" % h.get("health")]})
        prev_keys = {proc_key(p) for p in prev.get("familia", [])}
        for p in cur.get("familia", []):
            if proc_key(p) not in prev_keys:
                events.append({"type": "started", "severity": "info", "host": host, "kind": p.get("kind"), "pid": p.get("pid"),
                               "node": node_for(spec, p), "detected": cur.get("time")})
    for k in cur.get("kills", []):
        key = "%s:%s:%s" % (host, k.get("ts"), k.get("pid"))
        if key in seen:
            continue
        seen.add(key)
        if prev is None:
            continue  # first sample: history only, not an alert
        if k.get("pid") in fam_pids:
            continue  # already reported as a death with this cause
        events.append({"type": "oom-kill", "severity": "warning", "host": host, "pid": k.get("pid"), "name": k.get("name"),
                       "detected": cur.get("time"), "cause": ["%s (%s)" % (k["source"], k.get("signal") or "kill")]})
    return events


def slim(sample):
    """What we persist between runs (for --once/--watch-deaths death detection across invocations)."""
    if not sample:
        return None
    return {k: sample.get(k) for k in ("ok", "time", "boot_time", "familia", "health", "mem")}


# ---------------------------------------------------------------- monitor core

class Monitor:
    def __init__(self, hosts, interval=3.0, event_log=None, on_death=None, persist=True):
        self.states = {n: HostState(s) for n, s in hosts.items()}
        self.interval, self.events, self.lock = interval, [], threading.Lock()
        self.event_log = event_log or os.path.join(STATE_DIR, "monitor-events.jsonl")
        self.on_death, self.persist, self.seen_kills, self.unacked = on_death, persist, set(), []
        self.pool = cf.ThreadPoolExecutor(max_workers=max(1, min(8, len(hosts))))
        self.last_path = os.path.join(STATE_DIR, "monitor-last.json")
        if persist:
            try:
                saved = json.load(open(self.last_path))
                self.seen_kills = set(saved.get("seen_kills", []))
                for n, s in saved.get("hosts", {}).items():
                    if n in self.states and s:
                        self.states[n].prev = s
            except (OSError, ValueError):
                pass

    def refresh(self, force=False):
        now = time.time()
        due = [st for st in self.states.values() if st.spec["transport"] and (force or now >= st.next_try)]
        futs = {}
        for st in due:
            ref = st.sample or st.prev
            since = (ref.get("time", now - 3600) - 5) if ref else now - 3600
            st.last_try = now
            futs[self.pool.submit(run_probe, st.spec, since)] = st
        new = []
        for f in cf.as_completed(futs):
            st = futs[f]
            sample, err, wall = f.result()
            st.wall_ms = wall
            if sample is None or not sample.get("ok", True):
                st.err = err or (sample or {}).get("error", "probe failed")
                st.fails += 1
                st.next_try = time.time() + backoff(st.fails, base=self.interval)
                continue
            prev = st.sample or st.prev
            st.prev, st.sample, st.err, st.fails = prev, sample, None, 0
            st.last_ok, st.next_try = time.time(), time.time() + self.interval
            new += diff_samples(st.spec, prev, sample, self.seen_kills)
        if new:
            self.record(new)
        if self.persist and futs:
            self.save()
        return new

    def record(self, events):
        with self.lock:
            self.events = (self.events + events)[-200:]
            self.unacked += [e for e in events if e["severity"] in ("critical", "warning")]
        try:
            os.makedirs(os.path.dirname(self.event_log), mode=0o700, exist_ok=True)
            fd = os.open(self.event_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                for e in events:
                    f.write(json.dumps(e, separators=(",", ":")) + "\n")
        except OSError:
            pass
        if self.on_death:
            for e in events:
                if e["type"] == "death":
                    run_hook(self.on_death, e)

    def save(self):
        try:
            os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
            tmp = self.last_path + ".tmp"
            data = {"hosts": {n: slim(st.sample or st.prev) for n, st in self.states.items()},
                    "seen_kills": sorted(self.seen_kills)[-500:]}
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.last_path)
        except OSError:
            pass


def run_hook(cmd, e):
    env = dict(os.environ, FAMILIA_HOST=str(e.get("host")), FAMILIA_NODE=str(e.get("node") or ""), FAMILIA_PID=str(e.get("pid")),
               FAMILIA_PROC=str(e.get("kind")), FAMILIA_PORT=str(e.get("port") or ""), FAMILIA_CAUSE="; ".join(e.get("cause", [])),
               FAMILIA_EVENT_JSON=json.dumps(e))
    try:
        subprocess.Popen(["sh", "-c", cmd], env=env, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as ex:
        sys.stderr.write("on-death hook failed to start: %s\n" % ex)


# ---------------------------------------------------------------- rendering

def system_agents_line(sa):
    """One line for the phone-assistant state written by scripts/termux/system_agent.py probe."""
    st = sa.get("shizuku") or "unknown"
    word = {"running": "running", "stopped": "STOPPED", "absent": "not set up",
            "stopped-after-reboot": "STOPPED after reboot (expected without root: open Shizuku, press Start)"}.get(st, st)
    prov = sa.get("providers") or {}
    have = [p for p, d in sorted(prov.items()) if isinstance(d, dict) and d.get("app")]
    age = sa.get("age_s")
    return "assistants: shizuku %s; apps %s%s" % (word, ", ".join(have) or "-", "" if age is None else " (checked %s ago)" % fmt_dur(age))


def fmt_dur(s):
    if s is None:
        return "?"
    s = int(s)
    if s < 120:
        return "%ds" % s
    if s < 7200:
        return "%dm" % (s // 60)
    if s < 172800:
        return "%dh%02dm" % (s // 3600, s % 3600 // 60)
    return "%dd%02dh" % (s // 86400, s % 86400 // 3600)


def host_level(st, now, interval):
    """('ok'|'warn'|'bad'|'stale'|'none', [reasons])."""
    if not st.spec["transport"]:
        return "none", ["no transport"]
    if st.stale(now, interval):
        return "stale", [st.err or "no sample yet"]
    s, why, lvl = st.sample, [], "ok"
    m = s.get("mem") or {}
    if m.get("total_mib") and m.get("available_mib") is not None:
        frac = m["available_mib"] / float(m["total_mib"])
        if frac < 0.07:
            lvl, why = "bad", why + ["RAM %d%% available" % (frac * 100)]
        elif frac < 0.15:
            lvl, why = "warn", why + ["RAM %d%% available" % (frac * 100)]
    if m.get("swap_total_mib") and m.get("swap_free_mib") is not None and m["swap_free_mib"] < 0.5 * m["swap_total_mib"]:
        lvl, why = ("warn" if lvl == "ok" else lvl), why + ["swap >50% used"]
    down = [n for n, d in st.spec["nodes"].items() if d.get("status") == "active" and
            not any(h["port"] == d["port"] and h.get("health") == 200 for h in s.get("health", []))]
    if down:
        lvl, why = ("warn" if lvl == "ok" else lvl), why + ["active node down: " + ",".join(down)]
    if s.get("kills"):
        lvl, why = "bad", why + ["%d OOM kill(s) since last sample" % len(s["kills"])]
    t = max([x["c"] for x in s.get("temps", [])] or [0])
    if t >= 90:
        lvl, why = "bad", why + ["temp %dC" % t]
    elif t >= 80:
        lvl, why = ("warn" if lvl == "ok" else lvl), why + ["temp %dC" % t]
    for d in s.get("disks", []):
        if d["total_mib"] and d["free_mib"] < 0.05 * d["total_mib"]:
            lvl, why = ("warn" if lvl == "ok" else lvl), why + ["disk %s %d%% free" % (d["mount"], 100 * d["free_mib"] // d["total_mib"])]
    return lvl, why


def summary_cols(st, now, interval):
    s = st.sample
    lvl, why = host_level(st, now, interval)
    if lvl == "none":
        return [st.spec["name"], "-", "no transport: add an ~/.ssh/config alias or %s" % CONFIG.replace(os.path.expanduser("~"), "~")], lvl
    if s is None:
        retry = max(0, int(st.next_try - now))
        return [st.spec["name"], "down", "never reached (%s); retry in %ds" % (st.err or "connecting", retry)], "stale"
    m = s.get("mem") or {}
    cpu = (s.get("cpu_pct") or {}).get("cpu")
    swap_used = (m.get("swap_total_mib") or 0) - (m.get("swap_free_mib") or 0)
    temp = max([x["c"] for x in s.get("temps", [])] or [None], key=lambda v: v or 0)
    up = sum(1 for h in s.get("health", []) if h.get("health") == 200)
    cols = [st.spec["name"], lvl if lvl != "stale" else "STALE",
            fmt_dur(s.get("uptime_s")), "%.2f" % (s.get("load") or [0])[0] if s.get("load") else "-",
            "%s%%" % (int(cpu) if cpu is not None else "-"),
            "%s/%s" % (m.get("available_mib", "?"), m.get("total_mib", "?")), "%d/%s" % (swap_used, m.get("swap_total_mib", 0)),
            "%dC" % temp if temp else "-", "%d" % len(s.get("familia", [])), "%d/%d" % (up, len(s.get("health", []))),
            "%s/%sms" % ((s.get("probe") or {}).get("elapsed_ms", "?"), st.wall_ms)]
    if lvl == "stale":
        cols.append("last seen %s ago: %s" % (fmt_dur(now - (st.last_ok or now)), st.err))
    elif why:
        cols.append("; ".join(why))
    return cols, lvl


HEAD = ["HOST", "STATE", "UP", "LOAD", "CPU", "MEM av/tot", "SWAP", "TEMP", "PROCS", "HEALTH", "PROBE", "NOTES"]
WIDTHS = [9, 6, 7, 5, 4, 11, 10, 5, 5, 6, 12]


def summary_line(cols):
    if len(cols) == 3:
        return "%-9s %-6s %s" % tuple(cols)
    return " ".join(("%-" + str(w) + "s") % c for w, c in zip(WIDTHS, cols)) + (" " + cols[11] if len(cols) > 11 else "")


def event_line(e):
    ts = time.strftime("%H:%M:%S", time.localtime(e.get("detected") or time.time()))
    if e["type"] == "death":
        what = "%s %s pid %s%s" % (e.get("node") or "-", e.get("kind"), e.get("pid"), " port %s" % e["port"] if e.get("port") else "")
        return "%s !! DEATH %s: %s died (up %s, %s MiB) - %s" % (ts, e["host"], what, fmt_dur(e.get("uptime_s")), e.get("rss_mib"), "; ".join(e["cause"]))
    if e["type"] == "oom-kill":
        return "%s !  OOM-KILL %s: pid %s (%s) - %s" % (ts, e["host"], e.get("pid"), e.get("name"), "; ".join(e["cause"]))
    if e["type"] == "unhealthy":
        return "%s !  UNHEALTHY %s: %s port %s - %s" % (ts, e["host"], e.get("node"), e.get("port"), "; ".join(e["cause"]))
    if e["type"] == "host":
        return "%s ~  HOST %s %s" % (ts, e["host"], e.get("cause", [""])[0])
    if e["type"] == "exited":
        return "%s .  exited %s: %s pid %s (one-shot tool, no OOM record)" % (ts, e["host"], e.get("kind"), e.get("pid"))
    return "%s .  started %s: %s pid %s (%s)" % (ts, e["host"], e.get("kind"), e.get("pid"), e.get("node") or "-")


def detail_lines(st, now, interval):
    s, out = st.sample, []
    lvl, why = host_level(st, now, interval)
    out.append("== %s  [%s] via %s%s" % (st.spec["name"], lvl, st.spec["transport"], ("  (" + "; ".join(why) + ")") if why else ""))
    if not s:
        return out + ["   no sample: %s" % (st.err or "not probed yet")]
    if lvl == "stale":
        out.append("   STALE: last seen %s ago, error: %s (showing last sample)" % (fmt_dur(now - (st.last_ok or now)), st.err))
    m = s.get("mem") or {}
    out.append("   %s | %s | up %s | load %s | ncpu %s" % (s.get("hostname"), s.get("os"), fmt_dur(s.get("uptime_s")),
               " ".join(str(x) for x in s.get("load", [])), s.get("ncpu")))
    cores = s.get("cpu_pct") or {}
    out.append("   cpu %s" % "  ".join("%s %s%%" % (k, int(v)) for k, v in sorted(cores.items())))
    out.append("   mem %s/%s MiB available, shmem %s; swap %s free of %s%s" % (
        m.get("available_mib"), m.get("total_mib"), m.get("shmem_mib", "-"), m.get("swap_free_mib"), m.get("swap_total_mib"),
        "".join("; %s %s->%s MiB" % (z["dev"], z["orig_mib"], z["compr_mib"]) for z in s.get("zram", []))))
    if s.get("battery"):
        out.append("   battery %s%% %s" % (s["battery"].get("pct"), s["battery"].get("status") or ""))
    if s.get("system_agents"):  # phone assistants via Shizuku (#80, docs/system-agents.md)
        out.append("   " + system_agents_line(s["system_agents"]))
    out.append("   familia processes:")
    for p in s.get("familia", []) or []:
        f = p.get("flags") or {}
        keys = " ".join("%s=%s" % (k, f[k]) for k in ("model", "ctx", "ngl", "threads", "parallel", "port", "kv_type", "cache_ram", "vk_visible") if k in f)
        out.append("     %-7s %-14s %-14s rss %5s MiB cpu %5s%% up %-7s %s" % (p["pid"], p["kind"], node_for(st.spec, p) or "-",
                   p.get("rss_mib"), p.get("cpu_pct", p.get("cpu_s")), fmt_dur(p.get("uptime_s")), keys))
    if not s.get("familia"):
        out.append("     (none running)")
    out.append("   node endpoints (127.0.0.1):")
    for nn, nd in sorted(st.spec["nodes"].items(), key=lambda kv: kv[1]["port"]):
        h = next((x for x in s.get("health", []) if x["port"] == nd["port"]), {})
        out.append("     %-20s :%-5s %-8s health=%s models=%s %s" % (nn, nd["port"], nd.get("status") or "", h.get("health", "?"),
                   h.get("models", "-"), ",".join(x for x in h.get("model_ids", []) if x)))
    out.append("   top RSS: " + ", ".join("%s(%s) %sM" % (t["comm"], t["pid"], t["rss_mib"]) for t in s.get("top", [])[:6]))
    out.append("   disks: " + ", ".join("%s %s/%sG free" % (d["mount"], d["free_mib"] // 1024, d["total_mib"] // 1024) for d in s.get("disks", [])))
    if s.get("gpus"):
        out.append("   gpus: " + "; ".join(" ".join("%s=%s" % (k, v) for k, v in g.items() if v not in (None, "")) for g in s["gpus"]))
    if s.get("temps"):
        out.append("   temps: " + ", ".join("%s %sC" % (t["name"], t["c"]) for t in s["temps"][:8]))
    for k in s.get("kills", []):
        out.append("   KILL %s %s pid %s (%s)" % (time.strftime("%H:%M:%S", time.localtime(k.get("ts") or 0)), k["source"], k.get("pid"), k.get("name")))
    for path, v in (s.get("logs") or {}).items():
        out.append("   log %s (%s ago)" % (path, fmt_dur(now - v.get("mtime", now))))
        out += ["     | " + l for l in v.get("tail") or []]
    pr = s.get("probe") or {}
    out.append("   probe: %s ms on host, %s ms CPU, %s KiB max RSS; round trip %s ms" % (pr.get("elapsed_ms"), pr.get("cpu_ms"), pr.get("maxrss_kib"), st.wall_ms))
    return out


def render_text(mon, now=None, details=None, events=8):
    now = now or time.time()
    sts = list(mon.states.values())
    up = sum(1 for st in sts if st.spec["transport"] and not st.stale(now, mon.interval))
    lines = ["familia monitor  %s  every %gs  %d/%d hosts up" % (time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(now)), mon.interval, up, len(sts))]
    for e in mon.unacked[-5:]:
        if e["type"] == "death":
            lines.append(event_line(e))
            lines += ["      log %s: %s" % (e.get("log"), l) for l in (e.get("log_tail") or [])[-2:]]
    lines.append(summary_line(HEAD))
    for st in sts:
        lines.append(summary_line(summary_cols(st, now, mon.interval)[0]))
    for st in sts:
        if details is True or (details and st.spec["name"] in details):
            lines.append("")
            lines += detail_lines(st, now, mon.interval)
    if events and mon.events:
        lines.append("")
        lines.append("recent events:")
        lines += ["  " + event_line(e) for e in mon.events[-events:]]
    return "\n".join(lines)


def to_json(mon, now=None):
    now = now or time.time()
    return {"time": now, "interval": mon.interval, "events": mon.events,
            "hosts": {n: dict(st.as_json(now, mon.interval), level=host_level(st, now, mon.interval)[0]) for n, st in mon.states.items()}}


# ---------------------------------------------------------------- live UIs

def poller(mon, stop, wake):
    while not stop.is_set():
        mon.refresh(force=wake.is_set())
        wake.clear()
        nxt = min([st.next_try for st in mon.states.values() if st.spec["transport"]] or [time.time() + mon.interval])
        wake.wait(max(0.2, min(mon.interval, nxt - time.time())))


def live_plain(mon):
    try:
        while True:
            mon.refresh()
            sys.stdout.write("\n" + render_text(mon) + "\n")
            sys.stdout.flush()
            time.sleep(mon.interval)
    except KeyboardInterrupt:
        pass


def live_curses(mon):
    import curses
    stop, wake = threading.Event(), threading.Event()
    th = threading.Thread(target=poller, args=(mon, stop, wake), daemon=True)
    th.start()
    help_ = "q quit  up/down/j/k select  Enter details  Esc/Left back  r refresh  a ack alerts  +/- interval  ? help"

    def ui(scr):
        curses.curs_set(0)
        scr.timeout(250)
        col = {}
        if curses.has_colors():
            curses.use_default_colors()
            for i, (k, c) in enumerate((("ok", curses.COLOR_GREEN), ("warn", curses.COLOR_YELLOW), ("bad", curses.COLOR_RED),
                                        ("stale", curses.COLOR_MAGENTA), ("none", curses.COLOR_BLUE)), 1):
                curses.init_pair(i, c, -1)
                col[k] = curses.color_pair(i)
            curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_RED)
            col["alert"] = curses.color_pair(9) | curses.A_BOLD
        sel, view, scroll, show_help, beeped = 0, None, 0, False, 0
        while True:
            now = time.time()
            names = list(mon.states)
            h, w = scr.getmaxyx()
            scr.erase()

            def put(y, x, s, a=0):
                if 0 <= y < h - 1:
                    try:
                        scr.addnstr(y, x, s, max(0, w - x - 1), a)
                    except curses.error:
                        pass
            put(0, 0, "familia monitor  %s  every %gs   %s" % (time.strftime("%H:%M:%S %Z"), mon.interval, "" if show_help else "? help"), curses.A_BOLD)
            y = 1
            alerts = [e for e in mon.unacked if e["severity"] == "critical"][-4:] + [e for e in mon.unacked if e["severity"] == "warning"][-2:]
            if len(mon.unacked) > beeped:
                if any(e["severity"] == "critical" for e in mon.unacked[beeped:]):
                    curses.beep()
                beeped = len(mon.unacked)
            for e in alerts:
                put(y, 0, (event_line(e) + "   [a]=ack").ljust(w - 1), col.get("alert", curses.A_REVERSE) if e["severity"] == "critical" else col.get("warn", 0) | curses.A_BOLD)
                y += 1
            if show_help:
                put(y, 0, help_, curses.A_DIM)
                y += 1
            if view is None:
                put(y, 0, summary_line(HEAD), curses.A_UNDERLINE)
                y += 1
                for i, n in enumerate(names):
                    cols, lvl = summary_cols(mon.states[n], now, mon.interval)
                    a = col.get(lvl, 0) | (curses.A_REVERSE if i == sel else 0)
                    put(y, 0, summary_line(cols), a)
                    y += 1
                y += 1
                put(y, 0, "events (log: %s)" % mon.event_log.replace(os.path.expanduser("~"), "~"), curses.A_BOLD)
                for e in mon.events[-(h - y - 3):] if h - y > 3 else []:
                    y += 1
                    put(y, 2, event_line(e), col.get({"critical": "bad", "warning": "warn"}.get(e["severity"], "ok"), 0))
            else:
                lines = detail_lines(mon.states[view], now, mon.interval)
                scroll = max(0, min(scroll, len(lines) - (h - y - 1)))
                for l in lines[scroll:]:
                    a = col.get(host_level(mon.states[view], now, mon.interval)[0], 0) | curses.A_BOLD if l.startswith("==") else (col.get("bad", 0) if "KILL" in l or "STALE" in l else 0)
                    put(y, 0, l, a)
                    y += 1
            put(h - 1, 0, ("Esc back  j/k scroll  r refresh  a ack  q quit" if view else "Enter details  r refresh  a ack  +/- interval  q quit"), curses.A_DIM)
            scr.refresh()
            k = scr.getch()
            if k in (ord("q"), ord("Q")):
                return
            if k in (curses.KEY_UP, ord("k")):
                if view:
                    scroll = max(0, scroll - 1)
                else:
                    sel = max(0, sel - 1)
            elif k in (curses.KEY_DOWN, ord("j")):
                if view:
                    scroll += 1
                else:
                    sel = min(len(names) - 1, sel + 1)
            elif k in (curses.KEY_NPAGE, ord(" ")) and view:
                scroll += h - 4
            elif k == curses.KEY_PPAGE and view:
                scroll = max(0, scroll - (h - 4))
            elif k in (10, 13, curses.KEY_ENTER, curses.KEY_RIGHT, ord("d")) and not view and names:
                view, scroll = names[sel], 0
            elif k in (27, curses.KEY_LEFT, curses.KEY_BACKSPACE, 127, ord("b")):
                view = None
            elif k in (ord("r"), ord("R")):
                for st in mon.states.values():
                    st.next_try = 0
                wake.set()
            elif k in (ord("a"), ord("A")):
                mon.unacked = []
            elif k == ord("+"):
                mon.interval = min(60, mon.interval + 1)
            elif k == ord("-"):
                mon.interval = max(1, mon.interval - 1)
            elif k == ord("?"):
                show_help = not show_help
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(ui)
    finally:
        stop.set()
        wake.set()


def watch_deaths(mon):
    """Alert loop for a phone/tmux pane: one line per event, bell on deaths, host up/down transitions."""
    was_up = {}
    sys.stdout.write("watching %d host(s) every %gs for familia process deaths (Ctrl-C to stop); events -> %s\n" % (
        len(mon.states), mon.interval, mon.event_log))
    sys.stdout.flush()
    try:
        while True:
            evs = mon.refresh()
            now = time.time()
            for n, st in mon.states.items():
                if not st.spec["transport"]:
                    continue
                up = not st.stale(now, mon.interval)
                if was_up.get(n) is not None and up != was_up[n]:
                    evs.append({"type": "host", "severity": "warning", "host": n, "detected": now,
                                "cause": ["back up" if up else "unreachable: %s (retrying with backoff)" % st.err]})
                was_up[n] = up
            for e in evs:
                if e["severity"] == "info":
                    continue
                sys.stdout.write(("\a" if e["type"] == "death" else "") + event_line(e) + "\n")
                for l in (e.get("log_tail") or [])[-3:]:
                    sys.stdout.write("      | %s\n" % l)
            sys.stdout.flush()
            time.sleep(mon.interval)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="familia-monitor", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog="Keys (live): " +
                                 "q quit, j/k select, Enter details, Esc back, r refresh, a ack alerts, +/- interval. See docs/monitoring.md")
    ap.add_argument("hosts", nargs="*", help="only these graph hosts")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="print one text snapshot and exit (exit 2 if any host is bad/stale)")
    mode.add_argument("--json", action="store_true", help="print one JSON snapshot and exit")
    mode.add_argument("--watch-deaths", action="store_true", help="alert loop: print deaths/OOM kills/host changes")
    mode.add_argument("--plain", action="store_true", help="live, but plain text instead of curses")
    ap.add_argument("-i", "--interval", type=float, default=float(os.environ.get("FAMILIA_MONITOR_INTERVAL", 3)), help="refresh seconds (default 3)")
    ap.add_argument("--details", action="store_true", help="with --once: per-host details for every host")
    ap.add_argument("--graph", default=os.path.join(ROOT, "graph.yaml"))
    ap.add_argument("--config", default=CONFIG, help="private host/transport overrides (JSON, never committed)")
    ap.add_argument("--event-log", default=None, help="JSONL event log (default %s/monitor-events.jsonl)" % STATE_DIR)
    ap.add_argument("--on-death", metavar="CMD", help="sh command run per familia process death; env FAMILIA_HOST/NODE/PID/PROC/PORT/CAUSE/EVENT_JSON")
    ap.add_argument("--no-state", action="store_true", help="don't load/save the last sample (no cross-run death detection)")
    ap.add_argument("--list", action="store_true", help="list hosts and how each is reached, then exit")
    a = ap.parse_args(argv)
    if a.interval < 1:
        ap.error("--interval must be >= 1")
    graph, cfg = load_graph(a.graph), load_config(a.config)
    unknown = [h for h in a.hosts if h not in (graph.get("hosts") or {}) and h not in cfg.get("hosts", {})]
    if unknown:
        ap.error("unknown host(s): %s (known: %s)" % (", ".join(unknown), ", ".join(list(graph.get("hosts") or {}) + list(cfg.get("hosts", {})))))
    hosts = build_hosts(graph, cfg, only=a.hosts or None)
    if a.list:
        for n, s in hosts.items():
            print("%-10s %-9s %-8s nodes: %s" % (n, s["transport"] or "-", s["os"], ", ".join("%s:%d" % (k, v["port"]) for k, v in s["nodes"].items()) or "-"))
        return 0
    mon = Monitor(hosts, a.interval, a.event_log, a.on_death, persist=not a.no_state)
    if a.once or a.json:
        mon.refresh(force=True)
        if a.json:
            print(json.dumps(to_json(mon), indent=1))
        else:
            print(render_text(mon, details=True if a.details else (set(a.hosts) or None)))
        bad = any(host_level(st, time.time(), mon.interval)[0] in ("bad", "stale") for st in mon.states.values())
        return 2 if bad or any(e["type"] == "death" for e in mon.events) else 0
    if a.watch_deaths:
        watch_deaths(mon)
        return 0
    if a.plain or not sys.stdout.isatty() or os.environ.get("TERM", "dumb") == "dumb":
        live_plain(mon)
        return 0
    try:
        import curses  # noqa: F401
    except ImportError:
        live_plain(mon)
        return 0
    live_curses(mon)
    return 0


if __name__ == "__main__":
    sys.exit(main())
