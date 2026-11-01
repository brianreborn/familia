import pytest
"""#115: offline system-prompt path checks (no network, no live inference)."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "system_prompts")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import system_prompt_check as spc  # noqa: E402


def test_classify_qwen_supported():
    text = open(os.path.join(FIX, "qwen_with_system.jinja"), encoding="utf-8").read()
    assert spc.classify_template(text) == "supported"


def test_classify_legacy_unsupported():
    text = open(os.path.join(FIX, "no_system_role.jinja"), encoding="utf-8").read()
    assert spc.classify_template(text) == "unsupported"


def test_hermes_assembles_system_once():
    r = spc.check_hermes_path(spc.MARKER)
    assert r["ok"] and r["system_count"] == 1


def test_llama_jinja_keeps_system_once_when_supported():
    path = os.path.join(FIX, "qwen_with_system.jinja")
    r = spc.check_llama_jinja_path(path, spc.MARKER)
    assert r["system_role"] == "supported"
    assert r["ok"], r


def test_llama_jinja_unsupported_is_agent_frontend():
    path = os.path.join(FIX, "no_system_role.jinja")
    r = spc.check_llama_jinja_path(path, spc.MARKER)
    assert r["system_role"] == "unsupported"
    assert r["frontend"] == "agent"
    assert r["path"] == "llama.cpp-jinja"
    assert r["ok"]


def test_duplicate_system_detected_when_supported():
    """If a template echoed system twice, count!=1 fails the check."""
    pytest.importorskip("jinja2", reason="duplicate detection needs a real Jinja render")
    # Craft a tiny supported template that duplicates
    import tempfile
    dup = "{% for m in messages %}{{ m.content }}{{ m.content }}{% endfor %}"
    # Actually this doesn't mention system role → unsupported. Force supported path:
    text = "{% if messages[0]['role'] == 'system' %}{{ messages[0]['content'] }}{{ messages[0]['content'] }}{% endif %}"
    with tempfile.NamedTemporaryFile("w", suffix=".jinja", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        r = spc.apply_once(path, spc.MARKER)
        assert r["system_role"] == "supported"
        assert r["count"] == 2
        assert r["ok"] is False
    finally:
        os.unlink(path)


def test_cli_fixtures_pass():
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "system_prompt_check.py"),
         "--fixtures", FIX, "--json"],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
