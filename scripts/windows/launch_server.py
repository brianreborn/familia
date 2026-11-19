#!/usr/bin/env python3
"""Start llama-server and record its pid.

start.bat calls this after the license gate and the auth guard. The pid file
is the server process, written as soon as that process exists, before model
load finishes. FAMILIA_PIDFILE is optional. No key material is printed.

argv: BIN MODEL HOST PORT CTX THREADS KV LOG KEYFILE [extra...]
"""
import os
import subprocess
import sys


def main(argv):
    if len(argv) < 10:
        sys.stderr.write("launch_server.py: need bin, model, host, port, ctx, threads, kv, log, keyfile\n")
        return 2
    binary, model, host, port, ctx, threads, kv, log_path, keyfile = argv[1:10]
    extra = [item for item in argv[10:] if item]
    args = [
        binary, "-m", model, "--host", host, "--port", port,
        "-c", ctx, "-t", threads, "-np", "1",
        "-ctk", kv, "-ctv", kv, "--api-key-file", keyfile,
        *extra,
    ]
    try:
        log = open(log_path, "ab")
    except OSError as exc:
        sys.stderr.write("launch_server.py: cannot open log: %s\n" % exc)
        return 1
    try:
        proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    except OSError as exc:
        sys.stderr.write("launch_server.py: cannot start server: %s\n" % exc)
        return 1
    pidfile = os.environ.get("FAMILIA_PIDFILE") or ""
    if pidfile:
        stage = pidfile + ".tmp"
        try:
            with open(stage, "w", encoding="ascii") as fh:
                fh.write("%s\n" % proc.pid)
            os.replace(stage, pidfile)
        except OSError as exc:
            sys.stderr.write("launch_server.py: pid file not written: %s\n" % exc)
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
