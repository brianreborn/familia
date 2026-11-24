"""#733 M2: key input hardening and the legacy fallback.

The decoder turns bytes into key tokens and never lets an escape sequence leak
out as text. The probe sends anything that is not a real terminal to the legacy
numeric menu, and the legacy menu reaches every item.
"""
import os
import pty
import re
import subprocess
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import menu_input as mi  # noqa: E402

MENU = os.path.join(ROOT, "familia-menu.sh")
HOME_SH = os.path.join(ROOT, "scripts", "familia_home.sh")
ITEMS_FILE = os.path.join(ROOT, "scripts", "menu-items.txt")
PAGE_SIZE = 7  # familia-menu.sh menu(): page_size=7


def names(keys):
    return [k.name if not k.text else (k.name, k.text) for k in keys]


def chars(keys):
    return "".join(k.text for k in keys if k.name == mi.K_CHAR)


# ---- decoder ------------------------------------------------------------------

@pytest.mark.parametrize("seq,name", [
    (b"\x1b[A", mi.K_UP), (b"\x1b[B", mi.K_DOWN), (b"\x1b[C", mi.K_RIGHT), (b"\x1b[D", mi.K_LEFT),
    (b"\x1bOA", mi.K_UP), (b"\x1bOB", mi.K_DOWN), (b"\x1b[H", mi.K_HOME), (b"\x1b[F", mi.K_END),
    (b"\x1bOH", mi.K_HOME), (b"\x1bOF", mi.K_END), (b"\x1b[1~", mi.K_HOME), (b"\x1b[7~", mi.K_HOME),
    (b"\x1b[4~", mi.K_END), (b"\x1b[8~", mi.K_END), (b"\x1b[5~", mi.K_PGUP), (b"\x1b[6~", mi.K_PGDN),
    (b"\x1b[3~", mi.K_DELETE), (b"\x1b[2~", mi.K_INSERT), (b"\x1b[Z", mi.K_BACKTAB),
    (b"\r", mi.K_ENTER), (b"\n", mi.K_ENTER), (b"\x1bOM", mi.K_ENTER), (b"\x7f", mi.K_BACKSPACE),
    (b"\x08", mi.K_BACKSPACE), (b"\t", mi.K_TAB), (b"\x03", mi.K_CTRL_C), (b"\x04", mi.K_CTRL_D),
    (b"\x1b[15~", "F5"), (b"\x1bOP", "F1"),
])
def test_known_keys(seq, name):
    assert names(mi.decode(seq)) == [name]
    assert names(mi.decode(seq + b"q")) == [name, (mi.K_CHAR, "q")]


def test_modifiers_are_reported_not_lost():
    k = mi.decode(b"\x1b[1;5A")
    assert names(k) == [mi.K_UP] and k[0].mods == 4  # Ctrl
    assert mi.decode(b"\x1b[5;2~")[0].mods == 1     # Shift


def test_crlf_is_one_enter_and_text_is_text():
    assert names(mi.decode(b"ab\r\n1")) == [(mi.K_CHAR, "a"), (mi.K_CHAR, "b"), mi.K_ENTER, (mi.K_CHAR, "1")]
    assert names(mi.decode("h\u00e9".encode())) == [(mi.K_CHAR, "h"), (mi.K_CHAR, "\u00e9")]


@pytest.mark.parametrize("junk", [
    b"\x1b[999~", b"\x1b[?1;2c", b"\x1b[>0;95;0c", b"\x1b[12;40R", b"\x1b[I", b"\x1b[O",
    b"\x1b[<0;10;5M", b"\x1b[<0;10;5m", b"\x1b[M !!", b"\x1b[M\xff\xfe\xfd", b"\x1b[2;3;4;5H",
    b"\x1b[1$x", b"\x1bOz", b"\x1b]0;title\x07", b"\x1b]52;c;ZXZpbA==\x1b\\", b"\x1bPdcs-body\x1b\\",
    b"\x1b_apc\x1b\\", b"\x9b2J", b"\x9b31m", b"\x8fA"[:0] + b"\x9d0;x\x07", b"\x00", b"\xff", b"\x80\xbf",
    b"\x1b[" + b"1" * 200 + b"A", b"\x1b[" + b";" * 200 + b"~", b"\x1b]" + b"A" * 5000 + b"\x07",
])
def test_unknown_sequences_are_consumed_and_never_leak(junk):
    d = mi.Decoder()
    keys = d.feed(junk + b"q") + d.flush()
    assert names(keys) == [(mi.K_CHAR, "q")], keys
    assert d.dropped >= 1


