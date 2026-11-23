#!/usr/bin/env python3
"""channel.py: release channels for familia's dependencies (bleeding | stable).

Two channels:
  bleeding  (default) familia's current behavior. Installers and fetchers keep doing exactly
            what they did before this module existed; they only call the resolver when the
            channel is 'stable'. resolve(..., channel='bleeding') returns the newest
            non-prerelease release, for callers (e.g. a Hermes hook) that want an explicit ref.
  stable    for each dependency, the most stable release published in the last N days
            (N = FAMILIA_STABLE_DAYS, default 30, allowed 1..365). No release numbers are pinned.

Configuration (explicit argument > environment > default):
  FAMILIA_CHANNEL=bleeding|stable      installers: --channel bleeding|stable
  FAMILIA_STABLE_DAYS=N                installers: --stable-days N
Both are validated strictly: the channel must be exactly one of the allowlist, N must be a
plain base-10 integer 1..365 (no sign, exponent, spaces or non-ASCII digits). Anything else is
an error (exit 2), never a silent default.

"Most stable" heuristic (documented in docs/release-channels.md):
  1. Candidates: releases that are not drafts, not flagged prerelease, whose tag does not look
     like a prerelease (rc, alpha, beta, pre, preview, dev, nightly, snapshot) and whose tag /
     revision passes the strict name check. Invalid names are skipped and logged, never used.
  2. Soak time of a candidate: for the newest candidate, time since it was published; for an
     older one, how long it stayed un-superseded (until the next candidate was published).
     A candidate qualifies when it soaked at least MIN_SOAK (24 h).
  3. In the window [now - N days, now], pick the NEWEST qualifying candidate (leans newer).
  4. If nothing in the window qualifies (or the window is empty), fall back to the newest
     qualifying candidate published before the window (logged as a fallback). Last resorts,
     also logged: the newest candidate before the window, then the newest in the window.
  Releases deleted ("yanked") upstream are simply absent from the list, so they are never picked.
  llama.cpp: upstream flags every bNNNN build as a prerelease and publishes vX.Y.Z releases as
  its stable line, each with a nightly-tag.txt asset naming the bNNNN build it was cut from.
  'stable' applies the heuristic to the vX.Y.Z releases and returns that bNNNN build (validated
  against b[0-9]{1,6}); 'bleeding' returns the newest bNNNN build.

API (stable; Hermes Wiring and installers call only this):
  resolve(source_id, channel=None, days=None, *, now=None, fetch=None, asset_re=None) -> ResolvedRef
  validate_channel(value) -> str ; validate_days(value) -> int ; effective(channel, days, environ)
  ResolvedRef fields: source, channel, days, ref, kind ('tag'|'commit'), published_at, fallback,
                      reason, release (upstream release the ref came from; == ref except llama.cpp)
  GITHUB_TOKEN / GH_TOKEN, when set, is sent only to the GitHub API host (rate limit); never logged.
CLI:
  python3 scripts/channel.py resolve SOURCE [--channel C] [--days N] [--asset-re RE] [--json] [--no-record]
  python3 scripts/channel.py show          effective channel and days (validated)
  python3 scripts/channel.py sources       known source ids
  SOURCE: llama.cpp | hermes-agent | github:OWNER/REPO | hf:ORG/NAME
`resolve` prints only the validated ref on stdout (or JSON with --json); reasons go to stderr.
Exit codes: 0 ok; 1 nothing could be resolved / network error; 2 invalid input.

Records: each CLI resolution is written to $XDG_STATE_HOME/familia/channel/<source>.json
(default $HOME/.local/state/...), created 0700 and owned by the user, via one private
tempfile.mkdtemp inside that directory per run and an atomic rename. Nothing goes to the system temp dir.
No listeners; outbound HTTPS GETs only (GitHub releases API, Hugging Face commits API).
Stdlib only.
"""
import argparse
import datetime as _dt
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

