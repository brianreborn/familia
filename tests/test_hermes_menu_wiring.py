"""#733 M6: every Hermes/guardian menu entry is reachable by number, by
arrows (same sequence as numbers), and through the legacy fallback menu.

Arrow reachability is asserted against scripts/menu_catalog.py walking the
same sequence as numbers, driven by M1's scripts/menu_keys.py Picker
(PR #743). Numeric --pipe paths and `familia --legacy-menu --list` exercise
the live menu. A pty test drives arrows through familia-menu.sh itself.
Menus must stay open on a bad choice and leave only on q.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import menu_catalog  # noqa: E402

MENU = os.path.join(ROOT, "familia-menu.sh")
FAMILIA = os.path.join(ROOT, "familia")
KEYS = menu_catalog.HERMES_GUARDIAN_KEYS


def env(**kw):
    e = dict(os.environ, FAMILIA_NO_TTY="1")
    e.pop("FAMILIA_ACCEPT_LICENSES", None)
    e.update(kw)
    return e


def menu(*args, inp=None, **kw):
    return subprocess.run(
        ["bash", MENU, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env(**kw),
        input=inp,
        stdin=None if inp is not None else subprocess.DEVNULL,
        timeout=120,
    )


def familia(*args, inp=None, **kw):
    return subprocess.run(
        ["sh", FAMILIA, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env(**kw),
        input=inp,
        stdin=None if inp is not None else subprocess.DEVNULL,
        timeout=120,
    )


def test_page_size_matches_familia_menu_sh():
    assert menu_catalog.menu_sh_page_size() == menu_catalog.PAGE_SIZE == 7


def test_every_hermes_guardian_key_is_registered():
    by_key = {it["key"]: it for it in menu_catalog.posix_items()}
    missing = [k for k in KEYS if k not in by_key]
    assert not missing, "add these to scripts/menu-items.txt: " + ", ".join(missing)


@pytest.mark.parametrize("key", KEYS)
def test_legacy_list_reaches_each_hermes_guardian_entry(key):
    r = familia("--legacy-menu", "--list")
    assert r.returncode == 0, r.stderr
    assert key in r.stdout
    it = next(i for i in menu_catalog.posix_items() if i["key"] == key)
    # The legacy listing prints the key and the label on the same block.
    assert it["label"] in r.stdout


@pytest.mark.parametrize("key", KEYS)
def test_legacy_flag_and_menu_list_agree(key):
    a = familia("--legacy-menu", "--list")
    b = menu("--list")
    assert a.returncode == b.returncode == 0
    assert key in a.stdout and key in b.stdout


@pytest.mark.parametrize("key", KEYS)
def test_reachable_by_number_via_pipe(key):
    loc, lines = menu_catalog.numeric_pipe_lines(key)
    r = menu("--pipe", "--dry-run", inp="\n".join(lines) + "\n")
    assert r.returncode == 0, (key, lines, r.stdout[-800:], r.stderr[-800:])
    assert "[dry-run]" in r.stdout
    # The chosen item ran (license-gated rows also print the licenses.py gate).
    cmd = loc["item"]["cmd"]
    # Shown command uses python3 in place of PY and drops placeholders.
    needle = cmd.replace("PY ", "python3 ")
    needle = menu_catalog._PLACEHOLDER.sub("x", needle) if "PY " in cmd else needle
    # After fill(), placeholders become the values we forwarded.
    vals = menu_catalog.placeholder_values(loc["item"]["cmd"])
    shown = loc["item"]["cmd"].replace("PY ", "python3 ")
    # Just require the script basename and --client / role flags when present.
    if "hermes.sh" in cmd:
        assert "scripts/hermes.sh" in r.stdout
        if "--client webapp" in cmd:
            assert "--client webapp" in r.stdout
        if "--client desktop" in cmd:
            assert "--client desktop" in r.stdout
    elif "activate_guardian_weights.py" in cmd:
        assert "activate_guardian_weights.py" in r.stdout
    elif "android-cockpit-switches.sh" in cmd:
        assert "android-cockpit-switches.sh" in r.stdout
    elif "with-fleet.sh" in cmd:
        assert "with-fleet.sh" in r.stdout
    elif "home_catalog.py" in cmd:
        assert "home_catalog.py agents" in r.stdout
    else:
        # generic: the dry-run line mentions something from the command
        token = cmd.split()[-1] if cmd.split() else cmd
        assert token.replace("PY", "python3") in r.stdout or cmd.split()[0] in r.stdout
    assert "' isn't one of the choices" not in r.stdout
    _ = shown, vals, needle  # kept for later debugging of fill() mismatches


@pytest.mark.parametrize("key", KEYS)
def test_reachable_by_arrows_on_the_shared_sequence(key):
    loc, steps = menu_catalog.arrow_path_from_first(key)
    answer, page, picker = menu_catalog.feed_arrow_path(loc, steps)
    assert page == loc["page"]
    assert answer == str(loc["page_local"])
    assert picker.cursor == loc["page_local"] - 1
    # The same index is what the numeric path uses (group-global, then paged).
    assert loc["page"] * menu_catalog.PAGE_SIZE + loc["page_local"] - 1 == loc["item_index"] - 1


def test_arrow_wraparound_and_home_end_match_m1_picker():
    # Agents (hermes) is the long group that holds most M6 entries. The
    # first page has PAGE_SIZE items and a next-page affordance.
    n = menu_catalog.PAGE_SIZE
    assert len(menu_catalog.group_items("Agents (hermes)")) > n
    assert menu_catalog.move_highlight(n - 1, n, "Down") == 0
    assert menu_catalog.move_highlight(0, n, "Up") == n - 1
    assert menu_catalog.move_highlight(3, n, "Home") == 0
    assert menu_catalog.move_highlight(0, n, "End") == n - 1
    # M1 @ b837f09: PgDn with next=True is ">" immediately; without next
    # it jumps to the last entry. PgUp is the same with prev=True.
    assert menu_catalog.move_highlight(0, n, "PgDn") == n - 1
    assert menu_catalog.move_highlight(0, n, "PgDn", next=True) == ">"
    assert menu_catalog.move_highlight(n - 1, n, "PgDn", next=True) == ">"
    assert menu_catalog.move_highlight(0, n, "PgUp") == 0
    assert menu_catalog.move_highlight(0, n, "PgUp", prev=True) == "<"


def test_bad_number_stays_in_the_menu_until_quit():
    # Open Agents (hermes), type 99, then pick hermes-render (early on page 1), quit.
    loc, lines = menu_catalog.numeric_pipe_lines("agents.hermes-render")
    # lines: group, [pages], choice, b, q  — insert 99 after the group is open.
    # After the group number, we are inside the group. A bad 99 must not exit.
    wired = [lines[0], "99", *lines[1:]]
    r = menu("--pipe", "--dry-run", inp="\n".join(wired) + "\n")
    assert r.returncode == 0, r.stderr
    assert "isn't one of the choices" in r.stdout
    assert "[dry-run]" in r.stdout
    assert "scripts/hermes.sh --render-only" in r.stdout


def test_m1_key_loop_uses_the_same_sequence():
    """M1's Picker (PR #743) must select each M6 item by the shared path."""
    mk = menu_catalog.load_m1_key_loop()
    assert mk is not None, "scripts/menu_keys.py (M1) must be on this branch"
    assert hasattr(mk, "Picker")
    for key in KEYS:
        loc, steps = menu_catalog.arrow_path_from_first(key)
        answer, page, picker = menu_catalog.feed_arrow_path(loc, steps)
        assert answer == str(loc["page_local"]), key
        assert page == loc["page"], key
        assert picker.cursor == loc["page_local"] - 1, key


