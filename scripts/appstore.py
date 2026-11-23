#!/usr/bin/env python3
"""App store: a plain display of tweets that promote apps.

usage: python3 scripts/appstore.py text [--platform P] [--data DIR] [--width N]
       python3 scripts/appstore.py html [--out DIR] [--platform P] [--data DIR]
       python3 scripts/appstore.py platforms [--data DIR]
       python3 scripts/appstore.py links [--platform P] [--data DIR]
       python3 scripts/appstore.py card N [--platform P] [--data DIR]
       python3 scripts/appstore.py banner
       python3 scripts/appstore.py where [--data DIR]
       python3 scripts/appstore.py checksums [--write | --verify] [--data DIR]

The data ships inside the release package: appstore/data/feed.json plus
appstore/data/media/ (images and video), listed in appstore/data/SHA256SUMS.
Lookup order for the feed:
  1. --data DIR, or FAMILIA_APPSTORE_DATA
  2. the installed release copy: FAMILIA_APPDIR/usr/share/familia/appstore/data
     (set by the AppImage's AppRun, so a writable checkout never shadows the
     release data), then this tree's appstore/data
  3. the example fixture examples/appstore/feed.sample.json (fake data)
A release feed with no items falls through to the fixture, with a note.

Each card puts the app first (name, pitch, link, platform), then the tweet
text, author and date. Nothing here touches the network or reads credentials.
Media paths are relative to the data dir; URLs, absolute paths and '..' are
refused, so the HTML page never loads anything remote.

example: python3 scripts/appstore.py text --platform Android
example: python3 scripts/appstore.py html --out "$HOME/.cache/familia/appstore"
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_DIR = os.path.join("appstore", "data")
FIXTURE_DIR = os.path.join(ROOT, "examples", "appstore")
FIXTURE_FEED = "feed.sample.json"
FEED = "feed.json"
SUMS = "SHA256SUMS"
FORMAT = "familia-appstore-feed"
REQUIRED = ("app_name", "app_pitch", "app_link", "platform",
            "author_handle", "author_name", "text", "date", "url")
MEDIA_TYPES = ("image", "video")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)")


class FeedError(ValueError):
    pass


def clean(value):
    """One line of display text: no escapes, no control characters."""
    s = "" if value is None else str(value)
    s = _ANSI.sub("", s)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\t", " ")
    s = _CTRL.sub("", s)
    return re.sub(r" {2,}", " ", s).strip()


def safe_url(value):
    """http(s) URLs only. Anything else (javascript:, data:, file:) is dropped."""
    s = clean(value)
    if re.match(r"^https?://[^\s<>\"']+$", s, re.I):
        return s
    return ""


def safe_media_path(value):
    """A relative path under the data dir, or '' if it could escape it."""
    s = clean(value).replace("\\", "/")
    if not s or s.startswith("/") or re.match(r"^[a-z][a-z0-9+.-]*:", s, re.I):
        return ""
    parts = s.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return ""
    return s


def parse_item(raw, index):
    if not isinstance(raw, dict):
        raise FeedError("item %d is not an object" % index)
    missing = [k for k in REQUIRED if not clean(raw.get(k))]
    if missing:
        raise FeedError("item %d is missing %s" % (index, ", ".join(missing)))
    item = {k: clean(raw.get(k)) for k in REQUIRED}
    item["app_link"] = safe_url(raw.get("app_link"))
    item["url"] = safe_url(raw.get("url"))
    item["author_handle"] = item["author_handle"].lstrip("@")
    media = []
    for m in raw.get("media") or []:
        if not isinstance(m, dict):
            continue
        kind = clean(m.get("type")).lower()
        path = safe_media_path(m.get("path"))
        if kind in MEDIA_TYPES and path:
            media.append({"type": kind, "path": path, "alt": clean(m.get("alt"))})
    item["media"] = media
    return item


def parse_feed(doc):
    """Return the list of items in a feed document (dict or bare list)."""
    if isinstance(doc, list):
        raw_items = doc
    elif isinstance(doc, dict):
        fmt = doc.get("format", FORMAT)
        if fmt != FORMAT:
            raise FeedError("unknown feed format %r" % fmt)
        raw_items = doc.get("items", [])
        if not isinstance(raw_items, list):
            raise FeedError("items is not a list")
    else:
        raise FeedError("feed is not a JSON object")
    items = [parse_item(r, i) for i, r in enumerate(raw_items)]
    items.sort(key=lambda it: it["date"], reverse=True)
    return items


def load_feed_file(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".jsonl"):
        doc = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    else:
        doc = json.loads(text)
    return parse_feed(doc), doc


def candidates(data_dir=None):
    """(dir, feed file, label) in lookup order."""
    out = []
    explicit = data_dir or os.environ.get("FAMILIA_APPSTORE_DATA")
    if explicit:
        out.append((explicit, FEED, "data dir"))
        return out
    appdir = os.environ.get("FAMILIA_APPDIR")
    if appdir:
        out.append((os.path.join(appdir, "usr", "share", "familia", RELEASE_DIR), FEED, "release"))
    out.append((os.path.join(ROOT, RELEASE_DIR), FEED, "release"))
    out.append((FIXTURE_DIR, FIXTURE_FEED, "example fixture"))
    return out


def load(data_dir=None):
    """Return (items, base_dir, label, notes)."""
    notes = []
    for base, name, label in candidates(data_dir):
        path = os.path.join(base, name)
        if not os.path.isfile(path):
            if label == "data dir":
                raise FeedError("no %s in %s" % (name, base))
            continue
        items, doc = load_feed_file(path)
        if not items and label == "release":
            notes.append("release feed has no apps yet; showing the example fixture")
            continue
        if isinstance(doc, dict) and doc.get("example"):
            label = "example fixture"
        return items, base, label, notes
    raise FeedError("no app store feed found")


def filter_platform(items, platform):
    if not platform or platform.lower() in ("all", "*"):
        return list(items)
    return [it for it in items if it["platform"].lower() == platform.lower()]


def platforms(items):
    seen = []
    for it in items:
        if it["platform"] not in seen:
            seen.append(it["platform"])
    return sorted(seen, key=str.lower)


# --- text (plain / gum fallback) -------------------------------------------

def card_lines(item, width=72):
    inner = max(20, width - 4)
    wrap = lambda s: textwrap.wrap(s, inner) or [""]
    lines = []
    lines += wrap("%s  [%s]" % (item["app_name"], item["platform"]))
    lines += wrap(item["app_pitch"])
    lines.append(item["app_link"] or "(no link)")
    for m in item["media"]:
        lines += wrap("[%s: %s]" % (m["type"], m["alt"] or m["path"]))
    lines.append("-" * inner)
    lines += wrap('"%s"' % item["text"])
    lines += wrap("@%s (%s)  %s" % (item["author_handle"], item["author_name"], item["date"][:10]))
    if item["url"]:
        lines += wrap(item["url"])
    return lines


def box(lines, width=72):
    inner = max(20, width - 4)
    top = "+" + "-" * (inner + 2) + "+"
    body = ["| " + ln.ljust(inner) + " |" for ln in lines]
    return "\n".join([top] + body + [top])


BANNER = r"""
    _                     _
   / \   _ __  _ __   ___| |_ ___  _ __ ___
  / _ \ | '_ \| '_ \ / __| __/ _ \| '__/ _ \
 / ___ \| |_) | |_) |\__ \ || (_) | | |  __/
