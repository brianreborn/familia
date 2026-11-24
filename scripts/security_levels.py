#!/usr/bin/env python3
"""familia security: named levels for the security nodes, without editing graph.yaml.

  familia security status            what is on, what is off, and why
  familia security list              the levels and sets (config/security-levels.yaml)
  familia security LEVEL             off | guardian | pentest | full (writes the local override)
  familia security enable SET        turn one set on  (guardian | pentest | other)
  familia security disable SET       turn one set off
  familia security clear             remove the local override (graph.yaml as declared)
  familia start --security-level=LEVEL     one run only; FAMILIA_SECURITY_LEVEL=LEVEL does the same

The level is a load-time overlay (docs/security-levels.md). graph.yaml is never rewritten.
Per-node risk tiers (low, medium, high) are `familia security tier`. A node
process cannot raise its own tier or a preset. See docs/security-levels.md.
Only `status` (active/planned) of security nodes and pentest seats changes; roles, aliases,
escalation, tools and seatbelts are untouched, so the fail-closed rules hold at every level.
Turning the pentest set on needs a typed confirmation on a terminal; there is no --yes.

Override file lookup (first existing wins, same family as hosts.local.yaml):
  1. $FAMILIA_SECURITY_OVERRIDE
  2. $XDG_CONFIG_HOME/familia/security.local.yaml (Windows: %LOCALAPPDATA%\\familia\\)
  3. security.local.yaml next to graph.yaml (gitignored)
Precedence for the level: --security-level > FAMILIA_SECURITY_LEVEL > override file > graph.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

SPEC_PATH = ROOT / "config" / "security-levels.yaml"
OVERRIDE_NAME = "security.local.yaml"
ENV_LEVEL = "FAMILIA_SECURITY_LEVEL"
ENV_OVERRIDE = "FAMILIA_SECURITY_OVERRIDE"
GRAPH_LEVEL = "graph"  # no override: graph.yaml as declared
FAIL_CLOSED = ("guardian", "pentest", "defender")


class SecurityLevelError(Exception):
    """A clear, user-facing error (bad level, bad override file, missing model, no terminal)."""


# ---------------------------------------------------------------- data file

def _yaml_load(path):
    try:
        import familia_yaml
        return familia_yaml.load(str(path)) or {}
    except ImportError:  # pragma: no cover
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}


def load_spec(path=None):
    p = Path(path) if path else SPEC_PATH
    try:
        spec = _yaml_load(p)
    except OSError as e:
        raise SecurityLevelError(f"cannot read {p}: {e}") from e
    if not isinstance(spec, dict) or not isinstance(spec.get("sets"), dict) or not isinstance(spec.get("levels"), dict):
        raise SecurityLevelError(f"{p}: needs `sets:` and `levels:` mappings")
    sets = spec["sets"]
    for name, s in sets.items():
        if not isinstance(s, dict):
            raise SecurityLevelError(f"{p}: sets.{name} must be a mapping")
        for r in s.get("requires") or []:
            if r not in sets:
                raise SecurityLevelError(f"{p}: sets.{name}.requires names unknown set {r!r}")
    for name, lv in spec["levels"].items():
        if name == GRAPH_LEVEL:
            raise SecurityLevelError(f"{p}: level name {GRAPH_LEVEL!r} is reserved")
        for s in (lv or {}).get("sets") or []:
            if s not in sets:
                raise SecurityLevelError(f"{p}: levels.{name} names unknown set {s!r}")
        for s in (lv or {}).get("sets") or []:
            for r in sets[s].get("requires") or []:
                if r not in lv["sets"]:
                    raise SecurityLevelError(f"{p}: levels.{name} has {s!r} without its required set {r!r}")
    return spec


def level_names(spec):
    return list(spec["levels"])


def check_level(spec, level, where="security level"):
    if level not in spec["levels"]:
        raise SecurityLevelError(
            f"unknown {where} {level!r}; choose one of: {', '.join(level_names(spec))} "
            f"(see `familia security list`)")
    return level


# ---------------------------------------------------------------- override file

def _config_dir(environ):
    import hosts_overlay  # reuse the #104 private-override location
    return hosts_overlay.config_dir(environ)


def resolve_override_path(graph_path=None, environ=None, for_write=False):
    """Path of the local override. for_write: where a new one goes when none exists."""
    env = os.environ if environ is None else environ
    explicit = (env.get(ENV_OVERRIDE) or "").strip()
    if explicit:
        return Path(os.path.expanduser(explicit))
    cfg = _config_dir(env) / OVERRIDE_NAME
    if cfg.is_file():
        return cfg
    repo = Path(graph_path).resolve().parent / OVERRIDE_NAME if graph_path else ROOT / OVERRIDE_NAME
    if repo.is_file():
        return repo
    return cfg if for_write else None


def empty_state():
    return {"level": None, "enable": [], "disable": [], "confirmed": []}


def _read_override(path):
    """Read the override with O_NOFOLLOW. Refuse a symlink, a foreign owner, or a loose mode."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise SecurityLevelError("%s: cannot open the override (%s)" % (path, exc.errno)) from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SecurityLevelError("%s: refusing a symlink override" % path)
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise SecurityLevelError("%s: override is not owned by the operator" % path)
        if st.st_mode & 0o077:
            raise SecurityLevelError("%s: override must be mode 0600 or 0400" % path)
        data = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8")
    finally:
        os.close(fd)


