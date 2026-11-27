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
    "actor", "exp", "factor", "host", "kind", "new_tier", "node", "nonce",
    "old_tier", "prev", "reason", "ts", "type",
)
ADMIN_KEY_ENV = "FAMILIA_FLEET_ADMIN_KEY_FILE"
GRANT_TTL = 3600
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_REASON_ENC = re.compile(r"^(?:%[0-9A-F]{2}|[A-Za-z0-9._-])*$")


class TierError(Exception):
    """A refused tier change or a broken catalog. Nothing was written."""


def caller_blocks_raise(env, actor=None, node=None):
    """Why this process is a node and may not raise, or None.

    A missing marker is not permission. Raises also need require_admin_context.
    """
    env = env or {}
    if env.get("FAMILIA_TIER_CALLER") == "node":
        return "FAMILIA_TIER_CALLER=node"
    if (env.get("FAMILIA_NODE_ID") or "").strip():
        return "FAMILIA_NODE_ID is set"
    if actor is not None and node is not None and actor == node:
        return "actor equals the node id"
    return None


def node_launch_env(base, node_id, node_home, writable):
    """Env for a node process. The admin key is scrubbed. The marker is always set."""
    env = dict(base or {})
    env.pop(ADMIN_KEY_ENV, None)
    env["FAMILIA_TIER_CALLER"] = "node"
    env["FAMILIA_NODE_ID"] = str(node_id)
    env["FAMILIA_NODE_HOME"] = str(node_home)
    env["FAMILIA_NODE_WRITABLE"] = str(writable)
    return env


def is_real_tty(isatty=None):
    if callable(isatty):
        return bool(isatty())
    if isatty is not None:
        return bool(isatty)
    try:
        return os.isatty(0) and os.isatty(1)
    except OSError:
        return False


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


def _parse_audit(raw):
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


def read_audit(path):
    """(entries, prev_hash, (dev, ino)). Opens O_NOFOLLOW and fstats the fd."""
    if not path or not os.path.lexists(path):
        return [], "", ("", "")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise TierError("audit log cannot be opened") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise TierError("audit path is not a regular file")
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise TierError("audit log is not owned by the operator")
        if st.st_mode & 0o077:
            raise TierError("audit log mode is too open")
        raw = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk
        ident = (str(st.st_dev), str(st.st_ino))
    finally:
        os.close(fd)
    entries, prev = _parse_audit(raw)
    return entries, prev, ident


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
        _entries, prev, _ident = read_audit(path)
        event.setdefault("exp", "0")
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
            if hasattr(os, "fchmod"):
                os.fchmod(out, 0o600)
            os.write(out, blob)
        finally:
            os.close(out)
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
        "exp": "0",
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


def _empty_state():
    return {"version": 1, "nodes": {}, "grants": [], "audit_dev": "", "audit_ino": "", "audit_tip": ""}


