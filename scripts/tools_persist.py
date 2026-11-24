#!/usr/bin/env python3
"""Keep llama-server --tools across restart (#630).

llama.cpp reads --tools only at process start. Two launch paths used to drop it:

* familia-start applied --tools only from the current argv or FAMILIA_EXTRA.
  A crash restart (systemd Restart=on-failure) or a later hand-start omitted
  the flag, so Server Tools came back disabled.
* start.sh prefers generated/graph-HOST.yaml. A stale copy that dropped
  server_tools launched without the flag even though graph.yaml still had it.

familia-start saves a capped tool list (mode 0600) and reapplies it when a
later start omits the flag. The saved list is never `all` and never a shell
or write tool: those stay an explicit CLI grant for that one launch. A file
that contains `all`, an unknown name, or garbage is refused (exit 2).

The shell hook lives in the Linux, Termux, FreeBSD, and unix installers.
Windows start.bat does not call this module (launcher_persists_tools is
false there). The writer itself still avoids Unix-only calls on Windows:
no fchmod, no directory fsync, and os.replace is retried when the dest is
in use.

A non-matching bind never receives --tools. The bind allowlist is the same
as familia_tools_check: 127.0.0.1, ::1, and localhost.
"""
import errno
import os
import stat
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OPT_OUT = {"", "none", "off", "false", "0"}
# Same names as graph_types.SERVER_TOOL_NAMES. Duplicated so a copied
# familia-start script does not import the graph package.
KNOWN_TOOLS = (
    "read_file", "file_glob_search", "grep_search",
    "exec_shell_command", "write_file", "edit_file", "get_info",
)
# Same list as validate_graph.READ_ONLY_TOOLS (H4). familia-start never
# persists a wider grant.
READ_ONLY_TOOLS = ("read_file", "file_glob_search", "grep_search", "get_info")
_KNOWN = set(KNOWN_TOOLS)
_READ_ONLY = set(READ_ONLY_TOOLS)
_LAUNCHER_BINDS = {"127.0.0.1", "::1", "localhost"}


def launcher_persists_tools():
    """Unix familia-start calls decide. Windows start.bat skips this hook."""
    return os.name != "nt"


def _launcher_bind(bind):
    """familia_tools_check allowlist. [::1] is normalized to ::1 first."""
    b = str(bind or "").strip()
    if b == "[::1]":
        b = "::1"
    return b in _LAUNCHER_BINDS


def _config_base(env):
    env = env if env is not None else os.environ
    if os.name == "nt":
        base = env.get("APPDATA") or os.path.expanduser("~")
    else:
        base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "familia", "server-tools")


def _familia_dir(env):
    return os.path.dirname(_config_base(env))


def state_path(port, env=None):
    return os.path.join(_config_base(env), str(port))


def lock_path(env=None):
    return os.path.join(_config_base(env), ".lock")


def _check_port(port):
    try:
        n = int(port)
    except (TypeError, ValueError):
        _refuse("port must be an integer")
    if n < 1 or n > 65535:
        _refuse("port out of range")
    return str(n)


def _refuse(msg):
    print("familia-start: " + msg, file=sys.stderr)
    raise SystemExit(2)


def _tool_names(token):
    return [p.strip() for p in str(token).split(",") if p.strip()]


def _tools_ok(value):
    """True for a comma list of known tool names. Rejects all and unknowns."""
    if not value or value.strip().lower() == "all":
        return False
    names = _tool_names(value)
    if not names:
        return False
    for name in names:
        if name == "all" or name not in _KNOWN:
            return False
        if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in name):
            return False
    return True


def _cap_read_only(token):
    """Names from token that familia-start may persist. `all` becomes the
    read-only list. Unknown names are refused. Write/shell names are dropped."""
    if str(token).strip() == "all":
        return list(READ_ONLY_TOOLS)
    if not _tools_ok(token):
        _refuse("saved --tools value %r is not a known tool list; refusing" % token)
    return [n for n in _tool_names(token) if n in _READ_ONLY]


def _is_opt_out(value):
    if value is False:
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    if isinstance(value, str) and value.strip().lower() in _OPT_OUT:
        return True
    return False


def _ordered_names(value):
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        return [p for p in value.split(",") if p]
    return []