def load_state(path):
    if path is None or not os.path.lexists(path):
        return empty_state()
    try:
        text = _read_override(path)
        import familia_yaml
        raw = familia_yaml.loads(text) or {}
    except SecurityLevelError:
        raise
    except Exception as e:  # malformed file: refuse, never guess
        raise SecurityLevelError(f"{path}: cannot parse ({e}); fix it or run `familia security clear`") from e
    if raw in (None, ""):
        return empty_state()
    if not isinstance(raw, dict):
        raise SecurityLevelError(f"{path}: must be a mapping (level:, enable:, disable:)")
    unknown = set(raw) - {"level", "enable", "disable", "confirmed"}
    if unknown:
        raise SecurityLevelError(f"{path}: unknown keys {', '.join(sorted(unknown))}")
    st = empty_state()
    lv = raw.get("level")
    if lv is False:  # hand-written `level: off` is a YAML 1.1 boolean
        lv = "off"
    if lv is not None and not isinstance(lv, str):
        raise SecurityLevelError(f"{path}: level must be a level name, got {lv!r}")
    st["level"] = lv or None
    for k in ("enable", "disable"):
        v = raw.get(k) or []
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise SecurityLevelError(f"{path}: {k} must be a list of set names")
        st[k] = sorted(set(v))
    # `confirmed:` is not a grant. A file that lists it does not turn the set on.
    st["confirmed"] = []
    return st


def dump_state(state):
    lines = ["# familia security level override (local, never commit). Written by `familia security`.",
             "# docs/security-levels.md. Delete this file (or `familia security clear`) for graph.yaml as declared."]
    if state.get("level"):
        lines.append(f'level: "{state['level']}"')
    for k in ("enable", "disable"):
        if state.get(k):
            lines.append(f"{k}: [{', '.join(sorted(state[k]))}]")
    return "\n".join(lines) + "\n"


def write_state(path, state):
    p = Path(path)
    parent = p.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise SecurityLevelError("%s: refusing a symlink directory" % parent)
    if p.is_symlink():
        raise SecurityLevelError("%s: refusing a symlink override" % p)
    tmp = p.with_name(p.name + ".tmp")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(tmp), flags, 0o600)
    try:
        os.write(fd, dump_state(state).encode("utf-8"))
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(p))


# ---------------------------------------------------------------- graph membership

def _norm(role):
    import unicodedata
    if not isinstance(role, str) or not role:
        return role
    return unicodedata.normalize("NFKC", role).casefold()


def _node_role(graph, name):
    n = (graph.get("nodes") or {}).get(name) or {}
    if n.get("role"):
        return _norm(n["role"])
    m = (graph.get("models") or {}).get(n.get("model")) or {}
    return _norm(m.get("role"))


def _is_fail_closed(graph, name):
    n = (graph.get("nodes") or {}).get(name) or {}
    m = (graph.get("models") or {}).get(n.get("model")) or {}
    return _norm(n.get("role")) in FAIL_CLOSED or _norm(m.get("role")) in FAIL_CLOSED


