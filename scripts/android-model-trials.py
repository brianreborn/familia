#!/usr/bin/env python3
"""Run a small, watchdog-supervised llama.cpp CPU/Vulkan trial matrix over ADB.

Requirements and limits:
- Commands run through `adb shell run-as <package>`, which needs a debuggable
  Termux build (release F-Droid/GitHub builds refuse with "package not
  debuggable"). The script checks this first and stops with a clear message.
- Keep Termux open with "Acquire wakelock" during a run; with the screen off the
  CPU sleeps and the numbers are noise. The journal records the power state.
- The server always binds with an API key (`--api-key-file`, default
  `<termux-home>/.config/familia/api.key`, created 0600 if missing). Only
  `/health` is unauthenticated.
- Interrupts (^C, SIGTERM, timeouts) stop the active trial's server and
  watchdog before exiting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Device:
    def __init__(self, adb: str, serial: str, package: str, home: str, termux_home: str, prefix: str, timeout: int,
                 vulkan_dir: str | None = None):
        self.adb, self.serial, self.package = adb, serial, package
        self.home, self.termux_home, self.prefix, self.timeout = home, termux_home, prefix, timeout
        self.vulkan_dir = vulkan_dir

    def shell(self, command: str, timeout: int | None = None) -> str:
        env = (f"export HOME={shlex.quote(self.termux_home)}\n"
               f"export PREFIX={shlex.quote(self.prefix)}\n"
               f"export PATH={shlex.quote(self.prefix + '/bin:/system/bin')}\n"
               f"export TMPDIR={shlex.quote(self.prefix + '/tmp')}\n"
               f"export LD_LIBRARY_PATH={shlex.quote(((self.vulkan_dir + ':') if self.vulkan_dir else '') + self.prefix + '/lib')}\n")
        argv = [self.adb, "-s", self.serial, "shell", "-T", "run-as", self.package,
                "/system/bin/sh", "-s"]
        return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, input=env + command + "\n",
                              timeout=timeout or self.timeout).stdout.strip()

    def forward(self, port: int) -> None:
        """Forward tcp:PORT. A stale forward from this phone is cleared; one owned by another
        device (another trial run) is never touched: refuse instead."""
        listing = subprocess.run([self.adb, "forward", "--list"], text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout or ""
        for line in listing.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == f"tcp:{port}":
                if fields[0] != self.serial:
                    raise RuntimeError(f"host port {port} is already forwarded to another device; "
                                       "pick another --port")
                self.unforward(port)
        subprocess.run([self.adb, "-s", self.serial, "forward", f"tcp:{port}", f"tcp:{port}"],
                       check=True, stdout=subprocess.DEVNULL)

    def unforward(self, port: int) -> None:
        subprocess.run([self.adb, "-s", self.serial, "forward", "--remove", f"tcp:{port}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def health(port: int, seconds: float = 2) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=seconds) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


HEALTH_PROBE_SECONDS = 6
STOP_GRACE_SECONDS = 10
WATCHDOG_TICK_SECONDS: float = 2
PHONE_SH = "/system/bin/sh"


def serial_tag(serial: str) -> str:
    """Short, stable, non-identifying tag for an ADB serial (journal and file names)."""
    return hashlib.sha256(serial.encode()).hexdigest()[:12]


def ensure_api_key(device: Device, key_file: str) -> str:
    """Create (0600) or reuse the key file on the phone and return the key."""
    q = shlex.quote(key_file)
    key = device.shell(
        f"umask 077; mkdir -p \"$(dirname {q})\"; "
        f"if [ ! -s {q} ]; then od -An -tx1 -N32 /dev/urandom | tr -d ' \\n' > {q}; fi; "
        f"chmod 600 {q}; cat {q}")
    key = key.strip()
    if len(key) < 16:
        raise RuntimeError(f"API key file {key_file} is empty or too short")
    return key


def port_listening(device: Device, port: int) -> bool:
    """True while anything on the phone still LISTENs on the port (IPv4 or IPv6)."""
    out = device.shell(
        f"awk -v p=':{port:04X}' '$2 ~ p\"$\" && $4 == \"0A\" {{f=1}} END {{print f ? \"busy\" : \"free\"}}' "
        "/proc/net/tcp /proc/net/tcp6 2>/dev/null")
    return out.strip().endswith("busy")


_OWNER_SH = r"""inode=$(awk -v p=':PORTHEX' '$2 ~ p"$" && $4 == "0A" {print $10; exit}' /proc/net/tcp /proc/net/tcp6 2>/dev/null)
[ -n "$inode" ] || { echo none; exit 0; }
p=$(cat PIDFILE 2>/dev/null)
if [ -n "$p" ] && ls -l /proc/$p/fd 2>/dev/null | grep -q "socket:\[$inode\]"; then echo ours; else echo other; fi"""


def port_owner(device: Device, port: int, pidfile: str) -> str:
    """'ours' when the pid in pidfile owns the LISTEN socket on port, 'other' when some other
    process does, 'none' when nothing listens. health() alone would accept any server's 200."""
    out = device.shell(_OWNER_SH.replace("PORTHEX", f"{port:04X}").replace("PIDFILE", shlex.quote(pidfile)))
    out = out.strip().splitlines()[-1] if out.strip() else "none"
    return out if out in ("ours", "other") else "none"