@pytest.mark.parametrize("cut", [b"\x1b[", b"\x1b[1", b"\x1b[1;", b"\x1b[1;5", b"\x1bO", b"\x1b[200",
                                 b"\x1b]0;ti", b"\x1b[M ", b"\xe2\x82"])
def test_truncated_sequences_are_dropped_at_end_of_input(cut):
    d = mi.Decoder()
    assert d.feed(cut) == []
    assert d.pending
    assert d.flush() == []
    assert not d.pending


@pytest.mark.parametrize("cut", [b"\x1b[1", b"\x1bO", b"\x1b[1;5", b"\xe2\x82"])
def test_truncated_sequence_then_a_new_key(cut):
    # The next ESC or control byte ends the broken sequence; the key after it still works.
    assert names(mi.decode(cut + b"\x1b[B")) == [mi.K_DOWN]
    assert names(mi.decode(cut + b"\r")) == [mi.K_ENTER]


def test_lone_esc_waits_for_the_timeout():
    d = mi.Decoder(esc_timeout=0.05)
    assert d.feed(b"\x1b") == []
    assert d.pending and d.pending_timeout() == 0.05
    assert names(d.timeout()) == [mi.K_ESC]
    # ESC then a sequence: the first is a real Esc, the second starts a key
    assert names(mi.decode(b"\x1b\x1b[A")) == [mi.K_ESC, mi.K_UP]
    assert names(mi.decode(b"\x1bq")) == [(mi.K_ALT, "q")]
    assert names(mi.decode(b"\x1b\r")) == [mi.K_ESC, mi.K_ENTER]


def test_esc_timeout_env_is_clamped(monkeypatch):
    monkeypatch.setenv("FAMILIA_ESC_TIMEOUT_MS", "999999")
    assert mi.Decoder().esc_timeout == 1.0
    monkeypatch.setenv("FAMILIA_ESC_TIMEOUT_MS", "0")
    assert mi.Decoder().esc_timeout == 0.01
    monkeypatch.setenv("FAMILIA_ESC_TIMEOUT_MS", "junk")
    assert mi.Decoder().esc_timeout == mi.ESC_TIMEOUT


def test_bracketed_paste_is_literal_text_never_keys():
    data = b"\x1b[200~q\r\x1b[A3\nrm -rf /\x1b[201~"
    keys = mi.decode(data)
    assert len(keys) == 1 and keys[0].name == mi.K_PASTE
    text = keys[0].text
    assert "\x1b" not in text and "\r" not in text and "\n" not in text
    assert text == "q [A3 rm -rf /"
    assert not keys[0].truncated
    # keys after the paste are keys again
    assert [k.name for k in mi.decode(data + b"\x1b[B")] == [mi.K_PASTE, mi.K_DOWN]


def test_paste_strips_controls_and_bidi_overrides():
    keys = mi.decode(b"\x1b[200~a\x07b\x00c\xe2\x80\xaed\x9be\x1b[201~")
    assert keys[0].text == "abcd\ufffde"
    assert all(ord(c) >= 0x20 for c in keys[0].text)


def test_paste_is_capped_and_end_marker_still_found():
    big = b"x" * 10000
    keys = mi.decode(b"\x1b[200~" + big + b"\x1b[201~q", paste_cap=100)
    assert names(keys)[0:1] == [(mi.K_PASTE, "x" * 100)]
    assert keys[0].truncated
    assert names(keys)[1:] == [(mi.K_CHAR, "q")]


def test_paste_cap_does_not_split_utf8():
    keys = mi.decode(b"\x1b[200~" + "\u00e9".encode() * 10 + b"\x1b[201~", paste_cap=5)
    assert keys[0].text == "\u00e9\u00e9" and keys[0].truncated


