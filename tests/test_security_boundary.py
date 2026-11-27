"""Boundary review M1-M4 and S1-S5 for tiered node security."""
import os
import stat
import time
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as HH  # noqa: E402
import security_levels as SL  # noqa: E402
import security_tier as ST  # noqa: E402
import start_graph  # noqa: E402

SPEC = SL.load_spec()
REASON = "boundary"
KEY = b"familia-test-admin-key"


def private(name):
    root = Path.home() / ".familia-boundary-test" / name
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def exp(seconds=3600):
    return str(int(time.time()) + seconds)


def keyfile(path):
    path.write_bytes(KEY + b"\n")
    os.chmod(path, 0o600)
    return path


def signed(path, host, node, typ, old, new, nonce, when=None):
    line = ST.canonical_grant(host, node, typ, old, new, "brian", nonce, REASON, when or exp())
    mac = ST.sign_grant(KEY, line)
    path.write_text(line + "\nhmac-sha256 " + mac + "\n", encoding="ascii")
    os.chmod(path, 0o600)
    return path


def layout(tmp_path, name):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    os.chmod(state_dir, 0o700)
    factor = private(name)
    keyfile(factor / "admin.key")
    return str(state_dir / "tiers.json"), str(state_dir / "audit.log"), factor


def test_m1_unset_marker_still_needs_a_terminal_and_the_admin_key(tmp_path):
    state, audit, factor = layout(tmp_path, "m1")
    grant = signed(factor / "g", "miryam", "coder", "coding-agent", "low", "medium", "a" * 32)
    with pytest.raises(ST.TierError, match="terminal"):
        ST.escalate(
            SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
            env={}, confirm=str(grant), key_path=str(factor / "admin.key"), isatty=False,
        )
    env = start_graph.node_launch_env(
        {"FAMILIA_FLEET_ADMIN_KEY_FILE": "/tmp/admin.key", "PATH": "/bin"}, "coder", "/var/empty", "/var/empty")
    assert env["FAMILIA_TIER_CALLER"] == "node"
    assert env["FAMILIA_NODE_ID"] == "coder"
    assert "FAMILIA_FLEET_ADMIN_KEY_FILE" not in env
    child = HH.hermes_child_env(environ={"FAMILIA_FLEET_ADMIN_KEY_FILE": "/tmp/admin.key", "PATH": "/bin"})
    assert child["FAMILIA_TIER_CALLER"] == "node"
    assert child["FAMILIA_NODE_ID"] == "hermes"
    assert "FAMILIA_FLEET_ADMIN_KEY_FILE" not in child
    text = open(os.path.join(ROOT, "scripts", "swarm", "swarm-bench-runner.sh"), encoding="ascii").read()
    assert "FAMILIA_TIER_CALLER=node" in text and "unset FAMILIA_FLEET_ADMIN_KEY_FILE" in text


def test_m2_world_writable_parent_rejected_and_grant_is_consumed(tmp_path):
    state, audit, factor = layout(tmp_path, "m2")
    open_dir = factor / "open"
    open_dir.mkdir(mode=0o777, exist_ok=True)
    os.chmod(open_dir, 0o777)
    grant = signed(open_dir / "g", "miryam", "coder", "coding-agent", "low", "medium", "b" * 32)
    with pytest.raises(ST.TierError, match="writable"):
        ST.escalate(
            SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
            env={}, confirm=str(grant), key_path=str(factor / "admin.key"), isatty=True,
        )
    assert grant.exists()
    os.chmod(open_dir, 0o700)
    fresh = signed(factor / "ok", "miryam", "coder", "coding-agent", "low", "medium", "c" * 32)
    ST.escalate(
        SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
        env={}, confirm=str(fresh), key_path=str(factor / "admin.key"), isatty=True,
    )
    assert not fresh.exists()


def test_m3_bad_signature_fails_closed_to_low(tmp_path):
    state, audit, factor = layout(tmp_path, "m3")
    grant = signed(factor / "g", "miryam", "coder", "coding-agent", "low", "medium", "d" * 32)
    ST.escalate(
        SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
        env={}, confirm=str(grant), key_path=str(factor / "admin.key"), isatty=True,
    )
    raw = open(state, "rb").read().replace(b"medium", b"highxx")
    open(state, "wb").write(raw)
    os.chmod(state, 0o600)
    seen = ST.show_tier(SPEC, state, "miryam", "coder", key=KEY, audit_path=audit)
    assert seen["tier"] == "low" and seen["source"] == "unverified"
    with pytest.raises(ST.TierError, match="verification"):
        again = signed(factor / "g2", "miryam", "coder", "coding-agent", "low", "high", "e" * 32)
        ST.escalate(
            SPEC, state, audit, "miryam", "coder", "coding-agent", "high", "brian", REASON,
            env={}, token=str(again), key_path=str(factor / "admin.key"), isatty=True,
        )