def wait_port_free(device: Device, port: int, seconds: int = STOP_GRACE_SECONDS) -> None:
    """CPU and Vulkan trials share one port: refuse to start while an old server still holds it,
    or a leftover server could answer health() for the next trial."""
    deadline = time.monotonic() + seconds
    while True:
        if not port_listening(device, port):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"port {port} still in use on the phone; refusing to start the next trial")
        time.sleep(1)


def stop_trial(device: Device, base: str, timeout: int = 30, port: int | None = None) -> None:
    """Stop a trial's watchdog and server: TERM, wait, then KILL; then check the port is free."""
    q = {k: shlex.quote(f"{base}.{k}") for k in ("stop", "pid", "wpid", "watchdog.sh")}
    out = device.shell(f"""touch {q['stop']}
i=0; while [ -e {q['watchdog.sh']} ] && {{ [ ! -s {q['pid']} ] || [ ! -s {q['wpid']} ]; }} && [ $i -lt 5 ]; do sleep 1; i=$((i+1)); done
p=$(cat {q['pid']} 2>/dev/null); w=$(cat {q['wpid']} 2>/dev/null)
alive() {{ for x in $p $w; do kill -0 "$x" 2>/dev/null && return 0; done; return 1; }}
[ -n "$w" ] && kill -TERM -"$w" 2>/dev/null
for x in $p $w; do kill -TERM "$x" 2>/dev/null; done
i=0; while alive && [ $i -lt {STOP_GRACE_SECONDS} ]; do sleep 1; i=$((i+1)); done
if alive; then [ -n "$w" ] && kill -9 -"$w" 2>/dev/null; for x in $p $w; do kill -9 "$x" 2>/dev/null; done; fi
i=0; while alive && [ $i -lt 5 ]; do sleep 1; i=$((i+1)); done
if alive; then echo STILL_ALIVE; else echo STOPPED; fi""", timeout=timeout)
    if "STILL_ALIVE" in out:
        raise RuntimeError(f"trial {base} survived kill -9")
    if port is not None:
        wait_port_free(device, port)


