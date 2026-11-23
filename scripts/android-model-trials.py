#!/usr/bin/env python3
"""Run a small, watchdog-supervised llama.cpp CPU/Vulkan trial matrix over ADB."""
from __future__ import annotations

import argparse
import json
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
    def __init__(self, adb: str, serial: str, package: str, home: str, termux_home: str, prefix: str, timeout: int):
        self.adb, self.serial, self.package = adb, serial, package
        self.home, self.termux_home, self.prefix, self.timeout = home, termux_home, prefix, timeout

    def shell(self, command: str, timeout: int | None = None) -> str:
        env = (f"export HOME={shlex.quote(self.termux_home)}\n"
               f"export PREFIX={shlex.quote(self.prefix)}\n"
               f"export PATH={shlex.quote(self.prefix + '/bin:/system/bin')}\n"
               f"export TMPDIR={shlex.quote(self.prefix + '/tmp')}\n"
               f"export LD_LIBRARY_PATH={shlex.quote(self.home + '/vulkan:' + self.prefix + '/lib')}\n")
        argv = [self.adb, "-s", self.serial, "shell", "-T", "run-as", self.package,
                "/system/bin/sh", "-s"]
        return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, input=env + command + "\n",
                              timeout=timeout or self.timeout).stdout.strip()

    def forward(self, port: int) -> None:
        subprocess.run([self.adb, "-s", self.serial, "forward", f"tcp:{port}", f"tcp:{port}"],
                       check=True, stdout=subprocess.DEVNULL)

    def unforward(self, port: int) -> None:
        subprocess.run([self.adb, "-s", self.serial, "forward", f"--remove", f"tcp:{port}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def health(port: int, seconds: float = 2) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=seconds) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def start_watchdog(device: Device, base: str, model: str, gpu_layers: int, port: int,
                   ctx: int, threads: int) -> tuple[str, str, str]:
    pidfile, logfile, statefile = (f"{base}.{suffix}" for suffix in ("pid", "log", "state"))
    readyfile, stopfile = f"{base}.ready", f"{base}.stop"
    watchdogfile = f"{base}.watchdog.sh"
    server = " ".join(map(shlex.quote, [
        "llama-server", "--model", model, "--host", "127.0.0.1", "--port", str(port),
        "--ctx-size", str(ctx), "--threads", str(threads), "--threads-batch", str(threads),
        "--n-gpu-layers", str(gpu_layers), "--parallel", "1", "--no-webui",
    ]))
    watchdog = f'''#!/system/bin/sh
echo STARTING > {shlex.quote(statefile)}
{server} > {shlex.quote(logfile)} 2>&1 &
server_pid=$!
echo "$server_pid" > {shlex.quote(pidfile)}
echo RUNNING > {shlex.quote(statefile)}
failures=0
while kill -0 "$server_pid" 2>/dev/null; do
  if [ -e {shlex.quote(stopfile)} ]; then
    echo STOPPED > {shlex.quote(statefile)}
    kill "$server_pid" 2>/dev/null
    exit 0
  fi
  if [ -e {shlex.quote(readyfile)} ]; then
    if python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:{port}/health", timeout=2).read()' >/dev/null 2>&1; then
      failures=0
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
  sleep 2
done
if [ ! -e {shlex.quote(stopfile)} ]; then
  echo CRASHED > {shlex.quote(statefile)}
  date -u '+%Y-%m-%dT%H:%M:%SZ server exited unexpectedly' >> {shlex.quote(base + '.watchdog')}
fi
'''
    command = (f"rm -f {shlex.quote(pidfile)} {shlex.quote(statefile)} {shlex.quote(readyfile)} {shlex.quote(stopfile)}\n"
               f"cat > {shlex.quote(watchdogfile)} <<'WATCHDOG_SCRIPT'\n{watchdog}WATCHDOG_SCRIPT\n"
               f"chmod 700 {shlex.quote(watchdogfile)}\n"
               f"nohup /system/bin/sh {shlex.quote(watchdogfile)} > {shlex.quote(base + '.watchdog-launch')} 2>&1 </dev/null &\n")
    device.shell(command)
    return pidfile, logfile, statefile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial", required=True, help="ADB serial for the Android phone")
    ap.add_argument("--package", default="com.termux")
    ap.add_argument("--home", default="/data/data/com.termux/files/home/brianreborn/familia-note9-0.5.0")
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
    args = ap.parse_args()
    if args.ctx < 1:
        ap.error("--ctx must be a positive documented context size")

    device = Device(args.adb, args.serial, args.package, args.home, args.termux_home, args.prefix, args.startup_timeout)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trial_dir = f"{args.home}/trials/{run_id}"
    device.shell(f"mkdir -p {shlex.quote(trial_dir)}")
    journal = Path(f"android-model-trials-{args.serial}-{run_id}.jsonl")

    def event(**fields: object) -> None:
        row = {"time": stamp(), "serial": args.serial, **fields}
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        print(json.dumps(row, sort_keys=True), flush=True)

    model = f"{args.home}/{args.model}"
    device.shell(f"test -r {shlex.quote(model)} && command -v llama-server")
    devices = device.shell("llama-server --list-devices 2>&1 || true")
    meminfo = device.shell("grep -E 'MemTotal|MemAvailable' /proc/meminfo")
    device.forward(args.port)
    event(event="trial-set-start", model=model, context=args.ctx, threads=args.threads,
          backend_devices=devices, memory=meminfo, watchdog=f"{trial_dir}/watchdog.sh", journal=str(journal))

    configs = [("cpu", 0), ("vulkan", 99)]
    results: list[tuple[float, str, int]] = []
    failed = False
    try:
        for label, gpu_layers in configs:
            base = f"{trial_dir}/{label}"
            pidfile, logfile, statefile = start_watchdog(device, base, model, gpu_layers,
                                                         args.port, args.ctx, args.threads)
            readyfile = f"{base}.ready"
            event(event="trial-start", config=label, gpu_layers=gpu_layers,
                  memory=device.shell("grep -E 'MemTotal|MemAvailable' /proc/meminfo"), watchdog_state=statefile)
            deadline = time.monotonic() + args.startup_timeout
            ready = False
            while time.monotonic() < deadline:
                state = device.shell(f"cat {shlex.quote(statefile)} 2>/dev/null || echo MISSING")
                if state == "CRASHED":
                    break
                if health(args.port):
                    ready = True
                    break
                time.sleep(2)
            if not ready:
                log_tail = device.shell(f"tail -n 30 {shlex.quote(logfile)} 2>/dev/null || true")
                event(event="trial-failed", config=label, reason="server failed health check",
                      watchdog_state=state, log_tail=log_tail[-3000:])
                failed = True
                device.shell(f"touch {shlex.quote(base+'.stop')}; kill $(cat {shlex.quote(pidfile)}) 2>/dev/null || true")
                continue

            device.shell(f"touch {shlex.quote(readyfile)}")

            payload = json.dumps({"prompt": "Write a Python function that returns the factorial of n and rejects negative input.",
                                  "n_predict": 48, "temperature": 0, "stream": False}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{args.port}/completion", data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            started = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=args.request_timeout) as response:
                    answer = json.loads(response.read())
                elapsed = time.monotonic() - started
                rate = float(answer.get("timings", {}).get("predicted_per_second", 0.0))
                state = device.shell(f"cat {shlex.quote(statefile)} 2>/dev/null || echo MISSING")
                if state != "RUNNING" or not health(args.port):
                    raise RuntimeError(f"watchdog state after request: {state}")
                results.append((rate, label, gpu_layers))
                event(event="trial-ok", config=label, seconds=round(elapsed, 2), tokens_per_second=rate,
                      response=answer.get("content", "")[:1200], watchdog_state=state)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                event(event="trial-failed", config=label, reason=str(exc))
                failed = True
            finally:
                device.shell(f"touch {shlex.quote(base+'.stop')}; kill $(cat {shlex.quote(pidfile)}) 2>/dev/null || true")
                time.sleep(2)

        if args.keep_best and results:
            rate, label, gpu_layers = max(results)
            base = f"{trial_dir}/final"
            pidfile, logfile, statefile = (f"{base}.{suffix}" for suffix in ("pid", "log", "state"))
            readyfile = f"{base}.ready"
            start_watchdog(device, base, model, gpu_layers, args.port, args.ctx, args.threads)
            deadline = time.monotonic() + args.startup_timeout
            while time.monotonic() < deadline and not health(args.port):
                time.sleep(2)
            if health(args.port):
                device.shell(f"touch {shlex.quote(readyfile)}")
                event(event="final-running", config=label, gpu_layers=gpu_layers, tokens_per_second=rate,
                      watchdog_state=statefile, watchdog_log=f"{base}.watchdog", server_log=logfile)
            else:
                event(event="final-start-failed", config=label, gpu_layers=gpu_layers)
                failed = True
    finally:
        device.unforward(args.port)
    event(event="trial-set-finished", status="partial" if failed else "complete", journal=str(journal))
    return 1 if failed and not results else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"android-model-trials: {error}", file=sys.stderr)
        raise SystemExit(2)
