"""Menu navigation (#733 M4): where-you-are line, &filter, key help, back, and every node reachable."""
import os
import pty
import re
import select
import shutil
import subprocess
import time

import pytest

from test_menu import MENU as MENU_PATH, env, items, menu, need_ok

GROUPS = list(dict.fromkeys(i["group"] for i in items() if i["cmd"]))
PAGE = 7


def test_breadcrumb_shows_where_you_are_at_every_level():
    hosts = GROUPS.index("Hosts") + 1
    r = menu("--pipe", "--dry-run", inp=f"{hosts}\n>\n/skills\nb\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "[familia]\nfamilia: what do you want to do?" in r.stdout
    assert "[familia > Hosts > page 1 of 2]" in r.stdout
    assert "[familia > Hosts > page 2 of 2]" in r.stdout
    assert "[familia > search 'skills']" in r.stdout


def test_every_group_has_a_description():
    r = menu("--pipe", inp="q\n")
    assert r.returncode == 0, r.stderr
    top = r.stdout.split("[familia]", 1)[1]
    for n, g in enumerate(GROUPS, 1):
        line = re.search(rf"^ *{n}\) .*$", top, re.M).group(0)
        assert g in line and line.split(g, 1)[1].strip(), f"group '{g}' has no description in group_desc"


KEYS = 'echo LOADED-KEYS >&2\nmenu_key_read() { printf "%s" "$1" >&2; IFS= read -r "$2"; }\n'


def checkout(tmp_path, keys=KEYS):
    """A copy of the checkout (no .git/tests/docs) with modes the loader trusts."""
    root = tmp_path / "co"
    shutil.copytree(os.path.dirname(MENU_PATH), root, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "tests", "docs", "__pycache__"))
    os.chmod(root, 0o755)
    os.chmod(root / "scripts", 0o755)
    if keys is not None:
        (root / "scripts" / "menu-keys.sh").write_text(keys)
        os.chmod(root / "scripts" / "menu-keys.sh", 0o644)
    return root


def tty_menu(root, lines, *args, **kw):
    """Run the menu on a pty, answering each prompt with the next line. Returns (rc, text)."""
    m, s = pty.openpty()
    kw.setdefault("TERM", "xterm")
    e = env(**kw)
    e.pop("FAMILIA_NO_TTY", None)
    p = subprocess.Popen(["bash", str(root / "familia-menu.sh"), *args], stdin=s, stdout=s, stderr=s,
                         env=e, cwd=str(root), close_fds=True)
    os.close(s)
    out, sent, deadline = b"", 0, time.time() + 60
    while time.time() < deadline:
        r, _, _ = select.select([m], [], [], 0.2)
        if r:
            try:
                d = os.read(m, 65536)
            except OSError:
                d = b""
            if not d:
                break
            out += d
        if sent < len(lines) and out.count(b"Choose") > sent:
            os.write(m, (lines[sent] + "\n").encode())
            sent += 1
        if p.poll() is not None and not r:
            break
    p.wait(timeout=10)
    os.close(m)
    return p.returncode, out.decode(errors="replace")


def test_key_reader_is_not_loaded_for_pipes_or_dumb_terminals(tmp_path):
    root = checkout(tmp_path)
    r = subprocess.run(["bash", str(root / "familia-menu.sh"), "--pipe"], input="q\n",
                       capture_output=True, text=True, timeout=60, env=env())
    assert r.returncode == 0, r.stderr
    assert "LOADED-KEYS" not in r.stdout + r.stderr
    rc, out = tty_menu(root, ["q"], TERM="dumb")
    assert rc == 0 and "LOADED-KEYS" not in out


def test_key_reader_loads_once_on_a_terminal(tmp_path):
    rc, out = tty_menu(checkout(tmp_path), ["1", "b", "2", "b", "q"])
    assert rc == 0, out[-800:]
    assert out.count("LOADED-KEYS") == 1
    assert "[familia > Skills" in out


def test_name_value_cannot_rearm_or_redirect_the_key_reader(tmp_path):
    root = checkout(tmp_path, keys=None)  # no reader in the real checkout
    evil = tmp_path / "evil"
    (evil / "scripts").mkdir(parents=True)
    (evil / "scripts" / "menu-keys.sh").write_text("echo EVIL-KEYS >&2\n")
    hit = f"ROOT={evil} KEYS_FILE={evil}/scripts/menu-keys.sh KEYS_TRIED= KEYS_OK=yes"
    rc, out = tty_menu(root, [hit + " 1", "b", "q"], f"ROOT={evil}", "KEYS_TRIED=", f"ITEMS_FILE={evil}/x")
    assert rc == 0, out[-800:]
    assert "EVIL-KEYS" not in out
    for n in ("ROOT", "KEYS_FILE", "KEYS_TRIED", "KEYS_OK", "ITEMS_FILE"):
        assert f"{n} is used by the menu itself; not setting it" in out, n
    assert "[familia > Set up" in out  # the menu kept working on its own checkout


