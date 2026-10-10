"""Shared loader + checks for graph.yaml `hosts:` and `meshes:` (familia #5, #22).

The key names the object, the edge names how it moves (DESIGN.md Transports).
Nothing here picks a transport: callers name one, and it must be declared.
"""
import ipaddress, os, yaml

TRANSPORT_TYPES = {"ssh", "bittorrent"}
HOST_KEYS = ("addr", "user", "port", "kind")

def load(path):
    g = yaml.safe_load(open(path)); g["_path"] = path; return g

def host(g, name):
    h = (g.get("hosts") or {}).get(name)
    if h is None: raise SystemExit(f"transport: host {name!r} is not declared in hosts:")
    return h

def transport(g, name, want):
    t = (g.get("meshes") or {}).get(name)
    if t is None: raise SystemExit(f"transport: {name!r} is not declared in meshes:")
    if t.get("type") != want: raise SystemExit(f"transport: {name!r} is type {t.get('type')!r}, need {want!r}")
    return t

def _lan(addr):
    try: ip = ipaddress.ip_address(addr)
    except ValueError: return False
    return (ip.is_private or ip.is_loopback) and not ip.is_unspecified

def validate_transports(g):
    errs, hosts = [], g.get("hosts") or {}
    meshes = g.get("meshes") or {}
    used = {m for t in meshes.values() for m in (t.get("members") or [])} | \
           {t.get(k) for t in meshes.values() for k in ("hub", "tracker")}
    for hn, h in hosts.items():
        for k in (HOST_KEYS if hn in used else ()):
            if k not in h: errs.append(f"host {hn}: missing required '{k}' (no defaults)")
        if "password" in h: errs.append(f"host {hn}: 'password' is not allowed; transports are key-only")
    for tn, t in meshes.items():
        ty = t.get("type")
        if ty not in TRANSPORT_TYPES:
            errs.append(f"transport {tn}: type {ty!r} not one of {sorted(TRANSPORT_TYPES)}"); continue
        if "password" in t: errs.append(f"transport {tn}: 'password' is not allowed; key-only")
        members = t.get("members") or []
        if not members: errs.append(f"transport {tn}: no members")
        for m in members:
            if m not in hosts: errs.append(f"transport {tn}: member {m!r} is not a declared host")
        if ty == "ssh":
            for k in ("hub", "root", "identity", "host_key_policy"):
                if k not in t: errs.append(f"transport {tn}: missing required '{k}'")
            if t.get("hub") not in hosts: errs.append(f"transport {tn}: hub {t.get('hub')!r} is not a declared host")
            if t.get("host_key_policy") not in ("accept-new", "yes"):
                errs.append(f"transport {tn}: host_key_policy must be accept-new or yes (never no)")
        else:
            for k in ("tracker", "bind", "port", "client", "private"):
                if k not in t: errs.append(f"transport {tn}: missing required '{k}'")
            if t.get("tracker") not in hosts: errs.append(f"transport {tn}: tracker {t.get('tracker')!r} is not a declared host")
            if "bind" in t and not _lan(str(t["bind"])):
                errs.append(f"transport {tn}: bind {t['bind']!r} must be a loopback or private LAN address (not 0.0.0.0/public)")
            th = hosts.get(t.get("tracker")) or {}
            if "bind" in t and th.get("addr") and str(t["bind"]) != str(th["addr"]) and not str(t["bind"]).startswith("127."):
                errs.append(f"transport {tn}: bind {t['bind']} != tracker host addr {th['addr']}")
            if t.get("client") not in ("aria2c",):
                errs.append(f"transport {tn}: client {t.get('client')!r} unsupported (PoC: aria2c)")
            if t.get("private") is not True: errs.append(f"transport {tn}: private must be true (no DHT/PEX/LPD leaks)")
    return errs
