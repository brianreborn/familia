r"""One place to find and attach the API key of the local familia/llama-server instance.

Every client that talks to :9931 (or any gateway that requires a key) must call
auth_headers() / open_url() instead of building a bare urllib.Request. Requiring the key
on the server is not enough: every caller, including internal and recursive ones, must send it.

The canonical store on every platform (Linux, Termux/phone, FreeBSD, Windows) is the
per-instance file ${XDG_CONFIG_HOME:-~/.config}/familia/instances/<port>/api-keys
(%APPDATA%\\familia\\instances\\<port>\\api-keys on Windows), mode 0600. The port the
client calls picks the key. Search order between layouts does not (#419).

Lookup (first hit wins):
  1. FAMILIA_API_KEY            explicit override
  2. LLAMA_API_KEY              set by code-bootstraps serve.sh (comma list; first key used)
  3. API_KEY_FILE or FAMILIA_API_KEY_FILE  (either name; first set wins)
  4. instances/<port>/api-keys  port = the URL's port, else FAMILIA_PORT/PORT, else 9931
An explicit env override is not an ambiguity: it wins for that process.

~/.config/familia/api.key and legacy <bootstrap>/.secrets/api-keys are migration
sources only. On first start, ensure-instance / the launchers copy the first safe
source into the instance file and log a notice. They are not consulted at lookup.
There is no Termux-only order (PR #321's termux_api_key_file check is not part of this layout).

CLI:  python3 scripts/familia_auth.py curl-config -o FILE
                                                    -> writes 'header = "Authorization: Bearer ..."' to a NEW
                                                       0600 FILE for `curl -K FILE` (never to stdout; #177)
      python3 scripts/familia_auth.py fingerprint   -> safe-to-log HMAC-SHA256 key id
      python3 scripts/familia_auth.py ensure-instance -> copy a legacy key into instances/<port>/api-keys
                                                       or create that file (0600); the key stays off stdout
      python3 scripts/familia_auth.py has-key       -> exit 0 when a key is found
      python3 scripts/familia_auth.py probe [URL]   -> authenticated probe of the instance:
                                                       0 up, 3 nothing listening, 4 key rejected (401/403:
                                                       a misconfiguration, NEVER "no server"), 5 other error
"""
import hashlib
import hmac
import os
import secrets
import stat
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _first_key_in(text):
    # drop comment lines first: the bootstrap key file's header contains a comma
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        for part in line.split(","):
            if part.strip():
                return part.strip()
    return ""


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _first_key_in(f.read())
    except OSError:
        return ""


DEFAULT_PORT = 9931


def instance_port(env=None):
    env = os.environ if env is None else env
    return str(env.get("FAMILIA_PORT") or env.get("PORT") or DEFAULT_PORT)


def instance_key_file(port=None, env=None):
    """The one stable key file of the instance on <port>."""
    env = os.environ if env is None else env
    port = str(port or instance_port(env))
    if os.name == "nt":
        base = env.get("APPDATA") or os.path.expanduser("~")
    else:
        base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "familia", "instances", port, "api-keys")


def installer_key_file(env=None):
    """Legacy familia-start path (~/.config/familia/api.key). Migration source only (#419)."""
    env = os.environ if env is None else env
    if os.name == "nt":
        base = env.get("APPDATA") or os.path.expanduser("~")
    else:
        base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "familia", "api.key")


def migration_sources(root=ROOT, env=None):
    """Legacy files copied into the instance file on first start. Not lookup candidates."""
    env = os.environ if env is None else env
    out = []

    def add(path):
        if path and path not in out:
            out.append(path)

    add(installer_key_file(env=env))
    # Installers write $HOME/.config/familia/api.key even when XDG_CONFIG_HOME is set.
    home = env.get("HOME") or os.path.expanduser("~")
    add(os.path.join(home, ".config", "familia", "api.key"))
    if os.name == "nt":
        add(os.path.join(env.get("USERPROFILE") or home, ".config", "familia", "api.key"))
    roots = [env.get("FAMILIA_BOOTSTRAP_ROOT", ""),
             os.path.join(root, "code-bootstraps-llama.cpp"),
             os.path.join(os.path.dirname(root), "code-bootstraps-llama.cpp"),
             os.path.join(home, "code-bootstraps-llama.cpp")]
    for r in roots:
        if r:
            add(os.path.join(r, ".secrets", "api-keys"))
    return out