def set_members(graph, spec):
    """{set: [("nodes"|"pentests", key), ...]} in data-file order; a key belongs to its first matching set."""
    nodes = graph.get("nodes") or {}
    pentests = graph.get("pentests") or {}
    taken = set()
    out = {}
    for sname, s in spec["sets"].items():
        mem = []
        roles = {_norm(r) for r in s.get("node_roles") or []}
        for n in nodes:
            k = ("nodes", n)
            if k in taken:
                continue
            if n in (s.get("nodes") or []) or (roles and _node_role(graph, n) in roles) \
                    or (s.get("fail_closed") and _is_fail_closed(graph, n)):
                mem.append(k)
        want = s.get("pentests")
        for p in pentests:
            k = ("pentests", p)
            if k in taken:
                continue
            if want == "*" or (isinstance(want, list) and p in want):
                mem.append(k)
        taken.update(mem)
        out[sname] = mem
    return out


# ---------------------------------------------------------------- the overlay

def resolve_source(state, level=None, environ=None):
    """(level or None, source label). None = graph as declared (plus file enable/disable)."""
    env = os.environ if environ is None else environ
    if level:
        return level, "--security-level"
    if (env.get(ENV_LEVEL) or "").strip():
        return env[ENV_LEVEL].strip(), ENV_LEVEL
    if state.get("level"):
        return state["level"], "override file"
    if state.get("enable") or state.get("disable"):
        return None, "override file"
    return None, None


def plan(graph, spec=None, state=None, level=None, environ=None, override_path=None):
    """Compute the effective status of every security entry. Pure: does not touch graph.

    Returns {"level", "source", "override", "enabled_sets", "entries": {"nodes.X": {...}}, "warnings"}.
    Each entry: status (effective), declared (graph.yaml), changed, why.
    """
    spec = spec or load_spec()
    if state is None:
        override_path = override_path or resolve_override_path(graph.get("_path"), environ)
        state = load_state(override_path)
    lvl, source = resolve_source(state, level, environ)
    if lvl is not None:
        check_level(spec, lvl, "security level" + (f" (from {source})" if source else ""))
    members = set_members(graph, spec)
    from_file = source == "override file"
    warnings = []

    if lvl is not None:
        enabled = list(spec["levels"][lvl].get("sets") or [])
    else:
        enabled = []
    if from_file:
        for s in state.get("enable") or []:
            if s not in spec["sets"]:
                raise SecurityLevelError(f"override enables unknown set {s!r}")
            if s not in enabled:
                enabled.append(s)
    disabled = list(state.get("disable") or []) if from_file else []
    for s in disabled:
        if s not in spec["sets"]:
            raise SecurityLevelError(f"override disables unknown set {s!r}")
    enabled = [s for s in enabled if s not in disabled]  # disable wins (fail closed)
    # A set that requires another set is only on with it.
    changed_req = True
    while changed_req:
        changed_req = False
        for s in list(enabled):
            missing = [r for r in spec["sets"][s].get("requires") or [] if r not in enabled]
            if missing:
                enabled.remove(s); disabled.append(s); changed_req = True
                warnings.append(f"set {s} stays off: it needs set {', '.join(missing)} on")
    # Confirm-required sets stay off unless a signed, unexpired grant is in the tier state.
    # A `confirmed:` list in the override is ignored.
    import security_tier
    env = os.environ if environ is None else environ
    key_path = (env.get(security_tier.ADMIN_KEY_ENV) or "").strip()
    granted = []
    if key_path and os.path.isabs(key_path):
        try:
            key = security_tier._read_key(key_path, security_tier._forbidden_roots(None, None, env))
            granted = security_tier.active_grants(security_tier.state_file(env), key)
        except security_tier.TierError:
            granted = []
    for s in list(enabled):
        if spec["sets"][s].get("confirm") and s not in granted:
            enabled.remove(s); disabled.append(s)
            warnings.append(f"set {s} stays off: it needs a signed grant from a terminal nonce "
                            f"(`familia security enable {s}`); a flag, env var, or confirmed: list cannot turn it on")

    entries = {}
    if source is None:
        return {"level": GRAPH_LEVEL, "source": None, "override": str(override_path) if override_path else None,
                "enabled_sets": [], "entries": entries, "warnings": warnings, "members": members}
    for sname, mem in members.items():
        for section, key in mem:
            declared = ((graph.get(section) or {}).get(key) or {}).get("status") or "planned"
            if sname in enabled:
                status, why = "active", f"set {sname} is on" + (f" (level {lvl})" if lvl and sname in (spec['levels'][lvl].get('sets') or []) else " (enable)")
            elif sname in disabled or lvl is not None:
                status, why = "planned", f"set {sname} is off" + (f" (level {lvl})" if lvl else " (disable)")
            else:
                status, why = declared, "as declared in graph.yaml"
            entries[f"{section}.{key}"] = {"set": sname, "status": status, "declared": declared, "why": why}
    # A pentest seat is only on when its node is on (after the overlay).
    for key, e in entries.items():
        if not key.startswith("pentests.") or e["status"] != "active":
            continue
        node = ((graph.get("pentests") or {}).get(key.split(".", 1)[1]) or {}).get("node")
        nstat = entries.get(f"nodes.{node}", {}).get("status") \
            or ((graph.get("nodes") or {}).get(node) or {}).get("status")
        if nstat != "active":
            e["status"], e["why"] = "planned", f"its node {node} is off"
    for e in entries.values():
        e["changed"] = e["status"] != e["declared"]
    return {"level": lvl or GRAPH_LEVEL, "source": source,
            "override": str(override_path) if override_path else None,
            "enabled_sets": enabled, "entries": entries, "warnings": warnings, "members": members}


