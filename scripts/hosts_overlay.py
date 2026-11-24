#!/usr/bin/env python3
"""Local host connection overlay for familia (#104).

Tracked graph.yaml must not carry RFC1918/link-local/ULA addresses, Termux
u0_a* accounts, or fleet-specific login names. Real addr/user/port (and mesh
bind) live in an untracked overlay merged at load time.

Lookup order (first existing file wins):
  1. $FAMILIA_HOSTS_OVERLAY (explicit path)
  2. XDG/Windows config: hosts.local.yaml
       POSIX:  $XDG_CONFIG_HOME/familia/hosts.local.yaml
               (default ~/.config/familia/hosts.local.yaml; Termux uses $HOME)
       Windows: %LOCALAPPDATA%\\familia\\hosts.local.yaml
  3. Repo-root hosts.local.yaml next to graph.yaml (gitignored)

Connection keys merged under hosts.<name>: addr, user, port.
Under meshes.<name>: bind (optional; also auto-filled from tracker host addr
when bind is a placeholder after merge).

Machine-local hostname pin (scripts/hostname_pin.py) is separate: it selects
which graph host this machine is, not how to reach peers.
"""
from __future__ import annotations

import ipaddress
import os
import re
import sys
from pathlib import Path

CONNECTION_HOST_KEYS = ("addr", "user", "port")
CONNECTION_MESH_KEYS = ("bind",)

PLACEHOLDERS = frozenset({
    "REPLACE_ME", "replace_me", "TBD", "tbd", "<addr>", "<user>", "<hub-lan-ip>",
    "<phone7-lan-ip>", "<phone8-lan-ip>", "<hub-user>", "<termux-user>",
    "<ssh-port>", "",
})

# IPv4 / IPv6 literals that look like addresses in free text.
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_RE = re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b")
_TERMUX_USER_RE = re.compile(r"\bu0_a\d+\b")


