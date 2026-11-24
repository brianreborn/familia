#!/usr/bin/env python3
"""Menu reachability harness for familia #733 M5 (X Bug Cartographer).

Walks the current home and legacy menus and reports, per item:
  - reachable by number
  - reachable by arrow keys
  - dead-end (process exits or hangs instead of returning to a prompt)
  - the menu returns rather than exiting on errors or invalid input
  - Ctrl-C at the legacy prompt and during a child action redraws the menu;
    the Exit option (q / exit) still quits 0. HUP and TERM still end it.

Headless and offline: --dry-run, isolated HOME, FAMILIA_SKIP_GUM_INSTALL=1,
no --apply, no model downloads, no network-facing side effects.

Prefer pexpect; fall back to the stdlib pty if pexpect is missing.

Usage:
  python3 tests/menu_harness.py
  python3 tests/menu_harness.py --json PATH --md PATH
  python3 -m pytest tests/test_menu_harness.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MENU = os.path.join(ROOT, "familia-menu.sh")
BASH = shutil.which("bash")
# Termux has no /bin/sh until termux-exec rewrites a shebang. Use the sh we found.
SH = shutil.which("sh") or "/bin/sh"
NOTICE = "Use the Exit option to quit"
HOME = os.path.join(ROOT, "scripts", "familia_home.sh")
FAMILIA = os.path.join(ROOT, "familia")
CATALOG = os.path.join(ROOT, "scripts", "menu-items.txt")
PAGE_SIZE = 7
PH_RE = re.compile(r"\{[A-Z]+:[^}]*\}")
HOME_TITLES = (
    "Models",
    "Harnesses",
    "Agents",
    "MCP servers",
    "Tool sets",
    "App store",
)
HOME_EXTRAS = (
    "Open llama-ui web cockpit",
    "List all models",
    "Configure all graphs",
    "Legacy menu",
)

try:
    import pexpect
except ImportError:  # pragma: no cover - optional
    pexpect = None


_UTF8_LOCALE = None


def utf8_locale():
    """A locale this host actually has. C.UTF-8 is missing on some macOS and older FreeBSD."""
    global _UTF8_LOCALE
    if _UTF8_LOCALE:
        return _UTF8_LOCALE
    import locale as locale_mod

    saved = locale_mod.setlocale(locale_mod.LC_ALL)
    chosen = "C"
    try:
        for name in ("C.UTF-8", "en_US.UTF-8", "C"):
            try:
                locale_mod.setlocale(locale_mod.LC_ALL, name)
            except locale_mod.Error:
                continue
            chosen = name
            break
    finally:
        try:
            locale_mod.setlocale(locale_mod.LC_ALL, saved)
        except locale_mod.Error:
            pass
    _UTF8_LOCALE = chosen
    return chosen


def isolated_env(**kw):
    """HOME and PATH never see the developer's gum or caches."""
    home = tempfile.mkdtemp(prefix="familia-m5-harness-")
    os.chmod(home, 0o700)
    for sub in ("cache", "run", ".local"):
        os.makedirs(os.path.join(home, sub), mode=0o700, exist_ok=True)
    env = dict(os.environ)
    # CI=true (GitHub Actions) forces line mode once the M1 reader lands (M7 T-1).
    # Drop it, and the T-4 detection knobs, so a laptop and CI start from the same env.
    # Callers can still pass CI=1 via kw; env.update(kw) runs after these pops.
    for key in (
        "CI",
        "FAMILIA_MENU",
        "FAMILIA_GLYPHS",
        "FAMILIA_ESC_MS",
        "FAMILIA_NO_TTY",
        "FAMILIA_ACCEPT_LICENSES",
        "FAMILIA_HOME_FORCE_MENU",
        "FAMILIA_LEGACY_MENU",
        "FAMILIA_MENU_PIPE",
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    ):
        env.pop(key, None)
    env["HOME"] = home
    env["XDG_CACHE_HOME"] = os.path.join(home, "cache")
    env["XDG_RUNTIME_DIR"] = os.path.join(home, "run")
    env["TERM"] = kw.pop("TERM", "xterm")
    env["NO_COLOR"] = "1"
    env["FAMILIA_COLOR"] = "never"
    env["FAMILIA_SKIP_GUM_INSTALL"] = "1"
    env["LC_ALL"] = utf8_locale()
    env["COLUMNS"] = "120"
    env["LINES"] = "40"
    parts = [
        p
        for p in env.get("PATH", "").split(os.pathsep)
        if p
        and not p.endswith(os.sep + ".local" + os.sep + "bin")
        and not p.endswith("/.local/bin")
    ]
    env["PATH"] = os.pathsep.join(parts) or "/usr/bin:/bin"
    env.update(kw)
    env["_HARNESS_HOME"] = home
    return env


