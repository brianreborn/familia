#!/usr/bin/env python3
"""menu_keys.py: arrow-key picker for familia-menu.sh (epic #733, M1).

Usage:
  python3 scripts/menu_keys.py pick [--prompt TEXT] [--count N] [--cursor N] [--top]
                                    [--prev] [--next] [--head LINE]... [--foot LINE]... [-- ENTRY...]

Reads keys from stdin (a terminal) and prints one answer line on stdout, the
same text a typed line would give. With ENTRY arguments it draws HEAD, ENTRY
(an entry may span lines) and FOOT lines on stderr and highlights the current
entry. With --count N and no entries (what scripts/menu-keys.sh uses; the menu
has already printed its list) only the prompt line is redrawn, and the current
number is shown highlighted after the prompt. Answers:
  N        the entry chosen with Enter (1-based), or a typed number
  TEXT     anything else typed before Enter (/word, FOO=1 3 ARG, n, <, ...)
  q        q on an empty line
  b        Esc, or Backspace on an empty line (not with --top)
  < / >    PgUp / PgDn with --prev / --next (else they go to the first / last)
Keys: Up/Down (wrap), Home/End, PgUp/PgDn, Enter, Esc, q, Backspace, digits.
Exit status: 0 answered, 3 cannot use the terminal (caller falls back to the
line prompt), 4 Ctrl-D on an empty line, 130 interrupted (terminal restored).

Example:
  choice=$(python3 scripts/menu_keys.py pick --prompt "Choose: " -- "  1) one" "  2) two")

Layers (so M2/M4 can replace pieces):
  menu_input   bytes -> keys, probe: scripts/menu_input.py (M2, #736) is the one decoder
  Picker       key names -> state / answer; pure
  render()     state -> lines; pure                             (M4: rendering)
  read_keys()  thin termios / msvcrt layer (raw mode, bracketed paste, signals)
This file has no escape decoder of its own. Without scripts/menu_input.py (until
#736 is on main) the picker exits 3 and the menu keeps its line prompt.
"""
import os
import sys
import unicodedata

UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
HOME, END, PGUP, PGDN = "home", "end", "pgup", "pgdn"
ENTER, ESC, BACKSPACE, DELETE = "enter", "esc", "backspace", "delete"
EOF, INTR, UNKNOWN, PASTE = "eof", "intr", "unknown", "paste"
SEQ_HOLD_CAP = 5.0  # backstop only: M2's KeyReader caps a sequence at SEQ_MAX_AGE (2 s) itself
MAX_LINE = 4096  # longest typed or pasted answer kept (same bound as M2's read_line)

class Picker:
    """Highlight + typed-line state. feed(key) returns None (keep going) or the
    answer string for familia-menu.sh."""

    def __init__(self, count, cursor=0, top=False, prev=False, next=False):
        self.count = max(0, count)
        self.cursor = min(max(0, cursor), self.count - 1) if self.count else 0
        self.top, self.prev, self.next = top, prev, next
        self.line = ""

    def feed(self, key):
        n = self.count
        if isinstance(key, tuple):  # (PASTE, text): literal, single line, never a key
            text = key[1].replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
            text = "".join(ch for ch in text if ch.isprintable())
            self.line = (self.line + text)[:MAX_LINE]
            return None
        if key == ENTER:
            if self.line:
                line, self.line = self.line.strip(), ""
                return line or None
            return str(self.cursor + 1) if n else None
        if key == BACKSPACE:
            if self.line:
                self.line = self.line[:-1]
                return None
            return None if self.top else "b"
        if key == ESC:
            if self.line:
                self.line = ""
                return None
            return None if self.top else "b"
        if key in (UP, DOWN, HOME, END, PGUP, PGDN) and n:
            if key == UP:
                self.cursor = (self.cursor - 1) % n
            elif key == DOWN:
                self.cursor = (self.cursor + 1) % n
            elif key == HOME:
                self.cursor = 0
            elif key == END:
                self.cursor = n - 1
            elif key == PGUP:
                if self.prev:
                    return "<"
                self.cursor = 0
            elif key == PGDN:
                if self.next:
                    return ">"
                self.cursor = n - 1
            self.line = ""
            return None
        if len(key) == 1:  # printable text
            if key in "qQ" and not self.line:
                return "q"
            if len(self.line) < MAX_LINE:
                self.line += key
            if self.line.isdigit() and 1 <= int(self.line) <= n:
                self.cursor = int(self.line) - 1  # follow typed digits
        return None


