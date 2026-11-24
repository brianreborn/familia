"""Release channels (scripts/channel.py, docs/release-channels.md). Network is always mocked."""
import datetime as dt
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import channel  # noqa: E402
import hf_fetch  # noqa: E402

NOW = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)


def ago(days, hours=0):
    return (NOW - dt.timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def gh(tag, days, hours=0, pre=False, draft=False, assets=()):
    return {"tag_name": tag, "published_at": ago(days, hours), "prerelease": pre, "draft": draft,
            "assets": [{"name": a} for a in assets]}


def fake(pages):
    """fetch() returning pages[url-page] for GitHub releases (page=N) or HF commits (p=N)."""
    calls = []

    def fetch(url):
        calls.append(url)
        assert url.startswith("https://")
        q = url.split("?", 1)[1]
        n = int(dict(x.split("=") for x in q.split("&")).get("page") or dict(x.split("=") for x in q.split("&")).get("p"))
        return pages.get(n, [])
    fetch.calls = calls
    return fetch


def no_text(url):
    raise AssertionError("unexpected text fetch " + url)


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("bad", ["stable;rm", "$(x)", "../", "Stable", " stable", "stable ", "", "edge", "bleeding\n", 1, b"stable"])
def test_channel_rejects(bad):
    with pytest.raises(channel.ChannelError):
        channel.validate_channel(bad)


@pytest.mark.parametrize("good", ["bleeding", "stable"])
def test_channel_accepts(good):
    assert channel.validate_channel(good) == good


@pytest.mark.parametrize("bad", ["0", "-1", "1e3", "366", "99999999999999999999", "+5", " 5", "5 ", "0x10", "1.5",
                                 "\u0665", "$(x)", "../", "", 0, -1, 366, 10 ** 30, True, 1.0])
def test_days_rejects(bad):
    with pytest.raises(channel.ChannelError):
        channel.validate_days(bad)


@pytest.mark.parametrize("good,n", [("1", 1), ("30", 30), ("365", 365), (7, 7), ("007", 7)])
def test_days_accepts(good, n):
    assert channel.validate_days(good) == n


def test_default_stays_bleeding():
    assert channel.effective(environ={}) == ("bleeding", 30)
    assert channel.effective(environ={"FAMILIA_CHANNEL": "", "FAMILIA_STABLE_DAYS": ""}) == ("bleeding", 30)
    assert channel.effective(environ={"FAMILIA_CHANNEL": "stable", "FAMILIA_STABLE_DAYS": "14"}) == ("stable", 14)
    assert channel.effective("bleeding", None, {"FAMILIA_CHANNEL": "stable"}) == ("bleeding", 30)
    with pytest.raises(channel.ChannelError):
        channel.effective(environ={"FAMILIA_CHANNEL": "stable;rm"})


@pytest.mark.parametrize("bad", ["v1;rm -rf", "$(x)", "../x", "a/b", "..", "x..y", "-rf", "", "a b", "tag\n", "é", "x" * 200])
def test_tag_name_validation(bad):
    assert not channel.valid_tag(bad)


@pytest.mark.parametrize("bad", ["github:../x", "github:a/b/c", "hf:a", "hf:$(x)/y", "github:a/..", "nope", "github:a/b;c"])
def test_source_id_validation(bad):
    with pytest.raises(channel.ChannelError):
        channel.source(bad)


# ---------------------------------------------------------------- selection

def test_window_newest_qualifying():
    # in a 30-day window: v1.0 (soaked 10d), v1.1 (soaked 2d), v1.2 (newest, 5d since publish)
    f = fake({1: [gh("v1.2", 5), gh("v1.1", 7), gh("v1.0", 17), gh("v0.9", 40)]})
    r = channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f, fetch_text=no_text)
    assert (r.ref, r.fallback, r.kind) == ("v1.2", False, "tag")
    assert r.channel == "stable" and r.days == 30


def test_window_skips_fresh_and_quickly_superseded():
    # v1.4 is 3 h old (not soaked); v1.3 was replaced after 2 h; v1.2 stood for about 10 days
    f = fake({1: [gh("v1.4", 0, 3), gh("v1.3", 0, 5), gh("v1.2", 10), gh("v1.1", 21), gh("v1.0", 40)]})
    r = channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f)
    assert (r.ref, r.fallback) == ("v1.2", False)


def test_fallback_skips_unqualified_before_window():
    # 1-day window: v1.3 is 5 h old (not soaked); before the window v1.2 was replaced after
    # 21 h (not qualifying), v1.1 stood for about 4 days
    f = fake({1: [gh("v1.3", 0, 5), gh("v1.2", 1, 2), gh("v1.1", 5), gh("v1.0", 9)]})
    r = channel.resolve("hermes-agent", "stable", 1, now=NOW, fetch=f)
    assert (r.ref, r.fallback) == ("v1.1", True) and "qualifying" in r.reason


