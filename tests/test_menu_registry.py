"""Menu registry (epic #733 M3): six equal categories, every item and graph entry placed once."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import familia_yaml  # noqa: E402
import home_catalog  # noqa: E402
import menu_registry as mr  # noqa: E402

SIX = ("models", "harnesses", "agents", "mcp", "tools", "apps")


def test_six_categories_match_home_areas():
    assert mr.CATEGORY_IDS == SIX
    assert tuple(mr.CATEGORIES) == tuple(home_catalog.AREAS)


def test_registry_is_ascii_and_well_formed():
    raw = open(mr.REGISTRY, "rb").read()
    raw.decode("ascii")
    rows, _empties, problems = mr.load()
    assert not problems, problems
    assert rows


def test_registry_check_is_clean():
    assert mr.check() == []


def test_no_duplicate_ids_or_targets():
    rows, _e, _p = mr.load()
    ids = [r[0] for r in rows]
    targets = [r[3] for r in rows]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    assert len(targets) == len(set(targets)), sorted({t for t in targets if targets.count(t) > 1})


def test_every_menu_item_is_placed():
    rows, _e, _p = mr.load()
    placed = {r[3][5:]: r[1] for r in rows if r[3].startswith("item:")}
    keys = [k for k, _g, _l in mr.menu_items()]
    assert keys
    missing = [k for k in keys if k not in placed]
    assert not missing, missing
    assert set(placed) == set(keys)


def test_every_graph_node_is_placed():
    doc = familia_yaml.load(os.path.join(ROOT, "graph.yaml"))
    rows, _e, _p = mr.load()
    targets = {r[3] for r in rows}
    for section in ("nodes", "agents", "harnesses", "self_improve"):
        for name in (doc.get(section) or {}):
            assert "graph:%s.%s" % (section, name) in targets, (section, name)


def test_each_category_non_empty_or_declared_empty():
    rows, empties, _p = mr.load()
    for cat in SIX:
        n = sum(1 for r in rows if r[1] == cat)
        assert n or cat in empties, cat


def test_home_items_sit_in_their_own_area():
    rows, _e, _p = mr.load()
    for rid, cat, _label, target, _n in rows:
        if target.startswith("item:home.") and target.count(".") >= 2:
            area = target.split(".")[1]
            if area in SIX:
                assert cat == area, (rid, cat)


def test_item_labels_follow_menu_items():
    rows, _e, _p = mr.load()
    label = {r[3][5:]: r[2] for r in rows if r[3].startswith("item:")}
    for key, _group, text in mr.menu_items():
        assert label[key] == mr.ascii_fold(text), key


def test_every_legacy_group_has_a_default_category():
    for key, group, _label in mr.menu_items():
        assert mr.group_category(group, key) in SIX, (key, group)


def _write_tmp(tmp_path, text):
    p = tmp_path / "reg.txt"
    p.write_text(text, encoding="ascii")
    return str(p)


def test_check_reports_missing_duplicate_and_empty(tmp_path):
    items = tmp_path / "items.txt"
    items.write_text("# h\na.one|G|One|cmd|||\na.two|G|Two|cmd|||\n", encoding="utf-8")
    graph = tmp_path / "graph.yaml"
    graph.write_text("version: 2\nnodes:\n  n1:\n    role: coder\n", encoding="utf-8")
    reg = _write_tmp(tmp_path, "a.one|models|One|item:a.one\n"
                               "a.one|tools|One again|item:a.one\n"
                               "empty|apps|nothing yet|-\n")
    problems = mr.check(reg, str(items), str(graph))
    text = "\n".join(problems)
    assert "duplicate id a.one" in text
    assert "menu item a.two has no registry row" in text
    assert "graph entry graph:nodes.n1 has no registry row" in text
    assert "category harnesses has no rows" in text
    assert "category apps" not in text


def test_check_reports_stale_and_bad_rows(tmp_path):
    items = tmp_path / "items.txt"
    items.write_text("a.one|G|One|cmd|||\n", encoding="utf-8")
    graph = tmp_path / "graph.yaml"
    graph.write_text("version: 2\n", encoding="utf-8")
    reg = _write_tmp(tmp_path, "a.one|models|One|item:a.one\n"
                               "gone|models|Gone|item:gone\n"
                               "x|nowhere|X|item:a.one\n"
                               "short|models\n")
    text = "\n".join(mr.check(reg, str(items), str(graph)))
    assert "missing menu item gone" in text
    assert "unknown category 'nowhere'" in text
    assert "want 4 fields" in text


@pytest.mark.parametrize("args", [["--check"], ["--counts"], ["--tree"], ["--tree", "mcp"], ["--help"]])
def test_cli_runs(args):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "menu_registry.py"), *args],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    r.stdout.encode("ascii")


def test_home_catalog_tree_lists_six_areas():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "home_catalog.py"), "--tree"],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    for i, title in enumerate(home_catalog.TITLES, 1):
        assert "%d) %s (" % (i, title) in r.stdout
    assert "node.coder" in r.stdout


def test_tree_rejects_unknown_area():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "menu_registry.py"), "--tree", "bogus"],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
