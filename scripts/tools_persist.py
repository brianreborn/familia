#!/usr/bin/env python3
"""Keep llama-server --tools across restart (#630).

llama.cpp reads --tools only at process start. Two launch paths used to drop it:

* familia-start applied --tools only from the current argv or FAMILIA_EXTRA.
  A crash restart (systemd Restart=on-failure) or a later hand-start omitted
  the flag, so Server Tools came back disabled.
* start.sh prefers generated/graph-HOST.yaml. A stale copy that dropped
  server_tools launched without the flag even though graph.yaml still had it.

This module saves a familia-start --tools value (mode 0600) and copies a
missing server_tools key from the fleet graph onto a generated graph.
An explicit key on the graph being launched, including an opt-out, wins.
A non-loopback bind never receives --tools.
"""
import os
import stat
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OPT_OUT = {"", "none", "off", "false", "0"}
_TOOLS_RE_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_,-")


def _loopback(bind):
    """Same rule as validate_graph._loopback. Inlined so a copied launcher
    script does not need the rest of the graph package."""
    import ipaddress
    b = str(bind or "").strip()
    if b.lower() == "localhost":
        return True
    if b.startswith("[") and b.endswith("]"):
        b = b[1:-1]
    try:
        ip = ipaddress.ip_address(b)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


def _config_base(env):
    env = env if env is not None else os.environ
    if os.name == "nt":
        base = env.get("APPDATA") or os.path.expanduser("~")
    else:
        base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "familia", "server-tools")


def state_path(port, env=None):
    return os.path.join(_config_base(env), str(port))


def _check_port(port):
    try:
        n = int(port)
    except (TypeError, ValueError):
        _refuse("port must be an integer")
    if n < 1 or n > 65535:
        _refuse("port out of range")
    return str(n)


def _tools_ok(value):
    if not value or not all(c in _TOOLS_RE_OK for c in value):
        return False
    if value.startswith(",") or value.endswith(",") or ",," in value:
        return False
    return True


def _refuse(msg):
    print("familia-start: " + msg, file=sys.stderr)
    raise SystemExit(2)


def _read_saved(port, env):
    """Return the saved tools token, 'none' for an opt-out, or None if unset.
    A symlink, a non-0600/0400 mode, or a file owned by someone else is refused.
    """
    path = state_path(port, env)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        _refuse("saved --tools file %s is a symlink; refusing" % path)
    if not stat.S_ISREG(st.st_mode):
        _refuse("saved --tools file %s is not a regular file; refusing" % path)
    if stat.S_IMODE(st.st_mode) & 0o077:
        _refuse("saved --tools file %s must be mode 0600; refusing" % path)
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        _refuse("saved --tools file %s is not owned by you; refusing" % path)
    try:
        raw = open(path, "r", encoding="ascii").read()
    except UnicodeError:
        _refuse("saved --tools file %s is not ASCII; refusing" % path)
    text = raw.strip()
    if text == "none":
        return "none"
    if not _tools_ok(text):
        _refuse("saved --tools file %s has an invalid value; refusing" % path)
    return text


