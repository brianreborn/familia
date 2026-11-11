#!/usr/bin/env python3
"""Interactive Terminal Dashboard & UI Inspector for the running llama-server / protomodel."""

import json, os, re, sys, time, urllib.request

URL = os.environ.get("FAMILIA_UI_URL", "http://127.0.0.1:9941")
BULLET = "\u2022"
# CSI (7-bit and 8-bit), OSC, DCS/PM/APC, and other 2-byte ESC sequences.
_ESC_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|\x1b[P^_][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|\x1b[@-Z\\-_]"
    r"|\x9b[0-9;?]*[ -/]*[@-~]"
)
# C0, DEL, and C1. Dashboard fields are single-line, so TAB/LF/CR go too.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize(text):
    """Strip ESC/CSI/OSC sequences and C0/C1 controls from a server-derived string."""
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    return _CTRL_RE.sub("", _ESC_RE.sub("", s))


def use_color(stream=None, environ=None):
    """ANSI styling only on a TTY, when NO_COLOR is unset and TERM is not dumb."""
    env = os.environ if environ is None else environ
    if env.get("NO_COLOR"):
        return False
    if env.get("TERM", "") == "dumb":
        return False
    stream = sys.stdout if stream is None else stream
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def bullet(stream=None):
    """Unicode bullet, or ASCII '*' when the stream encoding cannot represent it."""
    stream = sys.stdout if stream is None else stream
    enc = getattr(stream, "encoding", None) or "utf-8"
    try:
        BULLET.encode(enc)
        return BULLET
    except (LookupError, UnicodeEncodeError):
        return "*"


def _paint(enabled, code, text):
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def get_json(path):
    try:
        with urllib.request.urlopen(f"{URL}{path}", timeout=2) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)}


def render_dashboard(file=None, environ=None, fetch=None):
    out = sys.stdout if file is None else file
    env = os.environ if environ is None else environ
    get = get_json if fetch is None else fetch
    colored = use_color(out, env)
    mark = bullet(out)

    props = get("/props")
    slots = get("/slots")
    models = get("/v1/models")

    if "error" in props:
        err = sanitize(props["error"])
        print(_paint(colored, "1;31", f"[!] Cannot connect to llama-server on {URL}: {err}"), file=out)
        return

    if colored:
        print("\033[2J\033[H", end="", file=out)
    print(_paint(colored, "1;36", "=" * 72), file=out)
    title = _paint(colored, "1;32", "  FAMILIA PROTOMODEL / LLAMA-UI LIVE COCKPIT  ")
    print(f"{title} ({_paint(colored, '4', URL + '/')})", file=out)
    print(_paint(colored, "1;36", "=" * 72), file=out)

    # Model details
    alias = sanitize(props.get("model_alias", "unknown"))
    ftype = sanitize(props.get("model_ftype", "unknown"))
    mpath = sanitize(os.path.basename(props.get("model_path", "") or ""))
    print(f"{_paint(colored, '1', 'Model Alias:')}    {alias} ({ftype})", file=out)
    print(f"{_paint(colored, '1', 'Weights File:')}   {mpath}", file=out)
    ui = "Enabled (Svelte bundle active)" if props.get("ui") else "Disabled"
    print(f"{_paint(colored, '1', 'Web UI:')}         {ui}", file=out)

    # Slot state
    print(f"\n{_paint(colored, '1;33', '--- Active Engine Slots ---')}", file=out)
    if isinstance(slots, list):
        for s in slots:
            sid = sanitize(s.get("id", 0))
            ctx = sanitize(s.get("n_ctx", 0))
            spec = sanitize(s.get("speculative", False))
            proc = s.get("is_processing", False)
            task = sanitize(s.get("id_task", "-"))
            status = _paint(colored, "32", "IDLE") if not proc else _paint(colored, "33", "PROCESSING")
            print(f"  Slot #{sid} | Context: {ctx} tokens | Speculative: {spec} | Status: {status} (Task {task})", file=out)
    else:
        print("  Slots data unavailable", file=out)

    # Exposed Models / Routes
    print(f"\n{_paint(colored, '1;33', '--- Exposed Routes & Endpoints ---')}", file=out)
    for m in (models.get("data") or []):
        mid = sanitize(m.get("id", ""))
        caps = ",".join(sanitize(c) for c in m.get("capabilities", [])) if "capabilities" in m else "chat"
        print(f"  {mark} {mid:<15} [capabilities: {caps}]", file=out)

    print(f"\n{_paint(colored, '1;36', '-' * 72)}", file=out)
    footer = "  To view in browser, run: sh scripts/open_ui.sh or visit: " + URL + "/"
    print(_paint(colored, "2", footer), file=out)
    print(_paint(colored, "1;36", "=" * 72), file=out)

if __name__ == "__main__":
    render_dashboard()