def _state_payload(state):
    body = {
        "version": 1,
        "nodes": state.get("nodes") or {},
        "grants": state.get("grants") or [],
        "audit_dev": str(state.get("audit_dev") or ""),
        "audit_ino": str(state.get("audit_ino") or ""),
        "audit_tip": str(state.get("audit_tip") or ""),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")


def load_tier_state(path, key=None):
    """(state, status). status is missing, verified, or rejected.

    A bad signature or a loose/symlink file fails closed: the caller must treat the tier as low.
    """
    if not path or not os.path.lexists(path):
        return _empty_state(), "missing"
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        return _empty_state(), "rejected"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (hasattr(os, "getuid") and st.st_uid != os.getuid()) or st.st_mode & 0o077:
            return _empty_state(), "rejected"
        raw = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(fd)
    try:
        wrapped = json.loads(raw.decode("ascii"))
        payload = wrapped["payload"]
        mac = wrapped["hmac-sha256"]
        body = _state_payload(payload)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        return _empty_state(), "rejected"
    if not key or not hmac.compare_digest(sign_grant(key, body.decode("ascii")), mac):
        return _empty_state(), "rejected"
    if not isinstance(payload.get("nodes"), dict):
        return _empty_state(), "rejected"
    payload["version"] = 1
    return payload, "verified"


def save_tier_state(path, state, key):
    if not key:
        raise TierError("refusing to write an unsigned tier state")
    parent = os.path.dirname(os.path.abspath(path))
    old = os.umask(0o077)
    try:
        os.makedirs(parent, 0o700, exist_ok=True)
    finally:
        os.umask(old)
    if os.path.islink(parent):
        raise TierError("tier state directory is a symlink")
    pst = os.lstat(parent)
    if pst.st_uid != os.getuid() or pst.st_mode & 0o022:
        raise TierError("tier state directory is not a private directory")
    if os.path.lexists(path) and os.path.islink(path):
        raise TierError("tier state path is a symlink")
    body = _state_payload(state)
    wrapped = {"hmac-sha256": sign_grant(key, body.decode("ascii")), "payload": json.loads(body.decode("ascii"))}
    blob = (json.dumps(wrapped, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    fd, tmp = tempfile.mkstemp(prefix=".node-tiers.", dir=parent)
    try:
        os.write(fd, blob)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        os.close(fd)
        fd = None
        os.replace(tmp, path)
        tmp = None
    finally:
        if fd is not None:
            os.close(fd)
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


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


def canonical_grant(host, node, node_type, old, new, actor, nonce, reason, exp):
    return "v2 host=%s node=%s type=%s from=%s to=%s actor=%s nonce=%s exp=%s reason=%s" % (
        host, node, node_type, old, new, actor, nonce, exp, _quote_reason(reason))


def parse_grant(line, now=None):
    parts = line.split(" ")
    keys = ["host", "node", "type", "from", "to", "actor", "nonce", "exp", "reason"]
    if len(parts) != 10 or parts[0] != "v2":
        raise TierError("grant line must be v2 host= node= type= from= to= actor= nonce= exp= reason=")
    fields = {}
    for part, key in zip(parts[1:], keys):
        name, sep, value = part.partition("=")
        if sep != "=" or name != key or not value:
            raise TierError("grant line field %s is missing or out of order" % key)
        fields[key] = value
    if _NONCE.fullmatch(fields["nonce"]) is None:
        raise TierError("grant nonce must be 32 lowercase hex characters")
    if not fields["exp"].isdigit():
        raise TierError("grant exp must be a unix time")
    if int(fields["exp"]) < int(time.time() if now is None else now):
        raise TierError("grant has expired")
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


def _assert_private_parents(path):
    """Reject a factor whose directory, or any ancestor, is group or world writable."""
    cur = os.path.dirname(os.path.abspath(path))
    root = os.path.abspath(os.sep)
    while cur and cur != root:
        try:
            st = os.lstat(cur)
        except OSError as exc:
            raise TierError("cannot inspect parent directory %s" % cur) from exc
        if stat.S_ISLNK(st.st_mode):
            raise TierError("a parent directory is a symlink")
        if st.st_mode & 0o022:
            raise TierError("parent directory is group or world writable: %s" % cur)
        cur = os.path.dirname(cur)


def open_private(path, roots, label, walk_parents=True):
    """Read a file with O_NOFOLLOW. fstat the fd. Do not chmod by path."""
    if not path or not os.path.isabs(path):
        raise TierError("%s path must be absolute" % label)
    if walk_parents:
        _assert_private_parents(path)
    _outside_roots(path, roots, label)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise TierError("%s cannot be opened" % label) from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise TierError("%s must be a regular file, not a symlink" % label)
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise TierError("%s is not owned by the operator" % label)
        if st.st_mode & 0o077:
            raise TierError("%s must be mode 0600 or 0400" % label)
        data = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
        return data
    finally:
        os.close(fd)


def _read_key(path, roots):
    raw = open_private(path, roots, "admin key")
    if raw.endswith(b"\n"):
        raw = raw[:-1]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
    if b"\n" in raw or len(raw) < 16:
        raise TierError("admin key must be one line of at least 16 bytes")
    return raw


def require_admin_context(env, key_path, roots, isatty=None):
    """A raise needs a terminal and a readable admin key. A missing node marker is not enough."""
    blocked = caller_blocks_raise(env)
    if blocked:
        raise TierError("refusing self-escalate: %s" % blocked)
    if not is_real_tty(isatty):
        raise TierError("admin context requires a terminal")
    if not key_path:
        raise TierError("admin context requires %s or --admin-key-file" % ADMIN_KEY_ENV)
    return _read_key(key_path, roots)


def _match_grant(line, host, node, node_type, old, new, actor, reason, now=None):
    fields = parse_grant(line, now=now)
    expect = {
        "host": host, "node": node, "type": node_type, "from": old, "to": new, "actor": actor,
    }
    for key, value in expect.items():
        if fields[key] != value:
            raise TierError("grant %s does not match this request" % key)
    if fields["reason_text"] != reason:
        raise TierError("grant reason does not match this request")
    canon = canonical_grant(
        host, node, node_type, old, new, actor, fields["nonce"], reason, fields["exp"])
    if line != canon:
        raise TierError("grant line is not in canonical form")
    return fields["nonce"], fields["exp"]


def _signed_lines(raw, label):
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TierError("%s is not ASCII" % label) from exc
    lines = text.splitlines()
    if len(lines) != 2 or not lines[1].startswith("hmac-sha256 "):
        raise TierError("%s must be a v2 grant plus hmac-sha256" % label)
    return lines


def _check_signed_grant(raw, key, label, host, node, node_type, old, new, actor, reason):
    lines = _signed_lines(raw, label)
    got = lines[1].split(" ", 1)[1].strip()
    mac = sign_grant(key, lines[0])
    if len(got) != len(mac) or not hmac.compare_digest(got, mac):
        raise TierError("%s hmac does not match" % label)
    return _match_grant(lines[0], host, node, node_type, old, new, actor, reason)


def _consume(path):
    try:
        os.unlink(path)
    except OSError as exc:
        raise TierError("could not consume the grant file") from exc


def _read_factor(confirm, token, key, roots, host, node, node_type, old, new, actor, reason):
    """Both medium and high need an admin-signed grant. The file is consumed."""
    path = token or confirm
    if not path:
        raise TierError("escalate requires an admin-signed grant file")
    label = "admin token" if token else "confirm file"
    if token and confirm:
        label = "admin token"
    raw = open_private(path, roots, label)
    nonce, exp = _check_signed_grant(raw, key, label, host, node, node_type, old, new, actor, reason)
    _consume(path)
    factor = "admin-token" if token else "confirm-file"
    return factor, nonce, exp


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


def show_tier(spec, state_path, host, node, key=None, audit_path=None):
    _check_id("host", host)
    _check_id("node", node)
    state, status = load_tier_state(state_path, key)
    if status != "verified" or not _binding_ok(state, audit_path):
        return {"host": host, "node": node, "type": None, "tier": "low",
                "source": "default" if status == "missing" else "unverified"}
    return effective(state, host, node)


def _binding_ok(state, audit_path):
    if not state.get("audit_ino"):
        return True
    if not audit_path or not os.path.lexists(audit_path):
        return False
    try:
        _entries, tip, ident = read_audit(audit_path)
    except TierError:
        return False
    return (state.get("audit_dev"), state.get("audit_ino")) == ident and state.get("audit_tip") == tip


def active_grants(state_path, key, now=None):
    state, status = load_tier_state(state_path, key)
    if status != "verified":
        return []
    now = int(time.time() if now is None else now)
    names = []
    for grant in state.get("grants") or []:
        try:
            if int(grant.get("exp") or 0) >= now and grant.get("set"):
                names.append(grant["set"])
        except (TypeError, ValueError):
            continue
    return names


def record_set_grant(state_path, key, set_name, nonce, exp):
    state, status = load_tier_state(state_path, key)
    if status == "rejected":
        raise TierError("tier state failed verification; refusing to record a grant")
    if status == "missing":
        state = _empty_state()
    grants = [g for g in (state.get("grants") or []) if g.get("set") != set_name]
    grants.append({"set": set_name, "nonce": nonce, "exp": str(exp)})
    state["grants"] = grants
    save_tier_state(state_path, state, key)


def escalate(spec, state_path, audit_path, host, node, node_type, new_tier, actor, reason,
             env=None, confirm=None, token=None, key_path=None, isatty=None):
    env = env or {}
    host, node, node_type, actor, reason = _prepare(spec, host, node, node_type, actor, reason)
    if actor == node:
        raise TierError("refusing self-escalate: actor equals the node id")
    roots = _forbidden_roots(state_path, audit_path, env)
    key_path = key_path or (env.get(ADMIN_KEY_ENV) or "").strip() or None
    key = require_admin_context(env, key_path, roots, isatty)
    new_rank = _rank(new_tier)
    state, status = load_tier_state(state_path, key)
    if status == "rejected":
        raise TierError("tier state failed verification; refusing to raise")
    if not _binding_ok(state, audit_path):
        raise TierError("audit log does not match the signed state")
    cur = effective(state, host, node) if status == "verified" else {
        "host": host, "node": node, "type": None, "tier": "low", "source": "default"}
    old = cur["tier"]
    if cur["type"] and cur["type"] != node_type:
        raise TierError("type is %s; refusing to relabel" % cur["type"])
    if new_rank <= _rank(old):
        raise TierError("already at %s; de-escalate to go lower" % old)
    factor, nonce, exp = _read_factor(confirm, token, key, roots, host, node, node_type, old, new_tier, actor, reason)
    return _commit_tier(
        state_path, audit_path, host, node, node_type, old, new_tier, actor, reason,
        factor, nonce, exp, key, state if status == "verified" else _empty_state())


def deescalate(spec, state_path, audit_path, host, node, new_tier, actor, reason, env=None, key_path=None):
    env = env or {}
    _check_id("host", host)
    _check_id("node", node)
    _check_id("actor", actor)
    _check_reason(reason)
    new_rank = _rank(new_tier)
    key_path = key_path or (env.get(ADMIN_KEY_ENV) or "").strip() or None
    roots = _forbidden_roots(state_path, audit_path, env)
    key = _read_key(key_path, roots) if key_path else None
    state, status = load_tier_state(state_path, key)
    if status != "verified":
        if os.path.lexists(state_path) and not os.path.islink(state_path):
            os.unlink(state_path)
        raise TierError("already at the low tier; nothing to de-escalate")
    if not _binding_ok(state, audit_path):
        raise TierError("audit log does not match the signed state")
    cur = effective(state, host, node)
    if cur["type"] not in (spec.get("node_types") or {}):
        raise TierError("recorded type %r is not in the catalog" % (cur["type"],))
    if new_rank >= _rank(cur["tier"]):
        raise TierError("de-escalate only lowers a tier; current tier is %s" % cur["tier"])
    if not key:
        raise TierError("de-escalate of a signed tier requires the admin key to re-sign")
    return _commit_tier(
        state_path, audit_path, host, node, cur["type"], cur["tier"], new_tier,
        actor, reason, "local", secrets.token_hex(16), "0", key, state)


def _commit_tier(state_path, audit_path, host, node, node_type, old, new, actor, reason, factor, nonce, exp, key, state):
    """Append one audit line, then store a signed tier. The log is not rewritten."""
    if not audit_path:
        raise TierError("no audit path; set FAMILIA_SECURITY_AUDIT or pass --audit")
    parent = os.path.dirname(os.path.abspath(audit_path)) or "."
    old_umask = os.umask(0o077)
    try:
        os.makedirs(parent, 0o700, exist_ok=True)
    finally:
        os.umask(old_umask)
    pst = os.lstat(parent)
    if stat.S_ISLNK(pst.st_mode) or pst.st_uid != os.getuid() or pst.st_mode & 0o022:
        raise TierError("audit directory is not a private directory")
    fd = _lock(audit_path)
    try:
        entries, prev, ident = read_audit(audit_path)
        if state.get("audit_ino") and (state.get("audit_dev"), state.get("audit_ino")) != ident:
            raise TierError("audit file is not the bound inode")
        if state.get("audit_tip") and state.get("audit_tip") != prev:
            raise TierError("audit log tip does not match the signed state")
        if any(ent.get("nonce") == nonce for ent in entries):
            raise TierError("refusing replay: nonce already in the audit log")
        fresh, status = load_tier_state(state_path, key)
        cur_tier = effective(fresh, host, node)["tier"] if status == "verified" else "low"
        if cur_tier != old:
            raise TierError("tier changed before the write; retry")
        event = {
            "kind": "tier", "host": host, "node": node, "type": node_type,
            "old_tier": old, "new_tier": new, "actor": actor, "reason": reason,
            "factor": factor, "nonce": nonce, "exp": str(exp),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prev": prev,
        }
        blob = (json.dumps({k: event[k] for k in AUDIT_KEYS}, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        out = os.open(audit_path, flags, 0o600)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(out, 0o600)
            os.write(out, blob)
            st = os.fstat(out)
            ident = (str(st.st_dev), str(st.st_ino))
        finally:
            os.close(out)
        state = dict(fresh if status == "verified" else state)
        state.setdefault("nodes", {})
        state.setdefault("grants", state.get("grants") or [])
        state["nodes"][host + "/" + node] = {
            "host": host, "node": node, "type": node_type, "tier": new,
        }
        state["audit_dev"], state["audit_ino"] = ident
        state["audit_tip"] = _sha_line(blob)
        save_tier_state(state_path, state, key)
        return event
    finally:
        _unlock(fd)
