#!/usr/bin/env python3
"""Fail if a Markdown doc makes a host-hardware claim without linking the
canonical inventory (docs/HARDWARE-INVENTORY.md). See LESSONS-LEARNED L-hostloc.

A "claim" is a line naming a fleet host AND a hardware term. Opt out of a
historical file with the marker <!-- hw-inventory: historical -->.
Usage: python3 scripts/check_hw_claims.py [paths...]  (default: docs/ + *.md)
"""
import pathlib, re, sys

HOSTS = re.compile(r"\b(angel|uriel|qodesh|shalom|godslove|miryam|centos10-bigram)\b", re.I)
HW = re.compile(r"\b(G84|8600 ?GT|athlon|i5-\d{4}|VT-d|AMD-Vi|IOMMU|DMAR|Vertex ?2)\b", re.I)
LINK = "HARDWARE-INVENTORY.md"
OPT_OUT = "hw-inventory: historical"


def main(argv):
    root = pathlib.Path(__file__).resolve().parent.parent
    paths = [pathlib.Path(p) for p in argv] or \
        list(root.glob("*.md")) + list((root / "docs").rglob("*.md"))
    bad = []
    for p in paths:
        if p.name == LINK:
            continue
        text = p.read_text(errors="replace")
        if LINK in text or OPT_OUT in text:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if HOSTS.search(line) and HW.search(line):
                bad.append(f"{p}:{n}: host hardware claim without link to docs/{LINK}")
                break
    print("\n".join(bad) or "hw-claims: ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
