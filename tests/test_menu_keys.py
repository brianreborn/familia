"""scripts/menu_keys.py (epic #733 M1): key decoding, picker state, rendering, and the
terminal layer under a pty (raw mode on while picking, restored after Enter/Ctrl-D/SIGINT)."""
import os
import select
import signal
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import menu_keys as mk  # noqa: E402

PICKER = os.path.join(ROOT, "scripts", "menu_keys.py")
MENU = os.path.join(ROOT, "familia-menu.sh")


# ---- Picker ------------------------------------------------------------------

def feed(p, *keys):
    out = None
    for k in keys:
        out = p.feed(k)
        if out is not None:
            return out
    return out


def test_arrows_wrap_and_enter_answers_one_based():
    p = mk.Picker(3)
    assert feed(p, mk.UP, mk.ENTER) == "3"
    p = mk.Picker(3)
    assert feed(p, mk.DOWN, mk.DOWN, mk.DOWN, mk.ENTER) == "1"
    p = mk.Picker(3, cursor=1)
    assert feed(p, mk.ENTER) == "2"


def test_home_end_pgup_pgdn():
    p = mk.Picker(5, cursor=2)
    feed(p, mk.END); assert p.cursor == 4
    feed(p, mk.HOME); assert p.cursor == 0
    feed(p, mk.PGDN); assert p.cursor == 4
    feed(p, mk.PGUP); assert p.cursor == 0
    assert feed(mk.Picker(5, cursor=2, next=True), mk.PGDN) == ">"   # menu-keys.sh contract
    assert feed(mk.Picker(5, cursor=2, prev=True), mk.PGUP) == "<"


def test_numeric_entry_multi_digit_and_text_pass_through():
    assert feed(mk.Picker(19), "1", "2", mk.ENTER) == "12"
    assert feed(mk.Picker(3), "9", mk.ENTER) == "9"  # out of range: menu says so
    assert feed(mk.Picker(3), "/", "h", "e", "r", "m", "e", "s", mk.ENTER) == "/hermes"
    assert feed(mk.Picker(3), "F", "O", "O", "=", "1", " ", "2", mk.ENTER) == "FOO=1 2"
    assert feed(mk.Picker(3), "n", mk.ENTER) == "n"
    p = mk.Picker(5)
    feed(p, "3"); assert p.cursor == 2  # highlight follows typed digits


def test_backspace_edits_then_goes_back_and_esc():
    p = mk.Picker(9)
    assert feed(p, "1", "2", mk.BACKSPACE, mk.ENTER) == "1"
    assert feed(mk.Picker(3), mk.BACKSPACE) == "b"
    assert feed(mk.Picker(3), mk.ESC) == "b"
    p = mk.Picker(3)
    assert feed(p, "4", mk.ESC) is None and p.line == ""
    assert feed(mk.Picker(3, top=True), mk.ESC, mk.BACKSPACE) is None


def test_q_quits_only_on_empty_line():
    assert feed(mk.Picker(3), "q") == "q"
    assert feed(mk.Picker(3), "Q") == "q"
    assert feed(mk.Picker(3), "/", "q", mk.ENTER) == "/q"


def test_arrow_clears_typed_line_and_unknown_is_ignored():
    p = mk.Picker(3)
    assert feed(p, "2", mk.DOWN, mk.UNKNOWN, mk.ENTER) == "3"
    assert feed(mk.Picker(0), mk.DOWN, mk.ENTER) is None


def test_render_marks_current_entry():
    p = mk.Picker(2, cursor=1)
    p.line = "1"
    lines = mk.render(["head"], ["  1) a\n     runs: x", "  2) b\n     runs: y"], ["foot"], "Choose: ", p, False)
    assert lines == ["head", "  1) a", "     runs: x", "> 2) b", "     runs: y", "foot", "Choose: 1"]
    lines = mk.render([], ["  1) a"], [], "> ", mk.Picker(1), True)
    assert lines[0] == "\033[7m> 1) a\033[0m"


def test_render_prompt_only_shows_current_number():
    p = mk.Picker(7, cursor=2)
    assert mk.render([], [], [], "Choose: ", p, False) == ["Choose: [3]"]
    assert mk.render([], [], [], "Choose: ", p, True) == ["Choose: \033[7m[3]\033[0m"]
    p.line = "12"
    assert mk.render([], [], [], "Choose: ", p, True) == ["Choose: 12"]


def test_rows_counts_wrapped_and_wide_lines():
    assert mk.rows(["a" * 10, "b" * 25], 10) == 4
    assert mk.rows(["\033[7mabc\033[0m"], 3) == 1
    assert mk.rows(["\u4e2d" * 3], 4) == 2