def candidate_key_files(root=ROOT, env=None):
    """Explicit file overrides, then the one instance file. No legacy layouts."""
    env = os.environ if env is None else env
    out = []
    for name in ("API_KEY_FILE", "FAMILIA_API_KEY_FILE"):
        v = env.get(name)
        if v and v not in out:
            out.append(v)
    path = instance_key_file(env=env)
    if path not in out:
        out.append(path)
    return out


_ENV_OVERRIDES = ("FAMILIA_API_KEY", "LLAMA_API_KEY", "API_KEY_FILE", "FAMILIA_API_KEY_FILE")


def _read_nofollow(path):
    """Read a key without following a final-component symlink (O_NOFOLLOW when present)."""
    flags = os.O_RDONLY
    if getattr(os, "O_NOFOLLOW", 0):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        return ""
    try:
        chunks = []
        total = 0
        while total < 1024 * 1024:
            blob = os.read(fd, 65536)
            if not blob:
                break
            chunks.append(blob)
            total += len(blob)
        else:
            return ""
        try:
            text = b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return _first_key_in(text)


def _instance_port_of(path):
    """Return the port if path is .../familia/instances/<port>/api-keys, else None."""
    parts = os.path.normpath(path).split(os.sep)
    if len(parts) >= 4 and parts[-1] == "api-keys" and parts[-3] == "instances" and parts[-4] == "familia":
        port = parts[-2]
        if port.isdigit() and 1 <= int(port) <= 65535:
            return port
    return None


def _migration_source_key(path):
    """Key from a legacy file, or '' when the file is missing or unsafe.

    Unsafe (symlink, group/world-readable, BOM, CR, whitespace or comma in the
    token) is skipped and noted. The key itself is never logged.
    """
    try:
        if not os.path.lexists(path):
            return ""
    except OSError:
        return ""
    if os.path.islink(path):
        print("familia_auth: not migrating %s (symlink)" % path, file=sys.stderr)
        return ""
    if not os.path.isfile(path):
        print("familia_auth: not migrating %s (not a regular file)" % path, file=sys.stderr)
        return ""
    if os.name != "nt":
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except OSError:
            return ""
        if mode & 0o077:
            print("familia_auth: not migrating %s (mode %04o is group- or world-readable)" % (path, mode),
                  file=sys.stderr)
            return ""
        if not (mode & 0o400):
            print("familia_auth: not migrating %s (mode %04o is not owner-readable)" % (path, mode),
                  file=sys.stderr)
            return ""
    flags = os.O_RDONLY
    if getattr(os, "O_NOFOLLOW", 0):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as e:
        print("familia_auth: not migrating %s (%s)" % (path, e.strerror or type(e).__name__), file=sys.stderr)
        return ""
    try:
        data = b""
        while len(data) < 1024 * 1024:
            blob = os.read(fd, 65536)
            if not blob:
                break
            data += blob
        else:
            print("familia_auth: not migrating %s (too large)" % path, file=sys.stderr)
            return ""
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    if data.startswith(b"\xef\xbb\xbf"):
        print("familia_auth: not migrating %s (UTF-8 BOM)" % path, file=sys.stderr)
        return ""
    if b"\r" in data:
        print("familia_auth: not migrating %s (CR / CRLF)" % path, file=sys.stderr)
        return ""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        print("familia_auth: not migrating %s (not ASCII)" % path, file=sys.stderr)
        return ""
    key = _first_key_in(text)
    if not key:
        print("familia_auth: not migrating %s (no key)" % path, file=sys.stderr)
        return ""
    if any(c.isspace() for c in key) or "," in key:
        print("familia_auth: not migrating %s (key token has whitespace or comma)" % path, file=sys.stderr)
        return ""
    return key


def _install_existing_key(path, key, source):
    """Publish key at path when that file has no key yet. 0600, no clobber, no symlink.

    Returns the key now at path (an existing key, or the race winner's key).
    """
    if os.path.islink(path):
        raise OSError("refusing to write an API key through symlink %s" % path)
    existing = _read_nofollow(path)
    if existing:
        return existing
    if _empty_regular_file(path):
        try:
            os.unlink(path)
        except OSError:
            pass
    d = os.path.dirname(path) or "."
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = os.path.join(d, ".%s.%d.%s" % (os.path.basename(path), os.getpid(), secrets.token_hex(4)))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if getattr(os, "O_NOFOLLOW", 0):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        payload = ("# llama-server API key(s), one per line\n" + key + "\n").encode("ascii")
        _write_all(fd, payload, path)
        os.fsync(fd)
        os.close(fd)
        fd = None
        _publish_secret(tmp, path)
        got = _wait_for_key(path)
        if not got and _empty_regular_file(path):
            try:
                os.unlink(path)
            except OSError:
                pass
            _publish_secret(tmp, path)
            got = _wait_for_key(path)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if not got:
        raise MissingKey("key file %s is empty" % path)
    if source and got == key:
        print("familia_auth: copied API key from %s into %s (#419). "
              "Lookup uses this instance file unless an env override is set."
              % (source, path), file=sys.stderr)
    return got


