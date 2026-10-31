#!/usr/bin/env python3
"""Config documentation generator + checker (docs/config, CFG-* requirement IDs).

The schema in scripts/graph_types.py (TYPES) is the source of truth for graph.yaml
fields. This tool keeps docs/config/graph/<section>.md field tables and the stable
ID registry docs/config/requirement-ids.yaml in step with it.

  python3 scripts/config_docs.py --write   # refresh generated blocks; assign IDs to new fields
  python3 scripts/config_docs.py --check   # exit 1 if any schema field/section is undocumented

IDs are never renumbered: a new field gets the next free number in its section;
a removed field keeps its ID marked `status: removed`. Stdlib + PyYAML only.
"""
import argparse
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import graph_types as GT  # noqa: E402

DOCS = ROOT / "docs" / "config"
GRAPH_DOCS = DOCS / "graph"
IDS = DOCS / "requirement-ids.yaml"
BEGIN, END = "<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->", "<!-- END GENERATED: fields -->"
SCAN = sorted([p for p in (ROOT / "scripts").rglob("*.py")] + [p for p in (ROOT / "scripts").rglob("*.sh")]
              + [p for p in ROOT.glob("*.sh")])


def _schema_line(section):
    for i, line in enumerate((ROOT / "scripts" / "graph_types.py").read_text().splitlines(), 1):
        if re.match(r'\s*"%s": T\(' % re.escape(section), line):
            return i
    return None


def _fmt_spec(f):
    kind = f.kind
    extra = []
    if f.ref: extra.append(f"ref → `{f.ref}`")
    if f.choices: extra.append("one of " + ", ".join(f"`{c}`" for c in sorted(f.choices)))
    if f.min is not None: extra.append(f"min {f.min}")
    if f.nullable: extra.append("nullable")
    return kind, "; ".join(extra) or "—"


_cache = {}


def _consumers(section, field):
    hits = []
    pat = re.compile(r"""["']%s["']|\.%s\b""" % (re.escape(field), re.escape(field)))
    for p in SCAN:
        if p.name == "config_docs.py": continue
        t = _cache.get(p)
        if t is None:
            try: t = _cache[p] = p.read_text(encoding="utf-8", errors="replace")
            except OSError: continue
        if section not in t: continue
        if pat.search(t): hits.append(str(p.relative_to(ROOT)))
    return hits


def load_ids():
    if IDS.exists():
        return yaml.safe_load(IDS.read_text()) or {}
    return {}


def section_prefix(section):
    return "CFG-GRAPH-" + section.upper().replace("_", "")


def assign_ids(ids):
    graph = ids.setdefault("graph", {})
    for section, t in GT.TYPES.items():
        sec = graph.setdefault(section, {})
        used = [int(v["id"].rsplit("-", 1)[1]) for v in sec.values()]
        nxt = max(used, default=0) + 1
        for field in t.fields:
            if field not in sec:
                sec[field] = {"id": f"{section_prefix(section)}-{nxt:03d}", "status": "IMPLEMENTED"}
                nxt += 1
        for field, v in sec.items():
            if field not in t.fields and v.get("status") != "SPEC":
                v["status"] = "removed"
    return ids


def render_block(section, ids):
    t = GT.TYPES[section]
    line = _schema_line(section)
    rows = [BEGIN, "",
            f"Schema: `scripts/graph_types.py:{line}` ({'experimental' if t.experimental else 'stable'}; {t.doc}).",
            "Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.",
            "", "| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |", "|---|---|---|---|---|---|---|"]
    for field, f in t.fields.items():
        rid = ids["graph"][section][field]["id"]
        kind, extra = _fmt_spec(f)
        cons = _consumers(section, field)
        c = ", ".join(f"`{x}`" for x in cons[:6]) + (f" +{len(cons) - 6}" if len(cons) > 6 else "") if cons else "validator only"
        rows.append(f"| {rid} | `{field}` | {'opt' if f.optional else '**req**'} | {kind} | {extra} | IMPLEMENTED | {c} |")
    rows += ["", END]
    return "\n".join(rows)


def section_doc(section):
    return GRAPH_DOCS / f"{section}.md"


def write(ids):
    for section in GT.TYPES:
        p = section_doc(section)
        block = render_block(section, ids)
        if p.exists():
            text = p.read_text()
            if BEGIN in text and END in text:
                text = text.split(BEGIN)[0] + block + text.split(END, 1)[1]
            else:
                text = text.rstrip() + "\n\n## Field reference\n\n" + block + "\n"
        else:
            text = (f"# graph.yaml `{section}:`\n\nPurpose: {GT.TYPES[section].doc}.\n\n"
                    f"## Field reference\n\n{block}\n")
        p.write_text(text)
    IDS.write_text("# Stable requirement IDs for config fields. Never renumber. Managed by scripts/config_docs.py.\n"
                   + yaml.safe_dump(ids, sort_keys=False))


def check(ids):
    errs = []
    for section, t in GT.TYPES.items():
        p = section_doc(section)
        if not p.exists():
            errs.append(f"{section}: missing doc {p.relative_to(ROOT)}"); continue
        text = p.read_text()
        for field in t.fields:
            meta = (ids.get("graph") or {}).get(section, {}).get(field)
            if not meta:
                errs.append(f"{section}.{field}: no requirement ID in {IDS.relative_to(ROOT)}"); continue
            if f"| {meta['id']} | `{field}` |" not in text:
                errs.append(f"{section}.{field}: {meta['id']} not documented in {p.relative_to(ROOT)}")
    seen = {}
    for path in DOCS.rglob("*.md"):
        for rid in set(re.findall(r"\bCFG-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}\b", path.read_text())):
            seen.setdefault(rid, []).append(path)
    registered = {v["id"] for sec in (ids.get("graph") or {}).values() for v in sec.values()}
    registered |= {r for r in (ids.get("other") or {})}
    for rid in seen:
        if rid not in registered:
            errs.append(f"{rid}: used in docs but not registered in {IDS.relative_to(ROOT)} (add under other:)")
    return errs


def register(ids):
    """Register every CFG-* ID used in docs/config under other: with status from its table row."""
    other = ids.setdefault("other", {}) or {}
    ids["other"] = other
    for path in sorted(DOCS.rglob("*.md")):
        for line in path.read_text().splitlines():
            for rid in re.findall(r"\bCFG-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}\b", line):
                if rid in other or any(rid == v["id"] for sec in (ids.get("graph") or {}).values() for v in sec.values()):
                    continue
                st = "SPEC" if re.search(r"\|\s*SPEC\b|^- " + re.escape(rid), line) or "/pentest-policy" in str(path) and "CUR" not in rid else "IMPLEMENTED"
                other[rid] = {"status": st, "doc": str(path.relative_to(ROOT))}
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--register", action="store_true", help="register new CFG-* IDs used in docs/config")
    a = ap.parse_args(argv)
    ids = load_ids()
    if a.write:
        write(assign_ids(ids)); print("docs/config refreshed"); return 0
    if a.register:
        write(register(assign_ids(ids))); print("ids registered"); return 0
    errs = check(ids)
    for e in errs: print("config-docs: " + e, file=sys.stderr)
    print("config-docs: OK" if not errs else f"config-docs: {len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