def _write_saved(port, token, env):
    """Atomically write the tools token. token is 'none' or a tools list."""
    if token != "none" and not _tools_ok(token):
        _refuse("--tools value %r is not a tool name list; refusing" % token)
    parent = _config_base(env)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    # The directory holds only these records. Tighten it; do not follow a link.
    if os.path.islink(parent):
        _refuse("saved --tools directory %s is a symlink; refusing" % parent)
    os.chmod(parent, 0o700)
    path = state_path(port, env)
    if os.path.lexists(path) and os.path.islink(path):
        _refuse("saved --tools file %s is a symlink; refusing" % path)
    fd, tmp = tempfile.mkstemp(prefix=".tools-", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (token + "\n").encode("ascii"))
        os.close(fd)
        fd = None
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def split_tools(args):
    """Return (saw, value, args_without_tools). The last --tools wins."""
    saw = False
    value = ""
    out = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--tools":
            saw = True
            if i + 1 < len(args) and not str(args[i + 1]).startswith("-"):
                value = str(args[i + 1])
                i += 2
            else:
                value = ""
                i += 1
            continue
        if a.startswith("--tools="):
            saw = True
            value = a.split("=", 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1
    return saw, value, out


def decide(bind, port, args, env=None):
    """Return ('keep', ''), ('clear', ''), or ('append', token).

    A --tools token on this launch is saved. '--tools none' (also off/false/0)
    clears the save; the caller must drop the token so llama-server never sees
    it. When this launch omits --tools, ('append', token) asks the caller to
    add the saved value. Tools on a non-loopback bind are refused.
    """
    env = os.environ if env is None else env
    port = _check_port(port)
    saw, value, _rest = split_tools(list(args))
    if saw:
        if value.strip().lower() in _OPT_OUT:
            _write_saved(port, "none", env)
            return "clear", ""
        token = value.strip()
        if not _loopback(bind):
            _refuse("--tools (host-exec) is allowed only on a loopback bind; refusing")
        _write_saved(port, token, env)
        return "keep", ""
    saved = _read_saved(port, env)
    if saved and saved != "none":
        if not _loopback(bind):
            _refuse("--tools (host-exec) is allowed only on a loopback bind; refusing")
        return "append", saved
    return "keep", ""


def apply_args(bind, port, args, env=None):
    """Argv after decide(), for tests and other Python callers."""
    action, token = decide(bind, port, args, env=env)
    if action == "clear":
        _saw, _value, rest = split_tools(list(args))
        return rest
    if action == "append":
        return list(args) + ["--tools", token]
    return list(args)


def _generated_dir():
    env = os.environ.get("FAMILIA_GENERATED_DIR")
    if env and env.strip():
        return os.path.realpath(os.path.expanduser(env.strip()))
    return os.path.realpath(os.path.join(ROOT, "generated"))


def _is_generated_graph(path):
    if not path:
        return False
    try:
        gen = _generated_dir()
        p = os.path.realpath(path)
    except OSError:
        return False
    return p == gen or p.startswith(gen + os.sep)


def _role(graph, name, node):
    explicit = node.get("role")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    import node_role
    return node_role.infer_role(name, node, graph)


def _same_tools(values):
    norm = []
    for v in values:
        if isinstance(v, list):
            norm.append(tuple(v))
        else:
            norm.append(v)
    return len(set(norm)) == 1


def fleet_server_tools(name, node, gen_graph, fleet):
    """The server_tools value from the fleet node that matches host+role,
    or None when there is no match or the matches disagree."""
    host = node.get("host")
    try:
        role = _role(gen_graph, name, node)
    except Exception:
        return None
    matches = []
    for fname, fnode in (fleet.get("nodes") or {}).items():
        if not isinstance(fnode, dict) or "server_tools" not in fnode:
            continue
        if host and fnode.get("host") != host:
            continue
        try:
            frole = _role(fleet, fname, fnode)
        except Exception:
            continue
        if frole != role:
            continue
        matches.append(fnode)
    if not matches:
        return None
    port = node.get("port")
    same_port = [m for m in matches if port is not None and m.get("port") == port]
    use = same_port or matches
    values = [m.get("server_tools") for m in use]
    if not _same_tools(values):
        return None
    return values[0]


def _load_fleet(path):
    import familia_yaml
    return familia_yaml.load(path) or {}


def restore_server_tools(graph, fleet=None, fleet_path=None):
    """Copy server_tools from the fleet graph onto generated-graph nodes that
    dropped the key. An explicit key, including an opt-out, is left alone.
    Returns how many nodes were restored. A graph that is not under the
    generated directory is unchanged.
    """
    path = graph.get("_path") or ""
    if not _is_generated_graph(path):
        return 0
    if fleet is None:
        fleet_path = fleet_path or os.environ.get("FAMILIA_FLEET_GRAPH") or os.path.join(ROOT, "graph.yaml")
        if not fleet_path or not os.path.isfile(fleet_path):
            return 0
        fleet = _load_fleet(fleet_path)
    restored = 0
    for name, node in (graph.get("nodes") or {}).items():
        if not isinstance(node, dict) or "server_tools" in node:
            continue
        value = fleet_server_tools(name, node, graph, fleet)
        if value is None:
            continue
        node["server_tools"] = value
        restored += 1
    return restored


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: tools_persist.py decide --bind BIND --port PORT -- [args...]")
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    if argv[0] != "decide":
        print("tools-persist: unknown command %r" % argv[0], file=sys.stderr)
        return 2
    bind = None
    port = None
    rest = argv[1:]
    args = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            args = rest[i + 1:]
            break
        if a in ("--bind", "--port"):
            if i + 1 >= len(rest):
                print("tools-persist: %s needs a value" % a, file=sys.stderr)
                return 2
            if a == "--bind":
                bind = rest[i + 1]
            else:
                port = rest[i + 1]
            i += 2
            continue
        print("tools-persist: unknown argument %r" % a, file=sys.stderr)
        return 2
    if bind is None or port is None:
        print("tools-persist: rewrite needs --bind and --port", file=sys.stderr)
        return 2
    try:
        action, token = decide(bind, port, args)
    except SystemExit as e:
        code = e.code
        return code if isinstance(code, int) else 2
    if action == "append":
        print("append " + token)
    elif action == "clear":
        print("clear")
    else:
        print("keep")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
