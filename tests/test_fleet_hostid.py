"""Fleet host IDs: one physical device -> one canonical ID over every transport."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "fleet"))
sys.path.insert(0, str(ROOT / "scripts" / "swarm"))
import hostid  # noqa: E402

REG = hostid.load_registry()


def test_id_format_and_hash_only():
    r = hostid.make_id("Note9.lan", "soc-serial", "ABC 123")
    assert r["host_id"] == "note9-" + r["fingerprint"]
    assert re.fullmatch(r"[0-9a-f]{8}", r["fingerprint"])
    assert "abc" not in json.dumps(r).lower()
    assert r["weak"] is False
    # whitespace/case of the raw anchor do not change the ID
    assert hostid.make_id("note9", "soc-serial", "abc123") == r


def test_two_transports_dedupe_to_one_id():
    # The device reports the same anchor whether reached over Wi-Fi or the adb forward.
    wifi = hostid.make_id("note9", "soc-serial", "deadbeef01")
    usb = hostid.make_id("note9", "soc-serial", "deadbeef01")
    obs = [dict(wifi, alias="note9", transport="wifi"),
           dict(usb, alias="note9-usb", transport="usb-adb-forward")]
    merged = hostid.merge_observations(obs)
    assert list(merged) == [wifi["host_id"]]
    e = merged[wifi["host_id"]]
    assert e["aliases"] == ["note9", "note9-usb"]
    assert [t["kind"] for t in e["transports"]] == ["wifi", "usb-adb-forward"]


def test_label_drift_still_dedupes_by_fingerprint():
    a = hostid.make_id("phone7", "state-uuid", "u-1")
    b = hostid.make_id("galaxy1", "state-uuid", "u-1")
    assert a["host_id"] != b["host_id"] and a["fingerprint"] == b["fingerprint"]
    assert len(hostid.merge_observations([dict(a, alias="phone7"), dict(b, alias="galaxy1")])) == 1


def test_different_devices_stay_separate():
    a = hostid.make_id("galaxy", "soc-serial", "one")
    b = hostid.make_id("galaxy", "soc-serial", "two")
    assert len(hostid.merge_observations([dict(a, alias="x"), dict(b, alias="y")])) == 2


@pytest.mark.parametrize("anchor", [None, "", "unknown", "0123456789ABCDEF", "00000000-0000-0000-0000-000000000000"])
def test_unknown_anchor_falls_back_to_weak_hostname(anchor):
    r = hostid.make_id("galaxy2", "android-serial" if anchor is not None else None, anchor)
    assert r["anchor_type"] == "hostname" and r["weak"] is True
    assert r["host_id"] == "galaxy2-" + hostid.fingerprint("hostname", "galaxy2")


def test_localhost_label_becomes_host():
    assert hostid.make_id("localhost", None, None)["label"] == "host"
    assert hostid.slug("Weird Name!!.local") == "weird-name"


def test_unknown_anchor_type_rejected():
    with pytest.raises(ValueError):
        hostid.fingerprint("ip-address", "192.0.2.1")


def test_registry_and_graph_are_consistent():
    graph = hostid.load_yaml(ROOT / "graph.yaml")
    assert hostid.check(REG, graph) == []
    for g in ("generated/graph-miryam.yaml", "generated/graph-angel.yaml"):
        assert hostid.check(REG, hostid.load_yaml(ROOT / g)) == []


def test_registry_stores_no_raw_identifiers_or_addresses():
    text = (ROOT / "registry" / "fleet-hosts.yaml").read_text(encoding="ascii")
    assert not re.search(r"\b[0-9a-f]{12,}\b", text, re.I)          # no raw serial/machine-id
    assert not re.search(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", text, re.I)  # no MACs
    assert not re.search(r"\b(10|127|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d+\.\d+", text)  # no LAN IPs
    assert "u0_a" not in text


def test_note9_and_galaxy_aliases_resolve_to_one_entry():
    assert hostid.resolve("note9", REG) == hostid.resolve("note9-usb", REG) == "note9-7140b66c"
    assert hostid.resolve("phone7", REG) == hostid.resolve("galaxy1", REG)
    assert hostid.resolve("phone8", REG) == hostid.resolve("galaxy2", REG)
    assert hostid.resolve("renamed-7140b66c", REG) == "note9-7140b66c"
    assert hostid.resolve("no-such-host", REG) is None
    labels = [e["label"] for e in REG.values()]
    assert "note9-usb" not in labels and len(labels) == len(set(labels))


def test_check_flags_duplicates():
    fp = hostid.fingerprint("soc-serial", "x")
    reg = {"a-" + fp: {"label": "a", "fingerprint": fp, "anchor_type": "soc-serial"},
           "b-" + fp: {"label": "b", "fingerprint": fp, "anchor_type": "soc-serial"}}
    assert any("duplicate device" in e for e in hostid.check(reg))
    one = {"a-" + fp: {"label": "a", "fingerprint": fp, "anchor_type": "soc-serial", "aliases": ["b"]}}
    graph = {"hosts": {"a": {"host_id": "a-" + fp}, "b": {"host_id": "a-" + fp}}}
    assert any("share host_id" in e for e in hostid.check(one, graph))
    graph["hosts"]["b"]["alias_of"] = "a"
    assert hostid.check(one, graph) == []


def test_init_state_uuid_only_without_hardware_anchor(tmp_path, monkeypatch):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    monkeypatch.setattr(hostid, "local_anchor", lambda environ=None: (None, None))
    p = hostid.init_state_uuid(env)
    assert p and p.exists() and len(p.read_text().strip()) == 36
    before = p.read_text()
    assert hostid.init_state_uuid(env).read_text() == before  # idempotent
    monkeypatch.setattr(hostid, "local_anchor", lambda environ=None: ("machine-id", "x"))
    assert hostid.init_state_uuid(env) is None


def test_sh_and_python_agree_on_this_host():
    sh = ROOT / "scripts" / "fleet" / "hostid.sh"
    out = subprocess.run(["sh", str(sh), "--json", "--label", "parity"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    s = json.loads(out.stdout)
    p = hostid.local_id("parity")
    if s["anchor_type"] != p["anchor_type"]:
        pytest.skip("anchor sources differ on this platform: %s vs %s" % (s["anchor_type"], p["anchor_type"]))
    assert s == p


def test_sh_never_prints_raw_machine_id():
    mid = Path("/etc/machine-id")
    if not mid.exists():
        pytest.skip("no /etc/machine-id")
    raw = mid.read_text().strip()
    out = subprocess.run(["sh", str(ROOT / "scripts" / "fleet" / "hostid.sh"), "--json"],
                         capture_output=True, text=True, timeout=30).stdout
    assert raw and raw not in out


def test_deploy_fleet_skips_second_alias_of_same_device():
    import deploy_fleet
    got = deploy_fleet.dedupe_hosts(["note9", "note9-usb", "phone7", "galaxy1", "angel", "newhost"], REG)
    assert [h for h, _ in got] == ["note9", "phone7", "angel", "newhost"]
    assert dict(got)["newhost"] is None


def test_new_files_are_ascii():
    for rel in ("scripts/fleet/hostid.sh", "scripts/fleet/hostid.py", "scripts/fleet/hostid.ps1",
                "scripts/fleet/hostid.cmd", "registry/fleet-hosts.yaml", "docs/fleet-host-ids.md"):
        data = (ROOT / rel).read_bytes()
        if rel.endswith(".ps1"):  # repo rule: UTF-8 BOM for PowerShell 5.1, ASCII after it
            assert data.startswith(b"\xef\xbb\xbf")
            data = data[3:]
        data.decode("ascii")
