"""Fleet greeting in the non-hermes launchers: proto_chat.sh's system prompt, start_graph's join banner."""
import os, subprocess, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fleet_greeting as FG  # noqa: E402

DOC_BYTES = open(os.path.join(ROOT, "docs", "FLEET-GREETING.md"), "rb").read()
PROTO = os.path.join(ROOT, "scripts", "proto_chat.sh")


def run_proto_block(tmp_path, env_extra=None):
    """Print the prompt proto_chat.sh would send, from a cwd that is not the repo."""
    env = dict(os.environ, PYTHON=sys.executable, FAMILIA_NO_TTY="1")
    env.pop(FG.ENV, None)
    env.pop("FAMILIA_PROTOGRAPH_PROMPT", None)
    env.update(env_extra or {})
    return subprocess.run(
        ["sh", PROTO, "--print-system-prompt"],
        capture_output=True, env=env, cwd=str(tmp_path),
    )


def test_proto_chat_prompt_starts_with_greeting_once(tmp_path):
    r = run_proto_block(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith(DOC_BYTES)
    assert r.stdout.count(DOC_BYTES) == 1
    assert r.stdout.rstrip().endswith(b"Never claim cloud access you do not have.")
    assert b"You are the familia protomodel" in r.stdout
    assert b"graph_definition" in r.stdout


def test_proto_chat_missing_greeting_keeps_prompt(tmp_path):
    r = run_proto_block(tmp_path, {FG.ENV: str(tmp_path / "absent.md")})
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith(b"You are the familia protomodel")
    assert b"fleet-greeting: warning:" in r.stderr
    assert b"graph_definition" in r.stdout


def test_start_graph_banner(monkeypatch, capsys, tmp_path):
    import start_graph as SG
    monkeypatch.delenv(FG.ENV, raising=False); FG._cache.clear()
    assert SG._fleet_banner("miryam") is True
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "miryam" in err and os.path.join("docs", "FLEET-GREETING.md") in err
    monkeypatch.setenv(FG.ENV, str(tmp_path / "absent.md")); FG._cache.clear()
    assert SG._fleet_banner("miryam") is False
    FG._cache.clear()


def test_start_graph_calls_banner_on_live_start_only():
    src = open(os.path.join(ROOT, "scripts", "start_graph.py")).read()
    live = src.split("if options.dry_run:", 1)[1]
    assert "_fleet_banner(host)" in live
    assert live.index("_fleet_banner(host)") > live.index("nothing started")