CHANNELS = ("bleeding", "stable")
DEFAULT_CHANNEL = "bleeding"
DEFAULT_DAYS = 30
DAYS_MIN, DAYS_MAX = 1, 365
MIN_SOAK = _dt.timedelta(hours=24)
CHANNEL_ENV, DAYS_ENV = "FAMILIA_CHANNEL", "FAMILIA_STABLE_DAYS"

GITHUB_API = "https://api.github.com"
HF_ENDPOINT = "https://huggingface.co"
UA = "familia-channel/1 (stdlib urllib)"
MAX_PAGES = 10
MAX_BODY = 32 * 1024 * 1024  # a page of 100 llama.cpp releases with ~40 assets each is several MB

_DAYS_RE = re.compile(r"[0-9]{1,3}", re.ASCII)
# Tag / revision names that may be used in a path segment or handed to git. Conservative.
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", re.ASCII)
SHA_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)
_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", re.ASCII)
PRERELEASE_RE = re.compile(r"(?i)(?:^|[^a-z])(rc|alpha|beta|pre|preview|dev|nightly|snapshot)(?:[^a-z]|$)")


class ChannelError(ValueError):
    """Invalid channel, days, source id or name (exit 2)."""


class ResolveError(RuntimeError):
    """Nothing could be resolved (exit 1)."""


def _log(msg):
    print("channel: " + msg, file=sys.stderr)


# ---------------------------------------------------------------- validation

def validate_channel(value):
    if value is None:
        return DEFAULT_CHANNEL
    if not isinstance(value, str) or value not in CHANNELS:
        raise ChannelError("invalid channel %r: must be one of %s" % (value, ", ".join(CHANNELS)))
    return value


def validate_days(value):
    if value is None:
        return DEFAULT_DAYS
    if isinstance(value, bool):
        raise ChannelError("invalid stable days %r: must be an integer %d..%d" % (value, DAYS_MIN, DAYS_MAX))
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and _DAYS_RE.fullmatch(value):
        n = int(value, 10)
    else:
        raise ChannelError("invalid stable days %r: must be a base-10 integer %d..%d" % (value, DAYS_MIN, DAYS_MAX))
    if not DAYS_MIN <= n <= DAYS_MAX:
        raise ChannelError("invalid stable days %r: must be %d..%d" % (value, DAYS_MIN, DAYS_MAX))
    return n


def effective(channel=None, days=None, environ=None):
    """(channel, days) with precedence explicit > environment > default. Empty env = unset."""
    env = os.environ if environ is None else environ
    c = channel if channel is not None else (env.get(CHANNEL_ENV) or None)
    d = days if days is not None else (env.get(DAYS_ENV) or None)
    return validate_channel(c), validate_days(d)


def valid_tag(name):
    return isinstance(name, str) and bool(TAG_RE.fullmatch(name)) and ".." not in name


def _valid_repo(s):
    parts = s.split("/") if isinstance(s, str) else []
    return len(parts) == 2 and all(_PART_RE.fullmatch(p) and ".." not in p for p in parts)


# ---------------------------------------------------------------- data

@dataclass(frozen=True)
class Release:
    tag: str
    published: _dt.datetime
    prerelease: bool = False
    draft: bool = False
    assets: tuple = ()


@dataclass(frozen=True)
class ResolvedRef:
    source: str
    channel: str
    days: int
    ref: str
    kind: str
    published_at: str
    fallback: bool
    reason: str
    release: str = ""

    def to_dict(self):
        return asdict(self)


