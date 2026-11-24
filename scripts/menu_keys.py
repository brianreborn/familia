#!/usr/bin/env python3
"""menu_keys.py: arrow-key picker for familia-menu.sh (epic #733, M1).

Usage:
  python3 scripts/menu_keys.py pick [--prompt TEXT] [--cursor N] [--top] [--prev] [--next]
                                    [--head LINE]... [--foot LINE]... -- ENTRY...

Draws HEAD lines, ENTRY lines (an entry may span lines) and FOOT lines on stderr,
highlights one entry and reads keys from stdin (a terminal). Prints one answer
line on stdout for familia-menu.sh:
  N        the entry chosen with Enter (1-based), or a typed number
  TEXT     anything else typed before Enter (/word, FOO=1 3 ARG, n, <, ...)
  q        q on an empty line
  b        Esc, or Backspace on an empty line (not with --top)
  < / >    PgUp / PgDn past the first / last entry when --prev / --next
Keys: Up/Down (wrap), Home/End, PgUp/PgDn, Enter, Esc, q, Backspace, digits.
Exit status: 0 answered, 3 cannot use the terminal (caller falls back to the
line prompt), 4 Ctrl-D on an empty line, 130 interrupted (terminal restored).

Example:
  choice=$(python3 scripts/menu_keys.py pick --prompt "Choose: " -- "  1) one" "  2) two")

Layers (so M2/M4 can replace pieces):
  decode()     bytes -> key names; pure                         (M2: hardening)
  Picker       key names -> state / answer; pure
  render()     state -> lines; pure                             (M4: rendering)
  read_keys()  thin termios / msvcrt layer
"""
import os
import sys
import unicodedata

UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
HOME, END, PGUP, PGDN = "home", "end", "pgup", "pgdn"
ENTER, ESC, BACKSPACE, DELETE = "enter", "esc", "backspace", "delete"
EOF, INTR, UNKNOWN = "eof", "intr", "unknown"

_CSI_FINAL = {"A": UP, "B": DOWN, "C": RIGHT, "D": LEFT, "H": HOME, "F": END}
_CSI_TILDE = {"1": HOME, "7": HOME, "4": END, "8": END, "5": PGUP, "6": PGDN, "3": DELETE}
MAX_SEQ = 32  # longest escape sequence kept before it is dropped as unknown


def decode(buf, final=False):
    """Decode bytes into keys. Returns (keys, rest); rest is an incomplete
    sequence to retry with more bytes, or with final=True once input is idle
    (then a lone ESC is the Esc key). Printable text comes back as itself."""
    keys = []
    i, n = 0, len(buf)
    while i < n:
        b = buf[i]
        if b == 0x1B:
            if i + 1 >= n:
                if final:
                    keys.append(ESC)
                    i += 1
                    continue
                break
            nb = buf[i + 1]
            if nb in (0x5B, 0x4F):  # CSI "[" or SS3 "O"
                j = i + 2
                while j < n and j - i < MAX_SEQ and not 0x40 <= buf[j] <= 0x7E:
                    j += 1
                if j >= n:
                    if final:
                        keys.append(UNKNOWN)
                        i = n
                        continue
                    break
                if j - i >= MAX_SEQ:
                    keys.append(UNKNOWN)
                    i = j
                    continue
                params = buf[i + 2:j].decode("ascii", "replace")
                fin = chr(buf[j])
                if fin == "~":
                    keys.append(_CSI_TILDE.get(params.split(";")[0], UNKNOWN))
                elif fin in _CSI_FINAL and (nb == 0x4F or params in ("", "1") or params.startswith("1;")):
                    keys.append(_CSI_FINAL[fin])
                else:
                    keys.append(UNKNOWN)
                i = j + 1
            elif nb == 0x1B:
                keys.append(ESC)
                i += 1
            else:  # Alt+key: drop the key, treat as Esc
                keys.append(ESC)
                i += 2
            continue
        if b in (0x0D, 0x0A):
            keys.append(ENTER)
            if b == 0x0D and i + 1 < n and buf[i + 1] == 0x0A:
                i += 1
        elif b in (0x7F, 0x08):
            keys.append(BACKSPACE)
        elif b == 0x03:
            keys.append(INTR)
        elif b == 0x04:
            keys.append(EOF)
        elif b < 0x20:
            keys.append(UNKNOWN)
        elif b < 0x80:
            keys.append(chr(b))
        else:
            need = 2 if b >= 0xC0 else 1
            if b >= 0xE0:
                need = 3
            if b >= 0xF0:
                need = 4
            if i + need > n and not final:
                break
            ch = buf[i:i + need].decode("utf-8", "replace")
            keys.append(ch if ch.isprintable() and len(ch) == 1 else UNKNOWN)
            i += need
            continue
        i += 1
    return keys, buf[i:]


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
                if self.cursor == 0 and self.prev:
                    return "<"
                self.cursor = 0
            elif key == PGDN:
                if self.cursor == n - 1 and self.next:
                    return ">"
                self.cursor = n - 1
            self.line = ""
            return None
        if len(key) == 1:  # printable text
            if key in "qQ" and not self.line:
                return "q"
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
    out.append(prompt + picker.line)
    return out


