#!/usr/bin/env python3
"""Familia fleet host IDs (canonical host key; hostname is a display label only).

ID format:  <label-slug>-<fp8>      host UUID: 128-bit RFC 4122 string
  d = sha256("familia-hostid-v1|<anchor_type>|<anchor>").hexdigest()
  host_uuid = d[:32] shaped as a version-4 UUID (version nibble 4, variant 10xx)
  fp8 = d[:8] = first 8 hex of host_uuid
  anchor_type state-uuid: the stored random v4 UUID is the host UUID itself and
  fp8 is its first 8 hex (no hashing). This is how a host with no readable
  hardware serial is pinned (registry host_uuid; optional device file via --init).

The anchor is a stable identifier that is the same over every transport (USB,
Wi-Fi, ethernet), so one physical device always resolves to one ID. IP
addresses and (on phones) MACs are never primary anchors. Raw anchors never
leave this module: only the salted 8-hex fingerprint is printed or stored.
The fingerprint is the dedupe key; the label prefix is cosmetic, so a rename
(phone7 -> galaxy1) still matches the same registry entry.

Anchor order (same as scripts/fleet/hostid.sh):
  android-serial, soc-serial, android-id, machine-id, hostuuid (FreeBSD),
  platform-uuid (macOS), machine-guid (Windows), state-uuid, mac, hostname (weak)

CLI:
  hostid.py [--label NAME] [--json]        print this host's ID (read-only)
  hostid.py --uuid                         print this host's 128-bit host UUID
  hostid.py --init [--init-value UUID]     create $XDG_STATE_HOME/familia/host-uuid if
                                           no hardware anchor exists (opt-in write)
  hostid.py resolve NAME [--registry F]    map a label/alias/ssh alias/ID to its host ID
  hostid.py check [--registry F] [--graph G]  validate registry + graph host_id links
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path

SALT = "familia-hostid-v1"
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry" / "fleet-hosts.yaml"
GRAPH = ROOT / "graph.yaml"
ANCHOR_TYPES = ("android-serial", "soc-serial", "android-id", "machine-id", "hostuuid",
                "platform-uuid", "machine-guid", "state-uuid", "mac", "hostname")
WEAK = ("mac", "hostname")
BAD = {"", "unknown", "0", "00000000", "0123456789abcdef", "null",
       "00000000-0000-0000-0000-000000000000"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}-[0-9a-f]{8}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SKIP_NIC = re.compile(r"^(lo|docker|veth|br|virbr|tun|tap|wg|rndis|usb|vnet|dummy|bond|tailscale|zt)")


def slug(label: str | None) -> str:
    s = (label or "").split(".")[0].lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")[:24]
    return "host" if s in ("", "localhost") else s


def host_uuid(anchor_type: str, anchor: str) -> str:
    """128-bit RFC 4122 (version 4 layout) host UUID; never reveals the raw anchor."""
    if anchor_type not in ANCHOR_TYPES:
        raise ValueError("unknown anchor type %r" % anchor_type)
    raw = "".join(anchor.split()).lower()
    if anchor_type == "state-uuid":
        u = str(uuid.UUID(raw)).lower()
        if not UUID_RE.match(u):
            raise ValueError("state-uuid must be a version-4 UUID")
        return u
    d = hashlib.sha256(("%s|%s|%s" % (SALT, anchor_type, raw)).encode()).hexdigest()
    v = "89ab"[int(d[16], 16) & 3]
    return "%s-%s-4%s-%s%s-%s" % (d[0:8], d[8:12], d[13:16], v, d[17:20], d[20:32])


def fingerprint(anchor_type: str, anchor: str) -> str:
    return host_uuid(anchor_type, anchor)[:8]


def make_id(label: str | None, anchor_type: str | None, anchor: str | None) -> dict:
    """Build an ID record; a missing/bogus anchor falls back to a weak label hash."""
    s = slug(label)
    a = "".join((anchor or "").split()).lower()
    if not anchor_type or a in BAD:
        anchor_type, a = "hostname", s
    if anchor_type == "state-uuid":
        try:
            u = host_uuid(anchor_type, a)
        except ValueError:
            anchor_type, a = "hostname", s
            u = host_uuid(anchor_type, a)
    else:
        u = host_uuid(anchor_type, a)
    fp = u[:8]
    return {"host_id": "%s-%s" % (s, fp), "host_uuid": u, "label": s, "fingerprint": fp,
            "anchor_type": anchor_type, "weak": anchor_type in WEAK}


def fp_of(host_id: str) -> str:
    return host_id.rsplit("-", 1)[-1]


# ------------------------------------------------------------ local anchor
def _read(p: str) -> str:
    try:
        with open(p, encoding="ascii", errors="ignore") as f:
            return f.read(64).strip()
    except OSError:
        return ""


def _cmd(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def state_dir(environ=None) -> Path:
    env = os.environ if environ is None else environ
    if sys.platform == "win32":
        return Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "familia"
    x = (env.get("XDG_STATE_HOME") or "").strip()
    return (Path(x) if x else Path.home() / ".local" / "state") / "familia"


def local_anchor(environ=None) -> tuple[str | None, str | None]:
    """Return (anchor_type, raw_anchor) for this machine. Read-only."""
    cands = []
    if _cmd(["sh", "-c", "command -v getprop"]):
        cands += [("android-serial", lambda: _cmd(["getprop", "ro.serialno"])),
                  ("android-serial", lambda: _cmd(["getprop", "ro.boot.serialno"])),
                  ("soc-serial", lambda: _read("/sys/devices/soc0/serial_number")),
                  ("android-id", lambda: _cmd(["settings", "get", "secure", "android_id"]))]
    cands += [("machine-id", lambda: _read("/etc/machine-id")),
              ("machine-id", lambda: _read("/var/lib/dbus/machine-id")),
              ("hostuuid", lambda: _cmd(["sysctl", "-n", "kern.hostuuid"]) if sys.platform.startswith("freebsd") else ""),
              ("hostuuid", lambda: _read("/etc/hostid")),
              ("platform-uuid", _mac_platform_uuid),
              ("machine-guid", _windows_guid),
              ("state-uuid", lambda: _read(str(state_dir(environ) / "host-uuid"))),
              ("mac", _nic_mac)]
    for t, fn in cands:
        v = "".join((fn() or "").split()).lower()
        if v not in BAD and "notfound" not in v and "exception" not in v:
            return t, v
    return None, None


def _mac_platform_uuid() -> str:
    if sys.platform != "darwin":
        return ""
    m = re.search(r'"IOPlatformUUID" = "([^"]+)"', _cmd(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]))
    return m.group(1) if m else ""


def _windows_guid() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg  # type: ignore
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                           0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
        return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except OSError:
        return ""


def _nic_mac() -> str:
    base = Path("/sys/class/net")
    try:
        names = sorted(p.name for p in base.iterdir())
    except OSError:
        return ""
    for n in names:
        if SKIP_NIC.match(n) or not (base / n / "device").exists():
            continue
        v = _read(str(base / n / "address"))
        if v and v != "00:00:00:00:00:00":
            return v
    return ""


def local_label(explicit: str | None = None, environ=None) -> str:
    env = os.environ if environ is None else environ
    if explicit:
        return explicit
    if env.get("FAMILIA_HOST_LABEL"):
        return env["FAMILIA_HOST_LABEL"]
    pin = _read(str(state_dir(env) / "hostname")).splitlines()
    return pin[0] if pin and pin[0] else socket.gethostname()


def local_id(label: str | None = None) -> dict:
    t, a = local_anchor()
    return make_id(local_label(label), t, a)


def init_state_uuid(environ=None, value: str | None = None) -> Path | None:
    """Create a persistent random anchor only when no hardware anchor exists.

    value: the host_uuid already pinned in registry/fleet-hosts.yaml, so the device
    then reports the same ID the registry uses (galaxy1/galaxy2)."""
    t, _ = local_anchor(environ)
    if t not in (None, "mac"):
        return None
    p = state_dir(environ) / "host-uuid"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        u = host_uuid("state-uuid", value) if value else str(uuid.uuid4())
        p.write_text(u + "\n", encoding="ascii")
    return p


# ------------------------------------------------------------ registry
def load_yaml(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_registry(path: Path | str = REGISTRY) -> dict:
    return (load_yaml(Path(path)).get("hosts") or {})


def names_of(hid: str, e: dict) -> list[str]:
    out = [hid, e.get("label") or ""] + list(e.get("aliases") or []) + list(e.get("previous_ids") or [])
    out += [t.get("ssh_alias") for t in (e.get("transports") or []) if t.get("ssh_alias")]
    if e.get("graph_host"):
        out.append(e["graph_host"])
    return [n for n in out if n]


def resolve(name: str, reg: dict) -> str | None:
    """Label, alias, ssh alias, graph key, current or previous ID -> canonical host ID."""
    if name in reg:
        return name
    for hid, e in reg.items():
        if name in names_of(hid, e):
            return hid
    if ID_RE.match(name):  # same device under another label (label drift)
        for hid, e in reg.items():
            if fp_of(name) in [fp_of(hid)] + [fp_of(x) for x in (e.get("previous_ids") or [])]:
                return hid
    return None


def merge_observations(obs: list[dict], reg: dict | None = None) -> dict:
    """Dedupe probe observations by fingerprint.

    obs items: {"host_id", "anchor_type", "alias", "transport"} as reported by the
    device itself over one transport. Returns {host_id: entry} with every transport
    kept as a list under one entry. A known registry entry keeps its ID and label.
    """
    reg = reg or {}
    out: dict[str, dict] = {}
    by_fp: dict[str, str] = {}
    for o in obs:
        fp = fp_of(o["host_id"])
        known = resolve(o["host_id"], reg)
        hid = by_fp.get(fp) or known or o["host_id"]
        by_fp[fp] = hid
        e = out.setdefault(hid, {"label": (reg.get(hid) or {}).get("label") or hid.rsplit("-", 1)[0],
                                 "fingerprint": fp, "anchor_type": o.get("anchor_type"),
                                 "aliases": [], "transports": []})
        a = o.get("alias")
        if a and a not in e["aliases"]:
            e["aliases"].append(a)
        t = {"kind": o.get("transport") or "unknown", "ssh_alias": a}
        if t not in e["transports"]:
            e["transports"].append(t)
    return out


def check(reg: dict, graph: dict | None = None) -> list[str]:
    errs = []
    seen_fp: dict[str, str] = {}
    seen_name: dict[str, str] = {}
    seen_uuid: dict[str, str] = {}
    for hid, e in reg.items():
        if not ID_RE.match(hid):
            errs.append("%s: bad id format" % hid)
            continue
        if e.get("fingerprint") != fp_of(hid):
            errs.append("%s: fingerprint field %r != id suffix" % (hid, e.get("fingerprint")))
        if e.get("anchor_type") not in ANCHOR_TYPES:
            errs.append("%s: anchor_type %r not in %s" % (hid, e.get("anchor_type"), ANCHOR_TYPES))
        if e.get("anchor_type") == "hostname" and fingerprint("hostname", hid.rsplit("-", 1)[0]) != fp_of(hid):
            errs.append("%s: weak hostname id does not match its label" % hid)
        u = str(e.get("host_uuid") or "")
        if not UUID_RE.match(u):
            errs.append("%s: host_uuid %r is not a lowercase RFC 4122 version-4 UUID" % (hid, u))
        elif u[:8] != fp_of(hid):
            errs.append("%s: host_uuid prefix %s != id suffix" % (hid, u[:8]))
        elif e.get("anchor_type") == "hostname" and host_uuid("hostname", hid.rsplit("-", 1)[0]) != u:
            errs.append("%s: weak host_uuid does not match its label" % hid)
        elif u in seen_uuid:
            errs.append("%s: duplicate host_uuid (same as %s)" % (hid, seen_uuid[u]))
        if UUID_RE.match(u):
            seen_uuid.setdefault(u, hid)
        for old in e.get("previous_ids") or []:
            if not ID_RE.match(old):
                errs.append("%s: previous id %r has a bad format" % (hid, old))
            elif fp_of(old) in seen_fp and seen_fp[fp_of(old)] != hid:
                errs.append("%s: previous id %s collides with %s" % (hid, old, seen_fp[fp_of(old)]))
            else:
                seen_fp[fp_of(old)] = hid
        if fp_of(hid) in seen_fp:
            errs.append("%s: duplicate device (same fingerprint as %s)" % (hid, seen_fp[fp_of(hid)]))
        seen_fp[fp_of(hid)] = hid
        for n in set(names_of(hid, e)):
            if n in seen_name and seen_name[n] != hid:
                errs.append("name %r maps to both %s and %s" % (n, seen_name[n], hid))
            seen_name[n] = hid
    if graph is not None:
        for gk, gh in (graph.get("hosts") or {}).items():
            gh = gh or {}
            hid = gh.get("host_id")
            if not hid:
                errs.append("graph host %s: missing host_id" % gk)
            elif hid not in reg:
                errs.append("graph host %s: host_id %s not in registry" % (gk, hid))
            elif gk not in names_of(hid, reg[hid]):
                errs.append("graph host %s: not listed as label/alias of %s" % (gk, hid))
        by_id: dict[str, list[str]] = {}
        for gk, gh in (graph.get("hosts") or {}).items():
            if gh and gh.get("host_id"):
                by_id.setdefault(gh["host_id"], []).append(gk)
        for hid, keys in by_id.items():
            primary = [k for k in keys if not (graph["hosts"][k] or {}).get("alias_of")]
            if len(primary) > 1:
                errs.append("graph hosts %s share host_id %s; mark legacy ones alias_of" % (primary, hid))
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="id", choices=["id", "resolve", "check"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--label")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--uuid", action="store_true", help="print the host UUID instead of the ID")
    ap.add_argument("--init-value", help="with --init: the registry host_uuid to store")
    ap.add_argument("--registry", default=str(REGISTRY))
    ap.add_argument("--graph", default=str(GRAPH))
    a = ap.parse_args(argv)
    if a.cmd == "resolve":
        hid = resolve(a.name or "", load_registry(a.registry))
        if not hid:
            print("unknown host: %s" % a.name, file=sys.stderr)
            return 1
        print(hid)
        return 0
    if a.cmd == "check":
        errs = check(load_registry(a.registry), load_yaml(Path(a.graph)) if a.graph else None)
        for e in errs:
            print("ERROR " + e)
        print("ok" if not errs else "%d error(s)" % len(errs))
        return 1 if errs else 0
    if a.init:
        p = init_state_uuid(value=a.init_value)
        print("created/kept %s" % p if p else "hardware anchor present; nothing written")
    r = local_id(a.label)
    print(json.dumps(r) if a.json else r["host_uuid"] if a.uuid else r["host_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
