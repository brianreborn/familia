"""Fleet greeting in the non-hermes launchers: proto_chat.sh's system prompt, start_graph's join banner."""
import os, re, subprocess, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fleet_greeting as FG  # noqa: E402

DOC_BYTES = open(os.path.join(ROOT, "docs", "FLEET-GREETING.md"), "rb").read()
PROTO = os.path.join(ROOT, "scripts", "proto_chat.sh")


def proto_prompt_block():
    """The SYSTEM_PROMPT assignment + greeting lines, verbatim from scripts/proto_chat.sh."""
    src = open(PROTO).read()
    m = re.search(r"^SYSTEM_PROMPT='.*?^unset _greeted\n", src, re.S | re.M)
    assert m, "proto_chat.sh no longer greets its SYSTEM_PROMPT"
    return m.group(0)


def run_proto_block(tmp_path, env_extra=None):
    script = tmp_path / "block.sh"
    script.write_text(proto_prompt_block() + 'printf "%s" "$SYSTEM_PROMPT"\n')
    env = dict(os.environ, PY=sys.executable, FAMILIA_SCRIPTS=os.path.join(ROOT, "scripts"))
    env.pop(FG.ENV, None)
    env.update(env_extra or {})
    shell = open(PROTO).readline().strip()
    sh = "bash" if "bash" in shell else "sh"
    return subprocess.run([sh, str(script)], capture_output=True, env=env, cwd=str(tmp_path))


def test_proto_chat_prompt_starts_with_greeting_once(tmp_path):
    r = run_proto_block(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith(DOC_BYTES)
    assert r.stdout.count(DOC_BYTES) == 1
    assert r.stdout.endswith(b"Never claim cloud access you do not have.")
    assert b"You are the familia protomodel" in r.stdout


def test_proto_chat_missing_greeting_keeps_prompt(tmp_path):
    r = run_proto_block(tmp_path, {FG.ENV: str(tmp_path / "absent.md")})
    assert r.returncode == 0
    assert r.stdout.startswith(b"You are the familia protomodel")
    assert b"fleet-greeting: warning:" in r.stderr


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