def test_m4_override_symlink_mode_and_confirmed_list(tmp_path):
    real = tmp_path / "real.yaml"
    real.write_text('level: "pentest"\nconfirmed: [pentest]\n', encoding="ascii")
    os.chmod(real, 0o644)
    with pytest.raises(SL.SecurityLevelError, match="0600"):
        SL.load_state(real)
    os.chmod(real, 0o600)
    loaded = SL.load_state(real)
    assert loaded["confirmed"] == []
    link = tmp_path / "link.yaml"
    link.symlink_to(real)
    with pytest.raises(SL.SecurityLevelError, match="symlink"):
        SL.load_state(link)
    graph = SL._load_graph(os.path.join(ROOT, "graph.yaml"))
    plan = SL.plan(graph, state=loaded, level="pentest", environ={})
    assert "pentests.fleet" not in {k for k, e in plan["entries"].items() if e["status"] == "active"}


def test_s1_expired_grant_and_foreign_audit_inode(tmp_path):
    state, audit, factor = layout(tmp_path, "s1")
    old = signed(factor / "old", "miryam", "coder", "coding-agent", "low", "medium", "f" * 32, when=str(int(time.time()) - 10))
    with pytest.raises(ST.TierError, match="expired"):
        ST.escalate(
            SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
            env={}, confirm=str(old), key_path=str(factor / "admin.key"), isatty=True,
        )
    grant = signed(factor / "now", "miryam", "coder", "coding-agent", "low", "medium", "6" * 32)
    ST.escalate(
        SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
        env={}, confirm=str(grant), key_path=str(factor / "admin.key"), isatty=True,
    )
    other = tmp_path / "other-audit.log"
    with pytest.raises(ST.TierError, match="signed state|inode"):
        ST.escalate(
            SPEC, state, str(other), "miryam", "coder", "coding-agent", "high", "brian", REASON,
            env={}, token=str(signed(factor / "hi", "miryam", "coder", "coding-agent", "medium", "high", "7" * 32)),
            key_path=str(factor / "admin.key"), isatty=True,
        )


def test_s2_truncation_breaks_the_signed_tip(tmp_path):
    state, audit, factor = layout(tmp_path, "s2")
    ST.escalate(
        SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
        env={}, confirm=str(signed(factor / "a", "miryam", "coder", "coding-agent", "low", "medium", "8" * 32)),
        key_path=str(factor / "admin.key"), isatty=True,
    )
    ST.escalate(
        SPEC, state, audit, "miryam", "coder", "coding-agent", "high", "brian", REASON,
        env={}, token=str(signed(factor / "b", "miryam", "coder", "coding-agent", "medium", "high", "9" * 32)),
        key_path=str(factor / "admin.key"), isatty=True,
    )
    raw = open(audit, "rb").read()
    first = raw.splitlines(keepends=True)[0]
    fd = os.open(audit, os.O_WRONLY | os.O_TRUNC)
    os.write(fd, first)
    os.close(fd)
    os.chmod(audit, 0o600)
    seen = ST.show_tier(SPEC, state, "miryam", "coder", key=KEY, audit_path=audit)
    assert seen["tier"] == "low" and seen["source"] == "unverified"


def test_s3_symlink_factor_is_not_followed(tmp_path):
    state, audit, factor = layout(tmp_path, "s3")
    real = signed(factor / "real", "miryam", "coder", "coding-agent", "low", "medium", "1" * 32)
    link = factor / "link"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(real)
    with pytest.raises(ST.TierError, match="cannot be opened|symlink"):
        ST.escalate(
            SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
            env={}, confirm=str(link), key_path=str(factor / "admin.key"), isatty=True,
        )


def test_s4_pentest_nonce_not_the_word_pentest(tmp_path):
    path = tmp_path / "security.local.yaml"
    factor = private("s4")
    keyfile(factor / "admin.key")
    env = {
        "FAMILIA_FLEET_ADMIN_KEY_FILE": str(factor / "admin.key"),
        "FAMILIA_NODE_TIER_STATE": str(tmp_path / "tiers.json"),
        "FAMILIA_SECURITY_AUDIT": str(tmp_path / "audit.log"),
        "HOME": str(Path.home()),
    }
    graph = SL._load_graph(os.path.join(ROOT, "graph.yaml"))
    with pytest.raises(SL.SecurityLevelError, match="not confirmed"):
        SL.change(graph, SPEC, path, "level", "pentest", check_files=False, environ=env,
                  isatty=lambda: True, ask=lambda _p: "pentest")
    SL.change(graph, SPEC, path, "level", "pentest", check_files=False, environ=env,
              isatty=lambda: True, ask=lambda p: p.split()[2])
    assert "confirmed:" not in path.read_text()
    os.chmod(path, 0o600)


def test_s5_node_env_cannot_raise(tmp_path):
    state, audit, factor = layout(tmp_path, "s5")
    grant = signed(factor / "g", "miryam", "coder", "coding-agent", "low", "medium", "2" * 32)
    env = start_graph.node_launch_env({}, "coder", str(factor), str(factor))
    with pytest.raises(ST.TierError, match="self-escalate"):
        ST.escalate(
            SPEC, state, audit, "miryam", "coder", "coding-agent", "medium", "brian", REASON,
            env=env, confirm=str(grant), key_path=str(factor / "admin.key"), isatty=True,
        )
