#!/usr/bin/env python3
"""Iterate through design documents and report any identifiers
that are mentioned in the docs but not found in the implementation.

This is a lightweight impedance‑mismatch checker used for issue #580.
"""
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
CODE_DIR = REPO_ROOT / "scripts"

# Simple regex to capture back‑ticked identifiers or code fences
IDENTIFIER_RE = re.compile(r"`([^`]+)`|\bdef\s+([a-zA-Z_][a-zA-Z0-9_]*)|\bclass\s+([A-Z][a-zA-Z0-9_]*)")

def collect_identifiers_from_doc(path: pathlib.Path):
    identifiers = set()
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[WARN] Could not read {path}: {e}", file=sys.stderr)
        return identifiers
    for match in IDENTIFIER_RE.finditer(text):
        # match groups: 1 = back‑ticked, 2 = def name, 3 = class name
        name = match.group(1) or match.group(2) or match.group(3)
        if name:
            identifiers.add(name.strip())
    return identifiers

def find_definition(name: str):
    """Search the code base for a definition of *name* using grep.
    Returns True if a likely definition is found.
    """
    # Look for function or class definitions, or mentions in .py files
    try:
        result = subprocess.run([
            "grep",
            "-R",
            "-n",
            f"def {name}",
            f"class {name}",
            "--include=*.py",
            str(CODE_DIR)
        ], capture_output=True, text=True, timeout=15)
        return bool(result.stdout.strip())
    except Exception:
        return False

def main():
    all_identifiers = set()
    for doc in DOCS_DIR.rglob("*.md"):
        ids = collect_identifiers_from_doc(doc)
        if ids:
            print(f"[INFO] Found {len(ids)} identifiers in {doc.relative_to(REPO_ROOT)}")
        all_identifiers.update(ids)

    missing = []
    for name in sorted(all_identifiers):
        if not find_definition(name):
            missing.append(name)

    report_path = REPO_ROOT / "impedance_report.txt"
    with report_path.open("w", encoding="utf-8") as f:
        if missing:
            f.write("Identifiers mentioned in design docs but not found in code:\n")
            for n in missing:
                f.write(f"- {n}\n")
        else:
            f.write("All identifiers from design docs have matching definitions in the code base.\n")
    print(f"Report written to {report_path}")

if __name__ == "__main__":
    main()
