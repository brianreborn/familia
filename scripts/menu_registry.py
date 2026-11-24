#!/usr/bin/env python3
"""Menu registry: every menu item and graph entry under one of six equal categories.

usage: python3 scripts/menu_registry.py --check
       python3 scripts/menu_registry.py --tree [CATEGORY]
       python3 scripts/menu_registry.py --counts
       python3 scripts/menu_registry.py --write

The registry is scripts/menu-categories.txt, plain ASCII, one row per line:
    id|category|label|target
  category  one of the home areas: models harnesses agents mcp tools apps
            (scripts/home_catalog.py AREAS; Brian's 2026-11-10 rule: harnesses,
            agents, models, MCP servers, tool sets and the app store are equal)
  target    item:KEY            a row in scripts/menu-items.txt (run by the menu)
            home:AREA VERB      a scripts/home_catalog.py action
            graph:SECTION.NAME  an entry in graph.yaml (nodes, agents,
                                harnesses, self_improve, agents.A.mcp.M)
A category with no rows must be declared with a line "empty|CATEGORY|reason|-".

--check   exit 1 if a menu item or graph entry has no row, a row is stale,
          an id repeats, a category is unknown, or a category is empty
          without an "empty" line. Prints each problem.
--tree    print the six categories and their rows (what a menu would show).
--counts  print "CATEGORY N" for each category.
--write   add rows for new menu items and graph entries (category from the
          item's group), drop stale rows, refresh item labels from
          menu-items.txt (ASCII-folded). Hand-set categories are kept.

Key handling and rendering are not here (epic #733: M1 keys, M2 fallback,
M4 UX). A navigator asks this module for categories() and rows(category).

example: python3 scripts/menu_registry.py --check
example: python3 scripts/menu_registry.py --tree agents
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import familia_yaml  # noqa: E402

REGISTRY = os.path.join(ROOT, "scripts", "menu-categories.txt")
ITEMS = os.path.join(ROOT, "scripts", "menu-items.txt")

# Same order and keys as scripts/home_catalog.py AREAS (a test keeps them equal).
CATEGORIES = (
    ("models", "Models"),
    ("harnesses", "Harnesses"),
    ("agents", "Agents"),
    ("mcp", "MCP servers"),
    ("tools", "Tool sets"),
    ("apps", "App store"),
)
CATEGORY_IDS = tuple(c for c, _ in CATEGORIES)

# Default category for a legacy menu-items.txt group (used by --write for new rows).
GROUP_CATEGORY = {
    "Set up": "apps",
    "Skills": "tools",
    "Reach tools (Agent-Reach)": "tools",
    "Models": "models",
    "Graphs": "models",
    "Agents (hermes)": "agents",
    "App catalog": "apps",
    "Self-improving harness (Harness2)": "harnesses",
    "Test & benchmark": "harnesses",
    "Hosts": "models",
    "Advanced: models & graph": "models",
    "Advanced: agents": "agents",
    "Advanced: hosts & benchmarks": "models",
    "MCP servers": "mcp",
    "Tool sets": "tools",
    "App store": "apps",
    "Front door": "models",
    "Help": "apps",
}
# Groups whose name starts with one of these map like the full name.
GROUP_PREFIX = (("\u25c6 Proving grounds", "harnesses"),)
# Graph sections and the category their entries belong to.
GRAPH_SECTIONS = (
    ("nodes", "models"),
    ("agents", "agents"),
    ("harnesses", "harnesses"),
    ("self_improve", "harnesses"),
)


def ascii_fold(text):
    out = []
    for ch in str(text):
        o = ord(ch)
        out.append(ch if 32 <= o < 127 else "?")
    return "".join(out).replace("|", "/").strip()


def group_category(group, key=""):
    if key.startswith("home."):
        area = key.split(".")[1] if key.count(".") >= 1 else ""
        if area in CATEGORY_IDS:
            return area
    if group in GROUP_CATEGORY:
        return GROUP_CATEGORY[group]
    for prefix, cat in GROUP_PREFIX:
        if group.startswith(prefix):
            return cat
    return ""


def menu_items(path=ITEMS):
    """[(key, group, label)] from menu-items.txt, in file order."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            f = line.rstrip("\n").split("|")
            if len(f) < 3:
                continue
            out.append((f[0], f[1], f[2]))
    return out


