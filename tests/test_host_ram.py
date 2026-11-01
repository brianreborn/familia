"""#224: host RAM comes from a live probe or the graph's dated snapshot; unknown never crashes."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import validate_graph as vg  # noqa: E402


def test_unknown_host_is_none_not_keyerror(monkeypatch):
    monkeypatch.setattr(vg, "live_ram_mib", lambda: None)
    ram, why = vg.host_ram_mib("ghost", None, local="box")
    assert ram is None and "not declared" in why


def test_snapshot_used_for_remote_host(monkeypatch):
    monkeypatch.setattr(vg, "live_ram_mib", lambda: 999999)  # must not leak onto a remote host
    assert vg.host_ram_mib("miryam", {"ram_mib": 7270}, local="box") == (7270, "graph snapshot")


def test_live_probe_for_local_host_without_snapshot(monkeypatch):
    monkeypatch.setattr(vg, "live_ram_mib", lambda: 8000)
    assert vg.host_ram_mib("box", {}, local="box") == (8000, "live probe")


def test_local_host_uses_smaller_of_live_and_snapshot(monkeypatch):
    monkeypatch.setattr(vg, "live_ram_mib", lambda: 6000)
    assert vg.host_ram_mib("m", {"ram_mib": 7270}, local="m") == (6000, "live probe")
    monkeypatch.setattr(vg, "live_ram_mib", lambda: 16000)
    assert vg.host_ram_mib("m", {"ram_mib": 7270}, local="m") == (7270, "graph snapshot")


def test_bad_snapshot_values_ignored(monkeypatch):
    monkeypatch.setattr(vg, "live_ram_mib", lambda: None)
    for bad in (None, 0, -1, True, "7270"):
        assert vg.host_ram_mib("m", {"ram_mib": bad}, local=None)[0] is None


def test_live_probe_never_raises(monkeypatch):
    import host_measure
    monkeypatch.setattr(host_measure, "_meminfo_mib", lambda: (_ for _ in ()).throw(OSError("x")))
    assert vg.live_ram_mib() is None