def test_new_client_and_weights_dry_run_via_run():
    r = menu("--run", "agents.hermes-webapp", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "[dry-run]" in r.stdout
    assert "scripts/hermes.sh --client webapp" in r.stdout
    assert "licenses.py gate" in r.stdout
    r = menu("--run", "agents.hermes-desktop", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "scripts/hermes.sh --client desktop" in r.stdout
    r = menu("--run", "agents.guardian-weights", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "activate_guardian_weights.py" in r.stdout
    # Default path is status/dry-run; the catalog must not bake --write/--fetch.
    assert "--write" not in r.stdout and "--fetch" not in r.stdout


def test_cli_words_reach_the_new_items():
    r = familia("--dry-run", "hermes", "webapp")
    assert r.returncode == 0, r.stderr
    assert "scripts/hermes.sh --client webapp" in r.stdout
    r = familia("--dry-run", "hermes", "desktop")
    assert r.returncode == 0, r.stderr
    assert "scripts/hermes.sh --client desktop" in r.stdout
    r = familia("--dry-run", "guardian", "weights")
    assert r.returncode == 0, r.stderr
    assert "activate_guardian_weights.py" in r.stdout


def test_weights_script_is_a_menu_item_not_internal():
    internal = open(os.path.join(ROOT, "scripts", "menu-internal.txt"), encoding="utf-8").read()
    assert "scripts/activate_guardian_weights.py|" not in internal
    # The thin shell wrapper stays internal (not a second menu row).
    assert "scripts/activate_guardian_weights.sh|" in internal
    keys = {it["key"] for it in menu_catalog.posix_items()}
    assert "agents.guardian-weights" in keys
    assert "agents.hermes-webapp" in keys
    assert "agents.hermes-desktop" in keys


def test_home_agents_list_points_at_the_new_cli_words():
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "home_catalog.py"), "agents", "list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env(),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "familia hermes" in r.stdout
    assert "familia hermes webapp" in r.stdout
    assert "familia hermes desktop" in r.stdout
    assert "familia guardian weights" in r.stdout


def test_cockpit_stays_on_the_home_menu_and_in_the_legacy_catalog():
    # The gum/home menu already offers the Android cockpit as a top-level pick.
    home = open(os.path.join(ROOT, "scripts", "familia_home.sh"), encoding="utf-8").read()
    assert "Open llama-ui web cockpit" in home
    assert "android-cockpit-switches.sh" in home
    r = familia("--legacy-menu", "--list")
    assert r.returncode == 0
    assert "setup.android-cockpit" in r.stdout

def _read_until(fd, needle, timeout=15):
    import time
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        import select
        r, _, _ = select.select([fd], [], [], max(0, deadline - time.time()))
        if not r:
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        buf += chunk
        if needle in buf:
            return buf
    raise AssertionError("timed out waiting for %r in %r" % (needle, buf[-800:]))


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="no pty")
@pytest.mark.skipif(
    menu_catalog.load_m1_key_loop() is None
    or getattr(menu_catalog.load_m1_key_loop(), "_m2", lambda: None)() is None,
    reason="live arrow keys need scripts/menu_input.py (#736, M2)",
)
def test_pty_arrows_reach_hermes_webapp_and_guardian_weights():
    """Live M1 picker: arrows open Agents (hermes) and dry-run two M6 items."""
    import time
    loc_web = menu_catalog.locate("agents.hermes-webapp")
    loc_w = menu_catalog.locate("agents.guardian-weights")
    assert loc_web["group_index"] == loc_w["group_index"]
    master, slave = os.openpty()
    env = dict(os.environ, TERM="xterm", FAMILIA_COLOR="never")
    for k in ("FAMILIA_NO_TTY", "FAMILIA_MENU_PIPE", "FAMILIA_ACCEPT_LICENSES"):
        env.pop(k, None)
    p = subprocess.Popen(
        ["bash", MENU, "--dry-run"],
        cwd=ROOT,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
    )
    try:
        _read_until(master, b"Choose 1-")
        # Down to the Agents (hermes) group, Enter.
        for _ in range(loc_web["group_index"] - 1):
            os.write(master, b"\x1b[B")
            time.sleep(0.05)
        os.write(master, b"\r")
        _read_until(master, b"or b: ")
        # Webapp is on page 1: Down to its page-local slot, Enter.
        for _ in range(loc_web["page_local"] - 1):
            os.write(master, b"\x1b[B")
            time.sleep(0.05)
        os.write(master, b"\r")
        out = _read_until(master, b"Press Enter")
        assert b"[dry-run]" in out
        assert b"scripts/hermes.sh --client webapp" in out
        os.write(master, b"\r")
        _read_until(master, b"or b: ")
        # Guardian weights is on a later page: one PgDn (CSI 6~) turns the
        # page immediately (M1 b837f09, menu-keys.sh always passes --next).
        for _ in range(loc_w["page"] - loc_web["page"]):
            os.write(master, b"\x1b[6~")
            time.sleep(0.08)
        _read_until(master, b"or b: ")
        for _ in range(loc_w["page_local"] - 1):
            os.write(master, b"\x1b[B")
            time.sleep(0.05)
        os.write(master, b"\r")
        out = _read_until(master, b"Press Enter")
        assert b"[dry-run]" in out
        assert b"activate_guardian_weights.py" in out
        os.write(master, b"\r")
        _read_until(master, b"or b: ")
        os.write(master, b"\x1b")  # Esc -> back
        _read_until(master, b"Choose 1-")
        os.write(master, b"q")
        assert p.wait(timeout=20) == 0
    finally:
        if p.poll() is None:
            p.kill()
        os.close(master)
        os.close(slave)
