"""Versioned protograph system prompt (#327 section 2).

The file skills/protograph/prompts/system.md is the generator prompt.
scripts/proto_chat.sh and scripts/protograph.py load it from the repo root,
not the caller's cwd, and fall back to the short pre-#327 prompt when it is
missing or empty.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import protograph  # noqa: E402

PROMPT = ROOT / "skills" / "protograph" / "prompts" / "system.md"
PROTO = ROOT / "scripts" / "proto_chat.sh"
REL = "skills/protograph/prompts/system.md"

# Section 2 of #327, plus the compiler contract the prompt has to match.
REQUIRED = (
    "version: 1",
    "prompt-id: protograph-system",
    "## Purpose",
    "## Script index",
    "## Responsibilities",
    "## Constraints",
    "## Output format",
    "## Recipe contract",
    "## Platforms",
    "graph_definition",
    "benchmark_summary",
    "required_tools",
    "installation_plan",
    "canonical YAML",
    "protograph: 1",
    "scripts/protograph.py",
    "scripts/validate_graph.py",
    "scripts/menu-items.txt",
    "scripts/serve.sh",
    "scripts/registry.py",
    "scripts\\windows\\start.bat",
    "Host-only",
    "Non-destructive by default",
    "explicit consent",
    "confirmation",
    "destructive",
    "$TMPDIR",
    "REPLACE_ME",
    "127.0.0.1",
    "from_graph",
    "angel-coder",
    "Linux",
    "FreeBSD",
    "Termux",
    "Android",
    "Windows",
    "macOS",
)

# Brian's comment on #327: these must not be instructions in the prompt.
FORBIDDEN = (
    "/usr/home",
    ".gemini",
    "antigravity",
)


def _env(**extra):
    env = dict(os.environ, PYTHON=sys.executable, FAMILIA_NO_TTY="1")
    env.pop("FAMILIA_PROTOGRAPH_PROMPT", None)
    env.pop("FAMILIA_FLEET_GREETING", None)
    env.update(extra)
    return env


def _print_prompt(tmp_path, *args, shell="sh", **extra):
    return subprocess.run(
        [shell, str(PROTO), "--print-system-prompt", *args],
        capture_output=True, env=_env(**extra), cwd=str(tmp_path),
    )


def test_prompt_file_exists_and_is_ascii():
    raw = PROMPT.read_bytes()
    assert raw, "prompt file is empty"
    raw.decode("ascii")
    assert b"\0" not in raw
    assert raw.endswith(b"\n")


def test_prompt_has_required_sections_and_avoids_platform_paths():
    text = PROMPT.read_text(encoding="ascii")
    missing = [s for s in REQUIRED if s not in text]
    assert not missing, "prompt is missing: " + ", ".join(missing)
    present = [s for s in FORBIDDEN if s in text]
    assert not present, "prompt must stay platform-agnostic, found: " + ", ".join(present)
    assert "not a script in this tree" in text
    assert "menu-internal" not in text
    assert "RUN: ./familia" in text


def test_skill_points_at_the_prompt_file():
    skill = (ROOT / "skills" / "protograph" / "SKILL.md").read_text(encoding="ascii")
    assert REL in skill
    assert "FAMILIA_PROTOGRAPH_PROMPT" in skill


def test_proto_chat_loads_prompt_from_another_directory(tmp_path):
    r = _print_prompt(tmp_path)
    assert r.returncode == 0, r.stderr
    assert b"graph_definition" in r.stdout
    assert b"protograph: 1" in r.stdout
    assert b"using the short fallback" not in r.stderr
    # Fleet greeting is prepended; the versioned body is still the file.
    assert PROMPT.read_bytes().rstrip() in r.stdout


def test_proto_chat_relative_override_is_repo_root_not_cwd(tmp_path):
    r = _print_prompt(tmp_path, FAMILIA_PROTOGRAPH_PROMPT=REL)
    assert r.returncode == 0, r.stderr
    assert b"graph_definition" in r.stdout
    assert b"using the short fallback" not in r.stderr


def test_proto_chat_absolute_override_outside_is_rejected(tmp_path):
    custom = tmp_path / "custom.md"
    custom.write_text("CUSTOM-PROMPT-SENTINEL graph_definition\n", encoding="ascii")
    r = _print_prompt(tmp_path, FAMILIA_PROTOGRAPH_PROMPT=str(custom))
    assert r.returncode == 0, r.stderr
    assert b"outside" in r.stderr and b"using the short fallback" in r.stderr
    assert b"CUSTOM-PROMPT-SENTINEL" not in r.stdout


def test_proto_chat_windows_drive_override_is_not_joined_to_the_repo(tmp_path):
    # dash/FreeBSD sh: a drive path is absolute. Do not prefix the repo root.
    r = _print_prompt(
        tmp_path,
        FAMILIA_PROTOGRAPH_PROMPT=r"C:\no\such.md",
        FAMILIA_FLEET_GREETING=str(tmp_path / "no-greeting.md"),
    )
    assert r.returncode == 0, r.stderr
    err = r.stderr.decode("utf-8", "replace")
    assert r"C:\no\such.md" in err
    assert str(ROOT) + r"/C:" not in err
    assert r.stdout.rstrip(b"\n") == protograph.FALLBACK_SYSTEM_PROMPT.encode("utf-8")


def test_proto_chat_falls_back_when_missing(tmp_path):
    missing = tmp_path / "no-such-prompt.md"
    r = _print_prompt(
        tmp_path,
        FAMILIA_PROTOGRAPH_PROMPT=str(missing),
        FAMILIA_FLEET_GREETING=str(tmp_path / "no-greeting.md"),
    )
    assert r.returncode == 0, r.stderr
    assert b"outside" in r.stderr
    assert b"using the short fallback" in r.stderr
    assert r.stdout.rstrip(b"\n") == protograph.FALLBACK_SYSTEM_PROMPT.encode("utf-8")
    assert b"graph_definition" not in r.stdout


def test_proto_chat_falls_back_when_name_missing_inside_prompts(tmp_path):
    r = _print_prompt(
        tmp_path,
        FAMILIA_PROTOGRAPH_PROMPT="skills/protograph/prompts/does-not-exist.md",
        FAMILIA_FLEET_GREETING=str(tmp_path / "no-greeting.md"),
    )
    assert r.returncode == 0, r.stderr
    assert b"missing or empty" in r.stderr
    assert b"using the short fallback" in r.stderr
    assert r.stdout.rstrip(b"\n") == protograph.FALLBACK_SYSTEM_PROMPT.encode("utf-8")


def test_proto_chat_dotdot_override_is_rejected(tmp_path):
    r = _print_prompt(
        tmp_path,
        FAMILIA_PROTOGRAPH_PROMPT="../etc/passwd",
        FAMILIA_FLEET_GREETING=str(tmp_path / "no-greeting.md"),
    )
    assert r.returncode == 0, r.stderr
    assert b"outside" in r.stderr
    assert b"root:" not in r.stdout
    assert r.stdout.rstrip(b"\n") == protograph.FALLBACK_SYSTEM_PROMPT.encode("utf-8")


def test_proto_chat_help_mentions_print_flag():
    r = subprocess.run(
        ["sh", str(PROTO), "--help"],
        capture_output=True, text=True, env=_env(), cwd=str(ROOT),
    )
    assert r.returncode == 0
    assert "--print-system-prompt" in r.stdout


@pytest.mark.skipif(not os.path.exists("/bin/dash") and not os.path.exists("/usr/bin/dash"),
                    reason="dash is not installed")
def test_proto_chat_loads_prompt_under_dash(tmp_path):
    dash = "/usr/bin/dash" if os.path.exists("/usr/bin/dash") else "/bin/dash"
    r = _print_prompt(tmp_path, shell=dash)
    assert r.returncode == 0, r.stderr
    assert b"graph_definition" in r.stdout
    assert b"using the short fallback" not in r.stderr


def test_protograph_py_prints_the_same_file(tmp_path):
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "protograph.py"), "--print-prompt"],
        capture_output=True, env=_env(), cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == PROMPT.read_bytes() if PROMPT.read_bytes().endswith(b"\n") else PROMPT.read_bytes() + b"\n"
    assert r.stderr == b""


def test_protograph_py_relative_override_ignores_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FAMILIA_PROTOGRAPH_PROMPT", REL)
    text, path, fallback = protograph.load_system_prompt()
    assert fallback is False
    assert Path(path) == PROMPT
    assert "graph_definition" in text


def test_protograph_py_fallback_when_missing(tmp_path):
    missing = str(tmp_path / "absent.md")
    text, path, fallback = protograph.load_system_prompt(override=missing)
    assert fallback is True
    assert text == protograph.FALLBACK_SYSTEM_PROMPT
    assert path == missing
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "protograph.py"), "--print-prompt"],
        capture_output=True, env=_env(FAMILIA_PROTOGRAPH_PROMPT=missing), cwd=str(tmp_path),
    )
    assert r.returncode == 0
    assert b"using the short fallback" in r.stderr
    assert r.stdout.rstrip(b"\n") == protograph.FALLBACK_SYSTEM_PROMPT.encode("utf-8")


def test_protograph_py_rejects_non_ascii_prompt(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"not ascii \xe2\x80\x94\n")
    text, _, fallback = protograph.load_system_prompt(override=str(bad))
    assert fallback is True
    assert text == protograph.FALLBACK_SYSTEM_PROMPT


def test_protograph_py_still_requires_a_recipe():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "protograph.py")],
        capture_output=True, text=True, env=_env(), cwd=str(ROOT),
    )
    assert r.returncode != 0
    assert "recipe" in r.stderr


def test_windows_drive_override_is_not_joined_to_the_repo(tmp_path):
    # On POSIX, os.path.isabs("C:/...") is false. The loader must still not
    # prefix ROOT onto a drive path, and a drive path is outside the prompts dir.
    path = protograph.system_prompt_path(root=str(ROOT), override=r"C:\no\such\prompt.md")
    assert path == r"C:\no\such\prompt.md"
    assert not path.startswith(str(ROOT))
    text, _variant, fallback, warning = protograph.select_system_prompt(
        8192, override=r"C:\no\such\prompt.md", greeting="")
    assert fallback is True and text == protograph.FALLBACK_SYSTEM_PROMPT
    assert "outside" in warning and r"C:\no\such\prompt.md" in warning


def _prompt_tree(tmp_path):
    d = tmp_path / "skills" / "protograph" / "prompts"
    d.mkdir(parents=True)
    return d


def test_symlink_prompt_is_not_followed(tmp_path):
    d = _prompt_tree(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET-SHOULD-NOT-LOAD\n", encoding="ascii")
    (d / "system.md").symlink_to(secret)
    text, _variant, fallback, warning = protograph.select_system_prompt(
        8192, root=str(tmp_path), greeting="")
    assert fallback is True
    assert "SECRET-SHOULD-NOT-LOAD" not in text
    assert "symlink" in warning


def test_empty_prompt_inside_prompts_dir_falls_back(tmp_path):
    d = _prompt_tree(tmp_path)
    (d / "system.md").write_text("\n\n  \t\n", encoding="ascii")
    text, _variant, fallback, warning = protograph.select_system_prompt(
        8192, root=str(tmp_path), greeting="")
    assert fallback is True and text == protograph.FALLBACK_SYSTEM_PROMPT
    assert "empty" in warning


def test_non_ascii_prompt_inside_prompts_dir_falls_back(tmp_path):
    d = _prompt_tree(tmp_path)
    (d / "system.md").write_bytes(b"not ascii \xe2\x80\x94\n")
    text, _variant, fallback, warning = protograph.select_system_prompt(
        8192, root=str(tmp_path), greeting="")
    assert fallback is True and text == protograph.FALLBACK_SYSTEM_PROMPT
    assert "not ASCII" in warning


def test_budget_across_graph_ctx_sizes():
    import fleet_greeting
    greeting = fleet_greeting.load()
    ctxs = protograph.graph_ctx_values()
    assert ctxs == [256, 2048, 8192, 65536]
    seen = {}
    for ctx in ctxs:
        try:
            text, variant, fallback, _warn = protograph.select_system_prompt(ctx, greeting=greeting)
        except protograph.PromptRefuse as exc:
            assert ctx < protograph.MAX_OUTPUT_TOKENS + protograph.USER_TURN_TOKENS
            assert "ctx %s" % ctx in str(exc)
            continue
        again = protograph.select_system_prompt(ctx, greeting=greeting)
        assert again[0] == text and again[1] == variant
        assembled = fleet_greeting.prepend(text, greeting=greeting)
        assert (protograph.estimate_tokens(assembled) + protograph.USER_TURN_TOKENS
                + protograph.MAX_OUTPUT_TOKENS) <= ctx
        assert "RUN: ./familia" in text
        assert str(ctx) not in text
        seen[ctx] = (variant, fallback, text)
    assert seen[2048][0] == "compact" and seen[2048][1] is False
    assert seen[8192][0] == "full" and seen[65536][0] == "full"
    assert seen[8192][2] == seen[65536][2]
    assert seen[2048][2] != seen[8192][2]
    compact = (ROOT / "skills" / "protograph" / "prompts" / "system-compact.md").read_text(encoding="ascii")
    assert seen[2048][2] == compact or seen[2048][2] == compact.rstrip("\n")


def test_proto_chat_compact_for_ctx_2048_and_refuse_for_256(tmp_path):
    small = _print_prompt(
        tmp_path, "--ctx", "2048",
        FAMILIA_FLEET_GREETING=str(ROOT / "docs" / "FLEET-GREETING.md"),
    )
    assert small.returncode == 0, small.stderr
    assert b"prompt-id: protograph-system-compact" in small.stdout
    assert b"RUN: ./familia" in small.stdout
    refused = _print_prompt(tmp_path, "--ctx", "256")
    assert refused.returncode != 0
    err = refused.stderr.decode("utf-8", "replace")
    assert "does not fit" in err or "cannot hold" in err
