#!/usr/bin/env python3
"""hermes_pin.py: the one hook that picks which hermes-agent release familia targets.

resolve_ref(channel=None, days=None, *, offline=False) -> dict
  1. When scripts/channel.py (release channels: FAMILIA_CHANNEL=bleeding|stable, FAMILIA_STABLE_DAYS=N)
     is present, it validates channel/days and, unless offline, resolves the 'hermes-agent' source
     (channel.resolve). A network failure there falls back to the pin below (fallback=True).
  2. Otherwise (or offline) the channel-keyed pin in config/hermes-agent.pins.json is used.
     Default channel: bleeding. Nothing else in familia hardcodes a Hermes ref.
Result keys: channel, days, ref, commit (None when the ref is not one of the pins), source
('channel.py' | 'pin-file'), fallback, reason, python (minimum interpreter for that hermes).

CLI (stdout = the ref only, or JSON with --json; reasons on stderr):
  python3 scripts/hermes_pin.py resolve [--channel C] [--days N] [--offline] [--json]
  python3 scripts/hermes_pin.py check [--bin PATH] [--channel C] [--offline]   installed vs wanted;
      on a mismatch prints the upstream install.sh --commit command (familia never installs hermes)
Exit codes: 0 ok / match; 1 mismatch or nothing resolved; 2 invalid input.
Stdlib only. This file never edits scripts/channel.py; it only imports it when present.
"""
import argparse, importlib.util, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINS = os.path.join(ROOT, "config", "hermes-agent.pins.json")
CHANNEL_PY = os.path.join(ROOT, "scripts", "channel.py")
SOURCE = "hermes-agent"
CHANNELS = ("bleeding", "stable")
REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", re.ASCII)
COMMIT_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)   # full sha1: pins are pasted into a shell install hint
VERSION_RE = re.compile(r"\bv(\d+\.\d+\.\d+)\b.*?\blocal ([0-9a-f]{7,40})\b|\bv(\d+\.\d+\.\d+)\b", re.ASCII)


class PinError(ValueError):
    """Invalid channel/days or pin file (exit 2)."""


def _log(msg):
    print("hermes_pin: " + msg, file=sys.stderr)


