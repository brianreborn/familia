#!/usr/bin/env python3
"""Menu reachability harness for familia #733 M5 (X Bug Cartographer).

Walks the current home and legacy menus and reports, per item:
  - reachable by number
  - reachable by arrow keys
  - dead-end (process exits or hangs instead of returning to a prompt)
  - the menu returns rather than exiting on errors or invalid input

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
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MENU = os.path.join(ROOT, "familia-menu.sh")
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


def isolated_env(**kw):
    """HOME and PATH never see the developer's gum or caches."""
    home = tempfile.mkdtemp(prefix="familia-m5-harness-")
    os.chmod(home, 0o700)
    for sub in ("cache", "run", ".local"):
        os.makedirs(os.path.join(home, sub), mode=0o700, exist_ok=True)
    env = dict(os.environ)
    for key in (
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
    env["LC_ALL"] = "C.UTF-8"
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


def walk_legacy_numbers(tree, timeout=20):
    """Select every posix-visible item by number under --pipe --dry-run."""
    checks = []
    env = isolated_env()
    argv = ["bash", MENU, "--pipe", "--dry-run"]
    child = _spawn(argv, env, timeout=timeout)
    log = []
    try:
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
    checks = []
    env = isolated_env()
    # explicit q
    r = subprocess.run(
        ["bash", MENU, "--pipe"],
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
        ["bash", MENU, "--pipe"],
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
        ["bash", MENU, "--pipe", "--dry-run"],
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
    shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)
    return checks


def check_legacy_arrows(timeout=15):
    """Arrow keys do not move a highlight on the current legacy menu (M1 gap)."""
    if pexpect is None:
        return [
            Check("arrow", "legacy.top", "SKIP", "pexpect is not installed"),
        ]
    env = isolated_env()
    child = _spawn(["bash", MENU, "--dry-run"], env, timeout=timeout)
    try:
        _expect_choose(child, timeout=timeout)
        child.send("\x1b[B")  # Down
        time.sleep(0.3)
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
    checks = []
    env = isolated_env()
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
    shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)
    return checks


def check_home_stub_walk(timeout=20):
    """Walk every area/verb plus extras with a stub gum; menu must return until Quit."""
    checks = []
    env = isolated_env(TERM="dumb")
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
    script = """#!/bin/sh
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
""".replace("{path}", choice_file)
    with open(gum, "w", encoding="ascii") as fh:
        fh.write(script)
    os.chmod(gum, 0o755)
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]
    # Drive via a pty so familia_home.sh sees a terminal.
    if pexpect is None:
        checks.append(Check("home-walk", "stub-gum", "SKIP", "pexpect is not installed"))
        shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)
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
    shutil.rmtree(env.get("_HARNESS_HOME", ""), ignore_errors=True)
    return checks


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

    checks = []
    checks.extend(check_legacy_exit_rules(timeout=args.timeout))
    checks.extend(check_home_static())
    if not args.skip_walk and pexpect is not None:
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
    else:
        checks.append(
            Check(
                "number-walk",
                "legacy.complete",
                "SKIP",
                "skipped (--skip-walk or no pexpect)",
            )
        )
    if pexpect is not None:
        checks.extend(check_legacy_arrows(timeout=args.timeout))
        checks.extend(check_home_stub_walk(timeout=args.timeout))

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
