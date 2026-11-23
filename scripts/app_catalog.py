#!/usr/bin/env python3
"""app_catalog.py: familia's virtual app store (#397).

One place for the app-like things familia can run: menu items that are
really apps (skills store, model downloads, agents, phone assistants, ...),
the gum-home tools the legacy catalog leaves out (web UI, ui_bridge
dashboard, find models, X search), and ideas for new apps: open GitHub issues
labeled `applications` across public brianreborn repositories.

Usage:
  app_catalog.py list [--json]                 apps you can run here
  app_catalog.py search [WORDS...] [--refresh] [--offline] [--json]
  app_catalog.py run APP_ID [ARGS...] [--dry-run]
  app_catalog.py menu                          list + search, then run one

Examples:
  app_catalog.py list
  app_catalog.py search                        # cached; one request per TTL at most
  app_catalog.py search android --refresh      # bypass the TTL
  app_catalog.py run web-ui --dry-run

Search cache: $XDG_CACHE_HOME/familia/app-catalog.json (else
~/.cache/familia/app-catalog.json) holding payload, fetched_at, ttl_s and the
ETag. Default TTL 45 minutes (FAMILIA_APP_CATALOG_TTL=MINUTES). Expired
entries are revalidated with If-None-Match, so a 304 costs no payload.
Offline or rate-limited: the stale cache is shown with a clear note.
Public data only: no token is sent unless FAMILIA_APP_CATALOG_TOKEN=1 (then
GITHUB_TOKEN / GH_TOKEN, for rate-limit headroom only); the query always
carries is:public so a token never widens it to private issues.
Output is ASCII only; colors only on a TTY with NO_COLOR unset.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.environ.get("FAMILIA_APP_CATALOG_API", "https://api.github.com/search/issues")
OWNER = "brianreborn"
LABEL = "applications"
DEFAULT_TTL_MIN = 45

# Apps. kind "menu" runs a familia menu item (familia-menu.sh --run KEY), kind "script"
# runs a repo script the legacy catalog leaves out on purpose (scripts/menu-internal.txt).
APPS = [
    ("skills", "Skills store: switch bundled skills on/off for an agent", "menu", "skills.menu"),
    ("skill-vendor", "Bring a survey skill into green-zkillz", "menu", "skills.vendor"),
    ("find-models", "Find more models (guided Hugging Face fetch)", "script", "sh scripts/find_models.sh"),
    ("model-fetch", "Download and add a model from Hugging Face", "menu", "models.fetch"),
    ("model-cards", "Fetch only a model's card, config and license", "menu", "models.cards"),
    ("agent-reach", "Agent-Reach tools: status, opt-in, link", "menu", "reach.status"),
    ("hermes", "Hermes agent on the graph coder node", "menu", "agents.hermes"),
    ("fleet", "Launch a role from graph.yaml", "menu", "agents.fleet"),
    ("guardian", "Guardian/defender launch-test (seatbelts on)", "menu", "agents.guardian-launch-test"),
    ("harness2", "Self-improving harness (Harness2) status", "menu", "harness2.status"),
    ("phone-agents", "Phone assistants (Bixby, Gemini): status", "menu", "hosts.phone-agents"),
    ("phone-agent-probe", "On this phone: Shizuku and installed assistants", "menu", "hosts.phone-agent-probe"),
    ("phone-agent-open", "On this phone: bring Gemini or Bixby to the front", "menu", "hosts.phone-agent-open"),
    ("phone-agent-ask", "On this phone: ask Gemini (CLOUD; asks first)", "menu", "hosts.phone-agent-ask"),
    ("proving-grounds", "Proving grounds (graded progress)", "menu", "test.proving-grounds"),
    ("web-ui", "Open the running llama web UI in the browser", "script", "sh scripts/open_ui.sh"),
    ("ui-dashboard", "Terminal dashboard: llama-ui slots and routes", "script", "python3 scripts/ui_bridge.py"),
    ("x-search", "X/Twitter search via Agent-Reach", "script", "sh scripts/search_x.sh"),
    ("protomodel-chat", "Talk to the protomodel", "script", "sh scripts/proto_chat.sh"),
    ("home", "The gum front door (./familia)", "script", "sh scripts/familia_home.sh"),
]


def cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "familia", "app-catalog.json")


def ttl_s():
    try:
        return int(float(os.environ.get("FAMILIA_APP_CATALOG_TTL", DEFAULT_TTL_MIN)) * 60)
    except ValueError:
        return DEFAULT_TTL_MIN * 60


def query_url():
    q = f"is:issue is:open is:public label:{LABEL} user:{OWNER}"
    return API + "?" + urllib.parse.urlencode({"q": q, "per_page": 100, "sort": "updated"})


def http_get(url, headers, timeout=10):
    """-> (status, headers dict lowercased, body bytes). Raises OSError when offline."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


def load_cache():
    try:
        with open(cache_path(), encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) and "items" in c else None
    except (OSError, ValueError):
        return None


