"""Shared menu catalog for navigation wiring (familia #733 M6).

The numbered interactive menu (familia-menu.sh) and the forthcoming M1
arrow-key loop must walk the same item sequence in each group. This module
is the registration hook: it parses scripts/menu-items.txt in that order
and computes the group index, item index, page, and page-local number.

It does not read the keyboard or own the input loop (M1 / Race Reviewer).
M1 (scripts/menu_keys.py, PR #743) highlights entries on the current page.
Up/Down wrap on that page; Home/End jump to the first or last entry.
On M1 @ b837f09, PgDn/PgUp emit > / < immediately when the picker was
created with --next / --prev (familia-menu.sh paging via menu-keys.sh);
without those flags they jump to last/first. Highlight index i on a page
selects the same item as numeric choice i.

Menus exit only on an explicit user quit (q / quit / exit), never on an
error, a finished action, invalid input, or a timeout.
"""
from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS_FILE = os.path.join(ROOT, "scripts", "menu-items.txt")
# Must match `page_size=7` in familia-menu.sh.
PAGE_SIZE = 7
MENU_SH = os.path.join(ROOT, "familia-menu.sh")

# Hermes / guardian / phone-Hermes / webapp entries owned by M6. Each must
# stay in menu-items.txt so number, arrow (same sequence), and legacy
# fallback can all reach it.
HERMES_GUARDIAN_KEYS = (
    "setup.android-cockpit",
    "agents.hermes-model",
    "agents.hermes-graph",
    "agents.hermes",
    "agents.hermes-render",
    "agents.hermes-webapp",
    "agents.hermes-desktop",
    "agents.fleet-test",
    "agents.fleet",
    "agents.guardian-launch-test",
    "agents.guardian-start",
    "agents.guardian-weights",
    "agents.pentest-launch-test",
    "agents.pentest-start",
    "adv.hermes-selftest",
    "adv.hermes-escalate",
    "hosts.android",
    "hosts.phones",
    "hosts.watchdog",
    "home.agents.install",
    "home.agents.list",
    "home.agents.start",
    "home.agents.stop",
    "home.agents.status",
)

# Optional M1 module names. M6 does not implement the key loop; tests call
# load_m1_key_loop() and fall back to the catalog contract when none exists.
_M1_CANDIDATES = (
    "menu_keys",
    "menu_keyloop",
    "menu_input",
    "menu_nav_keys",
)

_PLACEHOLDER = re.compile(r"\{([A-Z]+):([^}]*)\}")
_DEFAULT = re.compile(r"\[([^]]+)\]")


