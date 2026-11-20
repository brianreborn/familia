"""scripts/ui_bridge.py: sanitize server-derived terminal output (L15)."""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ui_bridge as ub  # noqa: E402


def test_sanitize_strips_esc_c0_c1_and_newlines():
    raw = "ok\x1b[31mRED\x00\x07\x1f\x7f\x9b31mX\n\tY"
    out = ub.sanitize(raw)
    assert "\x1b" not in out
    assert "\x00" not in out and "\x07" not in out and "\x1f" not in out
    assert "\x7f" not in out and "\x9b" not in out
    assert "\n" not in out and "\t" not in out
    assert out == "okREDXY"
    for ch in out:
        assert not (ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F)


def test_sanitize_strips_osc_and_bare_esc():
    osc = "name\x1b]0;title\x07done"
    out = ub.sanitize(osc)
    assert "\x1b" not in out and "\x07" not in out
    assert out == "namedone"
    assert ub.sanitize("keep\x1bleft") == "keepleft"
    assert ub.sanitize(None) == ""
    assert ub.sanitize(12) == "12"


def test_use_color_tty_no_color_and_dumb_term():
    class Tty:
        def isatty(self):
            return True

    class Pipe:
        def isatty(self):
            return False

    tty, pipe = Tty(), Pipe()
    assert ub.use_color(stream=tty, environ={"TERM": "xterm"}) is True
    assert ub.use_color(stream=tty, environ={"TERM": "xterm", "NO_COLOR": "1"}) is False
    assert ub.use_color(stream=tty, environ={"TERM": "dumb"}) is False
    assert ub.use_color(stream=pipe, environ={"TERM": "xterm"}) is False
    # empty NO_COLOR is unset per no-color.org
    assert ub.use_color(stream=tty, environ={"TERM": "xterm", "NO_COLOR": ""}) is True


def test_bullet_ascii_fallback_when_encoding_cannot_represent_it():
    class Ascii:
        encoding = "ascii"

    class Utf8:
        encoding = "utf-8"

    class Unknown:
        encoding = None

    assert ub.bullet(Ascii()) == "*"
    assert ub.bullet(Utf8()) == "\u2022"
    assert ub.bullet(Unknown()) == "\u2022"


def _payload():
    return {
        "/props": {
            "model_alias": "alpha\x1b[31mX",
            "model_ftype": "Q4\x07",
            "model_path": "/weights/\x1b]0;evil\x07model.gguf",
            "ui": True,
        },
        "/slots": [
            {
                "id": 0,
                "n_ctx": 4096,
                "speculative": False,
                "is_processing": True,
                "id_task": "t\x1b[2J\x1b[H9",
            }
        ],
        "/v1/models": {
            "data": [{"id": "mid\x00id", "capabilities": ["chat\x1b[0m", "tools\x9b31m"]}]
        },
    }


def _fetch(table):
    def get(path):
        return table[path]
    return get


def test_render_strips_server_escapes_and_skips_ansi_when_not_tty():
    buf = io.StringIO()
    # StringIO is not a TTY; also pin NO_COLOR so styling stays off.
    ub.render_dashboard(file=buf, environ={"NO_COLOR": "1", "TERM": "xterm"}, fetch=_fetch(_payload()))
    out = buf.getvalue()
    assert "\x1b" not in out
    assert "\x00" not in out and "\x07" not in out
    assert "alphaX" in out
    assert "Q4" in out
    assert "model.gguf" in out
    assert "evil" not in out
    assert "t9" in out
    assert "midid" in out
    assert "chat,tools" in out
    assert "PROCESSING" in out
    assert "\u2022" in out or "*" in out


def test_render_emits_ansi_on_tty_but_not_server_escapes():
    class TtyIO(io.StringIO):
        def isatty(self):
            return True
        encoding = "utf-8"

    buf = TtyIO()
    ub.render_dashboard(file=buf, environ={"TERM": "xterm"}, fetch=_fetch(_payload()))
    out = buf.getvalue()
    assert "\033[2J\033[H" in out
    assert "\033[1;32m" in out
    assert "\033[33mPROCESSING\033[0m" in out
    # payload CSI/OSC/C0 must not appear
    assert "\x1b[31m" not in out
    assert "\x1b[2J\x1b[H9" not in out
    assert "\x1b]0;evil" not in out
    assert "\x00" not in out
    assert "alphaX" in out and "t9" in out and "midid" in out


def test_render_connection_error_is_sanitized_and_plain_without_color():
    buf = io.StringIO()
    def fetch(path):
        return {"error": "refused\x1b[31m!\x07"}
    ub.render_dashboard(file=buf, environ={"NO_COLOR": "1"}, fetch=fetch)
    out = buf.getvalue()
    assert "\x1b" not in out and "\x07" not in out
    assert "Cannot connect to llama-server" in out
    assert "refused!" in out
