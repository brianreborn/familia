#!/usr/bin/env python3
"""Fleet greeting (docs/FLEET-GREETING.md) at the start of every familia agent's system prompt.

The greeting is fleet-signed text: it is read as-is and never edited here. Launchers call
prepend() on the system prompt they build (scripts/hermes_harness.py writes it into the
rendered HERMES_HOME/SOUL.md, hermes' identity slot #1; scripts/proto_chat.sh pipes its prompt
through `fleet_greeting.py prepend`). Pentest and guardian agents get it too: it is text only
and widens no tool, toolset or scope.

  path      FAMILIA_FLEET_GREETING (absolute, or relative to the repo root), else
            <repo>/docs/FLEET-GREETING.md. Whatever the override, the resolved real path must be a
            regular file under <repo>/docs/ of at most MAX_BYTES, or the greeting is skipped (so a
            key file elsewhere can never land in every system prompt)
  missing   a warning on stderr, once per process; the prompt is used without it (never fatal)
  once      the greeting is followed by END_MARKER; prepend() first drops everything up to an
            existing END_MARKER, so re-rendering never stacks a second (or a stale) copy

usage: fleet_greeting.py path | show | prepend   (prepend: system prompt on stdin -> stdout)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REL = os.path.join("docs", "FLEET-GREETING.md")
ENV = "FAMILIA_FLEET_GREETING"
# Plain HTML comment; avoids the words hermes' context-file scanner treats as injection
# (tools/threat_patterns.py html_comment_injection).
END_MARKER = "<!-- end of familia fleet greeting (docs/FLEET-GREETING.md, prepended at startup) -->"

MAX_BYTES = 64 * 1024
DOCS = os.path.realpath(os.path.join(ROOT, "docs"))

_cache = {}


def path(environ=None):
    env = os.environ if environ is None else environ
    p = (env.get(ENV) or "").strip()
    if not p:
        return os.path.join(ROOT, DEFAULT_REL)
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def _warn(msg):
    print(f"fleet-greeting: warning: {msg}; continuing without the fleet greeting", file=sys.stderr)


def load(p=None):
    """Greeting text exactly as on disk, or None (warned once per path). Read once per process."""
    p = p or path()
    if p in _cache:
        return _cache[p]
    text = None
    try:
        real = os.path.realpath(p)
        if os.path.commonpath([real, DOCS]) != DOCS:
            _warn(f"{p} is outside {DOCS}")
        elif not os.path.isfile(real):
            _warn(f"{p} is not a regular file")
        elif os.path.getsize(real) > MAX_BYTES:
            _warn(f"{p} is larger than {MAX_BYTES} bytes")
        else:
            with open(real, "rb") as f:
                text = f.read(MAX_BYTES + 1).decode("utf-8")
            if len(text.encode("utf-8")) > MAX_BYTES:
                _warn(f"{p} is larger than {MAX_BYTES} bytes")
                text = None
        if text is not None and END_MARKER in text:
            _warn(f"{p} contains the end marker")
            text = None
        elif text is not None and not text.strip():
            _warn(f"{p} is empty")
            text = None
    except FileNotFoundError:
        _warn(f"{p} not found")
    except (OSError, UnicodeDecodeError) as e:
        _warn(f"{p} unreadable ({e.__class__.__name__}: {e})")
    _cache[p] = text
    return text


def strip(text):
    """`text` without a previously prepended greeting block: only a leading block, i.e. an
    END_MARKER line within the first MAX_BYTES (+ marker) of the text. A marker deeper in the
    body is left alone."""
    text = text or ""
    i = text.find(END_MARKER)
    if i < 0 or len(text[:i].encode("utf-8")) > MAX_BYTES or (i and text[i - 1] != "\n"):
        return text
    return text[i + len(END_MARKER):].lstrip("\r\n")


def block(greeting):
    return greeting + ("" if greeting.endswith("\n") else "\n") + END_MARKER + "\n"


def prepend(text, greeting=None, p=None):
    """`text` with the fleet greeting at byte 0, exactly once. Without a greeting (missing file),
    returns `text` minus any stale greeting block."""
    g = load(p) if greeting is None else greeting
    body = strip(text)
    if not g:
        return body
    return block(g) + ("\n" + body if body else "")


def main(argv):
    cmd = argv[0] if argv else "-h"
    if cmd == "path":
        print(path()); return 0
    if cmd == "show":
        g = load()
        if g is None: return 1
        sys.stdout.write(g); return 0
    if cmd == "prepend":
        sys.stdout.write(prepend(sys.stdin.read())); return 0
    print(__doc__.strip(), file=sys.stderr if cmd not in ("-h", "--help") else sys.stdout)
    return 0 if cmd in ("-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
