"""Pytest wrapper for the #733 M5 menu reachability harness.

Default CI stays green: legacy number reachability and exit-only-on-quit
must pass. Known gaps (no arrow-key loop, no numeric home picker, fallback
exec never returns) are reported by the harness and asserted as FAIL here
so a later M1/M3/M4 fix will flip them; those assertions use xfail until
the owning milestone lands.

Run the full report with:
  python3 tests/menu_harness.py --md PATH --json PATH
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tests"))

import menu_harness as harness  # noqa: E402

try:
    import pexpect
except ImportError:
    pexpect = None

pexpect_needed = pytest.mark.skipif(pexpect is None, reason="pexpect is not installed")


@pytest.fixture(scope="module")
def catalog():
    items, groups = harness.load_catalog()
    tree = harness.posix_tree(items, groups)
    return items, groups, tree


def test_catalog_parse_matches_menu_items(catalog):
    items, groups, tree = catalog
    posix = [it for it in items if it["posix_visible"]]
    assert len(groups) == 19
    assert len(posix) == sum(len(g["items"]) for g in tree)
    # Windows-only rows are hidden on POSIX (empty posix command).
    hidden = [it for it in items if not it["posix_visible"]]
    assert hidden
    assert all(it["windows_visible"] for it in hidden)


def test_legacy_explicit_q_and_eof_and_invalid_input():
    checks = {c.item: c for c in harness.check_legacy_exit_rules()}
    assert checks["legacy.explicit-q"].status == "PASS"
    assert checks["legacy.eof"].status == "PASS"
    assert checks["legacy.invalid-input"].status == "PASS"


def test_home_list_goals_has_six_equal_items():
    checks = {c.item: c for c in harness.check_home_static()}
    assert checks["list-goals"].status == "PASS"


@pexpect_needed
def test_legacy_every_posix_item_reachable_by_number(catalog):
    _items, _groups, tree = catalog
    checks, rc, err = harness.walk_legacy_numbers(tree, timeout=25)
    by_key = {c.item: c for c in checks if c.kind == "number"}
    missing = [it["key"] for g in tree for it in g["items"] if it["key"] not in by_key]
    failed = [c.item for c in checks if c.status == "FAIL"]
    assert err == "", err
    assert rc == 0, "menu did not quit 0 after the walk (rc=%s)" % rc
    assert not missing, "no number result for: %s" % ", ".join(missing[:20])
    assert not failed, "number reachability failed: %s" % ", ".join(failed[:20])
    assert all(c.status == "PASS" for c in by_key.values())


@pexpect_needed
@pytest.mark.xfail(reason="M1: legacy menu has no arrow-key traversal yet (#733)", strict=False)
def test_legacy_arrow_down_moves_highlight():
    checks = harness.check_legacy_arrows()
    assert checks
    assert checks[0].status == "PASS", checks[0].detail


@pytest.mark.xfail(reason="standing rule: numeric entry must keep working on the home menu", strict=False)
def test_home_interactive_accepts_numeric_entry():
    checks = {c.item: c for c in harness.check_home_static()}
    assert checks["home.interactive"].status == "PASS", checks["home.interactive"].detail


@pytest.mark.xfail(reason="#476: fallback_legacy execs away and never returns", strict=False)
def test_home_fallback_returns_to_home_menu():
    checks = {c.item: c for c in harness.check_home_static()}
    assert checks["home.fallback-exec"].status == "PASS", checks["home.fallback-exec"].detail