def migrate_instance_key(port=None, root=ROOT, env=None):
    """Copy the first safe legacy key into the instance file when that file has none.

    An existing instance key is never replaced. Returns the instance key, or ''
    when there is nothing to copy. Symlink destinations are refused.
    """
    env = os.environ if env is None else env
    path = instance_key_file(port=port, env=env)
    if os.path.islink(path):
        raise OSError("refusing to use symlink %s" % path)
    existing = _read_nofollow(path)
    if existing:
        return existing
    for src in migration_sources(root, env):
        try:
            if os.path.abspath(src) == os.path.abspath(path):
                continue
        except OSError:
            continue
        key = _migration_source_key(src)
        if key:
            return _install_existing_key(path, key, src)
    return ""


def seed_instance_from_file(port, src, env=None):
    """Copy src's key into the instance file when the instance file has no key yet.

    Used when a launcher was given an explicit key file: the server may use that
    file, and port-based clients need the same key in the canonical store.
    Never replaces an existing instance key.
    """
    env = os.environ if env is None else env
    if not src:
        return ""
    dest = instance_key_file(port=port, env=env)
    try:
        if os.path.abspath(os.path.expanduser(src)) == os.path.abspath(dest):
            return _read_nofollow(dest)
    except OSError:
        pass
    if os.path.islink(dest):
        raise OSError("refusing to write an API key through symlink %s" % dest)
    existing = _read_nofollow(dest)
    if existing:
        return existing
    key = _migration_source_key(os.path.expanduser(src))
    if not key:
        return ""
    return _install_existing_key(dest, key, os.path.expanduser(src))


def ensure_instance_key(port=None, root=ROOT, env=None):
    """Instance key for port: the existing file, a migrated legacy key, or a new 0600 key."""
    env = os.environ if env is None else env
    path = instance_key_file(port=port, env=env)
    k = migrate_instance_key(port=port, root=root, env=env)
    if k:
        return k
    return load_or_create_key_file(path, env=env)


def api_key(root=ROOT, env=None):
    env = os.environ if env is None else env
    for name in ("FAMILIA_API_KEY", "LLAMA_API_KEY"):
        k = _first_key_in(env.get(name, ""))
        if k:
            return k
    inst = instance_key_file(env=env)
    for path in candidate_key_files(root, env):
        try:
            same = os.path.abspath(path) == os.path.abspath(inst)
        except OSError:
            same = False
        k = _read_nofollow(path) if same else _read(path)
        if k:
            return k
    return ""


class MissingKey(RuntimeError):
    """No key to send. Callers fail closed instead of sending an unauthenticated request."""


SALT_NAME = "fingerprint-salt"
_process_salt = None


def fingerprint_salt(port=None, env=None):
    """Per-instance salt for fingerprint(), next to the instance key file (0600).

    Created only when the instance dir already exists (serve.sh / start_graph made it), so a
    bare import or a test never writes into ~/.config. Otherwise a per-process random salt is
    used: still safe to log, just not comparable across processes."""
    global _process_salt
    d = os.path.dirname(instance_key_file(port=port, env=env))
    path = os.path.join(d, SALT_NAME)
    s = _read(path)
    if not s and os.path.isdir(d):
        try:
            s = _load_or_create_secret(path, "# familia key-fingerprint salt (not a key; do not share)\n")
        except OSError:
            s = ""
    if s:
        return s.encode()
    if _process_salt is None:
        _process_salt = secrets.token_bytes(32)
    return _process_salt


def fingerprint(key, salt=None):
    """Safe-to-log identifier: HMAC-SHA256(per-instance salt, key), first 8 hex (#177).

    A keyed hash, not a bare sha256, so the logged id cannot be brute-forced back to a short
    or guessable key without the salt. Never log the key itself."""
    if not key:
        return "none"
    salt = fingerprint_salt() if salt is None else salt
    return "hmac-sha256:" + hmac.new(salt, key.encode(), hashlib.sha256).hexdigest()[:8]


