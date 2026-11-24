#!/usr/bin/env python3
"""menu_input.py: the key input layer for the interactive familia menu (#733 M2).

The arrow-key menu (#733 M1) owns raw mode, the key loop, drawing and terminal
restore. This module only turns bytes into key tokens, and decides whether the
interactive menu may run at all. It never writes to the terminal.

Interface for M1:
    probe(stdin_fd=0, stdout_fd=1, env=None) -> Probe(fancy, reason)
        fancy False means: use the legacy numeric menu (familia-menu.sh).
    KeyReader(fd).read_key(timeout=None) -> Key, or None on timeout
        raises EOFError when the input is closed.
    Decoder().feed(data) -> [Key];  .pending;  .pending_timeout();  .timeout() -> [Key]
    decode(data) -> [Key]   (whole buffer, end of input; for tests and fuzzing)
    Key(name, text, mods, truncated); names are the K_* constants below.
    m1_key(key) -> M1's key strings ("up", "enter", "intr", "eof", a character, ...).
        mods is the xterm modifier bitmask: 1 Shift, 2 Alt, 4 Ctrl (0 = none).
    BRACKETED_PASTE_ON / BRACKETED_PASTE_OFF: M1 writes these on enter / restore.

Rules:
- Unknown or malformed CSI / SS3 / OSC / DCS / mouse sequences are consumed and
  dropped. Their bytes never come back as K_CHAR.
- A lone ESC is K_ESC once no byte follows within esc_timeout (default 50 ms,
  FAMILIA_ESC_TIMEOUT_MS, clamped to 10..1000). After ESC [ / ESC O / ESC ] the
  decoder waits up to seq_timeout (1 s) for the tail, then skips to the final
  byte, BEL or ST, so a slow tail is never read as typed text.
- A sequence longer than MAX_SEQ bytes is dropped; the rest of it is skipped.
- Bracketed paste (ESC[200~ ... ESC[201~) is one K_PASTE whose text is literal
  and single-line: control and format characters removed, newlines and tabs
  become spaces, at most paste_cap bytes kept. At the cap the PASTE is emitted
  with truncated=True and the rest is skipped until ESC[201~ or paste_timeout
  of silence. A paste is never split into keys. A paste with no end marker
  ends after paste_timeout.
- Reads are at most READ_CHUNK bytes; nothing reads until EOF.

usage: python3 scripts/menu_input.py probe [--stdout-fd N]
       python3 scripts/menu_input.py decode < captured-bytes
example: python3 scripts/menu_input.py probe && echo fancy menu allowed
"""
import collections
import os
import stat
import sys
import unicodedata

K_CHAR = "CHAR"          # text = one printable character
K_PASTE = "PASTE"        # text = pasted literal text (sanitized, single line)
K_ALT = "ALT"            # text = the character typed with Alt (ESC + char)
K_ENTER = "ENTER"
K_ESC = "ESC"
K_BACKSPACE = "BACKSPACE"
K_TAB = "TAB"
K_BACKTAB = "BACKTAB"
K_UP = "UP"
K_DOWN = "DOWN"
K_LEFT = "LEFT"
K_RIGHT = "RIGHT"
K_HOME = "HOME"
K_END = "END"
K_PGUP = "PGUP"
K_PGDN = "PGDN"
K_INSERT = "INSERT"
K_DELETE = "DELETE"
K_CTRL_C = "CTRL_C"
K_CTRL_D = "CTRL_D"
K_CTRL_Z = "CTRL_Z"
# other C0 controls are "CTRL_<letter>", e.g. CTRL_L; F keys are "F1".."F12"

BRACKETED_PASTE_ON = "\x1b[?2004h"
BRACKETED_PASTE_OFF = "\x1b[?2004l"

MAX_SEQ = 32           # bytes in one CSI / SS3 sequence, ESC included
MAX_STR = 256          # bytes kept while skipping an OSC / DCS / APC / PM string
READ_CHUNK = 256       # bytes per os.read
PASTE_CAP = 4096       # bytes of pasted text kept
ESC_TIMEOUT = 0.05     # seconds
PASTE_TIMEOUT = 1.0    # seconds of silence that ends an unterminated paste
SEQ_TIMEOUT = 1.0      # seconds to wait for the tail of a CSI / SS3 / OSC / mouse sequence

