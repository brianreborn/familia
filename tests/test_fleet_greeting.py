"""Fleet greeting (docs/FLEET-GREETING.md) opens every familia agent's system prompt, exactly once.

scripts/fleet_greeting.py reads the fleet-signed file as-is; scripts/hermes_harness.py puts it at
byte 0 of the rendered HERMES_HOME/SOUL.md (hermes' identity slot #1) for every agent, pentest and
guardian included; scripts/proto_chat.sh pipes its prompt through it; scripts/start_graph.py prints a
one-line banner. Everything here writes under tmp_path only.
"""
import copy, os, subprocess, sys
import pytest, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fleet_greeting as FG  # noqa: E402

DOC = os.path.join(ROOT, "docs", "FLEET-GREETING.md")
DOC_BYTES = open(DOC, "rb").read()
DOC_TEXT = DOC_BYTES.decode("utf-8")


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(FG.ENV, raising=False)
    FG._cache.clear()
    yield
    FG._cache.clear()


# ---- the module ---------------------------------------------------------------------------------

def test_default_path_is_repo_doc_and_content_byte_exact():
    assert os.path.samefile(FG.path(), DOC)
    assert FG.load().encode("utf-8") == DOC_BYTES


def test_env_override_absolute_and_repo_relative(tmp_path, monkeypatch):
    alt = tmp_path / "greet.md"
    alt.write_bytes(b"# Hi fleet\n\nline two\n")
    monkeypatch.setenv(FG.ENV, str(alt))
    assert FG.path() == str(alt) and FG.load() == "# Hi fleet\n\nline two\n"
    monkeypatch.setenv(FG.ENV, os.path.join("docs", "FLEET-GREETING.md"))
    assert FG.path() == os.path.join(ROOT, "docs", "FLEET-GREETING.md")
    assert FG.load().encode("utf-8") == DOC_BYTES


def test_read_once_per_process(tmp_path):
    f = tmp_path / "g.md"
    f.write_text("first\n")
    assert FG.load(str(f)) == "first\n"
    f.write_text("second\n")
    assert FG.load(str(f)) == "first\n"   # startup read is cached, not re-read per prompt


def test_prepend_exactly_once_and_byte_exact():
    body = "You are a careful assistant.\n"
    once = FG.prepend(body)
    assert once.encode("utf-8").startswith(DOC_BYTES)
    assert once.endswith(body)
    assert once.count(DOC_TEXT) == 1 and once.count(FG.END_MARKER) == 1
    assert FG.prepend(once) == once
    assert FG.prepend(FG.prepend(once)) == once


def test_prepend_empty_body_and_greeting_without_trailing_newline():
    assert FG.prepend("", greeting="hello") == "hello\n" + FG.END_MARKER + "\n"
    assert FG.prepend("x", greeting="hello\n") == "hello\n" + FG.END_MARKER + "\n\nx"


def test_stale_greeting_replaced_not_stacked():
    old = FG.prepend("body\n", greeting="old greeting\n")
    new = FG.prepend(old, greeting="new greeting\n")
    assert new == "new greeting\n" + FG.END_MARKER + "\n\nbody\n"
    assert "old greeting" not in new


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "not-utf8"])
def test_missing_or_unreadable_warns_and_continues(tmp_path, monkeypatch, capsys, kind):
    p = tmp_path / "greet.md"
    if kind == "directory": p.mkdir()
    elif kind == "empty": p.write_text("  \n")
    elif kind == "not-utf8": p.write_bytes(b"\xff\xfe\x00bad")
    monkeypatch.setenv(FG.ENV, str(p))
    assert FG.load() is None
    assert FG.prepend("body\n") == "body\n"
    assert FG.prepend(FG.prepend("body\n", greeting="stale\n")) == "body\n"   # stale copy dropped
    err = capsys.readouterr().err
    assert err.count("fleet-greeting: warning:") == 1 and "continuing without the fleet greeting" in err


def test_marker_passes_hermes_context_scan_wording():
    # hermes tools/threat_patterns.py html_comment_injection: <!-- ... ignore|override|system|secret|hidden ... -->
    low = FG.END_MARKER.lower()
    assert not any(w in low for w in ("ignore", "override", "system", "secret", "hidden"))


def test_cli_prepend_and_path(tmp_path):
    env = dict(os.environ)
    env.pop(FG.ENV, None)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "fleet_greeting.py"), "prepend"],
                       input=b"sys prompt\n", capture_output=True, env=env, check=True)
    assert r.stdout.startswith(DOC_BYTES) and r.stdout.endswith(b"\nsys prompt\n")
    env[FG.ENV] = str(tmp_path / "absent.md")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "fleet_greeting.py"), "prepend"],
                       input=b"sys prompt\n", capture_output=True, env=env)
    assert r.returncode == 0 and r.stdout == b"sys prompt\n" and b"warning" in r.stderr
