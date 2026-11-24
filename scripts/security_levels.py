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


def load_state(path):
    if path is None or not Path(path).is_file():
        return empty_state()
    try:
        raw = _yaml_load(path)
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
    for k in ("enable", "disable", "confirmed"):
        v = raw.get(k) or []
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise SecurityLevelError(f"{path}: {k} must be a list of set names")
        st[k] = sorted(set(v))
    return st


def dump_state(state):
    lines = ["# familia security level override (local, never commit). Written by `familia security`.",
             "# docs/security-levels.md. Delete this file (or `familia security clear`) for graph.yaml as declared."]
    if state.get("level"):
        lines.append(f'level: "{state['level']}"')
    for k in ("enable", "disable", "confirmed"):
        if state.get(k):
            lines.append(f"{k}: [{', '.join(sorted(state[k]))}]")
    return "\n".join(lines) + "\n"


def write_state(path, state):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(dump_state(state), encoding="utf-8")
    os.replace(tmp, p)


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
    # Confirm-required sets (pentest) need a recorded typed confirmation.
    for s in list(enabled):
        if spec["sets"][s].get("confirm") and s not in (state.get("confirmed") or []):
            enabled.remove(s); disabled.append(s)
            warnings.append(f"set {s} stays off: it needs a typed confirmation once on a terminal "
                            f"(`familia security enable {s}`); a flag or env var cannot confirm it")

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
    isatty = isatty if isatty is not None else (lambda: sys.stdin.isatty())
    ask = ask or input
    if not isatty():
        raise SecurityLevelError(
            f"turning on set {sname} needs a typed confirmation on a terminal; there is no --yes. "
            f"Run `familia security enable {sname}` in a terminal")
    print(f"familia-security: set {sname}: {spec['sets'][sname].get('description', '')}", file=sys.stderr)
    print("familia-security: owned-fleet scope only. Seats stay operator-start only "
          "(FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh ... --operator-start) with tools.allow empty.", file=sys.stderr)
    try:
        got = ask(f"Type {sname} to turn it on: ")
    except EOFError:
        got = ""
    if got.strip() != sname:
        raise SecurityLevelError(f"not confirmed; set {sname} left off and nothing was written")


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
    new = _new_state_for(cmd, arg, state, spec)
    want_on = _sets_on(spec, new, graph)
    # Keep a confirmation only while its set stays on; turning it back on asks again.
    new["confirmed"] = sorted(s for s in new.get("confirmed") or [] if s in want_on)
    for s in want_on:
        if spec["sets"][s].get("confirm") and s not in new["confirmed"]:
            _confirm(s, spec, isatty=isatty, ask=ask)
            new["confirmed"] = sorted(set(new["confirmed"]) | {s})
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
    print(f"familia-security: wrote {path}; graph.yaml unchanged", file=out)
    for key, e in p["entries"].items():
        print(f"  [{'on ' if e['status'] == 'active' else 'off'}] {key}  {e['why']}", file=out)
    for w in p["warnings"]:
        print(f"  note: {w}", file=out)
    if os.environ.get(ENV_LEVEL) and environ is None:
        print(f"familia-security: note: {ENV_LEVEL} is set and wins over this file for now", file=out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="familia security",
        description="Security node levels: presets and toggles over graph.yaml (docs/security-levels.md). "
                    "graph.yaml is never rewritten; there is no --yes.")
    ap.add_argument("--graph", default=str(ROOT / "graph.yaml"))
    ap.add_argument("--spec", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", metavar="LEVEL|status|list|enable|disable|clear")
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
    except SecurityLevelError as e:
        print(f"familia-security: ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