def apply(graph, level=None, environ=None, spec=None, state=None, quiet=True):
    """Merge the effective security level into graph in place (status only). Returns the plan.
    With no flag, no env and no override file this is a no-op."""
    p = plan(graph, spec=spec, state=state, level=level, environ=environ)
    for key, e in p["entries"].items():
        section, name = key.split(".", 1)
        graph[section][name]["status"] = e["status"]
    if not quiet:
        for w in p["warnings"]:
            print(f"familia-security: {w}", file=sys.stderr)
    return p


# ---------------------------------------------------------------- model files

def _this_host(graph, environ=None):
    try:
        import start_graph
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            return start_graph.select_host(graph, environ=environ)
    except Exception:
        return None


def model_state(graph, node, host):
    """('present'|'missing'|'remote'|'unknown', path shown with ~)."""
    n = (graph.get("nodes") or {}).get(node) or {}
    m = (graph.get("models") or {}).get(n.get("model")) or {}
    gguf = m.get("gguf") or ""
    if not gguf:
        return "unknown", ""
    if host is None:
        return "unknown", gguf
    if n.get("host") != host:
        return "remote", gguf
    return ("present" if Path(os.path.expanduser(gguf)).is_file() else "missing"), gguf


def missing_models(graph, p, host):
    """Errors for nodes this plan turns on, on this host, whose model file is absent."""
    errs = []
    for key, e in p["entries"].items():
        if not key.startswith("nodes.") or e["status"] != "active":
            continue
        node = key.split(".", 1)[1]
        st, path = model_state(graph, node, host)
        if st == "missing":
            model = graph["nodes"][node].get("model")
            errs.append(f"node {node} needs model {model} at {path}, which is not on this machine. "
                        f"Fetch it first: python3 scripts/activate_guardian_weights.py (docs/guardian-weights.md), "
                        f"or pass --no-files to set the level anyway")
    return errs


# ---------------------------------------------------------------- CLI

def _load_graph(path):
    import hosts_overlay
    g = hosts_overlay.load_graph_with_overlay(str(path))
    if not isinstance(g.get("nodes"), dict):
        raise SecurityLevelError(f"{path}: no nodes")
    return g


def _confirm(sname, spec, isatty=None, ask=None):
    import secrets
    import security_tier
    ask = ask or input
    if not security_tier.is_real_tty(isatty if isatty is not None else None):
        raise SecurityLevelError(
            f"turning on set {sname} needs a typed nonce on a terminal; there is no --yes. "
            f"Run `familia security enable {sname}` in a terminal")
    nonce = secrets.token_hex(16)
    print(f"familia-security: set {sname}: {spec['sets'][sname].get('description', '')}", file=sys.stderr)
    print("familia-security: owned-fleet scope only. Seats stay operator-start only "
          "(FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh ... --operator-start) with tools.allow empty.", file=sys.stderr)
    try:
        got = ask("Type nonce %s to turn on %s: " % (nonce, sname))
    except EOFError:
        got = ""
    if got.strip() != nonce:
        raise SecurityLevelError(f"not confirmed; set {sname} left off and nothing was written")
    return nonce