def test_name_value_still_reaches_items():
    r = menu("--pipe", "--dry-run", inp="2\nPIPE=0 DRY=0 FAMILIA_X=1 1\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "PIPE is used by the menu itself" in r.stderr and "DRY is used by the menu itself" in r.stderr
    assert "[dry-run]" in r.stdout  # DRY=0 did not turn dry-run off


@pytest.mark.parametrize("case", ["file-0666", "file-0664", "scripts-0777", "checkout-0775",
                                  "file-symlink", "scripts-symlink"])
def test_untrusted_key_reader_is_refused(tmp_path, case):
    root = checkout(tmp_path)
    f = root / "scripts" / "menu-keys.sh"
    if case == "file-0666":
        os.chmod(f, 0o666)
    elif case == "file-0664":
        os.chmod(f, 0o664)
    elif case == "scripts-0777":
        os.chmod(root / "scripts", 0o777)
    elif case == "checkout-0775":
        os.chmod(root, 0o775)
    elif case == "file-symlink":
        real = tmp_path / "keys-elsewhere.sh"
        real.write_text(KEYS)
        f.unlink()
        f.symlink_to(real)
    elif case == "scripts-symlink":
        moved = tmp_path / "scripts-real"
        shutil.move(str(root / "scripts"), moved)
        (root / "scripts").symlink_to(moved)
    rc, out = tty_menu(root, ["q"])
    assert rc == 0, out[-800:]
    assert "LOADED-KEYS" not in out, case


def test_same_key_hints_in_every_group():
    r = menu("--pipe", "--dry-run", inp="1\nb\n2\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("  b) Back   q) Quit   h) Help   &word filter this menu") == 2
    assert "  q) Quit   h) Help   /word search every group" in r.stdout


def test_help_key_at_top_group_and_search():
    r = menu("--pipe", "--dry-run", inp="h\n1\nh\n/skills\nh\nb\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("Keys (type one, then Enter):") == 3


def test_back_at_top_stays_and_q_is_the_only_exit():
    r = menu("--pipe", "--dry-run", inp="b\nback\nq\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("Already at the top menu; q quits.") == 2


def test_filter_narrows_the_group_and_ampersand_clears_it():
    g, word = "Hosts", "PHONE"  # case is ignored
    mine = [i for i in items() if i["group"] == g and i["cmd"]]
    r = menu("--pipe", "--dry-run", inp=f"{GROUPS.index(g) + 1}\n&{word}\n&\n&zz-no-such\nb\nq\n")
    assert r.returncode == 0, r.stderr
    screens = r.stdout.split(f"[familia > {g}")
    filtered, cleared = screens[2], screens[3]
    m = re.search(rf"Filter: '{word}' \((\d+) of {len(mine)} items", filtered)
    assert m and 0 < int(m.group(1)) < len(mine), filtered
    rows = re.findall(r"^  \d+\) (.*)\n       runs: (.*)$", filtered.split("b) Back")[0], re.M)
    assert len(rows) == min(int(m.group(1)), PAGE)
    for label, _cmd in rows:  # each row is an item of this group whose key, label or command has the word
        it = next(i for i in mine if i["label"] == label)
        assert word.lower() in (it["key"] + " " + it["label"] + " " + _cmd).lower(), label
    assert "Filter:" not in cleared and f"page 1 of {-(-len(mine) // PAGE)}" in cleared
    assert f"No item in {g} matches 'zz-no-such'" in r.stdout


def test_filtered_pick_runs_the_matching_item():
    r = menu("--pipe", "--dry-run", inp=f"{GROUPS.index('Skills') + 1}\n&skills.py list\n1\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "[dry-run] python3 scripts/skills.py list" in r.stdout


@pytest.mark.parametrize("group", GROUPS)
def test_every_node_renders_and_is_reachable_and_back(group):
    mine = [i for i in items() if i["group"] == group and i["cmd"]]
    pages = -(-len(mine) // PAGE)
    inp, runs = [str(GROUPS.index(group) + 1)], 0
    for p in range(pages):
        for n, it in enumerate(mine[p * PAGE:(p + 1) * PAGE], 1):
            inp.append(str(n))
            if need_ok(it["need"]):
                inp += ["x"] * len(re.findall(r"\{[A-Z]+:", it["cmd"]))
                runs += 1
        if p < pages - 1:
            inp.append(">")
    inp += ["b", "q"]
    r = menu("--pipe", "--dry-run", inp="\n".join(inp) + "\n")
    assert r.returncode == 0, (group, r.stderr[-800:])
    for it in mine:
        assert it["label"] in r.stdout, (group, it["key"])
    assert r.stdout.count("[dry-run] ") - r.stdout.count("[dry-run] would first run") == runs, group
    assert f"[familia > {group}" in r.stdout
    assert "[familia]" in r.stdout.rsplit(f"[familia > {group}", 1)[1]  # b went back to the top