def items(path=None):
    """Parse menu-items.txt into dicts. Windows-only rows have an empty cmd."""
    out = []
    for line in open(path or ITEMS_FILE, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("|")
        if len(f) != 7:
            raise ValueError("menu-items.txt row must have 7 fields: %s" % line)
        out.append(dict(zip(("key", "group", "label", "cmd", "gate", "need", "win"), f)))
    return out


def posix_items(path=None):
    """Items the POSIX menu shows (empty posix command = Windows only)."""
    return [it for it in items(path) if it["cmd"]]


def groups(path=None):
    """Group names in catalog order, posix items only."""
    order = []
    for it in posix_items(path):
        if it["group"] not in order:
            order.append(it["group"])
    return order


def group_items(group, path=None):
    """Posix items in one group, in menu-items.txt (and number/arrow) order."""
    return [it for it in posix_items(path) if it["group"] == group]


def locate(key, path=None, page_size=PAGE_SIZE):
    """Return navigation indices for a menu key.

    group_index and page_local are 1-based, matching the numbers printed by
    familia-menu.sh. item_index is 1-based in the group. page is 0-based.
    """
    gs = groups(path)
    found = None
    for it in posix_items(path):
        if it["key"] == key:
            found = it
            break
    if found is None:
        raise KeyError("not a posix menu item: %s" % key)
    grp = found["group"]
    gi = gs.index(grp) + 1
    gitems = group_items(grp, path)
    keys = [it["key"] for it in gitems]
    item_index = keys.index(key) + 1
    page = (item_index - 1) // page_size
    page_local = (item_index - 1) % page_size + 1
    pages = (len(gitems) + page_size - 1) // page_size
    return {
        "key": key,
        "item": found,
        "group": grp,
        "group_index": gi,
        "item_index": item_index,
        "page": page,
        "page_local": page_local,
        "pages": pages,
        "group_size": len(gitems),
    }


def placeholder_values(cmd):
    """Values to satisfy {NAME:prompt [default]} when driving the menu by number."""
    vals = []
    for _name, rest in _PLACEHOLDER.findall(cmd):
        m = _DEFAULT.search(rest)
        vals.append(m.group(1) if m else "x")
    return vals


def numeric_pipe_lines(key, path=None, page_size=PAGE_SIZE):
    """--pipe lines that open the group, page to the item, pick it, then quit.

    Invalid input is not included; the caller may insert a bad choice first
    to assert the menu stays open. After a --pipe run there is no
    'Press Enter' prompt, so the next line is back (b) then quit (q).
    """
    loc = locate(key, path=path, page_size=page_size)
    lines = [str(loc["group_index"])]
    lines.extend([">"] * loc["page"])
    vals = placeholder_values(loc["item"]["cmd"])
    choice = str(loc["page_local"])
    if vals:
        choice = choice + " " + " ".join(vals)
    lines.append(choice)
    lines.append("b")
    lines.append("q")
    return loc, lines


def _menu_keys():
    """Import Race Reviewer's M1 picker (scripts/menu_keys.py)."""
    mod = load_m1_key_loop()
    if mod is None or not hasattr(mod, "Picker"):
        raise RuntimeError("scripts/menu_keys.py (M1 Picker) is required")
    return mod


def move_highlight(index, count, key, page_size=PAGE_SIZE, prev=False, next=False):
    """Move a 0-based highlight the way M1's Picker does.

    Up/Down wrap. Home/End jump to the ends. With next=True, PgDn returns
    '>' immediately (M1 b837f09 / menu-keys.sh always passes --next/--prev);
    without it, PgDn jumps to the last item. With prev=True, PgUp returns
    '<'; otherwise it jumps to the first item. Those strings are page turns
    in familia-menu.sh, not new cursor positions.
    """
    if count <= 0:
        raise ValueError("empty group")
    mk = _menu_keys()
    names = {
        "Up": mk.UP, "Down": mk.DOWN, "Home": mk.HOME, "End": mk.END,
        "PgUp": mk.PGUP, "PgDn": mk.PGDN,
        mk.UP: mk.UP, mk.DOWN: mk.DOWN, mk.HOME: mk.HOME, mk.END: mk.END,
        mk.PGUP: mk.PGUP, mk.PGDN: mk.PGDN,
    }
    if key not in names:
        raise ValueError("unknown key: %s" % key)
    p = mk.Picker(count, cursor=index, prev=prev, next=next)
    out = p.feed(names[key])
    if out in ("<", ">"):
        return out
    return p.cursor


def arrow_path_from_first(key, path=None, page_size=PAGE_SIZE):
    """M1 key sequence from the first item of a group to `key`, then Enter.

    Full pages are skipped with one PgDn each (M1 emits '>' when next=True).
    Down moves within the target page. Reachability by arrows means this
    path selects the same page-local number the numeric path uses.
    """
    mk = _menu_keys()
    loc = locate(key, path=path, page_size=page_size)
    steps = []
    for _p in range(loc["page"]):
        steps.append(mk.PGDN)
    steps.extend([mk.DOWN] * (loc["page_local"] - 1))
    steps.append(mk.ENTER)
    return loc, steps


def feed_arrow_path(loc, steps, page_size=PAGE_SIZE):
    """Replay arrow_path_from_first steps with M1's Picker. Returns the answer."""
    mk = _menu_keys()
    page = 0
    pages = loc["pages"]
    # items on this page
    def page_count(p):
        start = p * page_size
        return min(page_size, loc["group_size"] - start)

    p = mk.Picker(
        page_count(page),
        cursor=0,
        prev=False,
        next=pages > 1,
    )
    out = None
    for key in steps:
        if page >= pages:
            raise RuntimeError("paged past the end reaching %s" % loc["key"])
        out = p.feed(key)
        if out == ">":
            page += 1
            p = mk.Picker(
                page_count(page),
                cursor=0,
                prev=True,
                next=page < pages - 1,
            )
            out = None
            continue
        if out == "<":
            page -= 1
            p = mk.Picker(
                page_count(page),
                cursor=0,
                prev=page > 0,
                next=True,
            )
            out = None
            continue
        if out is not None:
            return out, page, p
    return out, page, p


def menu_sh_page_size(path=None):
    """Read page_size from familia-menu.sh so tests catch catalog drift."""
    text = open(path or MENU_SH, encoding="utf-8").read()
    m = re.search(r"page_size=([0-9]+)", text)
    if not m:
        raise ValueError("familia-menu.sh has no page_size=N")
    return int(m.group(1))


def load_m1_key_loop():
    """Return M1's key-loop module if it has been merged; otherwise None."""
    import sys
    scripts = os.path.join(ROOT, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    for name in _M1_CANDIDATES:
        try:
            mod = __import__(name)
        except ImportError:
            continue
        return mod
    return None
