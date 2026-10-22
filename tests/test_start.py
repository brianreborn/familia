"""Launcher tests for explicit GNU screen session modes."""
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START = os.path.join(ROOT, "start.sh")


@pytest.mark.parametrize(
    ("mode", "screen_flags", "attached_text"),
    [
        ("screen", ["-h", "10000", "-dmS", "familia-server"], "launching graph topology"),
        ("screen-attached", ["-h", "10000", "-S", "familia-server"], "launching attached graph topology"),
    ],
)
def test_screen_session_mode_is_explicit_and_named(tmp_path, mode, screen_flags, attached_text):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "screen-args"
    screen = fake_bin / "screen"
    screen.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SCREEN_CAPTURE\"\n",
        encoding="utf-8",
    )
    screen.chmod(0o755)
    env = dict(os.environ)
    env.update(
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_SYNC_DONE=ROOT,
        SCREEN_CAPTURE=str(capture),
        LOG_FILE=str(tmp_path / "server.log"),
        DETACH_MODE=mode,
        PATH=f"{fake_bin}:{env['PATH']}",
    )

    result = subprocess.run(
        ["sh", START, "--yes"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert attached_text in result.stderr
    args = capture.read_text(encoding="utf-8").splitlines()
    assert args[: len(screen_flags)] == screen_flags
    assert args[len(screen_flags)] == "python3"
    assert args[len(screen_flags) + 1].endswith("scripts/start_graph.py")
    assert "--yes" in args
    assert "familia-server" in result.stderr