def _width(s):
    w = 0
    esc = False
    for ch in s:
        if esc:
            esc = not ch.isalpha()
            continue
        if ch == "\033":
            esc = True
            continue
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def render(head, entries, foot, prompt, picker, color):
    """Lines to draw. The current entry gets a '>' mark (always) and reverse video (color)."""
    out = list(head)
    for i, e in enumerate(entries):
        lines = e.split("\n")
        if i == picker.cursor:
            first = lines[0]
            first = ">" + first[1:] if first.startswith(" ") else "> " + first
            lines[0] = "\033[7m" + first + "\033[0m" if color else first
        out.extend(lines)
    out.extend(foot)
    if picker.line or entries or not picker.count:
        out.append(prompt + picker.line)
    else:  # prompt-only mode: the current number stands in for the highlight
        cur = "[%d]" % (picker.cursor + 1)
        out.append(prompt + ("\033[7m" + cur + "\033[0m" if color else cur))
    return out


def rows(lines, cols):
    cols = max(1, cols)
    return sum(max(1, -(-_width(l) // cols)) for l in lines)


# ---- thin terminal layer ----------------------------------------------------

class NoTerminal(Exception):
    pass


_SAVED = []  # [in_fd, termios attrs, out_fd] while the picker owns the terminal
BRACKETED_PASTE_ON, BRACKETED_PASTE_OFF = "\033[?2004h", "\033[?2004l"


def restore_terminal():
    """Put the saved terminal mode back and end bracketed paste (idempotent; also
    used after Ctrl-C and before a Ctrl-Z stop)."""
    if _SAVED:
        fd, attrs, out_fd = _SAVED
        try:
            import termios
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass
        try:
            os.write(out_fd, BRACKETED_PASTE_OFF.encode())
        except OSError:
            pass


def _term_size(fd):
    try:
        sz = os.get_terminal_size(fd)
        if sz.columns > 0 and sz.lines > 0:
            return sz.columns, sz.lines
    except OSError:
        pass
    return 80, 24


def _m2():
    """scripts/menu_input.py (M2, Boundary): the decoder of record, KeyReader and probe."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import menu_input
        menu_input.KeyReader, menu_input.probe, menu_input.m1_key  # interface check (#736 >= 67be19c)
        return menu_input
    except (ImportError, AttributeError):
        return None


def from_m2(m2, key):
    """M2 Key -> picker key via menu_input.m1_key (the one mapping, in M2). Modifiers
    are ignored there (Ctrl+Up is up); alt/unknown are ignored here (never Esc = back).
    A paste becomes (PASTE, text): literal text for the typed line, never keys."""
    name = m2.m1_key(key)
    return (PASTE, key.text) if name == PASTE else name


def _posix_session(in_fd, out_fd, draw):
    import signal
    import termios

    m2 = _m2()
    if m2 is None:  # one decoder of record: M2's; until #736 is on main, line prompt
        raise NoTerminal("scripts/menu_input.py (#733 M2) is not here; using the line prompt")
    try:
        saved = termios.tcgetattr(in_fd)
    except termios.error as e:
        raise NoTerminal(str(e))
    _SAVED[:] = [in_fd, saved, out_fd]
    resized = []
    old = {}
    raw = []

    def enter_raw():
        termios.tcsetattr(in_fd, termios.TCSADRAIN, raw[0])
        os.write(out_fd, BRACKETED_PASTE_ON.encode())

    def on_winch(signum, frame):  # flag only; the loop redraws
        resized.append(1)

    def on_term(signum, frame):  # unwind through finally, which restores the terminal
        raise SystemExit(128 + signum)

    def on_tstp(signum, frame):  # Ctrl-Z: cooked terminal while stopped, raw again after fg
        restore_terminal()
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)  # stops here until SIGCONT
        signal.signal(signal.SIGTSTP, on_tstp)
        enter_raw()
        resized.append(1)

    try:
        for name, h in (("SIGWINCH", on_winch), ("SIGTERM", on_term), ("SIGHUP", on_term), ("SIGTSTP", on_tstp)):
            sig = getattr(signal, name, None)
            if sig is not None:
                old[sig] = signal.signal(sig, h)
        new = termios.tcgetattr(in_fd)
        new[3] &= ~(termios.ICANON | termios.ECHO)  # ISIG stays on: Ctrl-C is SIGINT
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
        raw.append(new)
        enter_raw()
        draw(full=False)
        import time
        reader = m2.KeyReader(in_fd)
        held = None  # when the decoder started holding a half-read sequence
        while True:
            try:
                # bounded wait so a resize is seen; the reader keeps partial sequences
                # (M2's KeyReader owns the inter-byte timing, #736)
                key = reader.read_key(timeout=0.2)
            except EOFError:  # closed input: report once and stop, never spin
                yield EOF
                return
            if resized:
                del resized[:]
                draw(full=True)
            if key is not None:
                yield from_m2(m2, key)
            if reader.decoder.pending and key is None:
                held = held or time.monotonic()
                if time.monotonic() - held > SEQ_HOLD_CAP:
                    # wall-clock cap: an endless sequence (e.g. OSC) is dropped with a fresh
                    # reader; Ctrl-C is a signal (ISIG on), so it is never blocked anyway
                    reader = m2.KeyReader(in_fd)
                    held = None
            else:
                held = None
    finally:
        restore_terminal()
        del _SAVED[:]
        for sig, h in old.items():
            signal.signal(sig, h)


_WIN_KEYS = {"H": UP, "P": DOWN, "K": LEFT, "M": RIGHT, "G": HOME, "O": END, "I": PGUP, "Q": PGDN, "S": DELETE}


def _windows_session(draw):
    import msvcrt

    draw(full=False)
    while True:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            yield _WIN_KEYS.get(msvcrt.getwch(), UNKNOWN)
        elif ch == "\r":
            yield ENTER
        elif ch == "\x08":
            yield BACKSPACE
        elif ch == "\x1b":
            yield ESC
        elif ch == "\x03":
            yield INTR
        elif ch in ("\x04", "\x1a"):
            yield EOF
        elif ch.isprintable():
            yield ch


def pick(head, entries, foot, prompt, picker, color, in_fd=0, out_fd=2, prompt_only=False):
    """Run the picker on a terminal. Returns (status, answer)."""
    if not (os.isatty(in_fd) and os.isatty(out_fd)):
        raise NoTerminal("not a terminal")
    state = {"rows": 0}

    def write(s):
        data = s.encode("utf-8", "replace")
        while data:
            data = data[os.write(out_fd, data):]

    def draw(full):
        lines = render(head, entries, foot, prompt, picker, color)
        cols, height = _term_size(out_fd)
        need = rows(lines, cols)
        if full and prompt_only:  # never clear the list the menu printed; repaint the prompt
            s = "\r\033[J"
        elif full or need >= height:
            s = "\033[H\033[2J"
        elif state["rows"] > 1:
            s = "\r\033[%dA\033[J" % (state["rows"] - 1)
        else:
            s = "\r\033[J"
        write(s + "\n".join(lines))
        state["rows"] = need

    session = _windows_session(draw) if os.name == "nt" else _posix_session(in_fd, out_fd, draw)
    try:
        for key in session:
            if key == INTR:
                raise KeyboardInterrupt
            if key == EOF:  # closed input (Ctrl-D or EOFError): end, typed text dropped
                write("\n")
                return 4, ""
            answer = picker.feed(key)
            if answer is not None:
                write("\n")
                return 0, answer
            draw(full=False)
    finally:
        session.close()  # runs the finally above: terminal restored
    return 4, ""


def _parse(argv):
    opts = {"prompt": "Choose: ", "cursor": 0, "count": 0, "top": False, "prev": False, "next": False,
            "head": [], "foot": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return opts, argv[i + 1:]
        if a in ("--top", "--prev", "--next"):
            opts[a[2:]] = True
        elif a in ("--prompt", "--cursor", "--count", "--head", "--foot") and i + 1 < len(argv):
            v = argv[i + 1]
            i += 1
            if a in ("--cursor", "--count"):
                opts[a[2:]] = int(v) if v.isdigit() else 0
            elif a in ("--head", "--foot"):
                opts[a[2:]].append(v)
            else:
                opts["prompt"] = v
        else:
            raise SystemExit("menu_keys.py: unknown option %r (see --help)" % a)
        i += 1
    return opts, []


def _color(fd):
    mode = os.environ.get("FAMILIA_COLOR", "auto")
    if mode in ("always", "never"):
        return mode == "always"
    return os.isatty(fd) and not os.environ.get("NO_COLOR") and os.environ.get("TERM", "dumb") != "dumb"


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] != "pick":
        print("menu_keys.py: unknown command %r (see --help)" % argv[0], file=sys.stderr)
        return 2
    opts, entries = _parse(argv[1:])
    m2 = _m2() if os.name != "nt" else None
    if m2 is not None:  # M2 decides whether the arrow-key reader may run (stdout is our answer pipe)
        verdict = m2.probe(0, 2)
        if not verdict.fancy:
            print("menu_keys.py: line prompt (%s)" % verdict.reason, file=sys.stderr)
            return 3
    picker = Picker(len(entries) or opts["count"], opts["cursor"], opts["top"], opts["prev"], opts["next"])
    try:
        status, answer = pick(opts["head"], entries, opts["foot"], opts["prompt"], picker, _color(2),
                              prompt_only=not entries)
    except NoTerminal as e:
        print("menu_keys.py: %s" % e, file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        restore_terminal()  # again, in case Ctrl-C landed inside the first restore
        # terminal restored; die by SIGINT so the calling shell stops too
        try:
            os.write(2, b"\r\n")
            import signal
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGINT)
        except (AttributeError, OSError):
            pass
        return 130
    if status == 0:
        sys.stdout.write(answer + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