def narrow_server_tools(current, fleet):
    """Grant no wider than the fleet policy. A present opt-out stays.
    `all` on a generated node is stale when the fleet list is narrower."""
    if _is_opt_out(current):
        return current
    if current is None:
        return fleet
    if fleet is None or _is_opt_out(fleet):
        if current == "all":
            return list(READ_ONLY_TOOLS)
        if _is_opt_out(fleet):
            return []
        return current
    if current == "all":
        if fleet == "all":
            return "all"
        return _ordered_names(fleet)
    if fleet == "all":
        return current
    allowed = set(_ordered_names(fleet))
    return [n for n in _ordered_names(current) if n in allowed]


def _same_grant(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return a == b
    return a == b


def _open_nofollow(path, flags, mode=None):
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        if mode is None:
            return os.open(path, flags)
        return os.open(path, flags, mode)
    except OSError as e:
        err = getattr(e, "errno", None)
        if err == errno.ENOENT:
            return None
        if err in (errno.ELOOP, getattr(errno, "EPERM", None)):
            return "symlink"
        raise


def _check_dir(path):
    """Owner is the caller, not a symlink, and not group or world writable."""
    if os.path.islink(path):
        _refuse("%s is a symlink; refusing" % path)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = _open_nofollow(path, flags)
    if fd == "symlink" or fd is None:
        _refuse("%s is a symlink; refusing" % path)
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            _refuse("%s is not a directory; refusing" % path)
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            _refuse("%s is not owned by you; refusing" % path)
        if os.name != "nt" and stat.S_IMODE(st.st_mode) & 0o022:
            _refuse("%s is group or world writable; refusing" % path)
    finally:
        os.close(fd)


def _ensure_tree(env):
    """Create familia/ and server-tools/ without following a planted symlink."""
    familia = _familia_dir(env)
    tools = _config_base(env)
    parent = os.path.dirname(familia)
    if parent and not os.path.isdir(parent) and not os.path.islink(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    if os.path.islink(parent):
        _refuse("%s is a symlink; refusing" % parent)
    for path in (familia, tools):
        if os.path.islink(path):
            _refuse("%s is a symlink; refusing" % path)
        if not os.path.exists(path):
            os.mkdir(path, 0o700)
        _check_dir(path)
    if os.name != "nt":
        os.chmod(tools, 0o700)
    return tools


class _Lock(object):
    def __init__(self, fd, kind):
        self.fd = fd
        self.kind = kind

    def release(self):
        fd = self.fd
        if fd is None:
            return
        self.fd = None
        try:
            if self.kind == "flock":
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif self.kind == "msvcrt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def _lock_windows(fd):
    import msvcrt
    if os.fstat(fd).st_size < 1:
        os.lseek(fd, 0, os.SEEK_SET)
        _write_all(fd, b"\0")
        os.fsync(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    last = None
    for _ in range(40):
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError as e:
            last = e
            time.sleep(0.01)
    _refuse("could not lock saved --tools (%s)" % last)


def _acquire_lock(env):
    tools = _ensure_tree(env)
    path = os.path.join(tools, ".lock")
    flags = os.O_RDWR | os.O_CREAT
    fd = _open_nofollow(path, flags, 0o600)
    if fd == "symlink":
        _refuse("saved --tools lock %s is a symlink; refusing" % path)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            _refuse("saved --tools lock %s is not a regular file; refusing" % path)
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            _refuse("saved --tools lock %s is not owned by you; refusing" % path)
        if os.name == "nt":
            _lock_windows(fd)
            kind = "msvcrt"
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            kind = "flock"
    except BaseException:
        os.close(fd)
        raise
    return _Lock(fd, kind)


def _write_all(fd, data):
    view = memoryview(data)
    while len(view):
        n = os.write(fd, view)
        if not n or n < 0:
            _refuse("short write saving --tools")
        view = view[n:]


def _fchmod(fd, path, mode):
    if hasattr(os, "fchmod"):
        os.fchmod(fd, mode)
    else:
        os.chmod(path, mode)


def _replace(src, dst):
    tries = 20 if os.name == "nt" else 1
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i + 1 == tries:
                _refuse("could not replace saved --tools file %s" % dst)
            time.sleep(0.05)


def _fsync_dir(parent):
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = _open_nofollow(parent, flags)
    if fd == "symlink" or fd is None:
        _refuse("%s is a symlink; refusing" % parent)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_saved(port, env):
    """Return the saved token, 'none' for an opt-out, or None if unset.

    Opened with O_NOFOLLOW. The fd is fstat'd: regular file, not
    group/world writable, owned by the caller. The parent directories
    were checked by _ensure_tree before this runs.
    """
    path = state_path(port, env)
    flags = os.O_RDONLY
    fd = _open_nofollow(path, flags)
    if fd == "symlink":
        _refuse("saved --tools file %s is a symlink; refusing" % path)
    if fd is None:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            _refuse("saved --tools file %s is not a regular file; refusing" % path)
        if os.name != "nt" and stat.S_IMODE(st.st_mode) & 0o077:
            _refuse("saved --tools file %s must be mode 0600; refusing" % path)
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            _refuse("saved --tools file %s is not owned by you; refusing" % path)
        chunks = []
        total = 0
        while total < 4096:
            part = os.read(fd, 4096 - total)
            if not part:
                break
            chunks.append(part)
            total += len(part)
        if total >= 4096:
            _refuse("saved --tools file %s is too large; refusing" % path)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        text = data.decode("ascii").strip()
    except UnicodeError:
        _refuse("saved --tools file %s is not ASCII; refusing" % path)
    if text == "":
        _refuse("saved --tools file %s is empty; refusing" % path)
    if text == "none":
        return "none"
    if not _tools_ok(text):
        _refuse("saved --tools file %s has an invalid value; refusing" % path)
    return text


def _write_saved(port, token, env):
    """Atomically write the tools token. token is 'none' or a tool list."""
    if token != "none" and not _tools_ok(token):
        _refuse("--tools value %r is not a tool name list; refusing" % token)
    parent = _ensure_tree(env)
    path = state_path(port, env)
    if os.path.lexists(path) and os.path.islink(path):
        _refuse("saved --tools file %s is a symlink; refusing" % path)
    fd, tmp = tempfile.mkstemp(prefix=".tools-", dir=parent)
    try:
        _fchmod(fd, tmp, 0o600)
        _write_all(fd, (token + "\n").encode("ascii"))
        os.fsync(fd)
        os.close(fd)
        fd = None
        _replace(tmp, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
        _fsync_dir(parent)
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


def _decide_locked(bind, port, saw, value, env):
    if saw:
        if value.strip().lower() in _OPT_OUT:
            _write_saved(port, "none", env)
            return "clear", ""
        if not _launcher_bind(bind):
            _refuse("--tools (host-exec) is allowed only on a loopback bind; refusing")
        capped = _cap_read_only(value)
        _write_saved(port, ",".join(capped) if capped else "none", env)
        return "keep", ""
    # Re-read while the lock is held so a concurrent writer cannot change
    # the file between the stat and the value we return.
    saved = _read_saved(port, env)
    if not saved or saved == "none":
        return "keep", ""
    capped = _cap_read_only(saved)
    if not capped:
        return "keep", ""
    if not _launcher_bind(bind):
        _refuse("--tools (host-exec) is allowed only on a loopback bind; refusing")
    return "append", ",".join(capped)


def decide(bind, port, args, env=None):
    """Return ('keep', ''), ('clear', ''), or ('append', token).

    Held under the persist lock for the whole read or write. A --tools
    token on this launch is saved, capped to READ_ONLY_TOOLS. '--tools none'
    clears the save. When this launch omits --tools, the saved list is
    re-read under the lock and appended if it is still allowed.
    """
    env = os.environ if env is None else env
    port = _check_port(port)
    saw, value, _rest = split_tools(list(args))
    lock = _acquire_lock(env)
    try:
        return _decide_locked(bind, port, saw, value, env)
    finally:
        lock.release()


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
    if not all(_same_grant(values[0], v) for v in values[1:]):
        return None
    return values[0]


def _load_fleet(path):
    import familia_yaml
    return familia_yaml.load(path) or {}


def restore_server_tools(graph, fleet=None, fleet_path=None):
    """Copy or narrow server_tools from the fleet graph onto a generated graph.

    A missing key is filled from the fleet node. A present opt-out stays.
    A present grant wider than the fleet policy, including a stale `all`
    against a tighter fleet list, is narrowed. Returns how many nodes changed.
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
        if not isinstance(node, dict):
            continue
        fleet_value = fleet_server_tools(name, node, graph, fleet)
        if "server_tools" not in node:
            if fleet_value is None:
                continue
            node["server_tools"] = fleet_value
            restored += 1
            continue
        narrowed = narrow_server_tools(node.get("server_tools"), fleet_value)
        if not _same_grant(narrowed, node.get("server_tools")):
            node["server_tools"] = narrowed
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
        print("tools-persist: decide needs --bind and --port", file=sys.stderr)
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
