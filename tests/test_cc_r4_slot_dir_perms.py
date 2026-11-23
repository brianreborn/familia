"""CC-R4: slot-save dirs (KV/prompt saves) are owner-only."""
import os, stat, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_graph as vg  # noqa: E402


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_default_slot_dir_chain_is_0700(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    old = os.umask(0o022)
    try:
        (tmp_path / ".cache" / "familia").mkdir(parents=True, mode=0o755)
        d = vg.ensure_private_slot_dir({"slot_save": True}, "n1")
    finally:
        os.umask(old)
    fam = tmp_path / ".cache" / "familia"
    assert d == str(fam / "slots" / "n1")
    for p in (fam, fam / "slots", fam / "slots" / "n1"):
        assert _mode(p) == 0o700, p


def test_existing_spill_path_tightened(tmp_path):
    sp = tmp_path / "ssd" / "spill"
    sp.mkdir(parents=True); os.chmod(sp.parent, 0o755); os.chmod(sp, 0o755)
    d = vg.ensure_private_slot_dir({"spill_path": str(sp)}, "n2")
    assert d == str(sp) and _mode(sp) == 0o700
    assert _mode(tmp_path / "ssd") == 0o755  # parent of an explicit spill_path is left alone


def test_symlinked_leaf_target_not_chmodded(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "elsewhere"
    target.mkdir(); os.chmod(target, 0o755)
    slots = tmp_path / ".cache" / "familia" / "slots"
    slots.mkdir(parents=True)
    (slots / "n3").symlink_to(target)
    vg.ensure_private_slot_dir({"slot_save": True}, "n3")
    assert _mode(target) == 0o755
    assert "not chmodding symlink" in capsys.readouterr().err
    assert _mode(slots) == 0o700  # real dirs in the chain are still tightened