/_/   \_\ .__/| .__/ |___/\__\___/|_|  \___|
        |_|   |_|     familia app store
""".strip("\n")


def render_text(items, label, notes, width=72, banner=True):
    out = []
    if banner:
        out.append(BANNER)
        out.append("")
    out.append("source: %s  |  %d apps" % (label, len(items)))
    for n in notes:
        out.append("note: " + n)
    out.append("")
    for it in items:
        out.append(box(card_lines(it, width), width))
        out.append("")
    if not items:
        out.append("(no apps for this filter)")
    text = "\n".join(out).rstrip("\n") + "\n"
    return "".join(ch if ord(ch) < 128 else "?" for ch in text)


# --- HTML (cockpit look, no frameworks, no remote loads) --------------------

CSS = """
:root{--bg:#111;--panel:#1a1a1a;--edge:#00afaf;--rule:#00ffff;--title:#00ff00;
--soft:#80ffff;--gold:#ffd700;--amber:#ffaf00;--text:#dddddd;--dim:#999}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:"DejaVu Sans",Arial,sans-serif;font-size:14px}
header{margin:16px;padding:10px 16px;background:var(--panel);
border:2px solid var(--edge);border-radius:8px}
header h1{margin:0;padding:8px 0;color:var(--title);font-size:18px;
border-top:2px solid var(--rule);border-bottom:2px solid var(--rule)}
header p{margin:6px 0;color:var(--soft);font-size:12px}
nav{margin:8px 0 0}
nav a{display:inline-block;margin:0 6px 6px 0;padding:2px 10px;color:var(--gold);
border:1px solid var(--gold);border-radius:12px;text-decoration:none;font-size:12px}
nav a:hover,nav a:focus{background:var(--gold);color:#111}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
gap:16px;margin:16px}
article{background:var(--panel);border:2px solid var(--edge);border-radius:8px;
padding:14px;display:flex;flex-direction:column;gap:8px}
article:target{border-color:var(--gold)}
.app h2{margin:0;color:#fff;font-size:17px}
.platform{float:right;color:var(--amber);border:1px solid var(--amber);
border-radius:10px;padding:0 8px;font-size:11px}
.pitch{margin:0;color:var(--gold);font-weight:bold}
.get{display:inline-block;color:var(--title);font-weight:bold;word-break:break-all}
.media img,.media video{max-width:100%;max-height:180px;border-radius:6px;
border:1px solid #333;background:#000}
.tweet{border-top:1px solid #333;padding-top:8px;color:var(--text)}
.tweet p{margin:0 0 6px;white-space:pre-wrap}
.who{color:var(--dim);font-size:12px}
.who a{color:var(--soft)}
.empty{margin:16px;color:var(--dim)}
footer{margin:16px;color:var(--dim);font-size:11px}
"""

esc = lambda s: html.escape(s, quote=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def card_html(it):
    parts = ['<article id="app-%s" data-platform="%s">' % (esc(slug(it["app_name"])), esc(it["platform"].lower()))]
    parts.append('<div class="app"><span class="platform">%s</span><h2>%s</h2></div>'
                 % (esc(it["platform"]), esc(it["app_name"])))
    parts.append('<p class="pitch">%s</p>' % esc(it["app_pitch"]))
    if it["app_link"]:
        parts.append('<a class="get" href="%s" rel="noopener noreferrer nofollow">%s</a>'
                     % (esc(it["app_link"]), esc(it["app_link"])))
    for m in it["media"]:
        if m["type"] == "image":
            parts.append('<div class="media"><img src="%s" alt="%s" loading="lazy"></div>'
                         % (esc(m["path"]), esc(m["alt"])))
        else:
            parts.append('<div class="media"><video src="%s" controls preload="none" title="%s"></video></div>'
                         % (esc(m["path"]), esc(m["alt"])))
    who = "@%s &middot; %s &middot; %s" % (esc(it["author_handle"]), esc(it["author_name"]), esc(it["date"][:10]))
    if it["url"]:
        who += ' &middot; <a href="%s" rel="noopener noreferrer nofollow">post</a>' % esc(it["url"])
    parts.append('<div class="tweet"><p>%s</p><div class="who">%s</div></div>' % (esc(it["text"]), who))
    parts.append("</article>")
    return "\n".join(parts)


def render_html(items, label, notes, all_platforms=None):
    plats = all_platforms if all_platforms is not None else platforms(items)
    chips = "".join('<a href="#" data-p="%s">%s</a>' % (esc(p.lower()), esc(p)) for p in plats)
    note = "".join("<p>note: %s</p>" % esc(n) for n in notes)
    cards = "\n".join(card_html(it) for it in items) or ""
    empty = "" if items else '<p class="empty">No apps for this filter.</p>'
    # The only script toggles card visibility; it loads nothing.
    js = ("document.querySelectorAll('nav a').forEach(function(a){a.addEventListener('click',"
          "function(e){e.preventDefault();var p=a.getAttribute('data-p');"
          "document.querySelectorAll('article').forEach(function(c){"
          "c.hidden=!!p&&c.getAttribute('data-platform')!==p;});});});")
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<meta name="referrer" content="no-referrer">
<title>familia app store</title>
<style>%s</style>
</head>
<body>
<header>
<h1>&nbsp; FAMILIA APP STORE &nbsp;</h1>
<p>source: %s &middot; %d apps</p>%s
<nav><a href="#" data-p="">All</a>%s</nav>
</header>
<main>
%s
</main>%s
<footer>Static page written by scripts/appstore.py. No remote loads.</footer>
<script>%s</script>
</body>
</html>
""" % (CSS, esc(label), len(items), note, chips, cards, empty, js)


def write_html(items, base, label, notes, out_dir, all_platforms=None):
    os.makedirs(out_dir, exist_ok=True)
    for it in items:
        for m in it["media"]:
            src = os.path.join(base, m["path"])
            dst = os.path.join(out_dir, m["path"])
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
    page = os.path.join(out_dir, "index.html")
    tmp = page + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(render_html(items, label, notes, all_platforms))
    os.replace(tmp, page)
    return page


# --- release checksums -------------------------------------------------------

def data_files(base):
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for f in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, f), base).replace(os.sep, "/")
            if rel != SUMS and not f.startswith("."):
                out.append(rel)
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sums_text(base):
    return "".join("%s  %s\n" % (sha256(os.path.join(base, r)), r) for r in data_files(base))


def verify_sums(base):
    path = os.path.join(base, SUMS)
    if not os.path.isfile(path):
        return ["missing %s" % SUMS]
    with open(path, encoding="utf-8") as fh:
        want = fh.read()
    have = sums_text(base)
    if want == have:
        return []
    return ["%s does not match the data (run: python3 scripts/appstore.py checksums --write)" % SUMS]


# --- CLI ----------------------------------------------------------------------

def default_out():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "familia", "appstore")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="appstore.py", description=__doc__.split("\n")[0],
                                 epilog="example: python3 scripts/appstore.py text --platform Android")
    ap.add_argument("cmd", choices=("text", "html", "platforms", "links", "card", "banner", "where", "checksums"))
    ap.add_argument("index", nargs="?", type=int, help="card: 0-based card number")
    ap.add_argument("--data", help="data dir holding feed.json (and media/)")
    ap.add_argument("--platform", help="only this platform (All for every one)")
    ap.add_argument("--out", help="html: output dir (default $XDG_CACHE_HOME/familia/appstore)")
    ap.add_argument("--width", type=int, default=72)
    ap.add_argument("--no-banner", action="store_true")
    ap.add_argument("--write", action="store_true", help="checksums: rewrite SHA256SUMS")
    ap.add_argument("--verify", action="store_true", help="checksums: check SHA256SUMS")
    a = ap.parse_args(argv)

    if a.cmd == "checksums":
        base = a.data or os.path.join(ROOT, RELEASE_DIR)
        if a.write:
            with open(os.path.join(base, SUMS), "w", encoding="utf-8") as fh:
                fh.write(sums_text(base))
            print("wrote %s" % os.path.join(base, SUMS))
            return 0
        if a.verify:
            errs = verify_sums(base)
            for e in errs:
                print("appstore: " + e, file=sys.stderr)
            if not errs:
                print("ok: %s" % base)
            return 1 if errs else 0
        sys.stdout.write(sums_text(base))
        return 0

    try:
        items, base, label, notes = load(a.data)
    except (FeedError, OSError, ValueError) as exc:
        print("appstore: %s" % exc, file=sys.stderr)
        return 1
    shown = filter_platform(items, a.platform)
    if a.cmd == "where":
        print("%s\t%s" % (label, base))
    elif a.cmd == "platforms":
        print("\n".join(platforms(items)))
    elif a.cmd == "links":
        for it in shown:
            print("%s\t%s\t%s" % (it["app_name"], it["platform"], it["app_link"]))
    elif a.cmd == "banner":
        # Same width on every line so a centered gum box keeps the art's shape.
        rows = BANNER.split("\n")
        wide = max(len(r) for r in rows)
        print("\n".join(r.ljust(wide) for r in rows))
    elif a.cmd == "card":
        if a.index is None or not 0 <= a.index < len(shown):
            print("appstore: card index out of range (0..%d)" % (len(shown) - 1), file=sys.stderr)
            return 2
        text = "\n".join(card_lines(shown[a.index], a.width)) + "\n"
        sys.stdout.write("".join(ch if ord(ch) < 128 else "?" for ch in text))
    elif a.cmd == "text":
        sys.stdout.write(render_text(shown, label, notes, a.width, not a.no_banner))
    elif a.cmd == "html":
        page = write_html(shown, base, label, notes, a.out or default_out(), platforms(items))
        print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