def _parse_time(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        t = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


# ---------------------------------------------------------------- network (mocked in tests)

def _get(url, timeout, accept):
    if not url.startswith("https://"):
        raise ResolveError("refusing non-https URL")
    h = {"User-Agent": UA, "Accept": accept}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok and url.startswith(GITHUB_API + "/"):
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(MAX_BODY)
    except (urllib.error.URLError, OSError) as e:
        raise ResolveError("%s: %s" % (url.split("?")[0], e))


def http_get_json(url, timeout=30):
    try:
        return json.loads(_get(url, timeout, "application/json"))
    except ValueError as e:
        raise ResolveError("%s: bad JSON: %s" % (url.split("?")[0], e))


def http_get_text(url, timeout=30):
    return _get(url, timeout, "text/plain").decode("utf-8", "replace")


class GitHubReleases:
    kind = "tag"

    def __init__(self, repo, tag_re=None):
        if not _valid_repo(repo):
            raise ChannelError("invalid GitHub repo %r" % (repo,))
        self.repo = repo
        self.tag_re = re.compile(tag_re, re.ASCII) if tag_re else None

    def pick(self, rels, channel, days, now, asset_re=None):
        return select(rels, channel, days, now, asset_re)

    def finalize(self, rel, fetch_text):
        return rel.tag

    def url(self, page):
        owner, name = self.repo.split("/")
        q = urllib.parse.urlencode({"per_page": 100, "page": int(page)})
        return "%s/repos/%s/%s/releases?%s" % (GITHUB_API, urllib.parse.quote(owner, safe=""),
                                              urllib.parse.quote(name, safe=""), q)

    def releases(self, fetch, since=None):
        out = []
        for page in range(1, MAX_PAGES + 1):
            data = fetch(self.url(page))
            if not isinstance(data, list) or not data:
                break
            oldest = None
            for r in data:
                if not isinstance(r, dict):
                    continue
                t = _parse_time(r.get("published_at") or r.get("created_at"))
                tag = r.get("tag_name")
                if t is None:
                    continue
                oldest = t if oldest is None or t < oldest else oldest
                if not valid_tag(tag) or (self.tag_re and not self.tag_re.fullmatch(tag)):
                    _log("skipping release with unexpected tag name %r" % (tag,))
                    continue
                names = tuple(a.get("name", "") for a in (r.get("assets") or []) if isinstance(a, dict))
                out.append(Release(tag, t, bool(r.get("prerelease")), bool(r.get("draft")), names))
            # Stop once a page reaches past the window and one release older than it is known.
            if since is not None and oldest is not None and oldest < since and any(x.published < since for x in out):
                break
            if len(data) < 100:
                break
        return out


class HFCommits:
    kind = "commit"

    def __init__(self, repo, branch="main"):
        if not _valid_repo(repo) or not valid_tag(branch):
            raise ChannelError("invalid Hugging Face repo %r" % (repo,))
        self.repo, self.branch = repo, branch

    def pick(self, rels, channel, days, now, asset_re=None):
        return select(rels, channel, days, now, None)

    def finalize(self, rel, fetch_text):
        return rel.tag

    def url(self, page):
        org, name = self.repo.split("/")
        base = os.environ.get("HF_ENDPOINT", HF_ENDPOINT).rstrip("/")
        if not base.startswith("https://"):
            base = HF_ENDPOINT
        q = urllib.parse.urlencode({"p": int(page)})
        return "%s/api/models/%s/%s/commits/%s?%s" % (base, urllib.parse.quote(org, safe=""),
                                                      urllib.parse.quote(name, safe=""),
                                                      urllib.parse.quote(self.branch, safe=""), q)

    def releases(self, fetch, since=None):
        out = []
        for page in range(0, MAX_PAGES):
            data = fetch(self.url(page))
            if not isinstance(data, list) or not data:
                break
            for c in data:
                if not isinstance(c, dict):
                    continue
                sha, t = c.get("id"), _parse_time(c.get("date"))
                if t is None:
                    continue
                if not (isinstance(sha, str) and SHA_RE.fullmatch(sha)):
                    _log("skipping commit with unexpected id %r" % (sha,))
                    continue
                out.append(Release(sha, t))
            if since is not None and out and min(x.published for x in out) < since:
                break
            if len(data) < 50:
                break
        return out


BUILD_RE = re.compile(r"b[0-9]{1,6}", re.ASCII)
VERSION_RE = re.compile(r"v[0-9]{1,4}\.[0-9]{1,4}(?:\.[0-9]{1,4})?", re.ASCII)


class LlamaCppReleases(GitHubReleases):
    """ggml-org/llama.cpp: bNNNN builds (flagged prerelease upstream) + vX.Y.Z stable releases."""

    def __init__(self):
        super().__init__("ggml-org/llama.cpp", tag_re=r"b[0-9]{1,6}|v[0-9]{1,4}\.[0-9]{1,4}(?:\.[0-9]{1,4})?")

    def pick(self, rels, channel, days, now, asset_re=None):
        if channel == "bleeding":
            rx = re.compile(asset_re) if asset_re else None
            builds = sorted((r for r in rels if BUILD_RE.fullmatch(r.tag) and not r.draft
                             and (rx is None or any(rx.search(a) for a in r.assets))),
                            key=lambda r: r.published)
            if not builds:
                raise ResolveError("no llama.cpp bNNNN build found")
            return builds[-1], False, "bleeding: newest llama.cpp build"
        versions = [r for r in rels if VERSION_RE.fullmatch(r.tag)]
        return select(versions, channel, days, now, None)

    def finalize(self, rel, fetch_text):
        if BUILD_RE.fullmatch(rel.tag):
            return rel.tag
        if "nightly-tag.txt" not in rel.assets:
            raise ResolveError("llama.cpp %s has no nightly-tag.txt; cannot map it to a build" % rel.tag)
        url = "https://github.com/%s/releases/download/%s/nightly-tag.txt" % (
            self.repo, urllib.parse.quote(rel.tag, safe=""))
        build = (fetch_text(url) or "").strip()
        if not BUILD_RE.fullmatch(build):
            raise ResolveError("llama.cpp %s: nightly-tag.txt is not a bNNNN build name" % rel.tag)
        return build


# Known dependencies. Hermes resolution lives here so Hermes wiring only calls resolve().
SOURCES = {
    "llama.cpp": LlamaCppReleases,
    "hermes-agent": lambda: GitHubReleases("NousResearch/hermes-agent"),
}


def source(source_id):
    if not isinstance(source_id, str):
        raise ChannelError("invalid source id %r" % (source_id,))
    if source_id in SOURCES:
        return SOURCES[source_id]()
    if source_id.startswith("github:") and _valid_repo(source_id[7:]):
        return GitHubReleases(source_id[7:])
    if source_id.startswith("hf:") and _valid_repo(source_id[3:]):
        return HFCommits(source_id[3:])
    raise ChannelError("unknown source %r: use one of %s, github:OWNER/REPO or hf:ORG/NAME"
                       % (source_id, ", ".join(sorted(SOURCES))))


# ---------------------------------------------------------------- selection

def candidates(releases, asset_re=None):
    rx = re.compile(asset_re) if asset_re else None
    out = []
    for r in releases:
        if r.draft or r.prerelease or PRERELEASE_RE.search(r.tag) or not valid_tag(r.tag):
            continue
        if rx is not None and not any(rx.search(a) for a in r.assets):
            continue
        out.append(r)
    return sorted(out, key=lambda r: r.published)


def select(releases, channel, days, now, asset_re=None):
    """Return (Release, fallback: bool, reason: str). Pure; no network."""
    cands = candidates(releases, asset_re)
    if not cands:
        raise ResolveError("no non-prerelease release found")
    if channel == "bleeding":
        return cands[-1], False, "bleeding: newest non-prerelease"
    start = now - _dt.timedelta(days=days)
    soak = {}
    for i, r in enumerate(cands):
        nxt = cands[i + 1].published if i + 1 < len(cands) else now
        soak[r] = nxt - r.published
    window = [r for r in cands if start <= r.published <= now]
    ripe = [r for r in window if soak[r] >= MIN_SOAK]
    if ripe:
        best = ripe[-1]  # cands is sorted by publish time: newest qualifying in the window
        return best, False, "stable: newest release of the last %d days that soaked %s (%s)" % (
            days, _fmt(MIN_SOAK), _fmt(soak[best]))
    why = "no release in the last %d days soaked %s" % (days, _fmt(MIN_SOAK)) if window \
        else "no release in the last %d days" % days
    older = [r for r in cands if r.published < start]
    older_ripe = [r for r in older if soak[r] >= MIN_SOAK]
    if older_ripe:
        return older_ripe[-1], True, "stable fallback: %s; newest qualifying release before the window" % why
    if older:
        return older[-1], True, "stable fallback: %s; nothing before the window soaked %s either; newest release before the window" % (why, _fmt(MIN_SOAK))
    return window[-1], True, "stable fallback: %s; nothing older than the window; newest release in it" % why


def _fmt(td):
    h = int(td.total_seconds() // 3600)
    return "%dd%02dh" % (h // 24, h % 24)


def resolve(source_id, channel=None, days=None, *, now=None, fetch=None, fetch_text=None,
            asset_re=None, environ=None):
    """Resolve one dependency to a validated ref for the effective channel. See module doc.
    fetch(url)->JSON and fetch_text(url)->str are injectable (tests mock the network)."""
    ch, n = effective(channel, days, environ)
    src = source(source_id)
    if asset_re is not None and (not isinstance(asset_re, str) or len(asset_re) > 200):
        raise ChannelError("invalid asset pattern")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = now - _dt.timedelta(days=n) if ch == "stable" else None
    rels = src.releases(fetch or http_get_json, since=since)
    rel, fb, why = src.pick(rels, ch, n, now, asset_re)
    ref = src.finalize(rel, fetch_text or http_get_text)
    ok = SHA_RE.fullmatch(ref) if src.kind == "commit" else valid_tag(ref)
    if not ok:  # defense in depth: pick()/finalize() already filtered
        raise ResolveError("resolved name failed validation")
    if fb:
        _log("%s: %s" % (source_id, why))
    return ResolvedRef(source_id, ch, n, ref, src.kind,
                       rel.published.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), fb, why,
                       rel.tag)


# ---------------------------------------------------------------- record (user-owned, no system temp dir)

def state_dir(environ=None):
    env = os.environ if environ is None else environ
    base = env.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "familia", "channel")


def record(ref, directory=None):
    d = directory or state_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.stat(d)
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise ResolveError("state dir is not owned by this user: %s" % d)
    work = tempfile.mkdtemp(prefix=".run-", dir=d)
    try:
        tmp = os.path.join(work, "r.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ref.to_dict(), f, indent=1, sort_keys=True)
        dest = os.path.join(d, re.sub(r"[^A-Za-z0-9._-]", "_", ref.source) + ".json")
        os.replace(tmp, dest)
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(prog="channel.py", description="familia release channels (bleeding | stable)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="print the validated ref for SOURCE")
    r.add_argument("source")
    r.add_argument("--channel")
    r.add_argument("--days")
    r.add_argument("--asset-re", help="require a release asset matching this regex (llama.cpp platform)")
    r.add_argument("--json", action="store_true")
    r.add_argument("--no-record", action="store_true")
    sub.add_parser("show", help="effective channel and days")
    sub.add_parser("sources", help="known source ids")
    a = p.parse_args(argv)
    try:
        if a.cmd == "show":
            ch, n = effective()
            print("channel=%s stable_days=%d" % (ch, n))
            return 0
        if a.cmd == "sources":
            print("\n".join(sorted(SOURCES) + ["github:OWNER/REPO", "hf:ORG/NAME"]))
            return 0
        ref = resolve(a.source, a.channel, a.days, asset_re=a.asset_re)
    except ChannelError as e:
        _log("error: %s" % e)
        return 2
    except (ResolveError, re.error) as e:
        _log("error: %s" % e)
        return 1
    _log("%s -> %s%s (%s, published %s)" % (ref.source, ref.ref,
                                             "" if ref.release == ref.ref else " from " + ref.release,
                                             ref.reason, ref.published_at))
    if not a.no_record:
        try:
            record(ref)
        except (OSError, ResolveError) as e:
            _log("warning: could not write record: %s" % e)
    print(json.dumps(ref.to_dict(), sort_keys=True) if a.json else ref.ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