def test_paste_split_across_reads_and_partial_end_marker():
    d = mi.Decoder()
    out = []
    for chunk in (b"\x1b[20", b"0~ab\x1b[2", b"01", b"~", b"c"):
        out += d.feed(chunk)
    assert names(out) == [(mi.K_PASTE, "ab"), (mi.K_CHAR, "c")]
    # a near-miss end marker is pasted text
    assert mi.decode(b"\x1b[200~a\x1b[202~b\x1b[201~")[0].text == "a[202~b"


def test_unterminated_paste_ends_on_its_timeout():
    d = mi.Decoder(paste_timeout=0.2)
    assert d.feed(b"\x1b[200~hello\x1b[20") == []
    assert d.pending_timeout() == 0.2
    keys = d.timeout()
    assert names(keys) == [(mi.K_PASTE, "hello[20")]


def test_state_stays_bounded_on_hostile_input():
    d = mi.Decoder(paste_cap=64)
    d.feed(b"\x1b]" + b"A" * 100000)
    assert len(d._seq) <= mi.MAX_STR
    d.flush()
    d.feed(b"\x1b[200~" + b"B" * 100000)
    assert len(d._paste) <= 64 and len(d._pend) < len(mi.PASTE_END)


def test_cli_decode_prints_ascii_only():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "menu_input.py"), "decode"],
                       input=b"\x1b[A\x1b[999~\xc3\xa9\x1b[200~p\x1b[201~", capture_output=True, timeout=30)
    assert r.returncode == 0
    r.stdout.decode("ascii")
    assert r.stdout.splitlines() == [b"UP", b"CHAR '\\\\xe9'", b"PASTE 'p'", b"dropped 1"]


# ---- reader -------------------------------------------------------------------

def test_reader_esc_timeout_and_split_sequences_over_a_pipe():
    r, w = os.pipe()
    try:
        rd = mi.KeyReader(r, mi.Decoder(esc_timeout=0.05))
        os.write(w, b"\x1b")
        t0 = time.monotonic()
        k = rd.read_key(timeout=2)
        assert k.name == mi.K_ESC and time.monotonic() - t0 < 1.5
        os.write(w, b"\x1b[")
        assert rd.read_key(timeout=0.01) is None  # still waiting; nothing leaked
        os.write(w, b"B")
        assert rd.read_key(timeout=2).name == mi.K_DOWN
        assert rd.read_key(timeout=0.05) is None
        os.write(w, b"\x1b[1")  # cut short by end of input
        os.close(w)
        w = None
        with pytest.raises(EOFError):
            rd.read_key(timeout=2)
    finally:
        os.close(r)
        if w is not None:
            os.close(w)


def test_reader_reads_in_bounded_chunks():
    r, w = os.pipe()
    seen = []
    real = os.read

    def spy(fd, n):
        seen.append(n)
        return real(fd, n)

    try:
        os.write(w, b"a" * 5000)
        rd = mi.KeyReader(r)
        mi.os.read = spy
        try:
            assert rd.read_key(timeout=1).text == "a"
        finally:
            mi.os.read = real
        assert seen and max(seen) <= mi.READ_CHUNK
    finally:
        os.close(r)
        os.close(w)


# ---- probe --------------------------------------------------------------------

def _pty_pair():
    m, s = pty.openpty()
    return m, s


def test_probe_fancy_only_on_a_real_terminal():
    m, s = _pty_pair()
    try:
        assert mi.probe(s, s, {"TERM": "xterm-256color"}).fancy
        for env, why in (({}, "TERM is not set"), ({"TERM": ""}, "TERM is not set"),
                         ({"TERM": "dumb"}, "TERM=dumb"),
                         ({"TERM": "xterm", "FAMILIA_LEGACY_MENU": "1"}, "FAMILIA_LEGACY_MENU=1"),
                         ({"TERM": "xterm", "FAMILIA_NO_TTY": "1"}, "FAMILIA_NO_TTY=1")):
            p = mi.probe(s, s, env)
            assert not p.fancy and p.reason == why, (env, p)
        r, w = os.pipe()
        try:
            p = mi.probe(r, s, {"TERM": "xterm"})
            assert not p.fancy and p.reason == "stdin is a pipe"
            p = mi.probe(s, w, {"TERM": "xterm"})
            assert not p.fancy and p.reason == "stdout is a pipe"
        finally:
            os.close(r)
            os.close(w)
        with tempfile.TemporaryFile() as f:
            p = mi.probe(f.fileno(), s, {"TERM": "xterm"})
            assert not p.fancy and p.reason == "stdin is a file"
        p = mi.probe(987, s, {"TERM": "xterm"})
        assert not p.fancy and p.reason == "stdin is closed"
    finally:
        os.close(m)
        os.close(s)


