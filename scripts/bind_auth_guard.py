#!/usr/bin/env python3
"""Refuse a llama-server (or similar) argv that would listen without an API key.

DESIGN.md Security / CFG-CRED-009: a service listening on the network must
require an API key. familia llama-server launches are not a localhost-without-key
exception: a key is required on every bind, loopback included, matching the
Linux/Termux/FreeBSD installer convention (F-10). The key is passed as
--api-key-file (mode 0600, never the key on argv).

Usage:
  python3 scripts/bind_auth_guard.py [--ensure] -- <argv>

Exit 0 if the argv is allowed, 2 if it is refused. --ensure creates a missing
--api-key-file once (0600, never rotated) via familia_auth.load_or_create_key_file.
"""
from __future__ import annotations

import os
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def parse_host_and_key(argv):
    """Return (host, key_file, api_key) from a llama-server-style argv. Last flag wins."""
    args = list(argv)
    if args and not str(args[0]).startswith("-"):
        args = args[1:]
    host = "127.0.0.1"
    key_file = None
    api_key = None
    i = 0
    while i < len(args):
        a = str(args[i])
        def take(cur):
            if i + 1 < len(args):
                return args[i + 1], i + 2
            return cur, i + 1
        if a == "--host":
            host, i = take(host)
            continue
        if a.startswith("--host="):
            host = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--api-key-file":
            key_file, i = take(key_file)
            continue
        if a.startswith("--api-key-file="):
            key_file = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--api-key":
            api_key, i = take(api_key)
            continue
        if a.startswith("--api-key="):
            api_key = a.split("=", 1)[1]
            i += 1
            continue
        i += 1
    if isinstance(host, str) and host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host, key_file, api_key


def _key_file_error(path):
    """Return a refusal reason, or None if the file is an acceptable 0600 key file."""
    import familia_auth
    if not path:
        return "no --api-key-file in argv"
    if os.path.islink(path):
        return "API key file %s is a symlink; refusing" % path
    if not os.path.exists(path):
        return "API key file %s missing" % path
    if not os.path.isfile(path):
        return "API key file %s is not a regular file" % path
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode != 0o600:
            return "API key file %s mode is %04o, need 0600" % (path, mode)
    if not familia_auth._read(path):
        return "API key file %s is empty or has no usable key" % path
    return None


def check(argv, ensure=False):
    """Validate argv. Return (ok: bool, message: str)."""
    import familia_auth
    host, key_file, api_key = parse_host_and_key(argv)
    if key_file and ensure:
        try:
            familia_auth.load_or_create_key_file(key_file)
        except OSError as e:
            return False, "cannot create API key file %s (%s)" % (key_file, e.__class__.__name__)
    if (api_key or "").strip():
        if key_file:
            err = _key_file_error(key_file)
            if err:
                return False, err
        return True, "ok"
    if not key_file:
        return False, (
            "API key required on every bind (loopback included); "
            "argv has no --api-key-file or --api-key (host %s)" % (host or "?")
        )
    err = _key_file_error(key_file)
    if err:
        return False, err
    return True, "ok"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure = False
    if argv[:1] == ["--ensure"]:
        ensure = True
        argv = argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    elif argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    ok, msg = check(argv, ensure=ensure)
    if ok:
        return 0
    print("familia-auth-guard: %s; refusing" % msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