def is_placeholder(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in PLACEHOLDERS
    return False


def config_dir(environ=None) -> Path:
    """POSIX XDG config or Windows LOCALAPPDATA familia dir (same family as monitor.json)."""
    env = os.environ if environ is None else environ
    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "familia"
    xdg = (env.get("XDG_CONFIG_HOME") or "").strip()
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "familia"


def default_overlay_path(environ=None) -> Path:
    return config_dir(environ) / "hosts.local.yaml"


def resolve_overlay_path(graph_path=None, environ=None) -> Path | None:
    """Return the overlay file to load, or None when none exists."""
    env = os.environ if environ is None else environ
    explicit = (env.get("FAMILIA_HOSTS_OVERLAY") or "").strip()
    if explicit:
        p = Path(os.path.expanduser(explicit))
        return p if p.is_file() else None
    cfg = default_overlay_path(env)
    if cfg.is_file():
        return cfg
    if graph_path:
        root = Path(graph_path).resolve().parent
        repo = root / "hosts.local.yaml"
        if repo.is_file():
            return repo
    return None


def _load_yaml(path: Path):
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except OSError:
        return {}


def load_overlay(graph_path=None, environ=None, path=None) -> dict:
    """Load overlay mapping (may be empty). Keys: hosts, meshes."""
    if path is not None:
        p = Path(path)
        return _load_yaml(p) if p.is_file() else {}
    p = resolve_overlay_path(graph_path=graph_path, environ=environ)
    return _load_yaml(p) if p else {}


def merge_connection_overlay(graph: dict, overlay: dict | None = None,
                             graph_path=None, environ=None) -> dict:
    """Merge connection fields from overlay into graph in place; return graph.

    Only addr/user/port on hosts and bind on meshes are overwritten from the
    overlay. Other host hardware fields stay tracked. When meshes.*.bind is
    still a placeholder after merge and the tracker host has a real addr, bind
    is filled from that addr so operators need not duplicate it.
    """
    if overlay is None:
        overlay = load_overlay(graph_path=graph_path or graph.get("_path"),
                               environ=environ)
    if not overlay:
        _fill_mesh_bind_from_tracker(graph)
        return graph

    hosts = graph.setdefault("hosts", {})
    for name, oh in (overlay.get("hosts") or {}).items():
        if not isinstance(oh, dict):
            continue
        dest = hosts.setdefault(name, {})
        if not isinstance(dest, dict):
            continue
        for k in CONNECTION_HOST_KEYS:
            if k in oh and oh[k] is not None and not is_placeholder(oh[k]):
                dest[k] = oh[k]

    meshes = graph.setdefault("meshes", {})
    for name, om in (overlay.get("meshes") or {}).items():
        if not isinstance(om, dict):
            continue
        dest = meshes.setdefault(name, {})
        if not isinstance(dest, dict):
            continue
        for k in CONNECTION_MESH_KEYS:
            if k in om and om[k] is not None and not is_placeholder(om[k]):
                dest[k] = om[k]

    _fill_mesh_bind_from_tracker(graph)
    return graph


def _fill_mesh_bind_from_tracker(graph: dict) -> None:
    hosts = graph.get("hosts") or {}
    for _tn, t in (graph.get("meshes") or {}).items():
        if not isinstance(t, dict) or t.get("type") != "bittorrent":
            continue
        if not is_placeholder(t.get("bind")):
            continue
        th = hosts.get(t.get("tracker")) or {}
        addr = th.get("addr")
        if addr and not is_placeholder(addr):
            t["bind"] = addr


def _private_ip_literal(token: str) -> str | None:
    """Return the token if it is a private/link-local/ULA IP, else None."""
    try:
        ip = ipaddress.ip_address(token)
    except ValueError:
        return None
    if ip.is_private or ip.is_link_local or ip.is_loopback:
        # Loopback in tracked fleet graph is also undesirable as a "real dest",
        # but 127.0.0.1 appears in node bind fields intentionally. Only flag
        # RFC1918 / link-local / ULA here; loopback checked separately for
        # hosts.addr / meshes.bind.
        if ip.is_loopback:
            return None
        return token
    return None


def _scan_text_for_private(text: str, path_label: str) -> list[str]:
    errs = []
    for m in _IPV4_RE.finditer(text):
        tok = m.group(0)
        # Skip version-like false positives (e.g. Windows 10.0.19045) by requiring
        # a real private classification.
        bad = _private_ip_literal(tok)
        if bad:
            # Allow CIDR-ish only when clearly a /prefix in pentest fixtures? Still
            # private — reject in tracked graph.yaml body.
            errs.append(f"{path_label}: private/link-local address {bad!r} must not appear in tracked config (#104)")
    for m in _IPV6_RE.finditer(text):
        tok = m.group(0)
        # Avoid matching bare times / git shas: require at least two colons handled by regex
        if tok.count(":") < 2:
            continue
        bad = _private_ip_literal(tok)
        if bad:
            errs.append(f"{path_label}: private/link-local address {bad!r} must not appear in tracked config (#104)")
    for m in _TERMUX_USER_RE.finditer(text):
        errs.append(f"{path_label}: Termux account {m.group(0)!r} must not appear in tracked config (#104)")
    return errs


def _check_host_fields(graph: dict, path_label: str) -> list[str]:
    errs = []
    for name, h in (graph.get("hosts") or {}).items():
        if not isinstance(h, dict):
            continue
        addr = h.get("addr")
        if addr is not None and not is_placeholder(addr):
            if _private_ip_literal(str(addr)) or _IPV4_RE.fullmatch(str(addr).strip()) or ":" in str(addr):
                # Any concrete IP in tracked hosts.addr is rejected (use overlay).
                try:
                    ipaddress.ip_address(str(addr).strip())
                    errs.append(f"{path_label}: hosts.{name}.addr={addr!r} must be a placeholder or omitted (#104)")
                except ValueError:
                    pass  # hostname-like; still discourage fleet DNS — allow non-IP for now
        user = h.get("user")
        if user is not None and not is_placeholder(user):
            if _TERMUX_USER_RE.search(str(user)) or str(user).strip() not in PLACEHOLDERS:
                # Fleet-specific login names belong in the overlay only.
                errs.append(f"{path_label}: hosts.{name}.user={user!r} must be a placeholder or omitted (#104)")
        port = h.get("port")
        # Ports alone are low sensitivity; still prefer overlay. No hard fail on
        # well-known 22/8022 — privacy focus is addr/user. (Acceptance allows omit.)
        _ = port
    for name, t in (graph.get("meshes") or {}).items():
        if not isinstance(t, dict):
            continue
        bind = t.get("bind")
        if bind is not None and not is_placeholder(bind):
            try:
                ipaddress.ip_address(str(bind).strip())
                errs.append(f"{path_label}: meshes.{name}.bind={bind!r} must be a placeholder or omitted (#104)")
            except ValueError:
                pass
    return errs


def privacy_lint_graph(graph: dict, path_label: str = "graph.yaml",
                       raw_text: str | None = None) -> list[str]:
    """Reject private connection literals in a tracked graph (no overlay applied)."""
    errs = _check_host_fields(graph, path_label)
    if raw_text is not None:
        # Deduplicate while preserving order
        seen = set(errs)
        for e in _scan_text_for_private(raw_text, path_label):
            if e not in seen:
                errs.append(e)
                seen.add(e)
    return errs


def privacy_lint_path(path, skip_overlay_files=True) -> list[str]:
    """Lint a YAML file on disk for private connection literals."""
    p = Path(path)
    name = p.name
    if skip_overlay_files and name in ("hosts.local.yaml", "graph.local.yaml", "monitor.json"):
        return []
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        return [f"{p}: {e}"]
    data = _load_yaml(p)
    return privacy_lint_graph(data if isinstance(data, dict) else {}, path_label=str(p), raw_text=raw)


def load_graph_with_overlay(path, loader=None, environ=None, apply_overlay=True):
    """Load graph YAML from path and merge the connection overlay.

    loader: optional callable(path)->dict; default uses PyYAML via familia_yaml
    when available, else yaml.safe_load.
    """
    if loader is not None:
        g = loader(path) or {}
    else:
        try:
            import familia_yaml
            g = familia_yaml.load(path) or {}
        except Exception:
            g = _load_yaml(Path(path))
    if not isinstance(g, dict):
        g = {}
    g["_path"] = path
    if apply_overlay:
        merge_connection_overlay(g, graph_path=path, environ=environ)
    return g


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="familia hosts connection overlay (#104)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_path = sub.add_parser("path", help="print resolved overlay path (or default if missing)")
    p_path.add_argument("--graph", default="graph.yaml")
    p_lint = sub.add_parser("lint", help="privacy-lint a tracked graph (no overlay)")
    p_lint.add_argument("graph", nargs="?", default="graph.yaml")
    p_show = sub.add_parser("show", help="print merged hosts addr/user/port for debugging")
    p_show.add_argument("--graph", default="graph.yaml")
    a = ap.parse_args(argv)
    if a.cmd == "path":
        p = resolve_overlay_path(graph_path=a.graph)
        print(p if p else default_overlay_path())
        return 0 if p else 1
    if a.cmd == "lint":
        errs = privacy_lint_path(a.graph)
        for e in errs:
            print(f"privacy: ERROR: {e}", file=sys.stderr)
        return 1 if errs else 0
    if a.cmd == "show":
        g = load_graph_with_overlay(a.graph)
        for name, h in sorted((g.get("hosts") or {}).items()):
            if not isinstance(h, dict):
                continue
            bits = {k: h.get(k) for k in CONNECTION_HOST_KEYS if k in h}
            if bits:
                print(f"{name}: {bits}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