def need_ok(spec, root=ROOT):
    spec = (spec or "").strip()
    if not spec or spec == "-":
        return True
    if spec.startswith("file:"):
        return os.path.exists(os.path.join(root, spec[5:]))
    if spec.startswith("grep:"):
        _kind, path, text = spec.split(":", 2)
        full = os.path.join(root, path)
        if not os.path.exists(full):
            return False
        with open(full, encoding="utf-8", errors="replace") as fh:
            return text in fh.read()
    return True


def load_catalog(path=CATALOG):
    """Parse scripts/menu-items.txt. Skip blank and comment lines."""
    items = []
    groups = []
    seen = set()
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("|")
            while len(parts) < 7:
                parts.append("")
            key, group, label, posix, gate, need, windows = parts[:7]
            rec = {
                "line": lineno,
                "key": key,
                "group": group,
                "label": label,
                "posix": posix,
                "gate": gate,
                "need": need,
                "windows": windows,
                "placeholders": PH_RE.findall(posix),
                "posix_visible": bool(posix.strip()),
                "windows_visible": bool(windows.strip()),
                "available": need_ok(need) if posix.strip() else False,
            }
            items.append(rec)
            if rec["posix_visible"] and group not in seen:
                seen.add(group)
                groups.append(group)
    return items, groups


def posix_tree(items, groups):
    """Group -> list of posix-visible items, in catalog order (page size 7)."""
    tree = []
    for i, group in enumerate(groups, 1):
        rows = [it for it in items if it["group"] == group and it["posix_visible"]]
        pages = [rows[n : n + PAGE_SIZE] for n in range(0, len(rows), PAGE_SIZE)] or [[]]
        tree.append({"index": i, "group": group, "items": rows, "pages": pages})
    return tree


class Check:
    def __init__(self, kind, item, status, detail=""):
        self.kind = kind
        self.item = item
        self.status = status  # PASS, FAIL, SKIP
        self.detail = detail

    def as_dict(self):
        return {
            "kind": self.kind,
            "item": self.item,
            "status": self.status,
            "detail": self.detail,
        }


def _spawn(argv, env, timeout=20):
    if pexpect is None:
        raise RuntimeError("pexpect is required for the interactive walk")
    child = pexpect.spawn(
        argv[0],
        argv[1:],
        cwd=ROOT,
        env=env,
        encoding="utf-8",
        codec_errors="replace",
        timeout=timeout,
        dimensions=(40, 120),
    )
    child.delaybeforesend = 0.02
    return child


def _expect_choose(child, timeout=20):
    """Wait for a Choose prompt and return all output since the previous prompt."""
    child.expect(r"Choose ", timeout=timeout)
    text = (child.before or "") + (child.after or "")
    try:
        child.expect(r": ?", timeout=2)
        text += (child.before or "") + (child.after or "")
    except pexpect.TIMEOUT:
        pass
    return text


def _need_pexpect(item):
    if pexpect is None:
        return Check("exit-rule", item, "SKIP", "pexpect is not installed")
    if not BASH:
        return Check("exit-rule", item, "SKIP", "bash is not installed")
    return None


