r"""One place to find and attach the API key of the local familia/llama-server instance.

Every client that talks to :9931 (or any gateway that requires a key) must call
auth_headers() / open_url() instead of building a bare urllib.Request. Requiring the key
on the server is not enough: every caller, including internal and recursive ones, must send it.

Key lookup order (first hit wins):
  1. FAMILIA_API_KEY            explicit override
  2. LLAMA_API_KEY              set by code-bootstraps serve.sh (comma list; first key used)
  3. API_KEY_FILE               file, one key per line, '#' comments
  4. the per-instance key file  ${XDG_CONFIG_HOME:-~/.config}/familia/instances/<port>/api-keys
                                (%APPDATA%\familia\instances\<port> on Windows; port = FAMILIA_PORT/PORT, 9931)
  5. legacy <bootstrap root>/.secrets/api-keys for FAMILIA_BOOTSTRAP_ROOT, ROOT/code-bootstraps-llama.cpp,
     ROOT/../code-bootstraps-llama.cpp, ~/code-bootstraps-llama.cpp
The key is never generated here; serve.sh / serve.ps1 create it once per instance and never rotate it
(code-bootstraps-llama.cpp docs/api-key-design.md).

CLI:  python3 scripts/familia_auth.py curl-config -o FILE
                                                    -> writes 'header = "Authorization: Bearer ..."' to a NEW
                                                       0600 FILE for `curl -K FILE` (never to stdout; #177)
      python3 scripts/familia_auth.py fingerprint   -> safe-to-log HMAC-SHA256 key id
      python3 scripts/familia_auth.py has-key       -> exit 0 when a key is found
      python3 scripts/familia_auth.py probe [URL]   -> authenticated probe of the instance:
                                                       0 up, 3 nothing listening, 4 key rejected (401/403:
                                                       a misconfiguration, NEVER "no server"), 5 other error
"""
import hashlib
import hmac
import os
import secrets
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


def candidate_key_files(root=ROOT, env=None):
    env = os.environ if env is None else env
    out = []
    if env.get("API_KEY_FILE"):
        out.append(env["API_KEY_FILE"])
    out.append(instance_key_file(env=env))
    roots = [env.get("FAMILIA_BOOTSTRAP_ROOT", ""),
             os.path.join(root, "code-bootstraps-llama.cpp"),
             os.path.join(os.path.dirname(root), "code-bootstraps-llama.cpp"),
             os.path.join(os.path.expanduser("~"), "code-bootstraps-llama.cpp")]
    for r in roots:
        if r:
            out.append(os.path.join(r, ".secrets", "api-keys"))
    return out


def api_key(root=ROOT, env=None):
    env = os.environ if env is None else env
    for name in ("FAMILIA_API_KEY", "LLAMA_API_KEY"):
        k = _first_key_in(env.get(name, ""))
        if k:
            return k
    for path in candidate_key_files(root, env):
        k = _read(path)
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


def load_or_create_key_file(path):
    """Return the instance key at path; create it ONLY if missing.

    First write is atomic and 0600: write a private temp file in the same dir, then link()
    it into place, which fails if another starter won the race; then everyone reads the
    winner's key. An existing key is never rotated."""
    return _load_or_create_secret(path, "# llama-server API key(s), one per line\n")


def _load_or_create_secret(path, header):
    k = _read(path)
    if k:
        return k
    d = os.path.dirname(path) or "."
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = os.path.join(d, ".%s.%d.%s" % (os.path.basename(path), os.getpid(), secrets.token_hex(4)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(header + secrets.token_hex(24) + "\n")
            f.flush(); os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(tmp)
    k = _read(path)
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
                and not any(env.get(n) for n in ("FAMILIA_API_KEY", "LLAMA_API_KEY", "API_KEY_FILE")):
            k = _read(instance_key_file(port=u.port, env=env))
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
    if cmd == "has-key":
        return 0 if k else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
