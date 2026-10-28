"""OSC 7501 emit helper (#123) — encode, limits, wiring smoke."""
import os
import re
import base64
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OSC = ROOT / "scripts" / "osc7501.sh"
HUD = ROOT / "scripts" / "pilot_hud.sh"


def run(*args, env=None, timeout=30):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        list(args), cwd=ROOT, capture_output=True, text=True,
        timeout=timeout, env=e,
    )


def test_script_parses_and_self_test():
    assert OSC.is_file()
    assert run("sh", "-n", str(OSC)).returncode == 0
    r = run("sh", str(OSC), "--self-test")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "self-test ok" in r.stdout + r.stderr


def test_encode_roundtrip():
    r = run("sh", str(OSC), "encode", "Building frame")
    assert r.returncode == 0
    raw = r.stdout.strip()
    pad = "=" * ((4 - len(raw) % 4) % 4)
    assert base64.b64decode(raw + pad).decode() == "Building frame"


def test_emit_captured_sequence(tmp_path):
    cap = tmp_path / "osc.bin"
    env = {
        "OSC7501_CAPTURE": str(cap),
        "FAMILIA_OSC7501": "0",
        "PATH": "/usr/bin:/bin",
    }
    r = run(
        "sh", str(OSC), "emit", "working",
        "--id", "home/setup", "--app", "familia",
        "--msg", "Building frame", "--progress", "40",
        env=env,
    )
    assert r.returncode == 0, r.stderr
    data = cap.read_bytes()
    assert b"\x1b]7501;" in data
    assert data.endswith(b"\x1b\\") or b"\x1b\\" in data
    m = re.search(br"\x1b\]7501;([^\x1b]+)\x1b\\", data)
    assert m, data[:120]
    body = m.group(1).decode()
    kv = dict(p.split("=", 1) for p in body.split(":") if "=" in p)
    assert kv["state"] == "working"
    assert kv["id"] == "home/setup"
    assert kv["app"] == "familia"
    assert kv["progress"] == "40"
    pad = "=" * ((4 - len(kv["msg"]) % 4) % 4)
    assert base64.b64decode(kv["msg"] + pad).decode() == "Building frame"


def test_bad_state_rejected():
    r = run("sh", str(OSC), "emit", "bogus")
    assert r.returncode != 0


def test_query_captured(tmp_path):
    cap = tmp_path / "q.bin"
    r = run("sh", str(OSC), "query", env={"OSC7501_CAPTURE": str(cap)})
    assert r.returncode == 0
    assert b"\x1b]7501;?\x1b\\" in cap.read_bytes()


def test_pilot_hud_emits_via_capture(tmp_path):
    cap = tmp_path / "hud.bin"
    env = {"OSC7501_CAPTURE": str(cap), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    r = run("sh", str(HUD), "canopy", "TEST LINK", env=env)
    assert r.returncode == 0, r.stderr
    data = cap.read_bytes()
    assert b"\x1b]7501;" in data
    assert b"state=working" in data
    assert b"app=familia" in data


def test_pilot_ok_emits_done(tmp_path):
    cap = tmp_path / "ok.bin"
    env = {"OSC7501_CAPTURE": str(cap), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    r = run("sh", str(HUD), "ok", "finished", env=env)
    assert r.returncode == 0
    assert b"state=done" in cap.read_bytes()


def test_wired_scripts_parse():
    for rel in (
        "scripts/osc7501.sh",
        "scripts/pilot_hud.sh",
        "scripts/familia_home.sh",
        "scripts/setup_goals.sh",
        "scripts/proto_chat.sh",
    ):
        path = ROOT / rel
        assert path.is_file(), rel
        assert run("sh", "-n", str(path)).returncode == 0, rel
        text = path.read_text()
        assert "osc7501" in text or rel.endswith("osc7501.sh")


def test_docs_mapping_exists():
    doc = ROOT / "docs" / "protocol" / "osc7501.md"
    assert doc.is_file()
    body = doc.read_text()
    assert "7501" in body
    assert "superlogical.com/rex/docs/build/program-status" in body
    assert "pilot_hud" in body