def load_pins(path=PINS):
    """The pin file, validated. Every problem (unreadable, not JSON, bad shape) is a PinError with
    the path, never a traceback: refs match REF_RE, commits are 40 lowercase hex (or absent), and
    both channels must be present (a missing stable entry is an error, not a silent bleeding)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise PinError("pin file %s: cannot read (%s)" % (path, e.strerror or e))
    except (ValueError, UnicodeDecodeError) as e:   # json.JSONDecodeError is a ValueError
        raise PinError("pin file %s: not valid JSON (%s)" % (path, e))
    if not isinstance(data, dict) or not isinstance(data.get("channels"), dict):
        raise PinError("pin file %s: no channels object" % path)
    chans = data["channels"]
    for name, e in chans.items():
        if name not in CHANNELS or not isinstance(e, dict) or not isinstance(e.get("ref"), str) \
                or not REF_RE.fullmatch(e["ref"]) or ".." in e["ref"]:
            raise PinError("pin file %s: bad entry %r" % (path, name))
        c = e.get("commit")
        if c is not None and not (isinstance(c, str) and COMMIT_RE.fullmatch(c)):
            raise PinError("pin file %s: channel %r commit must be 40 lowercase hex, got %r" % (path, name, c))
    missing = [c for c in CHANNELS if c not in chans]
    if missing:
        raise PinError("pin file %s: no %s entry" % (path, " / ".join(missing)))
    py = data.get("python")
    if py is not None and not (isinstance(py, str) and re.fullmatch(r"\d+\.\d+", py, re.ASCII)):
        raise PinError("pin file %s: python must be like 3.14, got %r" % (path, py))
    return data


def channel_module(path=CHANNEL_PY):
    """The release-channel resolver module when its file exists, else None (never raises on absence)."""
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("familia_channel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod if callable(getattr(mod, "resolve", None)) else None


def _own_effective(channel, days, environ):
    env = os.environ if environ is None else environ
    c = channel if channel is not None else (env.get("FAMILIA_CHANNEL") or "bleeding")
    if c not in CHANNELS:
        raise PinError("invalid channel %r: must be one of %s" % (c, ", ".join(CHANNELS)))
    d = days if days is not None else (env.get("FAMILIA_STABLE_DAYS") or None)
    return c, _validate_days(d)


DAYS_MIN, DAYS_MAX, DEFAULT_DAYS = 1, 365, 30   # same bounds as scripts/channel.py


def _validate_days(d):
    """None/'' -> 30; otherwise a base-10 integer 1..365 (int or ASCII digits), else PinError (exit 2),
    like scripts/channel.py validate_days. Never silently 30, never unbounded."""
    if d is None or d == "":
        return DEFAULT_DAYS
    if isinstance(d, bool) or not (isinstance(d, int) or (isinstance(d, str) and re.fullmatch(r"[0-9]{1,3}", d, re.ASCII))):
        raise PinError("invalid stable days %r: must be an integer %d..%d" % (d, DAYS_MIN, DAYS_MAX))
    n = int(d)
    if not DAYS_MIN <= n <= DAYS_MAX:
        raise PinError("invalid stable days %r: must be an integer %d..%d" % (d, DAYS_MIN, DAYS_MAX))
    return n


def _pin_entry(pins, ch):
    e = pins["channels"].get(ch)
    if e is None:   # injected pins (tests); load_pins already refuses a file without both channels
        raise PinError("no %s entry in the pin file" % ch)
    return e


def resolve_ref(channel=None, days=None, *, offline=False, environ=None, pins=None, chmod=False):
    """See module doc. chmod: injected channel module (tests); False = load scripts/channel.py."""
    pins = pins or load_pins()
    mod = channel_module() if chmod is False else chmod
    if mod is not None:
        try:
            ch, n = mod.effective(channel, days, environ)
        except getattr(mod, "ChannelError", ValueError) as e:
            raise PinError(str(e))
    else:
        ch, n = _own_effective(channel, days, environ)
    pin = _pin_entry(pins, ch)
    out = {"channel": ch, "days": n, "ref": pin["ref"], "commit": pin.get("commit"), "source": "pin-file",
           "fallback": False, "reason": "%s pin (%s)" % (ch, pin.get("note", "config/hermes-agent.pins.json")),
           "python": pins.get("python")}
    if mod is None or offline:
        if mod is None:
            out["reason"] += "; scripts/channel.py not present"
        return out
    try:
        r = mod.resolve(SOURCE, ch, n)
    except getattr(mod, "ChannelError", ()) as e:
        raise PinError(str(e))
    except Exception as e:  # ResolveError / network: keep the channel's pin
        out.update(fallback=True, reason="channel.py could not resolve (%s); using the %s pin" % (e, ch))
        _log(out["reason"])
        return out
    ref = getattr(r, "ref", None)
    if not (isinstance(ref, str) and REF_RE.fullmatch(ref) and ".." not in ref):
        raise PinError("channel.py returned an invalid ref %r" % (ref,))
    by_ref = {e["ref"]: e for e in pins["channels"].values()}
    out.update(ref=ref, commit=(by_ref.get(ref) or {}).get("commit"), source="channel.py",
               fallback=bool(getattr(r, "fallback", False)), reason=getattr(r, "reason", ""),
               published_at=getattr(r, "published_at", None))
    return out


def installed_version(bin_path, run=subprocess.run, env=None):
    """(version 'vX.Y.Z' or None, short commit or None) from `<bin> --version` (full CLI only)."""
    try:
        r = run([bin_path, "--version"], capture_output=True, text=True, timeout=120, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    m = VERSION_RE.search((r.stdout or "") + "\n" + (r.stderr or ""))
    if not m:
        return None, None
    return "v" + (m.group(1) or m.group(3)), m.group(2)


def matches(want, version, commit):
    if want.get("commit") and commit and want["commit"].startswith(commit):
        return True
    return bool(version) and version == want["ref"]


# install.sh fetched from the pinned commit itself (scripts/install.sh upstream), never the moving
# https://hermes-agent.nousresearch.com/install.sh, so the script that runs is the one that was pinned.
# Download, then run (familia never prints a pipe-to-shell install; tests/test_install_polish.py).
INSTALL_SH_AT = "https://raw.githubusercontent.com/NousResearch/hermes-agent/%s/scripts/install.sh"


def install_hint(want, bin_path=""):
    """How to put the wanted ref in place. familia never installs hermes itself. Only a validated
    40-hex commit is ever printed in the install line (a crafted pin cannot inject shell)."""
    if str(bin_path).startswith("/snap/") or str(bin_path).startswith("/usr/local/bin/"):
        return ("this hermes comes from a snap/ports package, which follows its own version; "
                "install the upstream build (below) and set HERMES_BIN, or accept the mismatch")
    c = want.get("commit")
    ref = want.get("ref") if isinstance(want.get("ref"), str) and REF_RE.fullmatch(want["ref"]) else "?"
    if isinstance(c, str) and COMMIT_RE.fullmatch(c):
        return ("curl -fsSLo hermes-install.sh %s && bash hermes-install.sh --commit %s   # %s"
                % (INSTALL_SH_AT % c, c, ref))
    return ("git ls-remote https://github.com/NousResearch/hermes-agent refs/tags/%s   # then, with that sha: "
            "curl -fsSLo hermes-install.sh %s && bash hermes-install.sh --commit <sha>" % (ref, INSTALL_SH_AT % "<sha>"))


def main(argv=None):
    p = argparse.ArgumentParser(prog="hermes_pin.py", description="familia's hermes-agent pin hook")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("resolve", "check"):
        s = sub.add_parser(name)
        s.add_argument("--channel"); s.add_argument("--days"); s.add_argument("--offline", action="store_true")
        if name == "resolve":
            s.add_argument("--json", action="store_true")
        else:
            s.add_argument("--bin", help="hermes CLI to ask (default: the harness resolution)")
    a = p.parse_args(argv)
    try:
        want = resolve_ref(a.channel, a.days, offline=a.offline)
    except PinError as e:
        _log("error: %s" % e); return 2
    except (OSError, ValueError) as e:
        _log("error: %s" % e); return 1
    if a.cmd == "resolve":
        _log("%s -> %s (%s; %s)" % (want["channel"], want["ref"], want["source"], want["reason"]))
        print(json.dumps(want, sort_keys=True) if a.json else want["ref"])
        return 0
    bin_path = a.bin
    if not bin_path:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import hermes_harness as hh
        bin_path = hh.resolve_hermes(missing="die")[0]
    ver, commit = installed_version(bin_path)
    ok = matches(want, ver, commit)
    print("%s: installed %s (%s), wanted %s (%s, channel %s)" % ("ok" if ok else "MISMATCH", ver or "unknown",
          commit or "?", want["ref"], (want.get("commit") or "?")[:12], want["channel"]))
    if not ok:
        print("to install it: " + install_hint(want, bin_path))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