def test_probe_without_termios_is_legacy():
    code = ("import sys; sys.modules['termios'] = None; sys.path.insert(0, %r); import menu_input as mi;"
            " p = mi.probe(0, 1, {'TERM': 'xterm'}); print(p.fancy, p.reason)") % os.path.join(ROOT, "scripts")
    m, s = _pty_pair()
    try:
        out = subprocess.run([sys.executable, "-c", code], stdin=s, stdout=subprocess.PIPE, timeout=30).stdout
    finally:
        os.close(m)
        os.close(s)
    assert out.decode().startswith("False termios/tty/select are not available")


def test_probe_cli_exit_codes():
    script = os.path.join(ROOT, "scripts", "menu_input.py")
    env = dict(os.environ, TERM="xterm")
    env.pop("FAMILIA_LEGACY_MENU", None)
    env.pop("FAMILIA_NO_TTY", None)
    r = subprocess.run([sys.executable, script, "probe"], stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, env=env, timeout=30)
    assert r.returncode == 3 and r.stdout.startswith("legacy: stdin is")
    m, s = _pty_pair()
    try:
        r = subprocess.run([sys.executable, script, "probe"], stdin=s, stdout=s, stderr=subprocess.PIPE,
                           env=env, timeout=30)
        assert r.returncode == 0
        assert os.read(m, 100).startswith(b"fancy")
    finally:
        os.close(m)
        os.close(s)


# ---- legacy menu ----------------------------------------------------------------

