import importlib.util, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fleet_greeting_scope", ROOT / "scripts" / "fleet_greeting.py")
fg = importlib.util.module_from_spec(spec); spec.loader.exec_module(fg)


def _fresh():
    fg._cache.clear()


def test_outside_docs_absolute_rejected(tmp_path, capsys):
    _fresh()
    key = tmp_path / "id_ed25519"; key.write_text("SECRET KEY\n")
    assert fg.load(fg.path({fg.ENV: str(key)})) is None
    assert "outside" in capsys.readouterr().err


def test_dotdot_escape_rejected(capsys):
    _fresh()
    assert fg.load(fg.path({fg.ENV: "docs/../README.md"})) is None
    assert "outside" in capsys.readouterr().err


def test_symlink_in_docs_pointing_out_rejected(tmp_path, monkeypatch, capsys):
    _fresh()
    docs = tmp_path / "docs"; docs.mkdir()
    secret = tmp_path / "secret"; secret.write_text("SECRET\n")
    (docs / "g.md").symlink_to(secret)
    monkeypatch.setattr(fg, "DOCS", str(docs.resolve()))
    assert fg.load(str(docs / "g.md")) is None
    assert "outside" in capsys.readouterr().err


def test_oversize_and_marker_rejected(tmp_path, monkeypatch, capsys):
    _fresh()
    docs = tmp_path / "docs"; docs.mkdir()
    monkeypatch.setattr(fg, "DOCS", str(docs.resolve()))
    big = docs / "big.md"; big.write_text("x" * (fg.MAX_BYTES + 1))
    assert fg.load(str(big)) is None
    m = docs / "m.md"; m.write_text("hi\n" + fg.END_MARKER + "\n")
    assert fg.load(str(m)) is None
    err = capsys.readouterr().err
    assert "larger" in err and "end marker" in err


def test_default_greeting_still_loads():
    _fresh()
    assert fg.load(fg.path({})) == (ROOT / "docs" / "FLEET-GREETING.md").read_text(encoding="utf-8")


def test_strip_only_leading_block():
    body = "keep\n" + ("y" * (fg.MAX_BYTES + 10)) + "\n" + fg.END_MARKER + "\ntail\n"
    assert fg.strip(body) == body
    inline = "abc " + fg.END_MARKER + " def"
    assert fg.strip(inline) == inline
    assert fg.strip(fg.block("G\n") + "\nrest") == "rest"