def _section(doc, name):
    block = doc.get(name) if isinstance(doc, dict) else None
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if isinstance(k, str)}


def graph_entries(path=None):
    """[(id, category, label, target)] for every graph entry a menu must reach."""
    path = path or os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")
    doc = familia_yaml.load(path)
    out = []
    for name, cat in GRAPH_SECTIONS:
        for entry, spec in _section(doc, name).items():
            spec = spec if isinstance(spec, dict) else {}
            if name == "nodes":
                label = "node %s (%s on %s)" % (entry, spec.get("role") or "-", spec.get("host") or "-")
                rid = "node.%s" % entry
            elif name == "agents":
                label = "agent %s" % entry
                rid = "agent.%s" % entry
            elif name == "harnesses":
                label = "harness %s (%s)" % (entry, spec.get("kind") or "-")
                rid = "harness.%s" % entry
            else:
                label = "self-improve %s (%s)" % (entry, spec.get("mode") or "-")
                rid = "self-improve.%s" % entry
            out.append((rid, cat, ascii_fold(label), "graph:%s.%s" % (name, entry)))
    for agent, spec in _section(doc, "agents").items():
        mcp = spec.get("mcp") if isinstance(spec, dict) else None
        if isinstance(mcp, dict):
            for server in mcp:
                if isinstance(server, str):
                    out.append(("mcp.%s.%s" % (agent, server), "mcp",
                                ascii_fold("MCP server %s for %s" % (server, agent)),
                                "graph:agents.%s.mcp.%s" % (agent, server)))
    return out


def load(path=REGISTRY):
    """(rows, empties, problems). rows: [(id, category, label, target, lineno)]."""
    rows, empties, problems = [], {}, []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            raw = line.rstrip("\n")
            if raw.startswith("#") or not raw.strip():
                continue
            try:
                raw.encode("ascii")
            except UnicodeEncodeError:
                problems.append("line %d: not ASCII" % n)
            f = raw.split("|")
            if len(f) != 4:
                problems.append("line %d: want 4 fields id|category|label|target, got %d" % (n, len(f)))
                continue
            rid, cat, label, target = (x.strip() for x in f)
            if cat not in CATEGORY_IDS:
                problems.append("line %d: unknown category %r" % (n, cat))
            if rid == "empty":
                empties[cat] = label
                continue
            if not rid or not label or not target:
                problems.append("line %d: empty id, label or target" % n)
            rows.append((rid, cat, label, target, n))
    return rows, empties, problems


def categories():
    """[(category id, title)] in menu order."""
    return list(CATEGORIES)


def rows(category, path=REGISTRY):
    """[(id, label, target)] for one category, in registry order."""
    found, _, _ = load(path)
    return [(r[0], r[2], r[3]) for r in found if r[1] == category]