@pytest.mark.skipif(mk._m2() is None, reason="needs scripts/menu_input.py (#736, M2)")
def test_m2_keys_map_onto_picker_keys():
    """M1 has no decoder of its own; menu_input (M2, #736) is the decoder of record."""
    mi = mk._m2()
    Key = mi.Key
    assert mk.from_m2(mi, Key("UP", "", 4, False)) == mk.UP          # Ctrl+Up is Up
    assert mk.from_m2(mi, Key("CHAR", "7", 0, False)) == "7"
    assert mk.from_m2(mi, Key("CTRL_D", "", 0, False)) == mk.EOF
    assert mk.from_m2(mi, Key("CTRL_C", "", 0, False)) == mk.INTR
    assert mk.from_m2(mi, Key("PASTE", "/model x", 0, False)) == (mk.PASTE, "/model x")
    assert mk.Picker(3).feed(mk.from_m2(mi, Key("ALT", "b", 2, False))) is None  # never Esc = back
    assert [mk.from_m2(mi, k) for k in mi.decode(b"\x1b[B\x1b[1;5A\r")] == [mk.DOWN, mk.UP, mk.ENTER]


def test_paste_is_literal_single_line_and_bounded():
    assert feed(mk.Picker(3), (mk.PASTE, "q\x1b[A"), mk.ENTER) == "q[A"   # a pasted q is text, not quit
    assert feed(mk.Picker(3), (mk.PASTE, "/a\nb\tc"), mk.ENTER) == "/a b c"
    p = mk.Picker(3)
    feed(p, (mk.PASTE, "x" * 10000))
    assert len(p.line) == mk.MAX_LINE


