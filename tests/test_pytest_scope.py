"""pytest.ini keeps collection to tests/ and out of every pinned part (pins.txt)."""
import configparser
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_pinned_parts_not_collected():
    c = configparser.ConfigParser()
    c.read(os.path.join(ROOT, "pytest.ini"))
    assert c["pytest"]["testpaths"].split() == ["tests"]
    skip = c["pytest"]["norecursedirs"].split()
    for line in open(os.path.join(ROOT, "pins.txt")):
        if line.startswith("#") or "\t" not in line:
            continue
        name = line.split("\t")[0]
        if name in ("node", "transport"):
            continue
        assert name in skip or any(s.endswith("*") and name.startswith(s[:-1]) for s in skip), name
