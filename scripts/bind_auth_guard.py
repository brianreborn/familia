#!/usr/bin/env python3
"""Refuse a llama-server (or similar) argv that would listen without an API key.

DESIGN.md Security / CFG-CRED-009: a service listening on the network must
require an API key. familia llama-server launches are not a localhost-without-key
exception: a key is required on every bind, loopback included, matching the
installer F-10 policy (a key on every bind). The key is passed as
--api-key-file. --api-key on argv is refused (it shows in ps).

There are two on-disk layouts and no migration yet (see GitHub issue #419).
Canonical for graph-launched nodes (serve.sh, start.bat, graph_router,
familia_auth's default path) is instances/<port>/api-keys. familia-start
uses ~/.config/familia/api.key. Clients accept API_KEY_FILE or
FAMILIA_API_KEY_FILE as an override.

The file must be a regular file (not a symlink), owner-readable, and not
group- or world-readable (0600 or 0400 are both accepted). Every
--api-key-file is checked. The contents must match what llama-server
b11969 (common/arg.cpp) would keep, without encodings that diverge:
no UTF-8 BOM, no CR/CRLF, no whitespace or comma in a key line, and at
least one line that does not start with # at column 0.

Usage:
  python3 scripts/bind_auth_guard.py [--ensure] -- <argv>

Exit 0 if the argv is allowed, 2 if it is refused. --ensure creates a missing
--api-key-file once (0600, never rotated) via familia_auth.load_or_create_key_file.

Tokens after --extra-start are treated as launcher extras (FAMILIA_EXTRA or
serve.sh extra args). --host/--port/--api-key*/--ssl*/--path there are refused
so they cannot override the launcher's bind, port, auth, TLS, or path.
"""
from __future__ import annotations

import os
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _strip_bin(argv):
    args = list(argv)
    if args and not str(args[0]).startswith("-"):
        args = args[1:]
    return args


def _flag_name_is(a, name):
    a = str(a)
    return a == name or a.startswith(name + "=")


def _is_extra_override(a):
    """True if an extra token would override bind, port, auth, TLS, or path."""
    a = str(a)
    if a == "--host" or a.startswith("--host="):
        return True
    if a == "--port" or a.startswith("--port="):
        return True
    if a == "--api-key" or a.startswith("--api-key"):
        return True
    if a == "--ssl" or a.startswith("--ssl"):
        return True
    if a == "--path" or a.startswith("--path="):
        return True
    return False


def parse_host_and_key(argv):
    """Return (host, key_file, api_key) from a llama-server-style argv.

    Host and api_key: last flag before --extra-start wins. key_file is the
    last --api-key-file before --extra-start (use parse_key_files for all).
    """
    args = _strip_bin(argv)
    host = "127.0.0.1"
    key_file = None
    api_key = None
    i = 0
    while i < len(args):
        a = str(args[i])
        if a == "--extra-start":
            break

        def take(cur):
            if i + 1 < len(args) and str(args[i + 1]) != "--extra-start":
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


def parse_key_files(argv):
    """Return every --api-key-file path before --extra-start, in order."""
    args = _strip_bin(argv)
    files = []
    i = 0
    while i < len(args):
        a = str(args[i])
        if a == "--extra-start":
            break
        if a == "--api-key-file":
            if i + 1 < len(args) and str(args[i + 1]) != "--extra-start":
                files.append(args[i + 1])
                i += 2
                continue
            files.append("")
            i += 1
            continue
        if a.startswith("--api-key-file="):
            files.append(a.split("=", 1)[1])
            i += 1
            continue
        i += 1
    return files


def _key_file_bytes_error(path, data):
    """Refuse encodings llama-server b11969 would accept differently."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "API key file %s has a UTF-8 BOM; refusing" % path
    if b"\r" in data:
        return "API key file %s contains CR / CRLF; use LF line endings" % path
    keys = 0
    for line in data.split(b"\n"):
        if line == b"":
            continue
        if line.startswith(b"#"):
            continue
        if b"," in line or any(c in line for c in b" \t\f\v"):
            return "API key file %s has a key line with whitespace or comma; refusing" % path
        keys += 1
    if keys < 1:
        return "API key file %s is empty or has no usable key" % path
    return None


def _key_file_error(path):
    """Return a refusal reason, or None if the file is an acceptable key file."""
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
        if mode & 0o077:
            return "API key file %s mode is %04o, must not be group- or world-readable" % (path, mode)
        if not (mode & 0o400):
            return "API key file %s mode is %04o, must be owner-readable" % (path, mode)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return "API key file %s is unreadable (%s)" % (path, e.__class__.__name__)
    return _key_file_bytes_error(path, data)


def check(argv, ensure=False):
    """Validate argv. Return (ok: bool, message: str)."""
    import familia_auth
    host, key_file, api_key = parse_host_and_key(argv)
    args = _strip_bin(argv)
    str_args = [str(a) for a in args]
    if "--extra-start" in str_args:
        extra = args[str_args.index("--extra-start") + 1:]
        main_args = args[:str_args.index("--extra-start")]
        for t in extra:
            if _is_extra_override(t):
                return False, (
                    "token %s after --extra-start would override bind/port/auth/TLS/path"
                    % t
                )
    else:
        main_args = args
    if any(_flag_name_is(a, "--api-key") for a in main_args):
        return False, (
            "--api-key puts the key on argv (visible in ps); use --api-key-file "
            "with a 0600 file instead"
        )
    key_files = parse_key_files(argv)
    if ensure:
        for path in key_files:
            if not path:
                continue
            try:
                familia_auth.load_or_create_key_file(path)
            except OSError as e:
                return False, "cannot create API key file %s (%s)" % (path, e.__class__.__name__)
    if not key_files:
        return False, (
            "API key required on every bind (loopback included); "
            "argv has no --api-key-file (host %s)" % (host or "?")
        )
    for path in key_files:
        err = _key_file_error(path)
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