PASTE_END = b"\x1b[201~"

Key = collections.namedtuple("Key", "name text mods truncated")
Key.__new__.__defaults__ = ("", 0, False)

_CSI_LETTER = {"A": K_UP, "B": K_DOWN, "C": K_RIGHT, "D": K_LEFT, "H": K_HOME, "F": K_END,
               "Z": K_BACKTAB, "P": "F1", "Q": "F2", "R": "F3", "S": "F4"}
_CSI_TILDE = {1: K_HOME, 7: K_HOME, 4: K_END, 8: K_END, 2: K_INSERT, 3: K_DELETE, 5: K_PGUP, 6: K_PGDN,
              11: "F1", 12: "F2", 13: "F3", 14: "F4", 15: "F5", 17: "F6", 18: "F7", 19: "F8",
              20: "F9", 21: "F10", 23: "F11", 24: "F12"}
_SS3 = {"A": K_UP, "B": K_DOWN, "C": K_RIGHT, "D": K_LEFT, "H": K_HOME, "F": K_END, "M": K_ENTER,
        "P": "F1", "Q": "F2", "R": "F3", "S": "F4"}

_GROUND, _ESC, _CSI, _SS3S, _STR, _STR_ESC, _MOUSE, _SKIP, _UTF8, _PASTE, _PASTE_SKIP = range(11)


def _clamp_ms(value, default, lo, hi):
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(ms, lo), hi) / 1000.0


def sanitize_paste(raw):
    """bytes -> single-line printable text. Never returns a control character."""
    text = raw.decode("utf-8", "replace")
    out = []
    for ch in text:
        if ch in "\r\n\t":
            out.append(" ")
        elif unicodedata.category(ch)[0] == "C":  # Cc Cf Cs Co Cn: controls, bidi overrides, ...
            continue
        else:
            out.append(ch)
    return "".join(out)