def keys_match(given, expected):
    """Constant time, no length short-circuit (compare fixed-size digests)."""
    a = hashlib.sha256((given or "").encode()).digest()
    b = hashlib.sha256((expected or "").encode()).digest()
    return hmac.compare_digest(a, b) and bool(expected)


def load_or_create_key_file(path, env=None):
    """Return the instance key at path; create it ONLY if missing.

    When path is the canonical instances/<port>/api-keys file and it has no key
    yet, copy a legacy api.key or .secrets file into it first (#419). Otherwise
    the first write is atomic and 0600: a private temp file in the same dir (LF
    bytes, no BOM), then link() into place, which fails if another starter won
    the race; then everyone reads the winner's key. If link() is denied (Termux
    SELinux EACCES/EPERM, or ENOSYS/EXDEV), fall back to O_CREAT|O_EXCL|O_NOFOLLOW
    with mode 0600 (still no-clobber). An existing key is never rotated.
    """
    port = _instance_port_of(path)
    if port is not None:
        try:
            canonical = os.path.abspath(instance_key_file(port=port, env=env))
            same = os.path.abspath(path) == canonical
        except OSError:
            same = False
        if same:
            migrated = migrate_instance_key(port=port, env=env)
            if migrated:
                return migrated
    return _load_or_create_secret(path, "# llama-server API key(s), one per line\n")


def _write_all(fd, data, path):
    """Write data in full; raise on a short or failed write."""
    off = 0
    while off < len(data):
        n = os.write(fd, data[off:])
        if n <= 0:
            raise OSError("short write publishing %s" % path)
        off += n


def _publish_secret(tmp, path):
    """Atomically publish tmp at path: link, or no-clobber create if link is denied.

    If the O_EXCL fallback opens the path and then the write or fsync fails, the
    empty or partial file is unlinked so a later start is not stuck.
    """
    import errno
    try:
        os.link(tmp, path)
        return
    except FileExistsError:
        return
    except OSError as e:
        if e.errno not in (errno.EACCES, errno.EPERM, errno.ENOSYS, errno.EXDEV):
            raise
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if getattr(os, "O_NOFOLLOW", 0):
        flags |= os.O_NOFOLLOW
    fd = None
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    try:
        with open(tmp, "rb") as src:
            data = src.read()
        _write_all(fd, data, path)
        os.fsync(fd)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        fd = None
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _wait_for_key(path, attempts=5, delay=0.05):
    """Retry _read briefly so a race loser can see the winner's write."""
    import time
    k = _read(path)
    if k:
        return k
    for _ in range(max(0, attempts - 1)):
        time.sleep(delay)
        k = _read(path)
        if k:
            return k
    return ""


def _empty_regular_file(path):
    try:
        return (not os.path.islink(path)) and os.path.isfile(path) and os.path.getsize(path) == 0
    except OSError:
        return False


def _load_or_create_secret(path, header):
    k = _read(path)
    if k:
        return k
    d = os.path.dirname(path) or "."
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = os.path.join(d, ".%s.%d.%s" % (os.path.basename(path), os.getpid(), secrets.token_hex(4)))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if getattr(os, "O_NOFOLLOW", 0):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600)
    try:
        # Binary LF only: text mode on Windows would write CRLF, which the guard rejects.
        os.write(fd, (header + secrets.token_hex(24) + "\n").encode("ascii"))
        os.fsync(fd)
        os.close(fd)
        fd = None
        _publish_secret(tmp, path)
        k = _wait_for_key(path)
        # A crash mid-write can leave a stuck empty file; unlink once and republish.
        if not k and _empty_regular_file(path):
            try:
                os.unlink(path)
            except OSError:
                pass
            _publish_secret(tmp, path)
            k = _wait_for_key(path)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if not k:
        raise MissingKey("key file %s is empty" % path)
    return k


def auth_headers(headers=None, key=None, incoming=None, required=False):
    """Return headers with Authorization set.

    incoming: headers of a request we are forwarding; its Authorization/X-Api-Key wins so a
    caller's own key passes through proxies unchanged."""
    h = dict(headers or {})
    if any(k.lower() == "authorization" for k in h):
        return h
    if incoming is not None:
        for name in ("Authorization", "X-Api-Key"):
            v = incoming.get(name)
            if v:
                h["Authorization" if name == "Authorization" else "X-Api-Key"] = v
                return h
    k = api_key() if key is None else key
    if k:
        h["Authorization"] = "Bearer " + k
    elif required:
        raise MissingKey("no API key for this familia instance (set FAMILIA_API_KEY or API_KEY_FILE)")
    return h


