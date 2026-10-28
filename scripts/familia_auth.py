"""One place to find and attach the API key of the local familia/llama-server instance.

Every client that talks to :9931 (or any gateway that requires a key) must call
auth_headers() / open_url() instead of building a bare urllib.Request. Requiring the key
on the server is not enough: every caller, including internal and recursive ones, must send it.

Key lookup order (first hit wins):
  1. FAMILIA_API_KEY            explicit override
  2. LLAMA_API_KEY              set by code-bootstraps serve.sh (comma list; first key used)
  3. API_KEY_FILE               file, one key per line, '#' comments
  4. <bootstrap root>/.secrets/api-keys for FAMILIA_BOOTSTRAP_ROOT, ROOT/code-bootstraps-llama.cpp,
     ROOT/../code-bootstraps-llama.cpp, ~/code-bootstraps-llama.cpp
The key is never generated here; serve.sh creates it once and reuses it.

CLI:  python3 scripts/familia_auth.py curl-config   -> 'header = "Authorization: Bearer ..."' for curl -K -
      python3 scripts/familia_auth.py has-key       -> exit 0 when a key is found
"""
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _first_key_in(text):
    for line in text.replace(",", "\n").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _first_key_in(f.read())
    except OSError:
        return ""


def candidate_key_files(root=ROOT, env=None):
    env = os.environ if env is None else env
    out = []
    if env.get("API_KEY_FILE"):
        out.append(env["API_KEY_FILE"])
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


def auth_headers(headers=None, key=None, incoming=None):
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
    return h


def request(url, data=None, headers=None, method=None, incoming=None):
    return urllib.request.Request(url, data=data, method=method,
                                  headers=auth_headers(headers, incoming=incoming))


def open_url(url, data=None, headers=None, method=None, timeout=10, incoming=None):
    return urllib.request.urlopen(request(url, data, headers, method, incoming), timeout=timeout)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "has-key"
    k = api_key()
    if cmd == "curl-config":
        if k:
            print('header = "Authorization: Bearer %s"' % k)
        return 0
    if cmd == "has-key":
        return 0 if k else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
