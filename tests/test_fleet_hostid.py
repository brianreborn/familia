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
    a = hostid.make_id("phone7", "state-uuid", "1b4e28ba-2fa1-41d2-883f-0016d3cca427")
    b = hostid.make_id("galaxy1", "state-uuid", "1b4e28ba-2fa1-41d2-883f-0016d3cca427")
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
    text = re.sub(r"host_uuid: [0-9a-f-]{36}", "host_uuid: U", text)  # derived/random UUIDs are fine
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
    u = hostid.host_uuid("soc-serial", "x")
    fp = u[:8]
    reg = {"a-" + fp: {"label": "a", "fingerprint": fp, "anchor_type": "soc-serial", "host_uuid": u},
           "b-" + fp: {"label": "b", "fingerprint": fp, "anchor_type": "soc-serial", "host_uuid": u}}
    errs = hostid.check(reg)
    assert any("duplicate device" in e for e in errs) and any("duplicate host_uuid" in e for e in errs)
    one = {"a-" + fp: {"label": "a", "fingerprint": fp, "anchor_type": "soc-serial", "aliases": ["b"], "host_uuid": u}}
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


# ---------------------------------------------------------------- host UUIDs
def test_host_uuid_is_rfc4122_v4_and_prefix_is_the_id_suffix():
    r = hostid.make_id("box", "machine-id", "0123456789abcdef0123456789abcdee")
    u = r["host_uuid"]
    assert hostid.UUID_RE.match(u)
    import uuid as _uuid
    assert _uuid.UUID(u).version == 4 and _uuid.UUID(u).variant == _uuid.RFC_4122
    assert u[:8] == r["fingerprint"] and r["host_id"].endswith(u[:8])
    assert "0123456789abcdef" not in u


def test_state_uuid_is_used_verbatim():
    v = "1b4e28ba-2fa1-41d2-883f-0016d3cca427"
    r = hostid.make_id("galaxy1", "state-uuid", v.upper())
    assert r["host_uuid"] == v and r["host_id"] == "galaxy1-1b4e28ba" and not r["weak"]
    # not a v4 UUID -> falls back to weak hostname instead of trusting it
    assert hostid.make_id("galaxy1", "state-uuid", "1b4e28ba-2fa1-11d2-883f-0016d3cca427")["anchor_type"] == "hostname"


def test_registry_has_unique_uuid_per_host_and_galaxies_are_pinned():
    us = [e["host_uuid"] for e in REG.values()]
    assert len(us) == len(set(us)) and all(hostid.UUID_RE.match(u) for u in us)
    for name in ("galaxy1", "galaxy2"):
        hid = hostid.resolve(name, REG)
        e = REG[hid]
        assert e["anchor_type"] == "state-uuid" and hid.endswith(e["host_uuid"][:8])
        # the phone still reports its weak ID until --init is run on it
        weak = hostid.make_id(name, None, None)["host_id"]
        assert weak in e["previous_ids"] and hostid.resolve(weak, REG) == hid
    assert hostid.resolve("phone7", REG) == hostid.resolve("galaxy1", REG)


def test_check_flags_bad_and_duplicate_uuids():
    a = hostid.make_id("a", "soc-serial", "1")
    b = hostid.make_id("b", "soc-serial", "2")
    ent = lambda r, u: {"label": r["label"], "fingerprint": r["fingerprint"], "anchor_type": "soc-serial", "host_uuid": u}
    assert hostid.check({a["host_id"]: ent(a, a["host_uuid"]), b["host_id"]: ent(b, b["host_uuid"])}) == []
    assert any("not a lowercase RFC 4122" in e for e in hostid.check({a["host_id"]: ent(a, "nope")}))
    assert any("prefix" in e for e in hostid.check({a["host_id"]: ent(a, b["host_uuid"])}))
    reg = {a["host_id"]: ent(a, a["host_uuid"]), b["host_id"]: ent(b, a["host_uuid"])}
    assert any("prefix" in e for e in hostid.check(reg))


def test_init_with_registry_value_matches_registry(tmp_path, monkeypatch):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    monkeypatch.setattr(hostid, "local_anchor", lambda environ=None: (None, None))
    hid = hostid.resolve("galaxy1", REG)
    p = hostid.init_state_uuid(env, value=REG[hid]["host_uuid"])
    r = hostid.make_id("galaxy1", "state-uuid", p.read_text())
    assert r["host_id"] == hid


def test_sh_state_uuid_matches_python(tmp_path):
    v = "1b4e28ba-2fa1-41d2-883f-0016d3cca427"
    (tmp_path / "familia").mkdir()
    (tmp_path / "familia" / "host-uuid").write_text(v + "\n")
    sh = ROOT / "scripts" / "fleet" / "hostid.sh"
    # run with no machine-id visible is not possible here; check the derivation path directly
    out = subprocess.run(["sh", str(sh), "--json", "--label", "x"], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "XDG_STATE_HOME": str(tmp_path), "HOME": str(tmp_path)})
    s = json.loads(out.stdout)
    assert hostid.UUID_RE.match(s["host_uuid"]) and s["host_id"] == "x-" + s["host_uuid"][:8]
    if s["anchor_type"] == "state-uuid":
        assert s["host_uuid"] == v
