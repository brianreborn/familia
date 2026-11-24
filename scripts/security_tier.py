#!/usr/bin/env python3
"""Per-node risk tiers for familia security (docs/security-levels.md).

Low is the default. Medium needs an explicit out-of-band confirm file.
High needs an admin-signed token. De-escalate is local. A process with
FAMILIA_NODE_ID or FAMILIA_TIER_CALLER=node cannot raise a tier or a preset.

This is not the integrity axis in #684 / #699. Integrity labels how much an
artifact is trusted. A risk tier labels how much a node is allowed to do.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPEC_PATH = os.path.join(ROOT, "config", "security-levels.yaml")
SCHEMA_PATH = os.path.join(ROOT, "config", "security-levels.schema.json")
TIERS = ("low", "medium", "high")
AUDIT_KEYS = (
    "actor", "factor", "host", "kind", "new_tier", "node", "nonce",
    "old_tier", "prev", "reason", "ts", "type",
)
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_REASON_ENC = re.compile(r"^(?:%[0-9A-F]{2}|[A-Za-z0-9._-])*$")


class TierError(Exception):
    """A refused tier change or a broken catalog. Nothing was written."""


def caller_blocks_raise(env, actor=None, node=None):
    """Why this process may not raise a tier or a preset, or None."""
    env = env or {}
    if env.get("FAMILIA_TIER_CALLER") == "node":
        return "FAMILIA_TIER_CALLER=node"
    if (env.get("FAMILIA_NODE_ID") or "").strip():
        return "FAMILIA_NODE_ID is set"
    if actor is not None and node is not None and actor == node:
        return "actor equals the node id"
    return None


def preset_is_raise(cmd, arg, state):
    """True when a familia security preset command would turn more on."""
    if cmd == "disable":
        return False
    if cmd == "enable":
        return True
    ranks = {"off": 0, "guardian": 1, "pentest": 2, "full": 3}
    new_r = ranks.get(arg, 99)
    old = (state or {}).get("level")
    if not old:
        return new_r > 0
    return new_r > ranks.get(old, -1)


def preset_label(state):
    state = state or {}
    base = state.get("level") or "graph"
    extra = []
    if state.get("enable"):
        extra.append("enable=" + ",".join(state["enable"]))
    if state.get("disable"):
        extra.append("disable=" + ",".join(state["disable"]))
    return base if not extra else base + "+" + "+".join(extra)


# ---------------------------------------------------------------- schema

def _schema_fail(path, msg):
    loc = "/".join(path) or "(root)"
    raise TierError("schema: %s: %s" % (loc, msg))


def _is_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise TierError("schema: unsupported type %s" % name)


def _resolve_ref(root, ref):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise TierError("schema: bad $ref %r" % (ref,))
    target = root
    for part in ref[2:].split("/"):
        target = target[part]
    return target


def check_schema(instance, schema, root=None, path=()):
    """Validate instance against the small JSON Schema subset this catalog uses."""
    root = schema if root is None else root
    if "$ref" in schema:
        return check_schema(instance, _resolve_ref(root, schema["$ref"]), root, path)
    if "const" in schema and instance != schema["const"]:
        _schema_fail(path, "expected %r" % (schema["const"],))
    if "enum" in schema and instance not in schema["enum"]:
        _schema_fail(path, "not one of %r" % (schema["enum"],))
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(instance, t) for t in types):
            _schema_fail(path, "expected %s" % schema["type"])
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            _schema_fail(path, "shorter than %s" % schema["minLength"])
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            _schema_fail(path, "longer than %s" % schema["maxLength"])
        if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
            _schema_fail(path, "does not match %s" % schema["pattern"])
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            _schema_fail(path, "too few items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            _schema_fail(path, "too many items")
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(instance):
                check_schema(item, items, root, path + (str(i),))
        elif isinstance(items, list):
            if len(instance) != len(items):
                _schema_fail(path, "expected %d items" % len(items))
            for i, (item, sub) in enumerate(zip(instance, items)):
                check_schema(item, sub, root, path + (str(i),))
    if isinstance(instance, dict) and (
        "properties" in schema or "patternProperties" in schema or "required" in schema
        or "additionalProperties" in schema or schema.get("type") == "object"
    ):
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            _schema_fail(path, "too few properties")
        for key in schema.get("required") or []:
            if key not in instance:
                _schema_fail(path, "missing %s" % key)
        props = schema.get("properties") or {}
        patterns = [(re.compile(p), sub) for p, sub in (schema.get("patternProperties") or {}).items()]
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                check_schema(value, props[key], root, path + (str(key),))
                continue
            matched = False
            for cre, sub in patterns:
                if cre.fullmatch(str(key)):
                    check_schema(value, sub, root, path + (str(key),))
                    matched = True
                    break
            if matched:
                continue
            if additional is False:
                _schema_fail(path + (str(key),), "unexpected property")
            elif isinstance(additional, dict):
                check_schema(value, additional, root, path + (str(key),))
    return instance


def _load_json(path):
    raw = open(path, "rb").read()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TierError("%s is not ASCII" % path) from exc
    return json.loads(text)


def _load_yaml(path):
    raw = open(path, "rb").read()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TierError("%s is not ASCII" % path) from exc
    import familia_yaml
    data = familia_yaml.loads(text)
    if not isinstance(data, dict):
        raise TierError("%s must be a mapping" % path)
    return data


def validate_catalog(data, schema, repo_root=ROOT):
    check_schema(data, schema)
    types = data["node_types"]
    km = data["kind_map"]
    if data["risk"]["default"] != "low":
        raise TierError("catalog: default risk tier must be low")
    for name, spec in types.items():
        if km.get(name) != name:
            raise TierError("catalog: kind_map[%s] must be %s" % (name, name))
        seen = []
        caps = []
        for tier in TIERS:
            adds = spec["tiers"][tier]["adds"]
            for cap in adds:
                if cap in caps:
                    raise TierError("catalog: capability %s repeated on %s" % (cap, name))
                caps.append(cap)
        for alias in spec["aliases"]:
            if alias in seen:
                raise TierError("catalog: duplicate alias %s on %s" % (alias, name))
            seen.append(alias)
            if km.get(alias) != name:
                raise TierError("catalog: kind_map[%s] must be %s" % (alias, name))
        if spec["policy"] == "pentest-policy" and name != "guardian":
            raise TierError("catalog: only guardian uses the pentest-policy ladder")
    for key, target in km.items():
        if target not in types:
            raise TierError("catalog: kind_map[%s] -> unknown type %s" % (key, target))
        if key != target and key not in types[target]["aliases"]:
            raise TierError("catalog: %s maps to %s but is not an alias" % (key, target))
    modes = []
    for tier in TIERS:
        modes.extend(data["risk"]["policy_ladder"][tier])
    modes.extend(data["risk"]["not_granted"])
    spec_modes = _pentest_modes(repo_root)
    if spec_modes and set(modes) != set(spec_modes):
        raise TierError("catalog: policy ladder %s does not match pentest modes %s" % (modes, spec_modes))
    if "autonomous-lab" in data["risk"]["policy_ladder"]["high"]:
        raise TierError("catalog: high must not grant autonomous-lab")
    return data


def _pentest_modes(repo_root):
    path = os.path.join(repo_root, "docs", "config", "spec", "pentest-policy.schema.yaml")
    if not os.path.isfile(path):
        return []
    import familia_yaml
    doc = familia_yaml.load(path) or {}
    return list(doc.get("modes") or [])


def validate_files(spec_path=SPEC_PATH, schema_path=SCHEMA_PATH, repo_root=ROOT):
    return validate_catalog(_load_yaml(spec_path), _load_json(schema_path), repo_root)


def policy_modes(spec, node_type, tier):
    """Pentest-policy modes this risk tier permits. Empty when the type is not on that ladder."""
    if tier not in TIERS:
        raise TierError("unknown tier %r" % (tier,))
    info = (spec.get("node_types") or {}).get(node_type)
    if not info:
        raise TierError("unknown node type %r" % (node_type,))
    if info.get("policy") != "pentest-policy":
        return []
    return list((spec.get("risk") or {}).get("policy_ladder", {}).get(tier) or [])


def capabilities_for(spec, node_type, tier):
    info = (spec.get("node_types") or {}).get(node_type)
    if not info:
        raise TierError("unknown node type %r" % (node_type,))
    if tier not in TIERS:
        raise TierError("unknown tier %r" % (tier,))
    out = []
    for name in TIERS:
        out.extend(info["tiers"][name]["adds"])
        if name == tier:
            break
    return out


def infer_type(spec, kind):
    if kind is None:
        return None
    return (spec.get("kind_map") or {}).get(kind)


# ---------------------------------------------------------------- audit (append-only)

def audit_file(env=None):
    env = os.environ if env is None else env
    explicit = (env.get("FAMILIA_SECURITY_AUDIT") or "").strip()
    if explicit:
        return explicit
    base = env.get("XDG_STATE_HOME")
    if not base:
        home = env.get("HOME") or ""
        base = os.path.join(home, ".local", "state") if home else ""
    if not base:
        return None
    return os.path.join(base, "familia", "security-audit.log")


def state_file(env=None):
    env = os.environ if env is None else env
    explicit = (env.get("FAMILIA_NODE_TIER_STATE") or "").strip()
    if explicit:
        return explicit
    audit = audit_file(env)
    if not audit:
        raise TierError("no HOME or XDG_STATE_HOME for the tier state file")
    return os.path.join(os.path.dirname(audit), "node-tiers.json")


def _sha_line(line):
    return hashlib.sha256(line).hexdigest()


def read_audit(path):
    """(entries, prev_hash). Refuses a symlink, a loose mode, or a broken chain."""
    if not path or not os.path.lexists(path):
        return [], ""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise TierError("audit path is a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise TierError("audit path is not a regular file")
    if st.st_mode & 0o077:
        raise TierError("audit log mode is too open")
    raw = open(path, "rb").read()
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TierError("audit log is not ASCII") from exc
    if not raw:
        return [], ""
    if not raw.endswith(b"\n"):
        raise TierError("audit log is not intact: missing newline")
    prev = ""
    entries = []
    for line in raw.splitlines(keepends=True):
        if line.strip() == b"":
            raise TierError("audit log is not intact: blank line")
        try:
            obj = json.loads(line.decode("ascii"))
        except ValueError as exc:
            raise TierError("audit log is not intact: bad json") from exc
        if obj.get("prev") != prev:
            raise TierError("audit log is not intact: hash chain")
        for key in AUDIT_KEYS:
            if key not in obj or not isinstance(obj[key], str):
                raise TierError("audit log is not intact: missing %s" % key)
        entries.append(obj)
        prev = _sha_line(line)
    return entries, prev


def _lock(path):
    parent = os.path.dirname(os.path.abspath(path)) or "."
    old = os.umask(0o077)
    try:
        os.makedirs(parent, 0o700, exist_ok=True)
    finally:
        os.umask(old)
    if os.path.islink(parent):
        raise TierError("audit directory is a symlink")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path + ".lock", flags, 0o600)
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _unlock(fd):
    if fd is None:
        return
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
    os.close(fd)


def append_event(path, event):
    """Append one JSON line. Never rewrites earlier lines."""
    if not path:
        return None
    event = dict(event)
    event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    fd = _lock(path)
    try:
        _entries, prev = read_audit(path)
        event["prev"] = prev
        for key in AUDIT_KEYS:
            if not isinstance(event.get(key), str) or event[key] == "" and key not in ("prev",):
                if key == "prev":
                    continue
                raise TierError("audit event missing %s" % key)
        blob = (json.dumps({k: event[k] for k in AUDIT_KEYS}, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if os.path.lexists(path) and os.path.islink(path):
            raise TierError("audit path is a symlink")
        out = os.open(path, flags, 0o600)
        try:
            os.write(out, blob)
        finally:
            os.close(out)
        os.chmod(path, 0o600)
    finally:
        _unlock(fd)
    return event


def audit_preset(old_state, new_state, cmd, arg, env):
    path = audit_file(env)
    if not path:
        return None
    return append_event(path, {
        "kind": "preset",
        "host": "-",
        "node": "-",
        "type": "preset",
        "old_tier": preset_label(old_state),
        "new_tier": preset_label(new_state),
        "actor": "operator",
        "reason": "familia security %s %s" % (cmd, arg),
        "factor": "preset",
        "nonce": secrets.token_hex(16),
    })


# ---------------------------------------------------------------- tier state

def _check_id(label, value):
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise TierError("%s must be 1-128 ASCII letters, digits, or . _ : -" % label)
    return value


def _check_reason(reason):
    if not isinstance(reason, str) or not reason or len(reason) > 200:
        raise TierError("reason must be 1-200 characters")
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in reason):
        raise TierError("reason must be printable ASCII")
    return reason


def load_tier_state(path):
    if not path or not os.path.lexists(path):
        return {"version": 1, "nodes": {}}
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise TierError("tier state path is not a regular file")
    if st.st_mode & 0o077:
        raise TierError("tier state mode is too open")
    raw = open(path, "rb").read()
    try:
        data = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise TierError("tier state file is not ASCII JSON") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("nodes"), dict):
        raise TierError("tier state file is not version 1")
    return data


def save_tier_state(path, state):
    parent = os.path.dirname(os.path.abspath(path))
    old = os.umask(0o077)
    try:
        os.makedirs(parent, 0o700, exist_ok=True)
    finally:
        os.umask(old)
    if os.path.islink(parent):
        raise TierError("tier state directory is a symlink")
    if os.path.lexists(path) and os.path.islink(path):
        raise TierError("tier state path is a symlink")
    blob = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("ascii")
    fd, tmp = tempfile.mkstemp(prefix=".node-tiers.", dir=parent)
    try:
        os.write(fd, blob)
        os.close(fd)
        fd = None
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        tmp = None
    finally:
        if fd is not None:
            os.close(fd)
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    os.chmod(path, 0o600)


def effective(state, host, node):
    rec = (state.get("nodes") or {}).get(host + "/" + node)
    if not rec:
        return {"host": host, "node": node, "type": None, "tier": "low", "source": "default"}
    return {
        "host": rec["host"], "node": rec["node"], "type": rec["type"],
        "tier": rec["tier"], "source": "recorded",
    }


# ---------------------------------------------------------------- grants

def _quote_reason(reason):
    out = []
    for ch in reason:
        if ch.isalnum() or ch in "._-":
            out.append(ch)
        else:
            out.append("%%%02X" % ord(ch))
    return "".join(out)


def _unquote_reason(text):
    if _REASON_ENC.fullmatch(text) is None:
        raise TierError("reason encoding in the grant is not canonical")
    out = []
    i = 0
    while i < len(text):
        if text[i] == "%":
            out.append(chr(int(text[i + 1:i + 3], 16)))
            i += 3
        else:
            out.append(text[i])
            i += 1
    reason = "".join(out)
    return _check_reason(reason)


def canonical_grant(host, node, node_type, old, new, actor, nonce, reason):
    return "v1 host=%s node=%s type=%s from=%s to=%s actor=%s nonce=%s reason=%s" % (
        host, node, node_type, old, new, actor, nonce, _quote_reason(reason))


def parse_grant(line):
    parts = line.split(" ")
    keys = ["host", "node", "type", "from", "to", "actor", "nonce", "reason"]
    if len(parts) != 9 or parts[0] != "v1":
        raise TierError("grant line must be: v1 host= node= type= from= to= actor= nonce= reason=")
    fields = {}
    for part, key in zip(parts[1:], keys):
        name, sep, value = part.partition("=")
        if sep != "=" or name != key or not value:
            raise TierError("grant line field %s is missing or out of order" % key)
        fields[key] = value
    if _NONCE.fullmatch(fields["nonce"]) is None:
        raise TierError("grant nonce must be 32 lowercase hex characters")
    fields["reason_text"] = _unquote_reason(fields["reason"])
    return fields


def sign_grant(key, line):
    return hmac.new(key, line.encode("ascii"), hashlib.sha256).hexdigest()


def _forbidden_roots(state_path, audit_path, env):
    roots = [ROOT]
    for path in (state_path, audit_path):
        if path:
            roots.append(os.path.dirname(os.path.abspath(path)))
    home = (env or {}).get("FAMILIA_NODE_HOME") or ""
    if home:
        roots.append(home)
    writable = (env or {}).get("FAMILIA_NODE_WRITABLE") or ""
    if writable:
        roots.extend(p for p in writable.split(os.pathsep) if p)
    return roots


def _outside_roots(path, roots, label):
    real = os.path.realpath(path)
    for root in roots:
        if not root:
            continue
        base = os.path.realpath(root)
        if real == base or real.startswith(base + os.sep):
            raise TierError("%s is inside a node-controlled or recorded directory" % label)


def _operator_file(path, roots, label):
    if not path or not os.path.isabs(path):
        raise TierError("%s path must be absolute" % label)
    if not os.path.lexists(path):
        raise TierError("%s does not exist" % label)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise TierError("%s must be a regular file, not a symlink" % label)
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise TierError("%s is not owned by the operator" % label)
    if st.st_mode & 0o077:
        raise TierError("%s must be mode 0600 or 0400" % label)
    _outside_roots(path, roots, label)
    return path


def _read_key(path, roots):
    _operator_file(path, roots, "admin key")
    raw = open(path, "rb").read()
    if raw.endswith(b"\n"):
        raw = raw[:-1]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
    if b"\n" in raw or len(raw) < 16:
        raise TierError("admin key must be one line of at least 16 bytes")
    return raw


def _match_grant(line, host, node, node_type, old, new, actor, reason):
    fields = parse_grant(line)
    expect = {
        "host": host, "node": node, "type": node_type, "from": old, "to": new, "actor": actor,
    }
    for key, value in expect.items():
        if fields[key] != value:
            raise TierError("grant %s does not match this request" % key)
    if fields["reason_text"] != reason:
        raise TierError("grant reason does not match this request")
    canon = canonical_grant(host, node, node_type, old, new, actor, fields["nonce"], reason)
    if line != canon:
        raise TierError("grant line is not in canonical form")
    return fields["nonce"]


def _read_factor(confirm, token, key_path, roots, host, node, node_type, old, new, actor, reason, need_token):
    nonce = None
    factor = None
    if confirm:
        _operator_file(confirm, roots, "confirm file")
        lines = open(confirm, "r", encoding="ascii").read().splitlines()
        if len(lines) != 1:
            raise TierError("confirm file must be one line")
        nonce = _match_grant(lines[0], host, node, node_type, old, new, actor, reason)
        factor = "confirm-file"
    if token or need_token:
        if not token:
            raise TierError("high tier requires an admin-signed token")
        if not key_path:
            raise TierError("high tier requires FAMILIA_FLEET_ADMIN_KEY_FILE or --admin-key-file")
        _operator_file(token, roots, "admin token")
        key = _read_key(key_path, roots)
        lines = open(token, "r", encoding="ascii").read().splitlines()
        if len(lines) != 2 or not lines[1].startswith("hmac-sha256 "):
            raise TierError("admin token must be a grant line plus hmac-sha256")
        got = lines[1].split(" ", 1)[1].strip()
        mac = sign_grant(key, lines[0])
        if len(got) != len(mac) or not hmac.compare_digest(got, mac):
            raise TierError("admin token hmac does not match")
        token_nonce = _match_grant(lines[0], host, node, node_type, old, new, actor, reason)
        if nonce and nonce != token_nonce:
            raise TierError("confirm file and admin token name different nonces")
        nonce = token_nonce
        factor = "admin-token"
    if factor is None:
        raise TierError("escalate requires an out-of-band confirm file or admin token")
    if need_token and factor != "admin-token":
        raise TierError("high tier requires an admin-signed token")
    return factor, nonce


# ---------------------------------------------------------------- changes

def _rank(tier):
    try:
        return TIERS.index(tier)
    except ValueError as exc:
        raise TierError("unknown tier %r; choose low, medium, or high" % (tier,)) from exc


def _prepare(spec, host, node, node_type, actor, reason):
    _check_id("host", host)
    _check_id("node", node)
    _check_id("actor", actor)
    _check_reason(reason)
    if node_type not in (spec.get("node_types") or {}):
        raise TierError("unknown node type %r; see `familia security tier types`" % (node_type,))
    return host, node, node_type, actor, reason


def show_tier(spec, state_path, host, node):
    _check_id("host", host)
    _check_id("node", node)
    return effective(load_tier_state(state_path), host, node)


def escalate(spec, state_path, audit_path, host, node, node_type, new_tier, actor, reason,
             env=None, confirm=None, token=None, key_path=None):
    env = env or {}
    host, node, node_type, actor, reason = _prepare(spec, host, node, node_type, actor, reason)
    blocked = caller_blocks_raise(env, actor, node)
    if blocked:
        raise TierError("refusing self-escalate: %s" % blocked)
    new_rank = _rank(new_tier)
    state = load_tier_state(state_path)
    cur = effective(state, host, node)
    old = cur["tier"]
    if cur["type"] and cur["type"] != node_type:
        raise TierError("type is %s; refusing to relabel" % cur["type"])
    if new_rank <= _rank(old):
        raise TierError("already at %s; de-escalate to go lower" % old)
    need_token = new_tier == "high"
    roots = _forbidden_roots(state_path, audit_path, env)
    key = key_path or (env.get("FAMILIA_FLEET_ADMIN_KEY_FILE") or "").strip() or None
    factor, nonce = _read_factor(confirm, token, key, roots, host, node, node_type, old, new_tier, actor, reason, need_token)
    return _commit_tier(state_path, audit_path, host, node, node_type, old, new_tier, actor, reason, factor, nonce)


def deescalate(spec, state_path, audit_path, host, node, new_tier, actor, reason, env=None):
    env = env or {}
    _check_id("host", host)
    _check_id("node", node)
    _check_id("actor", actor)
    _check_reason(reason)
    new_rank = _rank(new_tier)
    state = load_tier_state(state_path)
    cur = effective(state, host, node)
    if cur["source"] != "recorded":
        raise TierError("already at the low tier; nothing to de-escalate")
    if cur["type"] not in (spec.get("node_types") or {}):
        raise TierError("recorded type %r is not in the catalog" % (cur["type"],))
    if new_rank >= _rank(cur["tier"]):
        raise TierError("de-escalate only lowers a tier; current tier is %s" % cur["tier"])
    return _commit_tier(
        state_path, audit_path, host, node, cur["type"], cur["tier"], new_tier,
        actor, reason, "local", secrets.token_hex(16),
    )


def _commit_tier(state_path, audit_path, host, node, node_type, old, new, actor, reason, factor, nonce):
    """Append one audit line, then store the new tier. The log is not rewritten."""
    if not audit_path:
        raise TierError("no audit path; set FAMILIA_SECURITY_AUDIT or pass --audit")
    parent = os.path.dirname(os.path.abspath(audit_path)) or "."
    old_umask = os.umask(0o077)
    try:
        os.makedirs(parent, 0o700, exist_ok=True)
    finally:
        os.umask(old_umask)
    fd = _lock(audit_path)
    try:
        entries, prev = read_audit(audit_path)
        if any(ent.get("nonce") == nonce for ent in entries):
            raise TierError("refusing replay: nonce already in the audit log")
        state = load_tier_state(state_path)
        cur = effective(state, host, node)
        if cur["tier"] != old:
            raise TierError("tier changed before the write; retry")
        if cur["type"] and cur["type"] != node_type:
            raise TierError("type is %s; refusing to relabel" % cur["type"])
        event = {
            "kind": "tier", "host": host, "node": node, "type": node_type,
            "old_tier": old, "new_tier": new, "actor": actor, "reason": reason,
            "factor": factor, "nonce": nonce,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prev": prev,
        }
        blob = (json.dumps({k: event[k] for k in AUDIT_KEYS}, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        out = os.open(audit_path, flags, 0o600)
        try:
            os.write(out, blob)
        finally:
            os.close(out)
        os.chmod(audit_path, 0o600)
        state.setdefault("nodes", {})
        state["nodes"][host + "/" + node] = {
            "host": host, "node": node, "type": node_type, "tier": new,
        }
        save_tier_state(state_path, state)
        return event
    finally:
        _unlock(fd)