def test_window_tie_goes_to_newer():
    f = fake({1: [gh("v1.2", 3), gh("v1.1", 6), gh("v1.0", 9)]})
    assert channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f).ref == "v1.2"


def test_prerelease_and_draft_excluded():
    f = fake({1: [gh("v2.0", 1, pre=True), gh("v1.9-rc1", 3), gh("v1.8", 4, draft=True), gh("v1.8-beta", 20),
                  gh("v1.7.0-dev", 25), gh("v1.6", 28), gh("v1.5", 60)]})
    r = channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f)
    assert r.ref == "v1.6" and not r.fallback


def test_bleeding_newest_non_prerelease():
    f = fake({1: [gh("v2.0", 0, 1, pre=True), gh("v1.9", 0, 2), gh("v1.8", 20)]})
    r = channel.resolve("hermes-agent", "bleeding", None, now=NOW, fetch=f)
    assert (r.ref, r.channel) == ("v1.9", "bleeding")


def test_fallback_when_window_empty():
    f = fake({1: [gh("v1.1", 40), gh("v1.0", 80)]})
    r = channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f)
    assert r.ref == "v1.1" and r.fallback and "no release in the last 30 days" in r.reason


def test_fallback_when_window_too_fresh():
    f = fake({1: [gh("v1.2", 0, 3), gh("v1.1", 40)]})
    r = channel.resolve("hermes-agent", "stable", 7, now=NOW, fetch=f)
    assert r.ref == "v1.1" and r.fallback


def test_only_fresh_and_nothing_older():
    f = fake({1: [gh("v0.1", 0, 3)]})
    r = channel.resolve("hermes-agent", "stable", 7, now=NOW, fetch=f)
    assert r.ref == "v0.1" and r.fallback


def test_nothing_resolvable():
    f = fake({1: [gh("v1.0-rc1", 3)]})
    with pytest.raises(channel.ResolveError):
        channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f)


def test_hostile_tag_names_never_returned():
    f = fake({1: [gh("$(reboot)", 1), gh("../../etc", 2), gh("v1;rm", 3), gh("v1.0", 20)]})
    r = channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f)
    assert r.ref == "v1.0"


def test_urls_are_quoted_and_https():
    f = fake({1: [gh("v1.0", 20)]})
    channel.resolve("github:some-org/some.repo", "stable", 30, now=NOW, fetch=f)
    assert f.calls[0].startswith("https://api.github.com/repos/some-org/some.repo/releases?")


def test_pagination_stops_past_window():
    page1 = [gh("v1.%d" % i, i) for i in range(1, 101)]          # 100 releases, days 1..100
    f = fake({1: page1, 2: [gh("v0.9", 200)]})
    channel.resolve("hermes-agent", "stable", 30, now=NOW, fetch=f)
    assert len(f.calls) == 1


# ---------------------------------------------------------------- llama.cpp

LL_ASSET = "llama-bNNNN-bin-ubuntu-x64.tar.gz"


def llama_pages():
    return {1: [gh("b12050", 0, 2, pre=True, assets=[LL_ASSET]), gh("b12040", 1, pre=True, assets=["other.zip"]),
                gh("b11960", 5, pre=True, assets=[LL_ASSET]), gh("v0.8.0", 5, assets=["nightly-tag.txt"]),
                gh("v0.7.0", 18, assets=["nightly-tag.txt"]), gh("v0.6.0", 40, assets=["nightly-tag.txt"])]}


def test_llama_stable_maps_version_to_build():
    seen = []

    def text(url):
        seen.append(url)
        return {"v0.7.0": "b11669\n", "v0.8.0": "b11960\n"}[url.rsplit("/", 2)[1]]
    r = channel.resolve("llama.cpp", "stable", 30, now=NOW, fetch=fake(llama_pages()), fetch_text=text)
    assert (r.ref, r.release, r.fallback) == ("b11960", "v0.8.0", False)   # leans newer over v0.7.0
    assert seen == ["https://github.com/ggml-org/llama.cpp/releases/download/v0.8.0/nightly-tag.txt"]
    r = channel.resolve("llama.cpp", "stable", 7, now=NOW, fetch=fake(llama_pages()), fetch_text=text)
    assert (r.ref, r.release) == ("b11960", "v0.8.0")
    r = channel.resolve("llama.cpp", "stable", 3, now=NOW, fetch=fake(llama_pages()), fetch_text=text)
    assert (r.ref, r.release, r.fallback) == ("b11960", "v0.8.0", True)   # window empty: newest before it


@pytest.mark.parametrize("body", ["b1;rm", "$(x)", "", "v0.7.0", "b12 34", "../b1"])
def test_llama_rejects_bad_nightly_tag(body):
    with pytest.raises(channel.ResolveError):
        channel.resolve("llama.cpp", "stable", 30, now=NOW, fetch=fake(llama_pages()), fetch_text=lambda u: body)


def test_llama_bleeding_newest_build_with_asset():
    r = channel.resolve("llama.cpp", "bleeding", None, now=NOW, fetch=fake(llama_pages()), fetch_text=no_text,
                        asset_re=r"bin-ubuntu-x64\.(tar\.gz|zip)$")
    assert r.ref == "b12050"