def key_for_url(url, env=None):
    """The key for the server at url: a local URL's own port picks that instance's key file
    (a server start.sh moved to another port needs no FAMILIA_PORT); else api_key()."""
    env = os.environ if env is None else env
    try:
        u = urllib.parse.urlparse(url)
        if u.port and (u.hostname or "") in ("127.0.0.1", "localhost", "::1") \
                and not any(env.get(n) for n in _ENV_OVERRIDES):
            k = _read_nofollow(instance_key_file(port=u.port, env=env))
            if k:
                return k
    except ValueError:
        pass
    return api_key(env=env)


def request(url, data=None, headers=None, method=None, incoming=None):
    return urllib.request.Request(url, data=data, method=method,
                                  headers=auth_headers(headers, key=key_for_url(url), incoming=incoming))


def open_url(url, data=None, headers=None, method=None, timeout=10, incoming=None):
    return urllib.request.urlopen(request(url, data, headers, method, incoming), timeout=timeout)


UP, DOWN, AUTH_REJECTED, OTHER = 0, 3, 4, 5


def probe(url=None, timeout=3):
    """Authenticated probe. A 401/403 means a server IS there and rejects our key: callers must
    treat that as a misconfiguration (log it, do not start another server), never as 'no server'."""
    import urllib.error
    url = (url or "http://127.0.0.1:%s" % instance_port()).rstrip("/") + "/v1/models"
    k = key_for_url(url)
    if not k:
        print("familia_auth: no API key for this instance (%s)" % instance_key_file(), file=sys.stderr)
        return OTHER
    try:
        with urllib.request.urlopen(request(url, headers=auth_headers(key=k)), timeout=timeout):
            return UP
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print("familia_auth: ERROR: %s rejected the instance key %s (HTTP %d). A server is running "
                  "but the key does not match: fix LLAMA_API_KEY / API_KEY_FILE; do NOT start another server."
                  % (url, fingerprint(k), e.code), file=sys.stderr)
            return AUTH_REJECTED
        return OTHER
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower():
            return DOWN
        return OTHER


def write_curl_config(path, key):
    """Write a curl -K config holding the Bearer header to a NEW file, mode 0600 (#177).

    O_EXCL|O_NOFOLLOW: never follows a planted symlink or overwrites an existing file. The key
    never goes to stdout or argv; the caller passes the file to `curl -K FILE` and removes it."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write('header = "Authorization: Bearer %s"\n' % key)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    if os.name != "nt":
        os.chmod(path, 0o600)   # umask cannot widen it, but be explicit


def curl_config(args, key):
    usage = "usage: familia_auth.py curl-config -o FILE   (then: curl -K FILE ...; FILE must not exist)"
    if len(args) != 2 or args[0] not in ("-o", "--output") or not args[1]:
        print("familia_auth: curl-config no longer writes to stdout. " + usage, file=sys.stderr)
        return 2
    if not key:
        print("familia_auth: no API key for this instance (%s); no curl config written" % instance_key_file(),
              file=sys.stderr)
        return 1
    try:
        write_curl_config(args[1], key)
    except FileExistsError:
        print("familia_auth: %s already exists; refusing to overwrite. %s" % (args[1], usage), file=sys.stderr)
        return 2
    except OSError as e:
        print("familia_auth: cannot write %s: %s" % (args[1], e.strerror or type(e).__name__), file=sys.stderr)
        return 2
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "has-key"
    k = api_key()
    if cmd == "fingerprint":
        print(fingerprint(k))
        return 0 if k else 1
    if cmd == "curl-config":
        return curl_config(argv[2:], k)
    if cmd == "probe":
        return probe(argv[2] if len(argv) > 2 else None)
    if cmd == "ensure-instance":
        try:
            got = ensure_instance_key()
        except (OSError, MissingKey) as e:
            print("familia_auth: cannot prepare the instance key (%s)" % (e.strerror if isinstance(e, OSError) and e.strerror else e),
                  file=sys.stderr)
            return 1
        return 0 if got else 1
    if cmd == "has-key":
        return 0 if k else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