def _print_status(graph, p, host, out=None):
    out = out or sys.stdout
    src = p["source"] or "no override (graph.yaml as declared)"
    print(f"security level: {p['level']}  (source: {src})", file=out)
    if p["override"]:
        print(f"override file: {p['override']}", file=out)
    print(f"sets on: {', '.join(p['enabled_sets']) or 'none'}", file=out)
    rows = p["entries"]
    if not rows:  # no override: report the security entries as declared
        for sname, mem in p["members"].items():
            for section, key in mem:
                st = ((graph.get(section) or {}).get(key) or {}).get("status") or "planned"
                rows[f"{section}.{key}"] = {"set": sname, "status": st, "declared": st,
                                            "why": "as declared in graph.yaml", "changed": False}
    for key, e in rows.items():
        mark = "on " if e["status"] == "active" else "off"
        extra = ""
        if key.startswith("nodes."):
            node = key.split(".", 1)[1]
            nd = graph["nodes"][node]
            ms, _path = model_state(graph, node, host)
            extra = f"  host={nd.get('host')} model={ms}"
        delta = f" (graph.yaml: {e['declared']})" if e.get("changed") else ""
        print(f"  [{mark}] {key:<28} set={e['set']:<9} {e['why']}{delta}{extra}", file=out)
    for w in p["warnings"]:
        print(f"  note: {w}", file=out)
    print("always, at every level: guardian/pentest/defender are never started by `familia start`, never a "
          "gateway route or escalation target; pentest seats are operator-start only.", file=out)


def _new_state_for(cmd, arg, state, spec):
    st = {k: (list(v) if isinstance(v, list) else v) for k, v in state.items()}
    if cmd == "level":
        st = empty_state() | {"confirmed": list(state.get("confirmed") or [])}
        st["level"] = arg
    elif cmd == "enable":
        st["disable"] = [s for s in st["disable"] if s != arg]
        if arg not in st["enable"]:
            st["enable"].append(arg)
    elif cmd == "disable":
        st["enable"] = [s for s in st["enable"] if s != arg]
        if arg not in st["disable"]:
            st["disable"].append(arg)
    for k in ("enable", "disable"):
        st[k] = sorted(set(st[k]))
    return st


def _sets_on(spec, state, graph):
    """Sets the given state would turn on, ignoring confirmation (to know what needs confirming)."""
    lvl = state.get("level")
    on = list(spec["levels"][lvl].get("sets") or []) if lvl else []
    on += [s for s in state.get("enable") or [] if s not in on]
    return [s for s in on if s not in (state.get("disable") or [])]


def change(graph, spec, path, cmd, arg, check_files=True, environ=None, isatty=None, ask=None, out=None):
    out = out or sys.stdout
    if cmd == "level":
        check_level(spec, arg)
    elif arg not in spec["sets"]:
        raise SecurityLevelError(f"unknown set {arg!r}; choose one of: {', '.join(spec['sets'])}")
    state = load_state(path)
    import security_tier
    env_for_raise = os.environ if environ is None else environ
    new = _new_state_for(cmd, arg, state, spec)
    want_on = _sets_on(spec, new, graph)
    new["confirmed"] = []
    if security_tier.preset_is_raise(cmd, arg, state):
        try:
            roots = security_tier._forbidden_roots(None, None, env_for_raise)
            key_path = (env_for_raise.get(security_tier.ADMIN_KEY_ENV) or "").strip() or None
            key = security_tier.require_admin_context(env_for_raise, key_path, roots, isatty)
        except security_tier.TierError as exc:
            raise SecurityLevelError(str(exc)) from exc
        exp = str(int(__import__("time").time()) + security_tier.GRANT_TTL)
        for s in want_on:
            if spec["sets"][s].get("confirm"):
                nonce = _confirm(s, spec, isatty=isatty, ask=ask)
                try:
                    security_tier.record_set_grant(
                        security_tier.state_file(env_for_raise), key, s, nonce, exp)
                except security_tier.TierError as exc:
                    raise SecurityLevelError(str(exc)) from exc
    env = dict(os.environ if environ is None else environ)
    env.pop(ENV_LEVEL, None)  # show what the file itself does
    g2 = json.loads(json.dumps({k: v for k, v in graph.items() if not k.startswith("_")}))
    p = plan(g2, spec=spec, state=new, environ=env, override_path=path)
    if check_files:
        errs = missing_models(graph, p, _this_host(graph, environ))
        if errs:
            raise SecurityLevelError("; ".join(errs))
    if new == state and Path(path).is_file():
        print(f"familia-security: no change (already {p['level']}"
              f"{'; sets on: ' + ', '.join(p['enabled_sets']) if p['enabled_sets'] else ''})", file=out)
        return 0
    write_state(path, new)
    try:
        security_tier.audit_preset(state, new, cmd, arg, env_for_raise)
    except security_tier.TierError as exc:
        raise SecurityLevelError("audit log: %s" % exc) from exc
    print(f"familia-security: wrote {path}; graph.yaml unchanged", file=out)
    for key, e in p["entries"].items():
        print(f"  [{'on ' if e['status'] == 'active' else 'off'}] {key}  {e['why']}", file=out)
    for w in p["warnings"]:
        print(f"  note: {w}", file=out)
    if os.environ.get(ENV_LEVEL) and environ is None:
        print(f"familia-security: note: {ENV_LEVEL} is set and wins over this file for now", file=out)
    return 0