class Decoder:
    """Byte-at-a-time terminal input decoder. Holds at most a bounded amount of state."""

    def __init__(self, esc_timeout=None, paste_timeout=PASTE_TIMEOUT, paste_cap=PASTE_CAP, seq_timeout=SEQ_TIMEOUT):
        if esc_timeout is None:
            esc_timeout = _clamp_ms(os.environ.get("FAMILIA_ESC_TIMEOUT_MS"), ESC_TIMEOUT, 10, 1000)
        self.esc_timeout = esc_timeout
        self.paste_timeout = paste_timeout
        self.seq_timeout = seq_timeout
        self._stale = False       # a sequence already timed out once: next silence ends it
        self.paste_cap = max(0, int(paste_cap))
        self.dropped = 0          # sequences consumed and ignored (for tests / M8 fuzzing)
        self._state = _GROUND
        self._seq = bytearray()
        self._need = 0
        self._last_cr = False
        self._paste = bytearray()
        self._pend = bytearray()
        self._paste_cut = False
        self._out = []

    # ---- public ---------------------------------------------------------------
    @property
    def pending(self):
        return self._state != _GROUND

    def pending_timeout(self):
        st = self._state
        if st in (_ESC, _UTF8):
            return self.esc_timeout  # only a lone ESC (or half a character) is decided fast
        if st in (_PASTE, _PASTE_SKIP):
            return self.paste_timeout
        return self.seq_timeout      # inside CSI / SS3 / OSC / mouse: wait for the tail

    def feed(self, data):
        for b in bytes(data):
            self._byte(b)
        out, self._out = self._out, []
        return out

    def timeout(self):
        """No byte came within pending_timeout(): resolve whatever is half-read.

        A sequence that stalls after its introducer is not dropped to ground at
        once (its tail would then leak as text, e.g. ESC [ <stall> 1;5A -> '1').
        CSI / SS3 go to _SKIP, which eats up to the final byte; OSC / DCS strings
        and mouse reports keep skipping. A second silence ends them."""
        st = self._state
        if st == _ESC:
            self._emit(K_ESC)
            self._reset()
        elif st == _PASTE:
            self._pend_commit_all()
            if self._state == _PASTE:  # the cap may already have emitted it
                self._finish_paste()
            self._reset()
        elif st in (_CSI, _SS3S) and not self._stale:
            self.dropped += 1
            self._state = _SKIP
            self._seq = bytearray()
            self._stale = True
        elif st in (_STR, _STR_ESC, _MOUSE) and not self._stale:
            self._stale = True
        else:
            if st not in (_GROUND, _PASTE_SKIP, _SKIP):
                self.dropped += 1
            self._reset()
        out, self._out = self._out, []
        return out

    def flush(self):
        """End of input: a lone ESC is Esc, a paste is emitted, anything else is dropped."""
        st = self._state
        if st == _ESC:
            self._emit(K_ESC)
        elif st == _PASTE:
            self._pend_commit_all()
            if self._state == _PASTE:
                self._finish_paste()
        elif st not in (_GROUND, _PASTE_SKIP, _SKIP):
            self.dropped += 1
        self._reset()
        out, self._out = self._out, []
        return out

    # ---- internals -------------------------------------------------------------
    def _reset(self):
        self._state = _GROUND
        self._seq = bytearray()
        self._need = 0
        self._stale = False

    def _emit(self, name, text="", mods=0, truncated=False):
        self._out.append(Key(name, text, mods, truncated))

    def _drop(self):
        self.dropped += 1
        self._reset()

    def _byte(self, b):
        st = self._state
        if st == _GROUND:
            self._ground(b)
        elif st == _ESC:
            self._after_esc(b)
        elif st == _CSI:
            self._csi(b)
        elif st == _SS3S:
            self._ss3(b)
        elif st in (_STR, _STR_ESC):
            self._str(b)
        elif st == _MOUSE:
            self._need -= 1
            if self._need <= 0:
                self._drop()
        elif st == _SKIP:
            # overlong sequence: skip up to its final byte; controls end it and are handled
            if 0x40 <= b <= 0x7E:
                self._reset()
            elif b < 0x20 or b >= 0x80:
                self._reset()
                self._ground(b)
        elif st == _UTF8:
            self._utf8(b)
        elif st in (_PASTE, _PASTE_SKIP):
            self._paste_byte(b)

    def _ground(self, b):
        cr, self._last_cr = self._last_cr, False
        if b == 0x1B:
            self._state = _ESC
            self._seq = bytearray([b])
        elif b == 0x0D:
            self._last_cr = True
            self._emit(K_ENTER)
        elif b == 0x0A:
            if not cr:  # CR LF is one Enter
                self._emit(K_ENTER)
        elif b in (0x7F, 0x08):
            self._emit(K_BACKSPACE)
        elif b == 0x09:
            self._emit(K_TAB)
        elif b == 0x03:
            self._emit(K_CTRL_C)
        elif b == 0x04:
            self._emit(K_CTRL_D)
        elif b == 0x1A:
            self._emit(K_CTRL_Z)
        elif b < 0x20:
            if b == 0:
                self.dropped += 1
            else:
                self._emit("CTRL_" + chr(b + 0x40))
        elif b < 0x7F:
            self._emit(K_CHAR, chr(b))
        elif 0xC2 <= b <= 0xF4:
            self._state = _UTF8
            self._seq = bytearray([b])
            self._need = 1 if b < 0xE0 else (2 if b < 0xF0 else 3)
        elif b == 0x9B:  # 8-bit CSI: parsed (and dropped if unknown) like ESC [
            self._state = _CSI
            self._seq = bytearray(b"\x1b[")
        elif b == 0x8F:  # 8-bit SS3
            self._state = _SS3S
            self._seq = bytearray(b"\x1bO")
        elif b in (0x9D, 0x90, 0x9F, 0x9E, 0x98):  # 8-bit OSC DCS APC PM SOS: skipped to ST
            self._state = _STR
            self._seq = bytearray()
        else:
            # stray continuation byte, other C1 control, or invalid lead: dropped
            self.dropped += 1

    def _utf8(self, b):
        if 0x80 <= b <= 0xBF:
            self._seq.append(b)
            self._need -= 1
            if self._need == 0:
                raw = bytes(self._seq)
                self._reset()
                try:
                    ch = raw.decode("utf-8")
                except UnicodeDecodeError:
                    self.dropped += 1
                    return
                if unicodedata.category(ch)[0] == "C":
                    self.dropped += 1
                else:
                    self._emit(K_CHAR, ch)
        else:
            self._drop()
            self._ground(b)

    def _after_esc(self, b):
        if b == 0x5B:  # [
            self._state = _CSI
            self._seq.append(b)
        elif b == 0x4F:  # O
            self._state = _SS3S
            self._seq.append(b)
        elif b in (0x5D, 0x50, 0x5F, 0x5E, 0x58):  # ] P _ ^ X : OSC DCS APC PM SOS
            self._state = _STR
            self._seq = bytearray()
        elif b == 0x1B:
            self._emit(K_ESC)  # ESC ESC: first is a lone Esc, second starts again
            self._seq = bytearray([b])
        elif 0x20 <= b < 0x7F:
            self._reset()
            self._emit(K_ALT, chr(b))
        else:
            self._reset()
            self._emit(K_ESC)
            self._ground(b)

    def _csi(self, b):
        if 0x20 <= b <= 0x3F:
            self._seq.append(b)
            if len(self._seq) > MAX_SEQ:
                self.dropped += 1
                self._state = _SKIP
                self._seq = bytearray()
        elif 0x40 <= b <= 0x7E:
            self._seq.append(b)
            self._csi_dispatch(bytes(self._seq[2:-1]).decode("ascii"), chr(b))
        elif b == 0x7F:
            pass  # DEL inside a sequence is ignored (VT rule)
        else:
            # ESC, another control, or a high byte: the sequence was cut short
            self._drop()
            self._ground(b)

    def _csi_dispatch(self, params, final):
        self._reset()
        if params == "" and final == "M":  # X10 mouse: three raw bytes follow
            self._state = _MOUSE
            self._need = 3
            return
        if params == "200" and final == "~":
            self._state = _PASTE
            self._paste = bytearray()
            self._pend = bytearray()
            self._paste_cut = False
            return
        if params[:1] in ("<", "=", ">", "?") or any(c not in "0123456789;" for c in params):
            self.dropped += 1  # private / SGR mouse / replies / intermediates: not keys
            return
        parts = params.split(";") if params else []
        if any(len(p) > 5 for p in parts) or len(parts) > 2:
            self.dropped += 1
            return
        mods = 0
        if len(parts) == 2 and parts[1]:
            mods = max(0, int(parts[1]) - 1)
        if final == "~":
            if not parts or not parts[0]:
                self.dropped += 1
                return
            name = _CSI_TILDE.get(int(parts[0]))
        else:
            if parts and parts[0] not in ("", "1"):
                self.dropped += 1
                return
            name = _CSI_LETTER.get(final)
        if name is None:
            self.dropped += 1
            return
        self._emit(name, "", mods)

    def _ss3(self, b):
        if 0x30 <= b <= 0x39 or b == 0x3B:  # some terminals send ESC O 5 A
            self._seq.append(b)
            if len(self._seq) > MAX_SEQ:
                self.dropped += 1
                self._state = _SKIP
                self._seq = bytearray()
        elif 0x40 <= b <= 0x7E:
            self._reset()
            name = _SS3.get(chr(b))
            if name is None:
                self.dropped += 1
            else:
                self._emit(name)
        else:
            self._drop()
            self._ground(b)

    def _str(self, b):
        # OSC/DCS/APC/PM/SOS: consumed until BEL or ST (ESC \). Never keys.
        if self._state == _STR_ESC:
            if b == 0x5C:
                self._drop()
                return
            self._state = _STR
        if b == 0x07:
            self._drop()
        elif b == 0x1B:
            self._state = _STR_ESC
        elif b == 0x9C:
            self._drop()
        elif len(self._seq) < MAX_STR:
            self._seq.append(b)  # bounded; bytes past MAX_STR are skipped, not kept

    def _paste_byte(self, b):
        self._pend.append(b)
        while self._pend and not PASTE_END.startswith(bytes(self._pend)):
            self._commit(self._pend.pop(0))
        if bytes(self._pend) == PASTE_END:
            self._pend = bytearray()
            if self._state == _PASTE:
                self._finish_paste()
            self._reset()

    def _commit(self, b):
        if self._state == _PASTE_SKIP:
            return  # past the cap: discarded until ESC[201~ or silence
        if len(self._paste) < self.paste_cap:
            self._paste.append(b)
        else:
            # cap reached: hand the truncated paste over now, then skip the rest
            self._paste_cut = True
            self._finish_paste()
            self._state = _PASTE_SKIP

    def _pend_commit_all(self):
        for b in bytes(self._pend):
            self._commit(b)
        self._pend = bytearray()

    def _finish_paste(self):
        raw = bytes(self._paste)
        cut = self._paste_cut
        if cut:
            # do not end on half a UTF-8 character
            raw = raw.decode("utf-8", "ignore").encode("utf-8") if raw else raw
        self._paste = bytearray()
        self._paste_cut = False
        self._emit(K_PASTE, sanitize_paste(raw), 0, cut)


