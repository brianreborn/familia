"""Menu navigation (#733 M4): where-you-are line, &filter, key help, back, and every node reachable."""
import re

import pytest

from test_menu import items, menu, need_ok

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
    assert all(word.lower() in (a + b).lower() or word.lower() in r.stdout.lower() for a, b in rows)
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