def rows(lines, cols):
    cols = max(1, cols)
    return sum(max(1, -(-_width(l) // cols)) for l in lines)


# ---- thin terminal layer ----------------------------------------------------

class NoTerminal(Exception):
    pass


_SAVED = []  # [fd, termios attrs] while the picker owns the terminal


def restore_terminal():
    """Put the saved terminal mode back (idempotent; also used after Ctrl-C)."""
    if _SAVED:
        fd, attrs = _SAVED
        try:
            import termios
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass


def _term_size(fd):
    try:
        sz = os.get_terminal_size(fd)
        if sz.columns > 0 and sz.lines > 0:
            return sz.columns, sz.lines
    except OSError:
        pass
    return 80, 24


def _posix_session(in_fd, out_fd, draw):
    import select
    import signal
    import termios

    try:
        saved = termios.tcgetattr(in_fd)
    except termios.error as e:
        raise NoTerminal(str(e))
    _SAVED[:] = [in_fd, saved]
    resized = []
    wake_r, wake_w = os.pipe()
    for fd in (wake_r, wake_w):
        os.set_blocking(fd, False)
    old = {}

    def on_winch(signum, frame):  # flag only; the loop redraws
        resized.append(1)

    def on_term(signum, frame):  # unwind through finally, which restores the terminal
        raise SystemExit(128 + signum)

    try:
        old_wake = signal.set_wakeup_fd(wake_w)
        for sig, h in ((getattr(signal, "SIGWINCH", None), on_winch),
                       (signal.SIGTERM, on_term), (getattr(signal, "SIGHUP", None), on_term)):
            if sig is not None:
                old[sig] = signal.signal(sig, h)
        new = termios.tcgetattr(in_fd)
        new[3] &= ~(termios.ICANON | termios.ECHO)  # ISIG stays on: Ctrl-C is SIGINT
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
        termios.tcsetattr(in_fd, termios.TCSADRAIN, new)
        pending = b""
        draw(full=False)
        while True:
            timeout = 0.05 if pending else None
            r, _, _ = select.select([in_fd, wake_r], [], [], timeout)
            if wake_r in r:
                try:
                    while os.read(wake_r, 64):
                        pass
                except BlockingIOError:
                    pass
            if resized:
                del resized[:]
                draw(full=True)
            if in_fd in r:
                chunk = os.read(in_fd, 256)
                if not chunk:
                    yield EOF
                    continue
                keys, pending = decode(pending + chunk)
            elif pending and not r:
                keys, pending = decode(pending, final=True)
            else:
                continue
            for k in keys:
                yield k
    finally:
        restore_terminal()
        for sig, h in old.items():
            signal.signal(sig, h)
        try:
            signal.set_wakeup_fd(old_wake)
        except (NameError, ValueError):
            pass
        os.close(wake_r)
        os.close(wake_w)


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


def pick(head, entries, foot, prompt, picker, color, in_fd=0, out_fd=2):
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
        if full or need >= height:
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
            if key == EOF:
                if not picker.line:
                    write("\n")
                    return 4, ""
                continue
            answer = picker.feed(key)
            if answer is not None:
                write("\n")
                return 0, answer
            draw(full=False)
    finally:
        session.close()  # runs the finally above: terminal restored
    return 4, ""


def _parse(argv):
    opts = {"prompt": "Choose: ", "cursor": 0, "top": False, "prev": False, "next": False,
            "head": [], "foot": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return opts, argv[i + 1:]
        if a in ("--top", "--prev", "--next"):
            opts[a[2:]] = True
        elif a in ("--prompt", "--cursor", "--head", "--foot") and i + 1 < len(argv):
            v = argv[i + 1]
            i += 1
            if a == "--cursor":
                opts["cursor"] = int(v) if v.isdigit() else 0
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
    picker = Picker(len(entries), opts["cursor"], opts["top"], opts["prev"], opts["next"])
    try:
        status, answer = pick(opts["head"], entries, opts["foot"], opts["prompt"], picker, _color(2))
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