def check(path=REGISTRY, items_path=ITEMS, graph=None):
    found, empties, problems = load(path)
    seen = {}
    for rid, cat, _label, target, n in found:
        if rid in seen:
            problems.append("line %d: duplicate id %s (first on line %d)" % (n, rid, seen[rid]))
        else:
            seen[rid] = n
    targets = {r[3]: r for r in found}
    keys = [k for k, _g, _l in menu_items(items_path)]
    for key in keys:
        if "item:%s" % key not in targets:
            problems.append("menu item %s has no registry row" % key)
    for rid, _cat, _label, target in graph_entries(graph):
        if target not in targets:
            problems.append("graph entry %s has no registry row (want id %s)" % (target, rid))
    keyset = set(keys)
    live_graph = {t for _i, _c, _l, t in graph_entries(graph)}
    for rid, _cat, _label, target, n in found:
        if target.startswith("item:") and target[5:] not in keyset:
            problems.append("line %d: %s points at missing menu item %s" % (n, rid, target[5:]))
        elif target.startswith("graph:") and target not in live_graph:
            problems.append("line %d: %s points at missing graph entry %s" % (n, rid, target[6:]))
        elif target.startswith("home:"):
            parts = target[5:].split()
            if len(parts) != 2 or parts[0] not in CATEGORY_IDS:
                problems.append("line %d: bad home target %s" % (n, target))
        elif not target.startswith(("item:", "graph:", "home:")):
            problems.append("line %d: unknown target kind %s" % (n, target))
    for cat in CATEGORY_IDS:
        if not any(r[1] == cat for r in found) and cat not in empties:
            problems.append("category %s has no rows and no 'empty|%s|reason|-' line" % (cat, cat))
    return problems


HEADER = """# familia menu registry (epic #733 M3): six equal top-level categories.
# id|category|label|target   (plain ASCII; see scripts/menu_registry.py --help)
# Categories, in menu order: models harnesses agents mcp tools apps
# Every scripts/menu-items.txt key and every graph.yaml node, agent, harness,
# self_improve entry and agent MCP server has exactly one row here.
# tests/test_menu_registry.py fails when one is missing, stale or repeated.
# New rows: python3 scripts/menu_registry.py --write, then fix the category by hand.
"""


def write(path=REGISTRY, items_path=ITEMS, graph=None):
    old = {}
    empties = {}
    if os.path.exists(path):
        found, empties, _ = load(path)
        old = {r[3]: r for r in found}
    out = [HEADER.rstrip("\n")]
    body = []
    for key, group, label in menu_items(items_path):
        target = "item:%s" % key
        cat = old[target][1] if target in old else group_category(group, key)
        body.append((key, cat, ascii_fold(label), target))
    for rid, cat, label, target in graph_entries(graph):
        if target in old:
            cat = old[target][1]
        body.append((rid, cat, label, target))
    for rid, _c, label, target, _n in old.values():
        if target.startswith("home:"):
            body.append((rid, old[target][1], label, target))
    for cat, _title in CATEGORIES:
        out.append("")
        out.append("# %s" % cat)
        here = [b for b in body if b[1] == cat]
        if not here and cat in empties:
            out.append("empty|%s|%s|-" % (cat, empties[cat]))
        for b in here:
            out.append("|".join(b))
    unplaced = [b for b in body if b[1] not in CATEGORY_IDS]
    if unplaced:
        out.append("")
        out.append("# UNPLACED: set a category for each row below")
        for b in unplaced:
            out.append("|".join(b))
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    return len(body), len(unplaced)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd = argv[0]
    if cmd == "--check":
        problems = check()
        for p in problems:
            print("menu-registry: %s" % p)
        if problems:
            return 1
        print("menu-registry: ok")
        return 0
    if cmd == "--counts":
        found, empties, _ = load()
        for cat, _title in CATEGORIES:
            n = sum(1 for r in found if r[1] == cat)
            print("%s %d%s" % (cat, n, " (empty: %s)" % empties[cat] if cat in empties and not n else ""))
        return 0
    if cmd == "--tree":
        want = argv[1] if len(argv) > 1 else None
        if want is not None and want not in CATEGORY_IDS:
            print("menu-registry: unknown category %s (want one of %s)" % (want, " ".join(CATEGORY_IDS)))
            return 2
        for i, (cat, title) in enumerate(CATEGORIES, 1):
            if want and cat != want:
                continue
            here = rows(cat)
            print("%d) %s (%d)" % (i, title, len(here)))
            for rid, label, target in here:
                print("    %-30s %s  [%s]" % (rid, label, target))
        return 0
    if cmd == "--write":
        total, unplaced = write()
        print("menu-registry: wrote %d rows, %d unplaced" % (total, unplaced))
        return 1 if unplaced else 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