def _posix_items():
    out = []
    for line in open(ITEMS_FILE, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("|")
        if f[3]:  # empty posix command = Windows only, hidden by familia-menu.sh
            out.append(dict(zip(("key", "group", "label", "cmd", "gate", "need", "win"), f)))
    return out


def _need_ok(spec):
    if not spec:
        return True
    if spec.startswith("file:"):
        return os.path.exists(os.path.join(ROOT, spec[5:]))
    path, text = spec[5:].split(":", 1)
    p = os.path.join(ROOT, path)
    return os.path.isfile(p) and text in open(p, encoding="utf-8").read()


def _legacy_env(tmp):
    return {"PATH": "/usr/bin:/bin", "HOME": tmp, "LANG": "C.UTF-8", "TERM": "dumb", "NO_COLOR": "1",
            "FAMILIA_NO_TTY": "1", "FAMILIA_MODEL_DB_DIR": tmp, "XDG_CONFIG_HOME": os.path.join(tmp, "cfg"),
            "XDG_CACHE_HOME": os.path.join(tmp, "cache"), "PYTHON": sys.executable}


def test_legacy_numeric_menu_reaches_every_item(tmp_path):
    """Walk the whole legacy tree by number only (group, page, item) with --dry-run."""
    items = _posix_items()
    groups = []
    for it in items:
        if it["group"] not in groups:
            groups.append(it["group"])
    feed, expect = [], []
    for gi, g in enumerate(groups, 1):
        members = [it for it in items if it["group"] == g]
        feed.append(str(gi))
        pages = [members[i:i + PAGE_SIZE] for i in range(0, len(members), PAGE_SIZE)]
        for pi, page in enumerate(pages):
            for n, it in enumerate(page, 1):
                feed.append(str(n))
                if _need_ok(it["need"]):
                    feed += ["x"] * len(re.findall(r"\{[A-Z]+:[^}]*\}", it["cmd"]))
                expect.append(it)
            if pi < len(pages) - 1:
                feed.append(">")
        feed.append("b")
    feed.append("q")
    r = subprocess.run(["bash", MENU, "--pipe", "--dry-run"], cwd=ROOT, input="\n".join(feed) + "\n",
                       capture_output=True, text=True, env=_legacy_env(str(tmp_path)), timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    assert "isn't one of the choices" not in r.stdout, r.stdout[-3000:]
    dry = [ln for ln in r.stdout.splitlines() if ln.startswith("[dry-run] ") and "would first run" not in ln]
    avail = [it for it in expect if _need_ok(it["need"])]
    assert len(expect) == len(items)
    assert len(dry) == len(avail), (len(dry), len(avail))
    missing = r.stderr.count("is not available yet")
    assert missing == len(expect) - len(avail)
    for it, line in zip(avail, dry):
        want = it["cmd"].replace("PY ", sys.executable + " ").replace("INSTALLER", "install/linux/install.sh")
        want = want.replace("PAGER ", "more ")
        want = re.sub(r"\{[A-Z]+:[^}]*\}", "x", want)
        assert line == "[dry-run] " + want, (it["key"], line, want)
    for it in items:
        assert it["label"] in r.stdout, it["key"]


def test_every_home_choice_has_a_legacy_item():
    """Home (fancy) top-level and submenu choices all exist in the legacy catalog."""
    src = open(HOME_SH, encoding="utf-8").read()
    keys = {it["key"] for it in _posix_items()}
    # six areas x verbs, plus the apps extras
    for area in re.findall(r"\) printf '%s\\n' (\w+) ;;", src):
        for verb in ("install", "list", "start", "stop", "status"):
            assert "home.%s.%s" % (area, verb) in keys
    assert {"home.apps.browse", "home.apps.web"} <= keys
    # extra top-level picks map to legacy items too
    by_cmd = {it["cmd"] for it in _posix_items()}
    assert any("open_ui.sh" in c or "android-cockpit-switches.sh" in c for c in by_cmd)
    assert "PY scripts/catalog.py models" in by_cmd
    assert "PY scripts/catalog.py graphs" in by_cmd


def test_legacy_input_is_hardened(tmp_path):
    env = _legacy_env(str(tmp_path))
    # an arrow key typed into the numeric menu is shown back without its ESC byte
    r = subprocess.run(["bash", MENU, "--pipe"], cwd=ROOT, input="\x1b[A\nq\n", capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 0
    assert "'?[A' isn't one of the choices" in r.stdout
    assert "\x1b" not in r.stdout
    # bracketed-paste markers are stripped: "1" pasted is choice 1
    r = subprocess.run(["bash", MENU, "--pipe"], cwd=ROOT, input="\x1b[200~1\x1b[201~\nb\nq\n",
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "Set up:" in r.stdout and "isn't one" not in r.stdout
    # an overlong piped line is not read without bound: refused, and the menu stops (not a quit)
    r = subprocess.run(["bash", MENU, "--pipe"], cwd=ROOT, input="9" * 50000 + "\nq\n",
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2
    assert "input line of 4096 or more characters; ignored" in r.stderr


# ---- review fixes (Race on #736 @c35dc41) ---------------------------------------

@pytest.mark.parametrize("intro,tail", [
    (b"\x1b[", b"1;5A"), (b"\x1b[1", b";5A"), (b"\x1b[1;", b"5A"), (b"\x1bO", b"A"), (b"\x1bO5", b"A"),
    (b"\x1b]0;ti", b"tle\x07"), (b"\x1b]52;c;", b"ZXZpbA==\x1b\\"), (b"\x1bP", b"dcs\x1b\\"),
    (b"\x1b[M", b" !!"), (b"\x1b[M ", b"!!"), (b"\x9b", b"12~"),
])
def test_stalled_sequence_tail_never_leaks_after_a_timeout(intro, tail):
    d = mi.Decoder(esc_timeout=0.05)
    assert d.feed(intro) == []
    assert d.pending_timeout() == d.seq_timeout  # not the 50 ms ESC timeout
    assert d.timeout() == []                     # first silence: keep skipping
    assert d.pending
    assert d.feed(tail) == []                    # the late tail is eaten, not typed
    assert names(d.feed(b"q")) == [(mi.K_CHAR, "q")]


def test_second_silence_ends_a_stalled_sequence():
    d = mi.Decoder()
    d.feed(b"\x1b[")
    d.timeout()
    assert d.timeout() == [] and not d.pending
    assert names(d.feed(b"1")) == [(mi.K_CHAR, "1")]


def test_only_a_lone_esc_uses_the_short_timeout():
    d = mi.Decoder(esc_timeout=0.05)
    d.feed(b"\x1b")
    assert d.pending_timeout() == 0.05
    d.feed(b"[")
    assert d.pending_timeout() == mi.SEQ_TIMEOUT


def test_paste_that_never_goes_silent_is_emitted_at_the_cap():
    d = mi.Decoder(paste_cap=10)
    out = d.feed(b"\x1b[200~")
    for _ in range(200):  # 200 KiB, no end marker, no silence
        out += d.feed(b"1\r" * 512)
    assert [k.name for k in out] == [mi.K_PASTE]
    assert out[0].truncated and out[0].text == "1 1 1 1 1 "
    assert len(d._paste) == 0 and len(d._pend) < len(mi.PASTE_END)
    # the rest is skipped until the end marker, then keys are keys again
    assert names(d.feed(b"1\r\x1b[201~q")) == [(mi.K_CHAR, "q")]
    # or until silence
    d.feed(b"\x1b[200~" + b"x" * 50)
    assert d.timeout() == [] and not d.pending
    assert names(d.feed(b"q")) == [(mi.K_CHAR, "q")]


def test_reader_closed_fd_is_end_of_input():
    r, w = os.pipe()
    rd = mi.KeyReader(r)
    os.close(r)
    os.close(w)
    with pytest.raises(EOFError):
        rd.read_key(timeout=1)
    rd = mi.KeyReader(-1)
    with pytest.raises(EOFError):
        rd.read_key(timeout=1)


def test_reader_waits_for_a_slow_sequence_tail():
    r, w = os.pipe()
    try:
        rd = mi.KeyReader(r, mi.Decoder(esc_timeout=0.02))
        os.write(w, b"\x1b[1;")
        assert rd.read_key(timeout=0.15) is None  # well past the ESC timeout: still waiting
        os.write(w, b"5A")
        k = rd.read_key(timeout=2)
        assert k.name == mi.K_UP and k.mods == 4
    finally:
        os.close(r)
        os.close(w)


def test_m1_names():
    keys = mi.decode(b"\x1b[A\x1b[B\x1b[H\x1b[F\x1b[5~\x1b[6~\r\x7f\x1b[3~\x03\x04x\x1bq\x1b[200~p\x1b[201~\t")
    assert [mi.m1_key(k) for k in keys] == ["up", "down", "home", "end", "pgup", "pgdn", "enter", "backspace",
                                            "delete", "intr", "eof", "x", "alt", "paste", "unknown"]
    assert [mi.m1_key(k) for k in mi.decode(b"\x1b")] == ["esc"]


def _front_door_pty(env, feed=b"q\n", timeout=60):
    m, s = pty.openpty()
    p = subprocess.Popen(["sh", os.path.join(ROOT, "familia")], stdin=s, stdout=s, stderr=s, cwd=ROOT, env=env,
                         start_new_session=True)
    os.close(s)
    os.write(m, feed)
    out = b""
    end = time.time() + timeout
    while time.time() < end:
        try:
            ready = __import__("select").select([m], [], [], 0.2)[0]
            if ready:
                chunk = os.read(m, 4096)
                if not chunk:
                    break
                out += chunk
            elif p.poll() is not None:
                break
        except OSError:
            break
    if p.poll() is None:
        p.kill()
    os.close(m)
    return p.wait(timeout=10), out.decode("utf-8", "replace")


def test_front_door_uses_the_probe_on_a_terminal(tmp_path):
    env = _legacy_env(str(tmp_path))
    env.pop("FAMILIA_NO_TTY")
    env["FAMILIA_SKIP_GUM_INSTALL"] = "1"
    env["PATH"] = os.path.dirname(sys.executable) + ":/usr/bin:/bin"
    rc, out = _front_door_pty(env)  # TERM=dumb
    assert rc == 0, out
    assert "familia: legacy: TERM=dumb; using the legacy numeric menu" in out
    assert "what do you want to do?" in out
    # a real terminal type: the probe says fancy and the home menu runs
    rc, out = _front_door_pty(dict(env, TERM="xterm"))
    assert "using the legacy numeric menu" not in out
    assert "familia-home:" in out
    # FAMILIA_MENU_PROBE=0: the probe is skipped and the home menu decides
    env["FAMILIA_MENU_PROBE"] = "0"
    rc, out = _front_door_pty(env)
    assert "using the legacy numeric menu" not in out
    assert "familia-home:" in out


def test_front_door_without_a_terminal_keeps_list_mode(tmp_path):
    env = _legacy_env(str(tmp_path))
    env.pop("FAMILIA_NO_TTY")
    r = subprocess.run(["sh", os.path.join(ROOT, "familia")], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "using the legacy numeric menu" not in r.stderr
    assert "Talk to the protomodel" in r.stdout


# ---- KeyReader stall clock (Fuzz M8 P1 on #736 @67be19c) ---------------------------

def _drain(rd, seconds):
    """Call read_key for `seconds` like the menu loop does; return every key."""
    out = []
    end = time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return out
        k = rd.read_key(timeout=left)
        if k is not None:
            out.append(k)


def _stalled(gap, tail, pty_pair=False, **kw):
    if pty_pair:
        import termios
        rfd, wfd = pty.openpty()  # master, slave: write into master, read the slave in raw mode
        wfd, rfd = rfd, wfd
        attrs = termios.tcgetattr(rfd)
        attrs[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)
        attrs[0] &= ~termios.ICRNL
        termios.tcsetattr(rfd, termios.TCSANOW, attrs)
    else:
        rfd, wfd = os.pipe()
    try:
        rd = mi.KeyReader(rfd, mi.Decoder(**kw))
        os.write(wfd, b"\x1b[")
        keys = _drain(rd, gap)  # the reader keeps polling through the silence
        os.write(wfd, tail)
        keys += _drain(rd, 0.4)
        return keys
    finally:
        os.close(rfd)
        os.close(wfd)


@pytest.mark.parametrize("use_pty", [False, True])
def test_reader_stall_under_seq_timeout_never_types_the_tail(use_pty):
    keys = _stalled(0.3, b"1;5A", use_pty)  # past the 50 ms ESC timeout, under 1 s
    assert not [k for k in keys if k.name == mi.K_CHAR], keys
    assert [k.name for k in keys] in ([mi.K_UP], []), keys


@pytest.mark.parametrize("use_pty", [False, True])
def test_reader_stall_over_seq_timeout_drops_but_never_types_the_tail(use_pty):
    keys = _stalled(1.3, b"1;5A", use_pty)  # past seq_timeout: may drop, must not type
    assert not [k for k in keys if k.name == mi.K_CHAR], keys


def test_reader_fuzz_repro_esc_bracket_sleep_then_A_enter():
    keys = _stalled(1.3, b"A\r")
    assert [k.name for k in keys] == [mi.K_ENTER], keys


def test_reader_second_silence_ends_the_skip():
    r, w = os.pipe()
    try:
        rd = mi.KeyReader(r, mi.Decoder(seq_timeout=0.2))
        os.write(w, b"\x1b[")
        assert _drain(rd, 0.6) == []  # first window -> skip, second window -> ground
        assert not rd.decoder.pending
        os.write(w, b"x")
        assert [(k.name, k.text) for k in _drain(rd, 0.2)] == [(mi.K_CHAR, "x")]
    finally:
        os.close(r)
        os.close(w)


def test_reader_lone_esc_still_fast_and_gap_clock_starts_at_construction():
    r, w = os.pipe()
    try:
        dec = mi.Decoder(esc_timeout=0.05)
        dec.feed(b"\x1b[")  # handed over mid-sequence
        rd = mi.KeyReader(r, dec)
        os.write(w, b"B")
        assert [k.name for k in _drain(rd, 0.2)] == [mi.K_DOWN]
        os.write(w, b"\x1b")
        t0 = time.monotonic()
        assert rd.read_key(timeout=2).name == mi.K_ESC
        assert time.monotonic() - t0 < 0.5
    finally:
        os.close(r)
        os.close(w)


def test_cli_decode_with_closed_stdin():
    code = ("import sys, runpy; sys.stdin.close(); sys.stdin = None; sys.argv = ['menu_input.py', 'decode'];"
            " runpy.run_path(%r, run_name='__main__')") % os.path.join(ROOT, "scripts", "menu_input.py")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "dropped 0"


# ---- Race review of #736 @67be19c -------------------------------------------------

def test_race_repro_read_key_none_then_tail():
    r, w = os.pipe()
    try:
        rd = mi.KeyReader(r)
        os.write(w, b"\x1b[")
        assert rd.read_key(timeout=1.3) is None  # past seq_timeout: skipping, not ground
        assert rd.decoder.pending
        os.write(w, b"1;5A")
        assert _drain(rd, 0.3) == []
        os.write(w, b"q")
        assert [(k.name, k.text) for k in _drain(rd, 0.2)] == [(mi.K_CHAR, "q")]
    finally:
        os.close(r)
        os.close(w)


@pytest.mark.parametrize("intro", [b"\x1b[" + b"0" * 40, b"\x1bO" + b"5" * 40])
def test_overlong_sequence_skip_survives_its_first_timeout(intro):
    d = mi.Decoder()
    assert d.feed(intro) == []
    assert d.timeout() == [] and d.pending
    assert d.feed(b"1A") == []
    assert names(d.feed(b"z")) == [(mi.K_CHAR, "z")]
    # a second silence still ends it
    d.feed(intro)
    d.timeout()
    assert d.timeout() == [] and not d.pending


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize("intro,filler", [
    (b"\x1b]", b"A"), (b"\x1bP", b"A"), (b"\x1b[", b"1"), (b"\x1b[" + b"1" * 40, b"1"), (b"\x1bO", b"5"),
])
def test_never_ending_sequence_is_abandoned_by_wall_clock(intro, filler):
    clk = _Clock()
    d = mi.Decoder(clock=clk)
    assert d.feed(intro + filler * 100) == []
    clk.t = 1.9
    assert d.feed(filler * 100) == [] and d.pending
    clk.t = 2.0
    dropped = d.dropped
    d.feed(filler)  # cap reached: back to ground, swallowed bytes not emitted
    assert not d.pending and d.dropped > dropped
    assert names(d.feed(b"\x1b[B")) == [mi.K_DOWN]


def test_never_ending_sequence_is_abandoned_by_byte_cap():
    d = mi.Decoder(max_skip_bytes=500)
    assert d.feed(b"\x1b]" + b"A" * 500) == [] and d.pending
    d.feed(b"A")
    assert not d.pending


def test_over_cap_paste_skip_has_its_own_wall_clock_cap():
    clk = _Clock()
    d = mi.Decoder(clock=clk, paste_cap=4)
    out = d.feed(b"\x1b[200~" + b"x" * 100)
    assert [k.name for k in out] == [mi.K_PASTE] and out[0].truncated
    clk.t = mi.PASTE_SKIP_MAX_AGE - 0.1
    assert d.feed(b"x" * 100) == [] and d.pending
    clk.t = mi.PASTE_SKIP_MAX_AGE
    d.feed(b"x")
    assert not d.pending


@pytest.mark.parametrize("intro", [b"\x1b]0;" + b"A" * 300, b"\x1bP" + b"A" * 300, b"\x1b[" + b"1" * 300,
                                   b"\x1b[1;", b"\x1b[M", b"\x1b[M ", b"\x1bO"])
@pytest.mark.parametrize("ctl,name", [(b"\x03", mi.K_CTRL_C), (b"\x04", mi.K_CTRL_D)])
def test_ctrl_c_and_ctrl_d_break_out_of_any_skip(intro, ctl, name):
    d = mi.Decoder()
    assert names(d.feed(intro + ctl)) == [name]
    assert not d.pending


def test_reader_returns_on_a_never_ending_osc_stream():
    r, w = os.pipe()
    try:
        rd = mi.KeyReader(r, mi.Decoder(max_age=0.3))
        os.write(w, b"\x1b]0;")
        t0 = time.monotonic()
        while time.monotonic() - t0 < 0.6:  # junk keeps coming, no silence
            os.write(w, b"A" * 8)
            time.sleep(0.02)
            assert rd.read_key(timeout=0.01) is None or True
        os.write(w, b"\x03")
        k = rd.read_key(timeout=1)
        while k is not None and k.name == mi.K_CHAR:  # bytes after the cap may be text
            k = rd.read_key(timeout=1)
        assert k is not None and k.name == mi.K_CTRL_C
    finally:
        os.close(r)
        os.close(w)