def _stop_child(child):
    if child is None:
        return
    try:
        if child.isalive():
            os.killpg(child.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            child.close(force=True)
        except Exception:
            pass
    try:
        if child.isalive():
            child.close(force=True)
    except Exception:
        pass


def walk_legacy_numbers(tree, timeout=20):
    """Select every posix-visible item by number under --pipe --dry-run."""
    checks = []
    if not BASH:
        return [Check("number-walk", "legacy.complete", "SKIP", "bash is not installed")], None, ""
    env = isolated_env()
    argv = [BASH, MENU, "--pipe", "--dry-run"]
    child = None
    log = []
    try:
        child = _spawn(argv, env, timeout=timeout)
        _expect_choose(child, timeout=timeout)
        for group in tree:
            child.sendline(str(group["index"]))
            text = _expect_choose(child, timeout=timeout)
            log.append(text)
            for pno, page in enumerate(group["pages"]):
                if pno:
                    child.sendline(">")
                    text = _expect_choose(child, timeout=timeout)
                    log.append(text)
                for local, rec in enumerate(page, 1):
                    shown = rec["label"] in (text or "") or rec["key"] in (child.before or "")
                    # The current page listing is in `text` (output since last Choose).
                    listed = rec["label"] in text
                    if rec["available"]:
                        child.sendline(str(local))
                        for _ph in rec["placeholders"]:
                            try:
                                child.expect(r": ", timeout=8)
                            except pexpect.TIMEOUT:
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "FAIL",
                                        "expected a prompt for %s, stayed at: %s"
                                        % (_ph, (child.before or "")[-200:]),
                                    )
                                )
                                break
                            child.sendline("harness")
                        else:
                            try:
                                nxt = _expect_choose(child, timeout=timeout)
                            except pexpect.TIMEOUT:
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "FAIL",
                                        "menu did not return after selecting this item",
                                    )
                                )
                                return checks, child.exitstatus, "timeout after %s" % rec["key"]
                            except pexpect.EOF:
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "FAIL",
                                        "menu exited after selecting this item",
                                    )
                                )
                                return checks, child.exitstatus, "exited after %s" % rec["key"]
                            blob = (child.before or "") + nxt
                            if rec["label"] not in text and rec["label"] not in blob and not listed:
                                # still count as selected if dry-run or not-available appeared
                                pass
                            if "[dry-run]" in blob or "not available" in blob or "exited with status" in blob or "Running:" in blob:
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "PASS",
                                        "selected by %s / page %s / %s; menu returned"
                                        % (group["index"], pno + 1, local),
                                    )
                                )
                            elif "Choose " in nxt:
                                # returned to the page; treat as a return, but flag if no dry-run
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "PASS",
                                        "selected by number; menu returned (no dry-run line)",
                                    )
                                )
                            else:
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "FAIL",
                                        "unclear result: %s" % blob[-240:],
                                    )
                                )
                            text = nxt
                    else:
                        # Disabled items are listed but must not be runnable.
                        if listed or rec["label"] in text:
                            checks.append(
                                Check(
                                    "number",
                                    rec["key"],
                                    "PASS",
                                    "listed on page %s as not available; not executed"
                                    % (pno + 1,),
                                )
                            )
                        else:
                            # Page banner may have scrolled; confirm by selecting.
                            child.sendline(str(local))
                            try:
                                nxt = _expect_choose(child, timeout=timeout)
                            except (pexpect.TIMEOUT, pexpect.EOF):
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "FAIL",
                                        "unavailable item was not listed and select did not return",
                                    )
                                )
                                return checks, child.exitstatus, "lost after %s" % rec["key"]
                            blob = (child.before or "") + nxt
                            if "not available" in blob:
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "PASS",
                                        "selecting the unavailable item stayed in the menu",
                                    )
                                )
                            else:
                                checks.append(
                                    Check(
                                        "number",
                                        rec["key"],
                                        "FAIL",
                                        "unavailable item not clearly listed or guarded",
                                    )
                                )
                            text = nxt
            child.sendline("b")
            _expect_choose(child, timeout=timeout)
        child.sendline("q")
        child.expect(pexpect.EOF, timeout=timeout)
        rc = child.wait()
        return checks, rc, ""
    except (pexpect.TIMEOUT, pexpect.EOF) as exc:
        before = child.before or ""
        try:
            child.close(force=True)
        except Exception:
            pass
        return checks, child.exitstatus, "%s: %s" % (type(exc).__name__, before[-400:])
    finally:
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def check_legacy_exit_rules(timeout=15):
    """Invalid input and EOF must not be a successful quit."""
    if not BASH:
        return [
            Check("exit-rule", "legacy.explicit-q", "SKIP", "bash is not installed"),
            Check("exit-rule", "legacy.eof", "SKIP", "bash is not installed"),
            Check("exit-rule", "legacy.invalid-input", "SKIP", "bash is not installed"),
        ]
    checks = []
    env = isolated_env()
    try:
        return _legacy_exit_rules(env, checks, timeout)
    finally:
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def _legacy_exit_rules(env, checks, timeout):
    # explicit q
    r = subprocess.run(
        [BASH, MENU, "--pipe"],
        input="q\n",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if r.returncode == 0:
        checks.append(Check("exit-rule", "legacy.explicit-q", "PASS", "q exits 0"))
    else:
        checks.append(
            Check(
                "exit-rule",
                "legacy.explicit-q",
                "FAIL",
                "q exited %s" % r.returncode,
            )
        )
    # EOF is not a successful quit
    r = subprocess.run(
        [BASH, MENU, "--pipe"],
        input="",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if r.returncode == 2 and "type q" in (r.stdout + r.stderr).lower():
        checks.append(Check("exit-rule", "legacy.eof", "PASS", "EOF exits 2, not 0"))
    else:
        checks.append(
            Check(
                "exit-rule",
                "legacy.eof",
                "FAIL",
                "EOF exited %s: %s" % (r.returncode, (r.stdout + r.stderr)[-200:]),
            )
        )
    # invalid input stays, then q
    r = subprocess.run(
        [BASH, MENU, "--pipe", "--dry-run"],
        input="zzz\nq\n",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    blob = r.stdout + r.stderr
    if r.returncode == 0 and "isn't one of the choices" in blob:
        checks.append(
            Check("exit-rule", "legacy.invalid-input", "PASS", "invalid input stayed; q quit 0")
        )
    else:
        checks.append(
            Check(
                "exit-rule",
                "legacy.invalid-input",
                "FAIL",
                "rc=%s text=%s" % (r.returncode, blob[-240:]),
            )
        )
    return checks


def check_legacy_arrows(timeout=15):
    """Arrow keys do not move a highlight on the current legacy menu (M1 gap)."""
    if pexpect is None:
        return [
            Check("arrow", "legacy.top", "SKIP", "pexpect is not installed"),
        ]
    if not BASH:
        return [Check("arrow", "legacy.top", "SKIP", "bash is not installed")]
    env = isolated_env()
    child = _spawn([BASH, MENU, "--dry-run"], env, timeout=timeout)
    try:
        _expect_choose(child, timeout=timeout)
        # A newline, then q on its own line. Without the newline, bash reads
        # the CSI bytes and the later "q" as one choice and the quit waits out.
        child.send("\x1b[B\r")  # Down, then Enter
        try:
            child.expect(r"Choose |isn't one of the choices", timeout=5)
            blob = (child.before or "") + (child.after or "")
        except pexpect.TIMEOUT:
            blob = child.before or ""
        still_alive = child.isalive()
        child.sendline("q")
        try:
            child.expect(pexpect.EOF, timeout=timeout)
        except pexpect.TIMEOUT:
            child.close(force=True)
        rc = child.exitstatus
        # Current menu has no highlight and treats the CSI sequence as a
        # bad choice, or swallows it. Either way, arrows do not select.
        moved = "highlight" in blob.lower() or re.search(r">\s+\d+\)", blob)
        if not still_alive:
            return [
                Check(
                    "arrow",
                    "legacy.top",
                    "FAIL",
                    "process exited after Down arrow (dead end)",
                )
            ]
        # Documented gap: no arrow-key traversal yet (owned by M1).
        detail = "Down arrow did not move a highlight (current menu is numeric + /search only)"
        if "isn't one of the choices" in blob or not moved:
            return [Check("arrow", "legacy.top", "FAIL", detail)]
        if rc == 0 and moved:
            return [Check("arrow", "legacy.top", "PASS", "highlight moved after Down")]
        return [Check("arrow", "legacy.top", "FAIL", detail + "; rc=%s" % rc)]
    except (pexpect.TIMEOUT, pexpect.EOF) as exc:
        try:
            child.close(force=True)
        except Exception:
            pass
        return [
            Check(
                "arrow",
                "legacy.top",
                "FAIL",
                "%s: %s" % (type(exc).__name__, (child.before or "")[-200:]),
            )
        ]
    finally:
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def check_home_static():
    """Home structure, numeric gap, extras vs list-goals, fallback exec."""
    env = isolated_env()
    try:
        return _check_home_static(env)
    finally:
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def _check_home_static(env):
    checks = []
    r = subprocess.run(
        ["sh", HOME, "--list-goals"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    out = r.stdout
    if r.returncode == 0 and all(t in out for t in HOME_TITLES) and "q) Quit" in out:
        checks.append(Check("home-structure", "list-goals", "PASS", "six equal items + Quit"))
    else:
        checks.append(
            Check(
                "home-structure",
                "list-goals",
                "FAIL",
                "rc=%s out=%s" % (r.returncode, out[:240]),
            )
        )
    # list-goals numbers items 1-6, but the interactive picker is gum choose
    # (arrows only, no numeric entry). That is a standing-rule gap.
    with open(HOME, encoding="utf-8") as fh:
        src = fh.read()
    if "gum choose" in src and "read_line" not in src.split("pick()")[0] if False else True:
        has_numeric = bool(
            re.search(r"pick\(\).*read ", src, re.S)
        ) or "Choose 1-" in src
        # pick() only calls gum choose; there is no number parser in the home loop.
        pick_fn = src[src.find("# pick HEADER") : src.find("area_of()")]
        if "gum choose" in pick_fn and "read " not in pick_fn:
            checks.append(
                Check(
                    "number",
                    "home.interactive",
                    "FAIL",
                    "interactive home uses gum choose only; numbered --list-goals entries cannot be typed",
                )
            )
        else:
            checks.append(
                Check(
                    "number",
                    "home.interactive",
                    "PASS",
                    "home pick() accepts numeric input",
                )
            )
    # Extra items on the interactive pick() are not numbered in --list-goals.
    if all(x in src for x in HOME_EXTRAS) and "Open llama-ui web cockpit" not in "\n".join(
        ln for ln in out.splitlines() if ln.strip().startswith(("1)", "2)", "3)", "4)", "5)", "6)"))
    ):
        if "Open llama-ui web cockpit" in out and not any(
            ln.strip().startswith(tuple("%d)" % i for i in range(1, 7))) and "Open llama-ui" in ln
            for ln in out.splitlines()
        ):
            checks.append(
                Check(
                    "home-structure",
                    "home.extras-unnumbered",
                    "FAIL",
                    "interactive extras (cockpit, list models, configure graphs, Legacy menu) are not numbered in --list-goals",
                )
            )
    # fallback_legacy execs away
    if "exec bash" in src and "fallback_legacy" in src:
        checks.append(
            Check(
                "exit-rule",
                "home.fallback-exec",
                "FAIL",
                "fallback_legacy execs familia-menu.sh and never returns to the home menu",
            )
        )
    return checks


def check_home_stub_walk(timeout=20):
    """Walk every area/verb plus extras with a stub gum; menu must return until Quit."""
    env = isolated_env(TERM="dumb")
    try:
        return _check_home_stub_walk(env, timeout)
    finally:
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def _check_home_stub_walk(env, timeout):
    checks = []
    bin_dir = os.path.join(env["_HARNESS_HOME"], "bin")
    os.makedirs(bin_dir, exist_ok=True)
    # Sequence: each area, list, Back, then extras that are safe, then Quit.
    # list/status do not apply and do not download.
    choices = []
    for title in HOME_TITLES:
        choices.extend([title, "list", "Back"])
    choices.extend(["List all models", "Configure all graphs", "Quit"])
    choice_file = os.path.join(bin_dir, "choices")
    with open(choice_file, "w", encoding="ascii") as fh:
        fh.write("\n".join(choices) + "\n")
    gum = os.path.join(bin_dir, "gum")
    # The stub stays under the mkdtemp HOME. Never put it on /sdcard: that
    # mount is noexec on Termux. The shebang is the sh we found, not a
    # hardcoded /bin/sh (Termux has none until termux-exec rewrites it).
    script = """#!__SH__
case "$1" in --version|-v) printf '%s\n' 'gum version 2.0.2'; exit 0 ;; esac
if [ "$1" = choose ] && [ "$2" = --help ]; then
  printf '%s\n' '--header' '--height'; exit 0
fi
if [ "$1" = choose ]; then
  line=$(head -n 1 '{path}')
  rest=$(tail -n +2 '{path}')
  printf '%s\n' "$rest" > '{path}'
  case "$line" in ''|CANCEL) exit 130 ;; *) printf '%s\n' "$line" ;; esac
  exit 0
fi
exit 0
""".replace("__SH__", SH).replace("{path}", choice_file)
    with open(gum, "w", encoding="ascii") as fh:
        fh.write(script)
    os.chmod(gum, 0o755)
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]
    # Drive via a pty so familia_home.sh sees a terminal.
    if pexpect is None:
        checks.append(Check("home-walk", "stub-gum", "SKIP", "pexpect is not installed"))
        return checks
    child = _spawn(["sh", HOME], env, timeout=timeout)
    try:
        child.expect(pexpect.EOF, timeout=timeout)
        rc = child.wait()
        out = child.before or ""
        leftover = open(choice_file, encoding="ascii").read().strip()
        if rc == 0 and leftover == "":
            checks.append(
                Check(
                    "home-walk",
                    "stub-gum-areas-list",
                    "PASS",
                    "listed all six areas and two extras, then Quit (rc=0)",
                )
            )
        else:
            checks.append(
                Check(
                    "home-walk",
                    "stub-gum-areas-list",
                    "FAIL",
                    "rc=%s leftover=%r out=%s" % (rc, leftover, out[-300:]),
                )
            )
        # Arrow reachability of the home menu cannot be proven with a stub gum.
        checks.append(
            Check(
                "arrow",
                "home.interactive",
                "SKIP",
                "home picker is gum choose; stub gum cannot prove arrow traversal (M1 does not own gum itself)",
            )
        )
    except (pexpect.TIMEOUT, pexpect.EOF) as exc:
        try:
            child.close(force=True)
        except Exception:
            pass
        checks.append(
            Check(
                "home-walk",
                "stub-gum-areas-list",
                "FAIL",
                "%s: %s" % (type(exc).__name__, (child.before or "")[-300:]),
            )
        )
    return checks


def _posix_item(tree, key):
    for group in tree:
        for pno, page in enumerate(group["pages"]):
            for local, rec in enumerate(page, 1):
                if rec["key"] == key:
                    return group, pno, local
    return None, None, None


def check_legacy_tty_eof(timeout=15):
    """EOF on a real tty is not a quit, and the after-item Enter prompt is reached.

    --pipe skips both. Platform ran this on a pty and it already passed.
    """
    skip = _need_pexpect("legacy.tty-eof")
    if skip:
        return [skip]
    env = isolated_env()
    child = None
    try:
        child = _spawn([BASH, MENU, "--dry-run"], env, timeout=timeout)
        _expect_choose(child, timeout=timeout)
        child.sendline("1")  # Set up
        _expect_choose(child, timeout=timeout)
        child.sendline("1")  # first item, no placeholder
        child.expect("Press Enter", timeout=timeout)
        child.sendline("")
        _expect_choose(child, timeout=timeout)
        child.sendeof()
        child.expect("input closed", timeout=timeout)
        _expect_choose(child, timeout=timeout)
        child.sendline("q")
        child.expect(pexpect.EOF, timeout=timeout)
        rc = child.wait()
        if rc == 0:
            return [
                Check(
                    "exit-rule",
                    "legacy.tty-eof",
                    "PASS",
                    "Press Enter, then tty EOF, reprompted; q exited 0",
                )
            ]
        return [Check("exit-rule", "legacy.tty-eof", "FAIL", "q exited %s" % rc)]
    except (pexpect.TIMEOUT, pexpect.EOF, OSError) as exc:
        return [
            Check(
                "exit-rule",
                "legacy.tty-eof",
                "FAIL",
                "%s: %s" % (type(exc).__name__, ((child.before if child else "") or "")[-240:]),
            )
        ]
    finally:
        _stop_child(child)
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def check_legacy_ctrl_c(timeout=15):
    """Ctrl-C at the prompt, at a sub-prompt, and during a child redraws.

    The explicit Exit option (the word exit, same as q) still exits 0.
    """
    skip = _need_pexpect("legacy.ctrl-c")
    if skip:
        return [skip]
    env = isolated_env()
    child = None
    try:
        sleeper = os.path.join(env["_HARNESS_HOME"], "py-sleep")
        with open(sleeper, "w", encoding="ascii") as fh:
            fh.write("#!/bin/sh\nsleep 30\n")
        os.chmod(sleeper, 0o755)
        env["PYTHON"] = sleeper
        items, _groups = load_catalog()
        tree = posix_tree(items, _groups)
        menu_group, _menu_page, menu_local = _posix_item(tree, "skills.menu")
        list_group, list_page, list_local = _posix_item(tree, "skills.list")
        if menu_group is None or list_group is None:
            return [Check("exit-rule", "legacy.ctrl-c", "FAIL", "skills.menu or skills.list missing")]
        child = _spawn([BASH, MENU], env, timeout=timeout)
        _expect_choose(child, timeout=timeout)
        child.sendintr()
        child.expect(NOTICE, timeout=timeout)
        _expect_choose(child, timeout=timeout)
        child.sendline(str(menu_group["index"]))
        _expect_choose(child, timeout=timeout)
        child.sendline(str(menu_local))
        child.expect("agent name", timeout=timeout)
        child.sendintr()
        child.expect(NOTICE, timeout=timeout)
        _expect_choose(child, timeout=timeout)
        for _ in range(list_page):
            child.sendline(">")
            _expect_choose(child, timeout=timeout)
        child.sendline(str(list_local))
        child.expect("Running:", timeout=timeout)
        time.sleep(0.2)
        child.sendintr()
        child.expect(NOTICE, timeout=timeout)
        _expect_choose(child, timeout=timeout)
        child.sendline("exit")
        child.expect(pexpect.EOF, timeout=timeout)
        rc = child.wait()
        if rc == 0:
            return [
                Check(
                    "exit-rule",
                    "legacy.ctrl-c",
                    "PASS",
                    "Ctrl-C at the prompt, at a sub-prompt, and during a child redraws; exit quits 0",
                )
            ]
        return [Check("exit-rule", "legacy.ctrl-c", "FAIL", "exit status %s" % rc)]
    except (pexpect.TIMEOUT, pexpect.EOF, OSError) as exc:
        return [
            Check(
                "exit-rule",
                "legacy.ctrl-c",
                "FAIL",
                "%s: %s" % (type(exc).__name__, ((child.before if child else "") or "")[-240:]),
            )
        ]
    finally:
        _stop_child(child)
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def check_legacy_signal_defaults(timeout=10):
    """HUP and TERM still kill the menu. --list does not install the INT trap."""
    skip = _need_pexpect("legacy.hup-term")
    if skip:
        return [
            skip,
            Check("exit-rule", "legacy.list-sigint", "SKIP", skip.detail),
        ]
    checks = []
    env = isolated_env()
    try:
        for sig, item, name in (
            (signal.SIGHUP, "legacy.hup", "HUP"),
            (signal.SIGTERM, "legacy.term", "TERM"),
        ):
            child = None
            try:
                child = _spawn([BASH, MENU], env, timeout=timeout)
                _expect_choose(child, timeout=timeout)
                os.kill(child.pid, sig)
                child.expect(pexpect.EOF, timeout=timeout)
                child.close()
                if child.signalstatus == sig and NOTICE not in (child.before or ""):
                    checks.append(
                        Check("exit-rule", item, "PASS", "%s still ends the menu" % name)
                    )
                else:
                    checks.append(
                        Check(
                            "exit-rule",
                            item,
                            "FAIL",
                            "exit=%s signal=%s" % (child.exitstatus, child.signalstatus),
                        )
                    )
            except (pexpect.TIMEOUT, pexpect.EOF, OSError) as exc:
                checks.append(
                    Check(
                        "exit-rule",
                        item,
                        "FAIL",
                        "%s: %s" % (type(exc).__name__, ((child.before if child else "") or "")[-200:]),
                    )
                )
            finally:
                _stop_child(child)
        child = None
        try:
            child = _spawn([BASH, MENU, "--list"], env, timeout=timeout)
            child.expect("familia menu items", timeout=timeout)
            os.kill(child.pid, signal.SIGINT)
            child.expect(pexpect.EOF, timeout=timeout)
            child.close()
            blob = child.before or ""
            if child.signalstatus == signal.SIGINT and NOTICE not in blob:
                checks.append(
                    Check(
                        "exit-rule",
                        "legacy.list-sigint",
                        "PASS",
                        "--list has no INT trap; SIGINT still kills it",
                    )
                )
            else:
                checks.append(
                    Check(
                        "exit-rule",
                        "legacy.list-sigint",
                        "FAIL",
                        "exit=%s signal=%s notice=%s"
                        % (child.exitstatus, child.signalstatus, NOTICE in blob),
                    )
                )
        except (pexpect.TIMEOUT, pexpect.EOF, OSError) as exc:
            checks.append(
                Check(
                    "exit-rule",
                    "legacy.list-sigint",
                    "FAIL",
                    "%s: %s" % (type(exc).__name__, ((child.before if child else "") or "")[-200:]),
                )
            )
        finally:
            _stop_child(child)
        return checks
    finally:
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def check_home_ctrl_c(timeout=15):
    """Ctrl-C while stub gum is choosing stays in the home menu, then Quit exits 0."""
    if pexpect is None:
        return [Check("exit-rule", "home.ctrl-c", "SKIP", "pexpect is not installed")]
    if not SH:
        return [Check("exit-rule", "home.ctrl-c", "SKIP", "sh is not installed")]
    env = isolated_env(TERM="dumb")
    child = None
    try:
        bin_dir = os.path.join(env["_HARNESS_HOME"], "bin")
        os.makedirs(bin_dir, exist_ok=True)
        mark = os.path.join(bin_dir, "gum-waiting")
        gum = os.path.join(bin_dir, "gum")
        # First choose sleeps so we can deliver ^C. Later chooses print Quit.
        # Kept under the temp HOME (not /sdcard, which is noexec on Termux).
        script = r"""#!__SH__
case "$1" in --version|-v) printf '%s\n' 'gum version 2.0.2'; exit 0 ;; esac
if [ "$1" = choose ] && [ "$2" = --help ]; then
  printf '%s\n' '--header' '--height'; exit 0
fi
if [ "$1" = choose ]; then
  if [ ! -f '__MARK__' ]; then
    touch '__MARK__'
    printf '%s\n' 'GUM-WAITING' >&2
    sleep 30
    exit 0
  fi
  printf '%s\n' Quit
  exit 0
fi
exit 0
""".replace("__SH__", SH).replace("__MARK__", mark)
        with open(gum, "w", encoding="ascii") as fh:
            fh.write(script)
        os.chmod(gum, 0o755)
        env["PATH"] = bin_dir + os.pathsep + env["PATH"]
        child = _spawn([SH, HOME], env, timeout=timeout)
        child.expect("six equal items", timeout=timeout)
        child.expect("GUM-WAITING", timeout=timeout)
        time.sleep(0.3)
        child.sendintr()
        child.expect("interrupted", timeout=timeout)
        # expect() only keeps the text since the previous match, so hold the notice.
        seen = (child.before or "") + (child.after or "")
        child.expect(pexpect.EOF, timeout=timeout)
        rc = child.wait()
        blob = seen + (child.before or "")
        if rc == 0 and "interrupted" in blob:
            return [
                Check(
                    "exit-rule",
                    "home.ctrl-c",
                    "PASS",
                    "Ctrl-C during gum stayed in the home menu; Quit exited 0",
                )
            ]
        return [
            Check(
                "exit-rule",
                "home.ctrl-c",
                "FAIL",
                "rc=%s out=%s" % (rc, blob[-240:]),
            )
        ]
    except (pexpect.TIMEOUT, pexpect.EOF, OSError) as exc:
        return [
            Check(
                "exit-rule",
                "home.ctrl-c",
                "FAIL",
                "%s: %s" % (type(exc).__name__, ((child.before if child else "") or "")[-240:]),
            )
        ]
    finally:
        _stop_child(child)
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)


def summarize(checks):
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    by_kind = {}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
        by_kind.setdefault(c.kind, {"PASS": 0, "FAIL": 0, "SKIP": 0})
        by_kind[c.kind][c.status] = by_kind[c.kind].get(c.status, 0) + 1
    return counts, by_kind


def render_md(checks, tree, extra_notes):
    counts, by_kind = summarize(checks)
    lines = []
    lines.append("# Menu harness report (M5)")
    lines.append("")
    lines.append("Generated by `python3 tests/menu_harness.py`. Headless, `--dry-run`, isolated HOME.")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("- PASS: %s" % counts.get("PASS", 0))
    lines.append("- FAIL: %s" % counts.get("FAIL", 0))
    lines.append("- SKIP: %s" % counts.get("SKIP", 0))
    lines.append("")
    lines.append("## By check kind")
    lines.append("")
    for kind, d in by_kind.items():
        lines.append(
            "- %s: %s pass, %s fail, %s skip"
            % (kind, d.get("PASS", 0), d.get("FAIL", 0), d.get("SKIP", 0))
        )
    lines.append("")
    lines.append("## Catalog (posix-visible)")
    lines.append("")
    n = sum(len(g["items"]) for g in tree)
    lines.append("%s items in %s groups (page size %s)." % (n, len(tree), PAGE_SIZE))
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Status | Kind | Item | Detail |")
    lines.append("|---|---|---|---|")
    for c in checks:
        detail = c.detail.replace("|", "\\|").replace("\n", " ")
        lines.append("| %s | %s | %s | %s |" % (c.status, c.kind, c.item, detail))
    if extra_notes:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for n in extra_notes:
            lines.append("- %s" % n)
    lines.append("")
    return "\n".join(lines)


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--json", dest="json_path", default="")
    parser.add_argument("--md", dest="md_path", default="")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--skip-walk",
        action="store_true",
        help="skip the per-item number walk (faster smoke)",
    )
    args = parser.parse_args(argv)

    items, groups = load_catalog()
    tree = posix_tree(items, groups)
    notes = []
    if pexpect is None:
        notes.append("pexpect was not importable; interactive walks are skipped or limited")

    windows_gap = Check(
        "platform",
        "windows.powershell",
        "SKIP",
        "POSIX pty harness; familia-menu.ps1 and familia-home.ps1 are untested (M7)",
    )
    if os.name == "nt":
        checks = [windows_gap]
        notes.append("Windows menus are not exercised by this harness")
    else:
        checks = []
        checks.extend(check_legacy_exit_rules(timeout=args.timeout))
        checks.extend(check_home_static())
        checks.extend(check_legacy_tty_eof(timeout=args.timeout))
        checks.extend(check_legacy_ctrl_c(timeout=args.timeout))
        checks.extend(check_legacy_signal_defaults(timeout=args.timeout))
    if os.name != "nt" and not BASH:
        checks.append(Check("number-walk", "legacy.complete", "SKIP", "bash is not installed"))
    elif os.name != "nt" and not args.skip_walk and pexpect is not None:
        walked, rc, err = walk_legacy_numbers(tree, timeout=args.timeout)
        checks.extend(walked)
        expected = [it["key"] for g in tree for it in g["items"]]
        seen = {c.item for c in walked if c.kind == "number"}
        missing = [k for k in expected if k not in seen]
        if err:
            notes.append("number walk ended early: rc=%s %s" % (rc, err))
            checks.append(Check("number-walk", "legacy.complete", "FAIL", err or "rc=%s" % rc))
        elif missing:
            checks.append(
                Check(
                    "number-walk",
                    "legacy.complete",
                    "FAIL",
                    "no result for %s item(s): %s" % (len(missing), ", ".join(missing[:12])),
                )
            )
        elif rc == 0:
            checks.append(
                Check(
                    "number-walk",
                    "legacy.complete",
                    "PASS",
                    "walked %s posix-visible items, quit 0" % len(expected),
                )
            )
        else:
            checks.append(
                Check("number-walk", "legacy.complete", "FAIL", "walk finished with rc=%s" % rc)
            )
    elif os.name != "nt":
        checks.append(
            Check(
                "number-walk",
                "legacy.complete",
                "SKIP",
                "skipped (--skip-walk or no pexpect)",
            )
        )
    if os.name != "nt" and pexpect is not None:
        checks.extend(check_legacy_arrows(timeout=args.timeout))
        checks.extend(check_home_stub_walk(timeout=args.timeout))
        checks.extend(check_home_ctrl_c(timeout=args.timeout))
    if os.name != "nt":
        checks.append(windows_gap)

    payload = {
        "root": ROOT,
        "posix_visible": sum(len(g["items"]) for g in tree),
        "groups": len(tree),
        "checks": [c.as_dict() for c in checks],
        "counts": summarize(checks)[0],
        "notes": notes,
        "pexpect": bool(pexpect),
    }
    md = render_md(checks, tree, notes)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
    if args.md_path:
        with open(args.md_path, "w", encoding="utf-8") as fh:
            fh.write(md)
            if not md.endswith("\n"):
                fh.write("\n")
    sys.stdout.write(md)
    if not md.endswith("\n"):
        sys.stdout.write("\n")
    # Exit 0 even when some checks FAIL: expected gaps (no arrows, no home
    # numbers, fallback exec) are the inventory. Pytest asserts the ones
    # that must stay green (legacy numbers, exit rules).
    return 0


if __name__ == "__main__":
    sys.exit(run())
