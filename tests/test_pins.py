from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_pins import PinError, parse_pins


SHA = "0123456789abcdef0123456789abcdef01234567"
ORIGIN = "https://github.com/example/project.git"


def row(revision=SHA, origin=ORIGIN):
    return f"example-project\t{revision}\t{origin}\tengine\n"


def test_parses_pins_but_skips_ontology_rows():
    pins = parse_pins("# comment\n" + row() + "node\tmodel\ntransport\tssh\n")
    assert pins == [{"name": "example-project", "revision": SHA, "origin": ORIGIN, "role": "engine"}]


def test_rejects_short_or_non_hex_revisions():
    with pytest.raises(PinError, match="full lowercase 40-hex"):
        parse_pins(row("0123456"))
    with pytest.raises(PinError, match="full lowercase 40-hex"):
        parse_pins(row("g" * 40))


def test_refuses_the_known_wrong_llama_cpp_commit():
    with pytest.raises(PinError, match="forbidden llama.cpp commit prefix"):
        parse_pins(row("b1b770d" + "0" * 33))


@pytest.mark.parametrize("origin", [
    "http://github.com/example/project.git",
    "https://user:password@github.com/example/project.git",
    "https://example.com/example/project.git",
    "https://github.com:invalid/example/project.git",
    "https://github.com/example/project.git?token=secret",
])
def test_rejects_noncanonical_or_credentialed_origins(origin):
    with pytest.raises(PinError, match="HTTPS GitHub repository URL"):
        parse_pins(row(origin=origin))


def test_rejects_duplicate_pin_names_and_malformed_rows():
    with pytest.raises(PinError, match="duplicate pin name"):
        parse_pins(row() + row())
    with pytest.raises(PinError, match="expected name, revision"):
        parse_pins("name\tvalue\n")


def test_current_repository_pins_are_all_full_and_not_forbidden():
    pins = parse_pins((ROOT / "pins.txt").read_text(encoding="utf-8"))
    assert len(pins) == 6
    assert all(len(pin["revision"]) == 40 for pin in pins)