def test_help_and_no_terminal_exit_3():
    r = subprocess.run([sys.executable, PICKER, "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "usage" in r.stdout.lower()
    r = subprocess.run([sys.executable, PICKER, "pick", "--", "a"], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 3 and r.stdout == ""


# ---- terminal layer under a pty ------------------------------------------------

termios = pytest.importorskip("termios")
pty = pytest.importorskip("pty")
needs_m2 = pytest.mark.skipif(mk._m2() is None, reason="arrow keys need scripts/menu_input.py (#736, M2)")


def _read_until(fd, needle, timeout=10):
    buf = b""
    end = time.time() + timeout
    while needle not in buf and time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
    return buf


def _start_picker(*args):
    master, slave = os.openpty()
    before = termios.tcgetattr(slave)
    p = subprocess.Popen([sys.executable, PICKER, "pick", "--prompt", "Pick: ", *args],
                         stdin=slave, stderr=slave, stdout=subprocess.PIPE, env=dict(os.environ, TERM="xterm"))
    _read_until(master, b"Pick: ")
    return p, master, slave, before


def _finish(p, master, slave, before):
    try:
        out, _ = p.communicate(timeout=10)
        lflag = termios.tcgetattr(slave)[3]
        assert lflag == before[3], "terminal mode not restored"
        return p.returncode, out.decode()
    finally:
        os.close(master)
        os.close(slave)


@needs_m2
def test_pty_arrows_select_and_restore_terminal():
    p, m, s, before = _start_picker("--", "  1) one", "  2) two", "  3) three")
    os.write(m, b"\x1b[B\x1b[B")
    time.sleep(0.2)
    os.write(m, b"\x1b[A\r")
    assert _finish(p, m, s, before) == (0, "2\n")


@needs_m2
def test_pty_bracketed_paste_on_then_off():
    p, m, s, before = _start_picker("--count", "2")
    os.write(m, b"\r")
    out = _read_until(m, b"\x1b[?2004l", timeout=5)
    assert _finish(p, m, s, before) == (0, "1\n")
    assert b"\x1b[?2004l" in out


@needs_m2
def test_pty_lone_esc_is_back_and_digits_work():
    p, m, s, before = _start_picker("--", "  1) one", "  2) two")
    os.write(m, b"\x1b")
    assert _finish(p, m, s, before) == (0, "b\n")
    p, m, s, before = _start_picker("--", *["  %d) x" % i for i in range(1, 13)])
    os.write(m, b"12\r")
    assert _finish(p, m, s, before) == (0, "12\n")


@needs_m2
def test_pty_ctrl_d_and_sigint_restore_terminal():
    p, m, s, before = _start_picker("--", "  1) one")
    os.write(m, b"\x04")
    assert _finish(p, m, s, before) == (4, "")
    p, m, s, before = _start_picker("--", "  1) one")
    p.send_signal(signal.SIGINT)
    rc, out = _finish(p, m, s, before)
    assert rc in (-signal.SIGINT, 130) and out == ""


@needs_m2
def test_pty_count_mode_and_page_keys():
    p, m, s, before = _start_picker("--count", "3", "--prev", "--next")
    os.write(m, b"\x1b[B\x1b[B\x1b[B\x1b[B\r")   # wraps: 1 -> 2 -> 3 -> 1 -> 2
    assert _finish(p, m, s, before) == (0, "2\n")
    p, m, s, before = _start_picker("--count", "3", "--prev", "--next")
    os.write(m, b"\x1b[6~")
    assert _finish(p, m, s, before) == (0, ">\n")
    p, m, s, before = _start_picker("--count", "3", "--prev", "--next")
    os.write(m, b"&mod\r")
    assert _finish(p, m, s, before) == (0, "&mod\n")


@needs_m2
def test_pty_count_mode_sigwinch_keeps_the_printed_list():
    p, m, s, before = _start_picker("--count", "2")
    p.send_signal(signal.SIGWINCH)
    out = _read_until(m, b"[1]", timeout=2)
    os.write(m, b"\r")
    assert _finish(p, m, s, before) == (0, "1\n")
    assert b"\x1b[2J" not in out


def test_menu_keys_sh_contract_without_terminal_falls_back_to_read_line():
    script = (". scripts/menu-keys.sh; read_line() { printf '%s' \"$1\" >&2; IFS= read -r \"$2\"; };"
              "menu_key_read 'P: ' got 3; echo \"rc=$? got=$got\"; menu_key_read 'P: ' got 3; echo \"rc=$?\"")
    r = subprocess.run(["bash", "-c", script], cwd=ROOT, input="2\n", capture_output=True, text=True,
                       env=dict(os.environ, FAMILIA_NO_TTY="1"))
    assert "rc=0 got=2" in r.stdout and "rc=1" in r.stdout


@needs_m2
def test_pty_sigwinch_redraws_full():
    p, m, s, before = _start_picker("--head", "HEAD", "--", "  1) one")
    p.send_signal(signal.SIGWINCH)
    assert b"\x1b[2J" in _read_until(m, b"\x1b[2J")
    os.write(m, b"\r")
    assert _finish(p, m, s, before) == (0, "1\n")


@needs_m2
def test_pty_familia_menu_arrows_and_numbers():
    """End to end: arrows pick a group and an item (dry run), numbers still work, q quits."""
    master, slave = os.openpty()
    env = dict(os.environ, TERM="xterm", FAMILIA_COLOR="never")
    for k in ("FAMILIA_NO_TTY", "FAMILIA_MENU_PIPE", "FAMILIA_ACCEPT_LICENSES"):
        env.pop(k, None)
    p = subprocess.Popen(["bash", MENU, "--dry-run"], cwd=ROOT, stdin=slave, stdout=slave, stderr=slave, env=env)
    try:
        assert b"Choose 1-" in _read_until(master, b"Choose 1-")
        os.write(master, b"\x1b[B\r")                     # group 2: Skills
        assert b"Skills:" in _read_until(master, b"or b: ")
        os.write(master, b"\x1b[B\r")                     # item 2: skills.list
        assert b"[dry-run] python3 scripts/skills.py list" in _read_until(master, b"Press Enter")
        os.write(master, b"\r")
        _read_until(master, b"or b: ")
        os.write(master, b"\x1b")                          # Esc: back to the top menu
        _read_until(master, b"Choose 1-")
        os.write(master, b"q")
        assert p.wait(timeout=20) == 0
    finally:
        if p.poll() is None:
            p.kill()
        os.close(master)
        os.close(slave)


@needs_m2
def test_pty_familia_menu_ctrl_c_restores_terminal_and_stops():
    """Ctrl-C typed on the controlling terminal: the menu stops and the terminal is cooked again."""
    import fcntl
    master, slave = os.openpty()
    before = termios.tcgetattr(slave)

    def ctty():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    env = dict(os.environ, TERM="xterm")
    for k in ("FAMILIA_NO_TTY", "FAMILIA_MENU_PIPE"):
        env.pop(k, None)
    p = subprocess.Popen(["bash", MENU, "--dry-run"], cwd=ROOT, stdin=slave, stdout=slave, stderr=slave,
                         env=env, preexec_fn=ctty)
    try:
        _read_until(master, b"Choose 1-")
        deadline = time.time() + 10
        while termios.tcgetattr(slave)[3] & termios.ICANON and time.time() < deadline:
            time.sleep(0.05)
        assert not termios.tcgetattr(slave)[3] & termios.ICANON, "picker never took the terminal"
        os.write(master, b"\x03")
        assert p.wait(timeout=20) != 0
        assert termios.tcgetattr(slave)[3] == before[3]
    finally:
        if p.poll() is None:
            p.kill()
        os.close(master)
        os.close(slave)


@pytest.mark.skipif(mk._m2() is not None, reason="only meaningful before #736 lands")
def test_without_m2_the_picker_steps_aside():
    master, slave = os.openpty()
    try:
        r = subprocess.run([sys.executable, PICKER, "pick", "--count", "2"], stdin=slave, stderr=slave,
                           capture_output=False, stdout=subprocess.PIPE, env=dict(os.environ, TERM="xterm"), timeout=10)
        assert r.returncode == 3 and r.stdout == b""
    finally:
        os.close(master)
        os.close(slave)