# ---------------------------------------------------------------- Hugging Face

def hf_commit(i, days):
    return {"id": ("%x" % i) * 40, "date": ago(days)}


def test_hf_stable_commit():
    f = fake({0: [hf_commit(1, 2), hf_commit(2, 4), hf_commit(3, 20), {"id": "../x", "date": ago(1)}]})
    r = channel.resolve("hf:Org/Model-GGUF", "stable", 30, now=NOW, fetch=f)
    assert r.ref == "1" * 40 and r.kind == "commit"   # newest commit that soaked 24 h
    assert f.calls[0].startswith("https://huggingface.co/api/models/Org/Model-GGUF/commits/main?")


def test_hf_fetch_default_revision(monkeypatch):
    assert hf_fetch.default_revision("Org/M", environ={}) == "main"
    seen = {}

    def res(src, ch, days, environ=None):
        seen["args"] = (src, ch, days)
        return channel.ResolvedRef(src, ch, days, "a" * 40, "commit", "", False, "")
    monkeypatch.setattr(channel, "resolve", res)
    env = {"FAMILIA_CHANNEL": "stable", "FAMILIA_STABLE_DAYS": "9"}
    assert hf_fetch.default_revision("Org/M", environ=env) == "a" * 40
    assert seen["args"] == ("hf:Org/M", "stable", 9)
    with pytest.raises(hf_fetch.HFError):
        hf_fetch.default_revision("Org/M", environ={"FAMILIA_CHANNEL": "$(x)"})


# ---------------------------------------------------------------- record + CLI

def test_record_user_owned_private(tmp_path):
    ref = channel.ResolvedRef("hf:a/b", "stable", 30, "c" * 40, "commit", "", False, "x")
    p = channel.record(ref, str(tmp_path / "state"))
    assert os.path.basename(p) == "hf_a_b.json"
    assert json.load(open(p))["ref"] == "c" * 40
    assert oct(os.stat(tmp_path / "state").st_mode & 0o777) == "0o700"
    assert os.listdir(tmp_path / "state") == ["hf_a_b.json"]   # private run dir removed


def test_state_dir_not_tmp():
    d = channel.state_dir({"XDG_STATE_HOME": "/x/state"})
    assert d == "/x/state/familia/channel"
    assert not channel.state_dir({}).startswith("/tmp")


def cli(*args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "channel.py"), *args],
                          capture_output=True, text=True, env=e, timeout=60)


@pytest.mark.parametrize("args,env", [(["resolve", "hermes-agent", "--channel", "stable;rm"], {}),
                                      (["resolve", "hermes-agent", "--days", "1e3"], {}),
                                      (["resolve", "hermes-agent", "--days", "-1"], {}),
                                      (["resolve", "../etc"], {}),
                                      (["show"], {"FAMILIA_CHANNEL": "$(x)"}),
                                      (["show"], {"FAMILIA_STABLE_DAYS": "0"})])
def test_cli_rejects_with_exit_2(args, env):
    r = cli(*args, env=env)
    assert r.returncode == 2 and r.stdout == "" and ("invalid" in r.stderr or "unknown source" in r.stderr)


def test_cli_show_default():
    env = {k: v for k, v in os.environ.items() if k not in ("FAMILIA_CHANNEL", "FAMILIA_STABLE_DAYS")}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "channel.py"), "show"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.stdout.strip() == "channel=bleeding stable_days=30"


def test_cli_lists_hermes_source():
    assert "hermes-agent" in cli("sources").stdout.split()


def test_no_listeners_or_shell():
    src = open(os.path.join(ROOT, "scripts", "channel.py")).read()
    for bad in ("socket.socket", "bind(", "listen(", "shell=True", "os.system", "eval(", "exec(", "/tmp"):
        assert bad not in src


# ---------------------------------------------------------------- installers

@pytest.mark.parametrize("script", ["install.sh", "install/linux/install.sh"])
@pytest.mark.parametrize("flag,val", [("--channel", "stable;rm"), ("--channel", "$(x)"), ("--stable-days", "0"),
                                      ("--stable-days", "-1"), ("--stable-days", "1e3"), ("--stable-days", "366"),
                                      ("--stable-days", "99999")])
def test_installers_reject_bad_channel_flags(tmp_path, script, flag, val):
    env = dict(os.environ, HOME=str(tmp_path), FAMILIA_PREFIX=str(tmp_path / "p"), INSTALL_PREFIX=str(tmp_path / "f"))
    r = subprocess.run(["sh", os.path.join(ROOT, script), "--dry-run", flag, val], capture_output=True, text=True,
                       env=env, timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode != 0 and "invalid --" in r.stderr


def test_installers_document_channel():
    for p in ("install.sh", "install/linux/install.sh"):
        s = open(os.path.join(ROOT, p)).read()
        assert "--channel" in s and "--stable-days" in s
