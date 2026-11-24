"""Per-node risk tiers: schema, default low, escalate, de-escalate, no self-escalate, audit."""
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import security_levels as SL  # noqa: E402
import security_tier as ST  # noqa: E402

SPEC = SL.load_spec()
GRAPH = os.path.join(ROOT, "graph.yaml")
REASON = "arm local tools"


def private_dir(name):
    root = Path.home() / ".familia-boundary-test"
    root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    path = root / name
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def paths(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    os.chmod(state_dir, 0o700)
    factor = private_dir(tmp_path.name)
    keyfile(factor / "admin.key")
    return str(state_dir / "node-tiers.json"), str(state_dir / "audit.log"), factor


def _exp():
    return str(int(time.time()) + 3600)


def grant(path, host, node, typ, old, new, actor="brian", reason=REASON, nonce=None, key=None):
    nonce = nonce or "ab" * 16
    line = ST.canonical_grant(host, node, typ, old, new, actor, nonce, reason, _exp())
    if key:
        line = line + "\nhmac-sha256 " + ST.sign_grant(key, line)
    path.write_text(line + "\n", encoding="ascii")
    os.chmod(path, 0o600)
    return line.split("\n", 1)[0], nonce


def keyfile(path, secret=b"familia-test-admin-key"):
    path.write_bytes(secret + b"\n")
    os.chmod(path, 0o600)
    return secret


def token(path, key, host, node, typ, old, new, actor="brian", reason=REASON, nonce=None, exp=None):
    nonce = nonce or "cd" * 16
    line = ST.canonical_grant(host, node, typ, old, new, actor, nonce, reason, exp or _exp())
    mac = ST.sign_grant(key, line)
    path.write_text(line + "\nhmac-sha256 " + mac + "\n", encoding="ascii")
    os.chmod(path, 0o600)
    return line, nonce


def escalate(state, audit, factor, host, node, typ, new, confirm=None, token_path=None, env=None, actor="brian"):
    return ST.escalate(
        SPEC, state, audit, host, node, typ, new, actor, REASON,
        env=env or {}, confirm=confirm, token=token_path,
        key_path=str(factor / "admin.key"), isatty=True,
    )


def test_catalog_matches_schema_and_default_is_low():
    data = ST.validate_files()
    assert data["risk"]["default"] == "low"
    assert data["risk"]["order"] == ["low", "medium", "high"]
    assert data["risk"]["not_granted"] == ["autonomous-lab"]
    assert data["risk"]["policy_ladder"]["high"] == ["tools-confirm"]
    assert "autonomous-lab" not in data["risk"]["policy_ladder"]["high"]
    raw = open(os.path.join(ROOT, "config", "security-levels.yaml"), "rb").read()
    raw.decode("ascii")
    open(os.path.join(ROOT, "config", "security-levels.schema.json"), "rb").read().decode("ascii")


def test_schema_rejects_a_high_tier_that_drops_its_arming():
    data = json.loads(json.dumps(SPEC))
    data["node_types"]["chat"]["tiers"]["low"]["arming"] = "explicit-arm"
    schema = ST._load_json(ST.SCHEMA_PATH)
    with pytest.raises(ST.TierError, match="arming"):
        ST.validate_catalog(data, schema)


def test_guardian_tiers_map_onto_the_pentest_ladder_and_stop_before_autonomous():
    assert ST.policy_modes(SPEC, "guardian", "low") == ["off", "planned"]
    assert ST.policy_modes(SPEC, "guardian", "medium") == ["slash-confirm"]
    assert ST.policy_modes(SPEC, "guardian", "high") == ["tools-confirm"]
    assert ST.policy_modes(SPEC, "coding-agent", "high") == []
    assert SPEC["integrity_profiles"]["provenance"][0] == "untrusted"
    assert SPEC["integrity_profiles"]["provenance"][-1] == "trusted"
    assert SPEC["integrity_profiles"]["traditional"] == ["low", "medium", "high"]


def test_low_is_not_a_security_preset():
    with pytest.raises(SL.SecurityLevelError, match="unknown"):
        SL.plan({"nodes": {}, "pentests": {}}, state=SL.empty_state(), level="low", environ={})


def test_known_node_kinds_map_to_a_tier_type():
    from box_archetypes import HOST_KINDS
    from node_role import NODE_ROLES
    km = SPEC["kind_map"]
    for role in NODE_ROLES:
        assert role in km, role
    for kind in HOST_KINDS:
        assert km[kind] == "host", kind
    for kind in ("llama-server", "drex-dlm", "sm11-legacy", "model-server"):
        assert km[kind] == "model-server"
    assert km["swarm-runner"] == "swarm-worker"
    assert km["hermes-agent"] == "coding-agent"
    assert km["coder"] == "coding-agent"
    assert km["green-roomz"] == "gateway"
    assert km["system-agent"] == "system-agent"
    assert km["thin-client"] == "thin-client"
    assert km["pentest"] == "guardian"
    assert "none" not in km and "reference" not in km
    text = open(os.path.join(ROOT, "scripts", "swarm", "configure-fleet-role.sh"), encoding="ascii").read()
    assert "thin-client|model-server|swarm-runner" in text


def test_show_defaults_to_low_and_writes_nothing(tmp_path):
    state, _audit, _factor = paths(tmp_path)
    cur = ST.show_tier(SPEC, state, "miryam", "coder")
    assert cur["tier"] == "low" and cur["source"] == "default" and cur["type"] is None
    assert not os.path.exists(state)


def test_escalate_medium_then_deescalate_writes_an_append_only_audit(tmp_path):
    state, audit, factor = paths(tmp_path)
    line_path = factor / "grant"
    key = keyfile(factor / "admin.key")
    _line, nonce = grant(line_path, "miryam", "coder", "coding-agent", "low", "medium", key=key)
    event = escalate(state, audit, factor, "miryam", "coder", "coding-agent", "medium", confirm=str(line_path))
    assert event["old_tier"] == "low" and event["new_tier"] == "medium"
    assert event["factor"] == "confirm-file" and event["nonce"] == nonce
    first = open(audit, "rb").read()
    body, status = ST.load_tier_state(state, key)
    assert status == "verified"
    assert ST.effective(body, "miryam", "coder")["tier"] == "medium"
    assert not line_path.exists()
    ST.deescalate(
        SPEC, state, audit, "miryam", "coder", "low", "coder", "back to default",
        env={"FAMILIA_NODE_ID": "coder"}, key_path=str(factor / "admin.key"),
    )
    second = open(audit, "rb").read()
    assert second.startswith(first)
    assert first.count(b"\n") == 1 and second.count(b"\n") == 2
    rows = [json.loads(line) for line in second.decode("ascii").splitlines()]
    assert rows[0]["host"] == "miryam" and rows[0]["node"] == "coder"
    assert rows[0]["actor"] == "brian" and rows[0]["reason"] == REASON
    assert rows[1]["old_tier"] == "medium" and rows[1]["new_tier"] == "low" and rows[1]["factor"] == "local"
    assert rows[1]["prev"] == hashlib.sha256(first).hexdigest()
    assert ST.read_audit(audit)[0][1]["new_tier"] == "low"
    before = hashlib.sha256(open(GRAPH, "rb").read()).hexdigest()
    assert hashlib.sha256(open(GRAPH, "rb").read()).hexdigest() == before


def test_high_requires_an_admin_token_and_a_confirm_file_is_not_enough(tmp_path):
    state, audit, factor = paths(tmp_path)
    confirm = factor / "grant"
    grant(confirm, "miryam", "coder", "coding-agent", "low", "high", nonce="11" * 16)
    with pytest.raises(ST.TierError, match="hmac"):
        escalate(state, audit, factor, "miryam", "coder", "coding-agent", "high", confirm=str(confirm))
    assert not os.path.exists(state) and not os.path.exists(audit)
    key = keyfile(factor / "admin.key")
    tok = factor / "token"
    token(tok, key, "miryam", "coder", "coding-agent", "low", "high", nonce="22" * 16)
    event = escalate(state, audit, factor, "miryam", "coder", "coding-agent", "high", token_path=str(tok))
    assert event["new_tier"] == "high" and event["factor"] == "admin-token"
    assert ST.policy_modes(SPEC, "coding-agent", "high") == []


def test_self_escalate_is_refused_even_with_a_valid_token(tmp_path):
    state, audit, factor = paths(tmp_path)
    key = keyfile(factor / "admin.key")
    tok = factor / "token"
    token(tok, key, "miryam", "coder", "coding-agent", "low", "medium", nonce="33" * 16)
    env = {"FAMILIA_NODE_ID": "coder", "FAMILIA_TIER_CALLER": "node"}
    with pytest.raises(ST.TierError, match="self-escalate"):
        escalate(state, audit, factor, "miryam", "coder", "coding-agent", "medium", token_path=str(tok), env=env)
    with pytest.raises(ST.TierError, match="self-escalate"):
        escalate(state, audit, factor, "miryam", "other", "chat", "medium", confirm=str(tok), env={"FAMILIA_NODE_ID": "coder"})
    with pytest.raises(ST.TierError, match="actor equals the node id"):
        escalate(state, audit, factor, "miryam", "coder", "coding-agent", "medium", token_path=str(tok), actor="coder")
    assert not os.path.exists(state) and not os.path.exists(audit)


def test_factor_inside_a_node_writable_root_is_refused(tmp_path):
    state, audit, factor = paths(tmp_path)
    nest = factor / "nodehome"
    nest.mkdir(mode=0o700, exist_ok=True)
    os.chmod(nest, 0o700)
    confirm = nest / "grant"
    grant(confirm, "miryam", "coder", "coding-agent", "low", "medium", nonce="44" * 16, key=keyfile(factor / "admin.key"))
    with pytest.raises(ST.TierError, match="node-controlled"):
        escalate(
            state, audit, factor, "miryam", "coder", "coding-agent", "medium",
            confirm=str(confirm), env={"FAMILIA_NODE_HOME": str(nest)},
        )
    assert not os.path.exists(audit)


def test_loose_factor_and_replay_are_refused(tmp_path):
    state, audit, factor = paths(tmp_path)
    confirm = factor / "grant"
    key = keyfile(factor / "admin.key")
    _line, nonce = grant(confirm, "miryam", "coder", "coding-agent", "low", "medium", nonce="55" * 16, key=key)
    os.chmod(confirm, 0o644)
    with pytest.raises(ST.TierError, match="0600"):
        escalate(state, audit, factor, "miryam", "coder", "coding-agent", "medium", confirm=str(confirm))
    os.chmod(confirm, 0o600)
    ST.escalate(
        SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
        env={}, confirm=str(confirm), key_path=str(factor / "admin.key"), isatty=True,
    )
    ST.deescalate(
        SPEC, state, audit, "miryam", "coder", "low", "brian", "lower before replay",
        env={}, key_path=str(factor / "admin.key"),
    )
    grant(confirm, "miryam", "coder", "coding-agent", "low", "medium", nonce=nonce, key=key)
    with pytest.raises(ST.TierError, match="replay"):
        escalate(state, audit, factor, "miryam", "coder", "coding-agent", "medium", confirm=str(confirm))
    assert nonce in open(audit, encoding="ascii").read()


def test_preset_raise_is_refused_for_a_node_and_off_is_local(tmp_path):
    path = tmp_path / "security.local.yaml"
    with pytest.raises(SL.SecurityLevelError, match="self-escalate"):
        SL.change(SL._load_graph(GRAPH), SPEC, path, "level", "guardian", check_files=False,
                  environ={"FAMILIA_NODE_ID": "fleet-guardian"})
    assert not path.exists()
    assert SL.change(SL._load_graph(GRAPH), SPEC, path, "level", "off", check_files=False,
                     environ={"FAMILIA_TIER_CALLER": "node"}) == 0
    assert SL.load_state(path)["level"] == "off"


def test_cli_show_is_low_and_graph_yaml_stays_byte_identical(tmp_path):
    before = hashlib.sha256(open(GRAPH, "rb").read()).hexdigest()
    env = dict(os.environ)
    env["FAMILIA_NODE_TIER_STATE"] = str(tmp_path / "tiers.json")
    env["FAMILIA_SECURITY_AUDIT"] = str(tmp_path / "audit.log")
    env.pop("FAMILIA_NODE_ID", None)
    env.pop("FAMILIA_TIER_CALLER", None)
    script = os.path.join(ROOT, "scripts", "security_levels.py")
    r = subprocess.run([sys.executable, script, "tier", "show", "--host", "miryam", "--node", "coder"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "tier=low" in r.stdout and "source=default" in r.stdout
    assert not (tmp_path / "tiers.json").exists()
    r = subprocess.run([sys.executable, script, "tier", "schema"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "schema: ok" in r.stdout
    assert hashlib.sha256(open(GRAPH, "rb").read()).hexdigest() == before
    text = open(script, encoding="ascii").read()
    assert "import socket" not in text and ".bind(" not in text


def test_audit_mode_is_owner_only(tmp_path):
    state, audit, factor = paths(tmp_path)
    confirm = factor / "grant"
    grant(confirm, "box", "embed", "embed", "low", "medium", nonce="66" * 16, key=keyfile(factor / "admin.key"))
    escalate(state, audit, factor, "box", "embed", "embed", "medium", confirm=str(confirm))
    mode = stat.S_IMODE(os.stat(audit).st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(os.stat(state).st_mode) == 0o600