def start_watchdog(device: Device, base: str, model: str, gpu_layers: int, port: int,
                   ctx: int, threads: int, api_key_file: str) -> tuple[str, str, str]:
    pidfile, logfile, statefile = (f"{base}.{suffix}" for suffix in ("pid", "log", "state"))
    readyfile, stopfile, busyfile = f"{base}.ready", f"{base}.stop", f"{base}.busy"
    watchdogfile = f"{base}.watchdog.sh"
    server = " ".join(map(shlex.quote, [
        "llama-server", "--model", model, "--host", "127.0.0.1", "--port", str(port),
        "--ctx-size", str(ctx), "--threads", str(threads), "--threads-batch", str(threads),
        "--n-gpu-layers", str(gpu_layers), "--parallel", "1", "--no-webui",
        "--api-key-file", api_key_file,
    ]))
    watchdog = f'''#!/system/bin/sh
echo $$ > {shlex.quote(base + '.wpid')}
echo STARTING > {shlex.quote(statefile)}
{server} > {shlex.quote(logfile)} 2>&1 &
server_pid=$!
echo "$server_pid" > {shlex.quote(pidfile)}
echo RUNNING > {shlex.quote(statefile)}
failures=0
ticks=0
while kill -0 "$server_pid" 2>/dev/null; do
  if [ -e {shlex.quote(stopfile)} ]; then
    echo STOPPED > {shlex.quote(statefile)}
    kill "$server_pid" 2>/dev/null
    exit 0
  fi
  ticks=$((ticks + 1))
  if [ -e {shlex.quote(busyfile)} ]; then
    failures=0  # a request is in flight; llama-server --parallel 1 may not answer /health until it ends
  elif [ -e {shlex.quote(readyfile)} ] && [ $((ticks % {max(1, int(HEALTH_PROBE_SECONDS / WATCHDOG_TICK_SECONDS))})) -eq 0 ]; then
    if python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:{port}/health", timeout=2).read()' >/dev/null 2>&1; then
      failures=0
    elif [ -e {shlex.quote(busyfile)} ]; then
      failures=0  # the request started while this probe was in flight
    else
      failures=$((failures + 1))
    fi
    if [ "$failures" -ge 3 ]; then
      echo UNHEALTHY > {shlex.quote(statefile)}
      date -u '+%Y-%m-%dT%H:%M:%SZ health check failed three times' >> {shlex.quote(base + '.watchdog')}
      kill "$server_pid" 2>/dev/null
      exit 1
    fi
  fi
  sleep {WATCHDOG_TICK_SECONDS}
done
if [ ! -e {shlex.quote(stopfile)} ]; then
  if [ -s {shlex.quote(logfile)} ]; then echo CRASHED > {shlex.quote(statefile)}; else echo 'KILLED?' > {shlex.quote(statefile)}; fi
  date -u '+%Y-%m-%dT%H:%M:%SZ server exited unexpectedly' >> {shlex.quote(base + '.watchdog')}
fi
'''
    command = (f"rm -f {shlex.quote(pidfile)} {shlex.quote(statefile)} {shlex.quote(readyfile)} {shlex.quote(stopfile)} {shlex.quote(busyfile)} {shlex.quote(base + '.wpid')}\n"
               f"cat > {shlex.quote(watchdogfile)} <<'WATCHDOG_SCRIPT'\n{watchdog}WATCHDOG_SCRIPT\n"
               f"chmod 700 {shlex.quote(watchdogfile)}\n"
               # setsid: the watchdog leads its own process group, so stop_trial can signal both
               f"if command -v setsid >/dev/null 2>&1; then s=setsid; else s=; fi\n"
               f"nohup $s {PHONE_SH} {shlex.quote(watchdogfile)} > {shlex.quote(base + '.watchdog-launch')} 2>&1 </dev/null &\n")
    device.shell(command)
    return pidfile, logfile, statefile