def save_cache(c):
    p = cache_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)
    os.replace(tmp, p)


def slim(item):
    repo = item.get("repository_url", "").rsplit("/repos/", 1)[-1]
    body = " ".join((item.get("body") or "").split())
    return {"repo": repo, "number": item.get("number"), "title": item.get("title", ""),
            "url": item.get("html_url", ""), "summary": body[:160]}


def fetch(refresh=False, offline=False, now=None, get=None):
    """-> (items, note). note is '' when fresh, else why the data may be old."""
    now = time.time() if now is None else now
    get = get or http_get
    c = load_cache()
    if c and not refresh and now - c.get("fetched_at", 0) < c.get("ttl_s", ttl_s()):
        return c["items"], ""
    if offline:
        return (c or {}).get("items", []), ("offline: showing the cache from %s" % _age(c, now)) if c else "offline: no cache yet"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "familia-app-catalog"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok and os.environ.get("FAMILIA_APP_CATALOG_TOKEN") == "1":
        headers["Authorization"] = "Bearer " + tok
    if c and c.get("etag") and c.get("url") == query_url():
        headers["If-None-Match"] = c["etag"]
    try:
        status, h, body = get(query_url(), headers)
    except OSError as e:
        return (c or {}).get("items", []), (f"GitHub unreachable ({e.__class__.__name__}); cache is stale, from {_age(c, now)}"
                                            if c else "GitHub unreachable and no cache yet")
    if status == 304 and c:
        c["fetched_at"], c["ttl_s"] = now, ttl_s()
        save_cache(c)
        return c["items"], ""
    if status != 200:
        return (c or {}).get("items", []), (f"GitHub answered {status}; cache is stale, from {_age(c, now)}"
                                            if c else f"GitHub answered {status} and no cache yet")
    try:
        items = [slim(i) for i in json.loads(body.decode("utf-8")).get("items", [])]
    except ValueError:
        return (c or {}).get("items", []), "GitHub sent unreadable JSON; showing the cache"
    save_cache({"url": query_url(), "fetched_at": now, "ttl_s": ttl_s(), "etag": h.get("etag"), "items": items})
    return items, ""


def _age(c, now):
    if not c:
        return "never"
    m = int((now - c.get("fetched_at", now)) / 60)
    return f"{m} min ago"


def _ascii(s):
    return str(s).encode("ascii", "replace").decode("ascii")


def _bold(s):
    return f"\033[1m{s}\033[0m" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else s


def find_app(app_id):
    return next((a for a in APPS if a[0] == app_id), None)


def run_app(app_id, args, dry_run=False):
    a = find_app(app_id)
    if not a:
        print(f"app_catalog: no app {app_id!r} (see: app_catalog.py list)", file=sys.stderr)
        return 1
    _, _, kind, target = a
    if kind == "menu":
        cmd = ["bash", os.path.join(ROOT, "familia-menu.sh")] + (["--dry-run"] if dry_run else []) + ["--run", target] + list(args)
        return subprocess.call(cmd, cwd=ROOT)
    parts = target.split() + list(args)
    if dry_run:
        print("[dry-run] " + " ".join(parts))
        return 0
    return subprocess.call(parts, cwd=ROOT)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="app_catalog.py", description=__doc__.split("\n")[0],
                                 epilog="Example: app_catalog.py search --refresh",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("list", "search", "run", "menu"))
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        if a.json:
            print(json.dumps([dict(zip(("id", "title", "kind", "target"), x)) for x in APPS], indent=1))
            return 0
        print(_bold("App catalog: apps you can run (app_catalog.py run ID)"))
        for i, t, k, tgt in APPS:
            print(f"  {i:<18} {t}  [{'menu ' + tgt if k == 'menu' else tgt}]")
        return 0
    if a.cmd == "run":
        if not a.rest:
            ap.error("run needs APP_ID")
        return run_app(a.rest[0], a.rest[1:], a.dry_run)
    words = [w.lower() for w in a.rest if w.lower() != "all"]
    items, note = fetch(refresh=a.refresh, offline=a.offline)
    items = [i for i in items if all(w in (i["title"] + " " + i["repo"] + " " + i["summary"]).lower() for w in words)]
    if a.json:
        print(json.dumps({"note": note, "items": items}, indent=1))
        return 0
    if a.cmd == "menu":
        main(["list"])
        print()
    print(_bold(f"Open '{LABEL}' issues across {OWNER} (public): {len(items)}"))
    if note:
        print(f"  NOTE: {note}")
    for i in items:
        print(_ascii(f"  {i['repo']}#{i['number']}  {i['title']}\n      {i['url']}" + (f"\n      {i['summary']}" if i["summary"] else "")))
    if a.cmd == "menu" and sys.stdin.isatty() and os.environ.get("FAMILIA_NO_TTY") != "1":
        ans = input("\napp id to run (Enter = back): ").strip()
        if ans:
            return run_app(ans.split()[0], ans.split()[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