def _add_tier_parsers(sub):
    """familia security tier: per-node low/medium/high. Does not rewrite graph.yaml."""
    pt = sub.add_parser("tier", help="per-node risk tier (low, medium, high); see docs/security-levels.md")
    pt.add_argument("--state", default=None, help="tier state file (default $FAMILIA_NODE_TIER_STATE or the state dir)")
    pt.add_argument("--audit", default=None, help="append-only audit log (default $FAMILIA_SECURITY_AUDIT)")
    tsub = pt.add_subparsers(dest="tier_cmd", required=True)
    show = tsub.add_parser("show", help="show one node's tier (default low)")
    show.add_argument("--host", required=True)
    show.add_argument("--node", required=True)
    listed = tsub.add_parser("list", help="list recorded tiers")
    del listed
    tsub.add_parser("types", help="list node types and the tier each one allows")
    tsub.add_parser("schema", help="check config/security-levels.yaml against its schema")
    tsub.add_parser("audit-check", help="check the append-only audit log")
    grant = tsub.add_parser("grant-line", help="print a confirm-file line; this does not change a tier")
    esc = tsub.add_parser("escalate", help="raise a tier; needs a confirm file, or an admin token for high")
    de = tsub.add_parser("de-escalate", help="lower a tier; local, including from the node itself")
    mint = tsub.add_parser("mint-token", help="write an admin token; refused when this process is a node")
    for parser in (grant, esc, mint):
        parser.add_argument("--host", required=True)
        parser.add_argument("--node", required=True)
        parser.add_argument("--type", required=True)
        parser.add_argument("--to", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
    grant.add_argument("--from", dest="old", required=True)
    grant.add_argument("--nonce", required=True)
    grant.add_argument("--exp", default=None)
    de.add_argument("--host", required=True)
    de.add_argument("--node", required=True)
    de.add_argument("--to", required=True)
    de.add_argument("--actor", required=True)
    de.add_argument("--reason", required=True)
    esc.add_argument("--confirm-file", default=None)
    esc.add_argument("--admin-token-file", default=None)
    esc.add_argument("--admin-key-file", default=None)
    mint.add_argument("--from", dest="old", required=True)
    mint.add_argument("--nonce", default=None)
    mint.add_argument("--exp", default=None)
    mint.add_argument("--admin-key-file", required=True)
    mint.add_argument("--out", required=True)


def _admin_key(state_path, audit_path):
    import security_tier
    key_path = (os.environ.get(security_tier.ADMIN_KEY_ENV) or "").strip()
    if not key_path:
        return None
    try:
        return security_tier._read_key(
            key_path, security_tier._forbidden_roots(state_path, audit_path, os.environ))
    except security_tier.TierError:
        return None


def _tier_paths(args):
    import security_tier
    env = os.environ
    state = args.state or security_tier.state_file(env)
    audit = args.audit or security_tier.audit_file(env)
    return state, audit


def _run_tier(spec, args):
    import security_tier
    cmd = args.tier_cmd
    if cmd == "schema":
        security_tier.validate_files(args.spec or str(SPEC_PATH))
        print("node-tier schema: ok")
        return 0
    if cmd == "types":
        for name in sorted(spec["node_types"]):
            info = spec["node_types"][name]
            aliases = ",".join(info["aliases"]) or "-"
            print("%s policy=%s aliases=%s" % (name, info["policy"], aliases))
            for tier in security_tier.TIERS:
                block = info["tiers"][tier]
                modes = ",".join(security_tier.policy_modes(spec, name, tier)) or "-"
                print("  %s arming=%s policy_modes=%s adds=%s" % (
                    tier, block["arming"], modes, ",".join(block["adds"])))
                print("    %s" % block["summary"])
        print("integrity profiles are not risk tiers (#684, #699):")
        for name, levels in spec["integrity_profiles"].items():
            if name == "note":
                print("  note: %s" % levels)
            else:
                print("  %s: %s" % (name, ",".join(levels)))
        return 0
    state_path, audit_path = _tier_paths(args)
    if cmd == "audit-check":
        rows, _prev = security_tier.read_audit(audit_path) if audit_path else ([], "")
        print("audit-check: ok (%d entries)" % len(rows))
        return 0
    if cmd == "show":
        key = _admin_key(state_path, audit_path)
        cur = security_tier.show_tier(spec, state_path, args.host, args.node, key=key, audit_path=audit_path)
        print("host=%s" % cur["host"])
        print("node=%s" % cur["node"])
        print("type=%s" % (cur["type"] or "-"))
        print("tier=%s" % cur["tier"])
        print("source=%s" % cur["source"])
        if cur["type"]:
            print("policy_modes=%s" % (",".join(security_tier.policy_modes(spec, cur["type"], cur["tier"])) or "-"))
        return 0
    if cmd == "list":
        key = _admin_key(state_path, audit_path)
        data, status = security_tier.load_tier_state(state_path, key)
        if status != "verified":
            print("no recorded tiers; unlisted nodes are low")
            return 0
        rows = sorted((data.get("nodes") or {}).values(), key=lambda r: (r["host"], r["node"]))
        if not rows:
            print("no recorded tiers; unlisted nodes are low")
            return 0
        for rec in rows:
            print("%s %s %s %s" % (rec["host"], rec["node"], rec["type"], rec["tier"]))
        return 0
    if cmd == "grant-line":
        blocked = security_tier.caller_blocks_raise(os.environ, args.actor, args.node)
        if blocked:
            raise security_tier.TierError("refusing self-escalate: %s" % blocked)
        security_tier._prepare(spec, args.host, args.node, args.type, args.actor, args.reason)
        if args.old not in security_tier.TIERS or args.to not in security_tier.TIERS:
            raise security_tier.TierError("from and to must be low, medium, or high")
        exp = args.exp or str(int(__import__("time").time()) + security_tier.GRANT_TTL)
        print(security_tier.canonical_grant(
            args.host, args.node, args.type, args.old, args.to, args.actor, args.nonce, args.reason, exp))
        return 0
    if cmd == "escalate":
        event = security_tier.escalate(
            spec, state_path, audit_path, args.host, args.node, args.type, args.to,
            args.actor, args.reason, env=os.environ, confirm=args.confirm_file,
            token=args.admin_token_file, key_path=args.admin_key_file,
        )
        print("%s/%s %s %s -> %s" % (event["host"], event["node"], event["type"], event["old_tier"], event["new_tier"]))
        return 0
    if cmd == "de-escalate":
        event = security_tier.deescalate(
            spec, state_path, audit_path, args.host, args.node, args.to, args.actor, args.reason,
            env=os.environ, key_path=args.admin_key_file if hasattr(args, "admin_key_file") else None,
        )
        print("%s/%s %s %s -> %s" % (event["host"], event["node"], event["type"], event["old_tier"], event["new_tier"]))
        return 0
    if cmd == "mint-token":
        security_tier._prepare(spec, args.host, args.node, args.type, args.actor, args.reason)
        roots = security_tier._forbidden_roots(state_path, audit_path, os.environ)
        key = security_tier.require_admin_context(os.environ, args.admin_key_file, roots)
        cur = security_tier.show_tier(spec, state_path, args.host, args.node, key=key, audit_path=audit_path)
        if args.old != cur["tier"]:
            raise security_tier.TierError("from tier is %s; the node is at %s" % (args.old, cur["tier"]))
        if cur["type"] and cur["type"] != args.type:
            raise security_tier.TierError("type is %s; refusing to relabel" % cur["type"])
        nonce = args.nonce or __import__("secrets").token_hex(16)
        exp = args.exp or str(int(__import__("time").time()) + security_tier.GRANT_TTL)
        line = security_tier.canonical_grant(
            args.host, args.node, args.type, args.old, args.to, args.actor, nonce, args.reason, exp)
        if not os.path.isabs(args.out):
            raise security_tier.TierError("token output path must be absolute")
        security_tier._assert_private_parents(args.out)
        security_tier._outside_roots(args.out, roots, "token output")
        if os.path.lexists(args.out):
            raise security_tier.TierError("token output already exists")
        mac = security_tier.sign_grant(key, line)
        parent = os.path.dirname(args.out)
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            os.write(fd, (line + "\nhmac-sha256 " + mac + "\n").encode("ascii"))
        finally:
            os.close(fd)
        print("wrote %s" % args.out)
        return 0
    raise SecurityLevelError("unknown tier command %r" % (cmd,))


def main(argv=None):
    import security_tier
    ap = argparse.ArgumentParser(
        prog="familia security",
        description="Security node levels and per-node risk tiers (docs/security-levels.md). "
                    "graph.yaml is never rewritten; there is no --yes. "
                    "example: familia security status",
        epilog="example: python3 scripts/security_levels.py tier show --host miryam --node coder")
    ap.add_argument("--graph", default=str(ROOT / "graph.yaml"))
    ap.add_argument("--spec", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", metavar="LEVEL|status|list|enable|disable|clear|tier")
    _add_tier_parsers(sub)
    ps = sub.add_parser("status", help="what is on, what is off, and why")
    ps.add_argument("--json", action="store_true")
    ps.add_argument("--security-level", default=None, help="show the effect of a level without saving it")
    sub.add_parser("list", help="levels and sets")
    for c in ("enable", "disable"):
        pc = sub.add_parser(c, help=f"{c} one set")
        pc.add_argument("set")
        pc.add_argument("--no-files", action="store_true", help="do not check model files on this machine")
    sub.add_parser("clear", help="remove the local override (graph.yaml as declared)")
    sub.add_parser("path", help="print the override file path")
    spec = None
    try:
        spec = load_spec(None)
        for lv in spec["levels"]:
            pl = sub.add_parser(lv, help=(spec["levels"][lv] or {}).get("description"))
            pl.add_argument("--no-files", action="store_true", help="do not check model files on this machine")
        a = ap.parse_args(argv)
        if a.spec:
            spec = load_spec(a.spec)
        cmd = a.cmd or "status"
        if cmd == "list":
            print("levels:")
            for lv, d in spec["levels"].items():
                print(f"  {lv:<9} sets: {', '.join(d.get('sets') or []) or 'none':<24} {d.get('description', '')}")
            print("sets:")
            g = _load_graph(a.graph)
            mem = set_members(g, spec)
            for s, d in spec["sets"].items():
                flags = []
                if d.get("confirm"):
                    flags.append("typed confirm")
                if d.get("requires"):
                    flags.append("needs " + ", ".join(d["requires"]))
                print(f"  {s:<9} {d.get('description', '')}" + (f" [{'; '.join(flags)}]" if flags else ""))
                print(f"            members: {', '.join(f'{x}.{y}' for x, y in mem[s]) or 'none in this graph'}")
            return 0
        path = resolve_override_path(a.graph, for_write=True)
        if cmd == "path":
            print(path)
            return 0
        if cmd == "clear":
            if path.is_file():
                path.unlink()
                print(f"familia-security: removed {path}; graph.yaml as declared")
            else:
                print("familia-security: no override file; graph.yaml as declared")
            return 0
        if cmd == "tier":
            return _run_tier(spec, a)
        g = _load_graph(a.graph)
        if cmd == "status":
            p = plan(g, spec=spec, level=getattr(a, "security_level", None),
                     override_path=path if path.is_file() else None,
                     state=load_state(path if path.is_file() else None))
            if getattr(a, "json", False):
                p = dict(p)
                p["members"] = {k: [f"{x}.{y}" for x, y in v] for k, v in p["members"].items()}
                print(json.dumps(p, indent=2, sort_keys=True))
            else:
                _print_status(g, p, _this_host(g))
            return 0
        if cmd in ("enable", "disable"):
            return change(g, spec, path, cmd, a.set, check_files=not a.no_files)
        return change(g, spec, path, "level", cmd, check_files=not a.no_files)
    except (SecurityLevelError, security_tier.TierError) as e:
        print(f"familia-security: ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
