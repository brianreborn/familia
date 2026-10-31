"""Private per-user runtime dir + safe pid/lock files (race-tmp sunset, t835u).

runtime_dir(): $XDG_RUNTIME_DIR/familia when XDG is ours+0700, else
${XDG_CACHE_HOME:-$HOME/.cache}/familia/run, else ${TMPDIR:-$PREFIX/tmp:-/tmp}/familia-<uid>,
all created with umask 077. Every dir is
lstat-verified (not a symlink, owner==uid, no group/other bits); otherwise
RuntimeDirError (fail-closed). Old /tmp paths are never followed.
"""
import errno, fcntl, logging, os, stat, tempfile

log = logging.getLogger("familia.runtime_dir")
if not log.handlers and not logging.getLogger().handlers:
    _h = logging.StreamHandler(); _h.setFormatter(logging.Formatter("%(message)s")); log.addHandler(_h)

APP = "familia"


class RuntimeDirError(OSError):
    pass


def check_private_dir(path):
    """Return path if it is a real dir owned by us with mode 0700-ish; else raise."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise RuntimeDirError(errno.ENOENT, "missing", path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise RuntimeDirError(errno.ELOOP, "not a real directory (symlink?)", path)
    if st.st_uid != os.getuid():
        raise RuntimeDirError(errno.EPERM, "foreign owner uid=%d" % st.st_uid, path)
    if st.st_mode & 0o077:
        raise RuntimeDirError(errno.EPERM, "group/other bits set %o" % (st.st_mode & 0o777), path)
    return path


def _ensure_private(path):
    old = os.umask(0o077)
    try:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
    finally:
        os.umask(old)
    return check_private_dir(path)


def _tmp_base():
    if os.environ.get("TMPDIR"):
        return os.environ["TMPDIR"]
    pre = os.environ.get("PREFIX")  # Termux
    if pre and os.path.isdir(os.path.join(pre, "tmp")):
        return os.path.join(pre, "tmp")
    return "/tmp"


def _cache_run(env):
    """${XDG_CACHE_HOME:-$HOME/.cache}/familia/run, or None if no home is known."""
    c = env.get("XDG_CACHE_HOME")
    if not c:
        h = env.get("HOME")
        if not h:
            return None
        c = os.path.join(h, ".cache")
    return os.path.join(c, APP, "run")


def _ensure_private_tree(path):
    """mkdir -p with 0700 for our own new components; leaf gets the full check."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        old = os.umask(0o077)
        try:
            os.makedirs(parent, 0o700, exist_ok=True)
        finally:
            os.umask(old)
    return _ensure_private(path)


def runtime_dir(env=None):
    """Order (aligned with b041fb8): $XDG_RUNTIME_DIR/familia if XDG is ours+0700,
    else ${XDG_CACHE_HOME:-$HOME/.cache}/familia/run (0700), only then
    ${TMPDIR:-/tmp}/familia-<uid>. Each rejection is logged with its reason."""
    env = os.environ if env is None else env
    xdg = env.get("XDG_RUNTIME_DIR")
    if xdg:
        try:
            check_private_dir(xdg)
            return _ensure_private(os.path.join(xdg, APP))
        except (RuntimeDirError, OSError) as e:
            log.warning("runtime_dir: reject XDG_RUNTIME_DIR candidate: %s", e)
    cache = _cache_run(env)
    if cache:
        try:
            return _ensure_private_tree(cache)
        except (RuntimeDirError, OSError) as e:
            log.warning("runtime_dir: reject cache candidate: %s", e)
    # Last resort: predictable per-uid name; verified, never followed (fail-closed).
    cand = os.path.join(_tmp_base(), "%s-%d" % (APP, os.getuid()))
    try:
        return _ensure_private(cand)
    except RuntimeDirError as e:
        log.error("runtime_dir: reject tmp candidate: %s", e)
        raise


def open_excl(path, mode=0o600):
    """O_CREAT|O_EXCL|O_NOFOLLOW create; raises FileExistsError if it exists."""
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), mode)


def open_lock(path):
    """Open (create if absent) a lock file without following symlinks; caller flocks the fd."""
    check_private_dir(os.path.dirname(path) or ".")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        os.close(fd)
        raise RuntimeDirError(errno.EPERM, "lock not our regular file", path)
    return fd


def _cmdline(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return None


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_pidfile(path, match, pid=None, cmdline=_cmdline, alive=_alive):
    """Write our pid to *path* under flock(path+'.lock'). Steal only a stale pid
    (dead, or alive but cmdline lacks *match*). Returns (ok, why)."""
    pid = os.getpid() if pid is None else pid
    lk = open_lock(path + ".lock")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            fd = open_excl(path)
        except FileExistsError:
            try:
                fd0 = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError as e:
                return False, "unreadable pidfile: %s" % e
            try:
                old = int((os.read(fd0, 32) or b"0").split()[0])
            except (ValueError, IndexError):
                old = 0
            finally:
                os.close(fd0)
            if old > 0 and alive(old):
                cl = cmdline(old)
                if cl is None or match in cl:
                    return False, "held by live pid %d" % old
            os.unlink(path)  # stale, and we hold the lock
            fd = open_excl(path)
        try:
            os.write(fd, b"%d\n" % pid)
        finally:
            os.close(fd)
        return True, "ok"
    finally:
        os.close(lk)


def safe_unlink_socket(path):
    """Unlink a stale socket only if it lives in our private dir and is our socket."""
    check_private_dir(os.path.dirname(path))
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return True
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
        return False
    os.unlink(path)
    return True


if __name__ == "__main__":
    try:
        print(runtime_dir())
    except RuntimeDirError as e:
        import sys
        print("runtime_dir: refuse: %s" % e, file=sys.stderr)
        sys.exit(1)