def _raise_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial", required=True, help="ADB serial for the Android phone")
    ap.add_argument("--package", default="com.termux")
    ap.add_argument("--home", default=None,
                    help="familia tree on the phone (default: <termux-home>/familia)")
    ap.add_argument("--api-key-file", default=None,
                    help="key file on the phone (default: <termux-home>/.config/familia/api.key, created 0600)")
    ap.add_argument("--vulkan-dir", default=None,
                    help="opt-in directory prepended to LD_LIBRARY_PATH for a bundled Vulkan loader")
    ap.add_argument("--termux-home", default="/data/data/com.termux/files/home")
    ap.add_argument("--prefix", default="/data/data/com.termux/files/usr")
    ap.add_argument("--model", default="models/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf")
    ap.add_argument("--port", type=int, default=18102)
    ap.add_argument("--ctx", type=int, required=True,
                    help="documented model context size; no smaller fallback is selected")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--startup-timeout", type=int, default=90)
    ap.add_argument("--request-timeout", type=int, default=90)
    ap.add_argument("--keep-best", action="store_true", help="leave the fastest healthy configuration running")
    args = ap.parse_args(argv)
    if args.home is None:
        args.home = f"{args.termux_home}/familia"
    if args.api_key_file is None:
        args.api_key_file = f"{args.termux_home}/.config/familia/api.key"
    if args.ctx < 1:
        ap.error("--ctx must be a positive documented context size")

    device = Device(args.adb, args.serial, args.package, args.home, args.termux_home, args.prefix, args.startup_timeout,
                    args.vulkan_dir)
    signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        device.shell("id -u")
    except subprocess.CalledProcessError as error:
        if "debuggable" in (error.output or ""):
            raise RuntimeError(f"run-as {args.package} refused: it needs a debuggable Termux build") from error
        raise
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trial_dir = f"{args.home}/trials/{run_id}"
    device.shell(f"mkdir -p {shlex.quote(trial_dir)}")
    tag = serial_tag(args.serial)
    journal = Path(f"android-model-trials-{tag}-{run_id}.jsonl")

    def event(**fields: object) -> None:
        row = {"time": stamp(), "time_zone": "UTC", "device": tag, **fields}
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        print(json.dumps(row, sort_keys=True), flush=True)

    model = f"{args.home}/{args.model}"
    device.shell(f"test -r {shlex.quote(model)} && command -v llama-server")
    devices = device.shell("llama-server --list-devices 2>&1 || true")
    meminfo = device.shell("grep -E 'MemTotal|MemAvailable' /proc/meminfo")
    api_key = ensure_api_key(device, args.api_key_file)
    power = device.shell("dumpsys power 2>/dev/null | grep -E 'mWakefulness|mHoldingWakeLock' || true")
    event(event="trial-set-start", model=model, context=args.ctx, threads=args.threads,
          backend_devices=devices, memory=meminfo, power=power,
          api_key_file=args.api_key_file, health_probe_seconds=HEALTH_PROBE_SECONDS, watchdog=f"{trial_dir}/watchdog.sh", journal=str(journal))

    configs = [("cpu", 0), ("vulkan", 99)]
    results: list[tuple[float, str, int]] = []
    failed = False
    active: str | None = None
    kept = False
    try:
        device.forward(args.port)
        for label, gpu_layers in configs:
            base = f"{trial_dir}/{label}"
            wait_port_free(device, args.port)
            active = base
            pidfile, logfile, statefile = start_watchdog(device, base, model, gpu_layers,
                                                         args.port, args.ctx, args.threads, args.api_key_file)
            readyfile = f"{base}.ready"
            event(event="trial-start", config=label, gpu_layers=gpu_layers,
                  memory=device.shell("grep -E 'MemTotal|MemAvailable' /proc/meminfo"), watchdog_state=statefile)
            deadline = time.monotonic() + args.startup_timeout
            ready = False
            state = "MISSING"
            while time.monotonic() < deadline:
                state = device.shell(f"cat {shlex.quote(statefile)} 2>/dev/null || echo MISSING")
                if state in ("CRASHED", "KILLED?"):
                    break
                owner = port_owner(device, args.port, pidfile)
                if owner == "ours" and health(args.port):
                    ready = True
                    break
                if owner == "other":
                    state = "PORT_OWNED_BY_OTHER"
                time.sleep(2)
            if not ready:
                log_tail = device.shell(f"tail -n 30 {shlex.quote(logfile)} 2>/dev/null || true")
                event(event="trial-failed", config=label, reason="server failed health check",
                      watchdog_state=state, log_tail=log_tail[-3000:])
                failed = True
                stop_trial(device, base, port=args.port)
                active = None
                continue

            device.shell(f"touch {shlex.quote(readyfile)}")

            payload = json.dumps({"prompt": "Write a Python function that returns the factorial of n and rejects negative input.",
                                  "n_predict": 48, "temperature": 0, "stream": False}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{args.port}/completion", data=payload,
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {api_key}"}, method="POST")
            busyfile = shlex.quote(f"{base}.busy")
            device.shell(f"touch {busyfile}")
            started = time.monotonic()
            try:
                try:
                    with urllib.request.urlopen(req, timeout=args.request_timeout) as response:
                        answer = json.loads(response.read())
                finally:
                    device.shell(f"rm -f {busyfile}")
                elapsed = time.monotonic() - started
                rate = float(answer.get("timings", {}).get("predicted_per_second", 0.0))
                state = device.shell(f"cat {shlex.quote(statefile)} 2>/dev/null || echo MISSING")
                if state != "RUNNING" or port_owner(device, args.port, pidfile) != "ours" or not health(args.port):
                    raise RuntimeError(f"watchdog state after request: {state}")
                results.append((rate, label, gpu_layers))
                event(event="trial-ok", config=label, seconds=round(elapsed, 2), tokens_per_second=rate,
                      response=answer.get("content", "")[:1200], watchdog_state=state)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                event(event="trial-failed", config=label, reason=str(exc))
                failed = True
            finally:
                stop_trial(device, base, port=args.port)
                active = None

        if args.keep_best and results:
            rate, label, gpu_layers = max(results)
            base = f"{trial_dir}/final"
            pidfile, logfile, statefile = (f"{base}.{suffix}" for suffix in ("pid", "log", "state"))
            readyfile = f"{base}.ready"
            wait_port_free(device, args.port)
            active = base
            start_watchdog(device, base, model, gpu_layers, args.port, args.ctx, args.threads, args.api_key_file)
            deadline = time.monotonic() + args.startup_timeout
            final_pid = f"{base}.pid"
            while time.monotonic() < deadline and not (port_owner(device, args.port, final_pid) == "ours"
                                                       and health(args.port)):
                time.sleep(2)
            if port_owner(device, args.port, final_pid) == "ours" and health(args.port):
                device.shell(f"touch {shlex.quote(readyfile)}")
                active = None  # intentionally left running (--keep-best)
                kept = True
                event(event="final-running", config=label, gpu_layers=gpu_layers, tokens_per_second=rate,
                      watchdog_state=statefile, watchdog_log=f"{base}.watchdog", server_log=logfile)
            else:
                event(event="final-start-failed", config=label, gpu_layers=gpu_layers)
                failed = True
    finally:
        try:
            if active is not None:
                stop_trial(device, active, timeout=20, port=args.port)
        except BaseException as error:  # incl. a second Ctrl-C; still remove the forward
            print(f"android-model-trials: cleanup of {active} incomplete: {error!r}", file=sys.stderr)
        finally:
            if not kept:  # --keep-best: leave the kept server reachable through its forward
                device.unforward(args.port)
    event(event="trial-set-finished", status="partial" if failed else "complete", journal=str(journal))
    if failed and not results:
        return 1
    return 3 if failed else 0  # 3 = partial: some configs failed


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("android-model-trials: interrupted; active trial stopped", file=sys.stderr)
        raise SystemExit(130)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError) as error:
        print(f"android-model-trials: {error}", file=sys.stderr)
        raise SystemExit(2)