# M1 (scripts/menu_keys.py, #743) names, so its Picker can take these keys unchanged.
M1_NAMES = {K_UP: "up", K_DOWN: "down", K_LEFT: "left", K_RIGHT: "right", K_HOME: "home", K_END: "end",
            K_PGUP: "pgup", K_PGDN: "pgdn", K_ENTER: "enter", K_ESC: "esc", K_BACKSPACE: "backspace",
            K_DELETE: "delete", K_CTRL_C: "intr", K_CTRL_D: "eof", K_PASTE: "paste", K_ALT: "alt"}
M1_UNKNOWN = "unknown"


def m1_key(key):
    """Key -> the string M1's Picker.feed() takes: a printable character is itself,
    named keys are lowercase ("up", "enter", "intr", "eof", ...), PASTE is "paste"
    (its text stays in key.text: append it to the typed line, never feed it per char),
    ALT is "alt", and anything else is "unknown"."""
    if key.name == K_CHAR:
        return key.text
    return M1_NAMES.get(key.name, M1_UNKNOWN)


def decode(data, **kw):
    """Decode a whole buffer as if input then ended. Returns [Key]."""
    d = Decoder(**kw)
    keys = d.feed(data)
    keys += d.flush()
    return keys


class KeyReader:
    """Reads keys from an fd that M1 has already put in raw mode."""

    def __init__(self, fd=0, decoder=None, chunk=READ_CHUNK):
        import select  # noqa: F401  (fails here, not mid-loop, where select is missing)
        self.fd = fd
        self.decoder = decoder or Decoder()
        self.chunk = max(1, min(int(chunk), 4096))
        self._queue = collections.deque()
        self._eof = False
        self._last = 0.0

    def read_key(self, timeout=None):
        """Next Key; None when `timeout` seconds pass with no key; EOFError at end of input."""
        import select
        import time
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            if self._queue:
                return self._queue.popleft()
            if self._eof:
                raise EOFError("input closed")
            wait = None
            if deadline is not None:
                wait = max(0.0, deadline - time.monotonic())
            if self.decoder.pending:
                # time left in the inter-byte gap, measured from the last byte read
                gap = max(0.0, self._last + self.decoder.pending_timeout() - time.monotonic())
                wait = gap if wait is None else min(wait, gap)
            try:
                ready, _, _ = select.select([self.fd], [], [], wait)
            except InterruptedError:
                continue
            except (OSError, ValueError):
                # EBADF, a hung-up fd, or fd -1: the input is gone
                self._eof = True
                self._queue.extend(self.decoder.flush())
                continue
            if ready:
                try:
                    data = os.read(self.fd, self.chunk)
                except InterruptedError:
                    continue
                except OSError:
                    data = b""  # EIO on a closed pty is end of input
                if not data:
                    self._eof = True
                    self._queue.extend(self.decoder.flush())
                    continue
                self._last = time.monotonic()
                self._queue.extend(self.decoder.feed(data))
                continue
            if self.decoder.pending and time.monotonic() - self._last >= self.decoder.pending_timeout():
                self._queue.extend(self.decoder.timeout())
                if self._queue:
                    continue
            if deadline is not None and time.monotonic() >= deadline:
                return None


Probe = collections.namedtuple("Probe", "fancy reason")


def _fd_kind(fd):
    try:
        mode = os.fstat(fd).st_mode
    except OSError:
        return "closed"
    if stat.S_ISFIFO(mode):
        return "a pipe"
    if stat.S_ISREG(mode):
        return "a file"
    if stat.S_ISSOCK(mode):
        return "a socket"
    return "not a terminal"


def probe(stdin_fd=0, stdout_fd=1, env=None):
    """May the interactive (arrow-key) menu run here? Any doubt -> legacy numeric menu."""
    env = os.environ if env is None else env
    if env.get("FAMILIA_LEGACY_MENU") == "1":
        return Probe(False, "FAMILIA_LEGACY_MENU=1")
    if env.get("FAMILIA_NO_TTY") == "1":
        return Probe(False, "FAMILIA_NO_TTY=1")
    try:
        import select  # noqa: F401
        import termios
        import tty  # noqa: F401
    except ImportError:
        return Probe(False, "termios/tty/select are not available (Windows or a minimal Python)")
    try:
        in_tty = os.isatty(stdin_fd)
    except OSError:
        in_tty = False
    if not in_tty:
        return Probe(False, "stdin is %s" % _fd_kind(stdin_fd))
    try:
        out_tty = os.isatty(stdout_fd)
    except OSError:
        out_tty = False
    if not out_tty:
        return Probe(False, "stdout is %s" % _fd_kind(stdout_fd))
    term = env.get("TERM", "")
    if not term:
        return Probe(False, "TERM is not set")
    if term in ("dumb", "unknown", "emacs"):
        return Probe(False, "TERM=%s" % term)
    try:
        termios.tcgetattr(stdin_fd)
    except (termios.error, OSError):
        return Probe(False, "cannot read the terminal settings")
    return Probe(True, "terminal ok")


def _show(key):
    text = key.text.encode("ascii", "backslashreplace").decode("ascii")
    extra = (" mods=%d" % key.mods if key.mods else "") + (" truncated" if key.truncated else "")
    return "%s %r%s" % (key.name, text, extra) if key.text else key.name + extra


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python3 scripts/menu_input.py probe [--stdout-fd N] | decode")
        print("  probe   exit 0 and print 'fancy' when the arrow-key menu may run,")
        print("          else exit 3 and print 'legacy: REASON'")
        print("  decode  read bytes on stdin (at most 1 MiB) and print one key per line")
        print("example: python3 scripts/menu_input.py probe && echo fancy menu allowed")
        return 0 if argv else 2
    if argv[0] == "probe":
        # --stdout-fd N: check fd N as the menu's stdout. A shell that captures
        # this output with $(...) passes the real stdout as fd 3:  { x=$(... probe --stdout-fd 3); } 3>&1
        out_fd = 1
        if len(argv) == 3 and argv[1] == "--stdout-fd" and argv[2].isdigit() and len(argv[2]) < 4:
            out_fd = int(argv[2])
        elif len(argv) != 1:
            print("menu_input: usage: probe [--stdout-fd N]", file=sys.stderr)
            return 2
        p = probe(0, out_fd)
        print("fancy" if p.fancy else "legacy: " + p.reason)
        return 0 if p.fancy else 3
    if argv[0] == "decode":
        data = sys.stdin.buffer.read(1 << 20)
        d = Decoder()
        for key in d.feed(data) + d.flush():
            print(_show(key))
        print("dropped %d" % d.dropped)
        return 0
    print("menu_input: unknown command %s (try --help)" % argv[0], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
