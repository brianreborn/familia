"""App store (tweet cards): data parsing, both views, escaping, release pack."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import appstore  # noqa: E402

PY = sys.executable
APP = os.path.join(ROOT, "scripts", "appstore.py")
SH = os.path.join(ROOT, "scripts", "appstore.sh")
FIXTURE = os.path.join(ROOT, "examples", "appstore", "feed.sample.json")
RELEASE = os.path.join(ROOT, "appstore", "data")


def env(**kw):
    e = dict(os.environ)
    for k in ("FAMILIA_APPSTORE_DATA", "FAMILIA_APPDIR"):
        e.pop(k, None)
    e["FAMILIA_NO_TTY"] = "1"
    e.update(kw)
    return e


def run(argv, **kw):
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                          env=kw.pop("env", None) or env(), timeout=60, **kw)


def item(**kw):
    base = dict(app_name="A", app_pitch="p", app_link="https://example.com/a",
                platform="Linux", author_handle="@x", author_name="X",
                text="t", date="2026-11-01T00:00:00Z",
                url="https://x.com/x/status/1")
    base.update(kw)
    return base


def feed_dir(tmp_path, items, media=None):
    d = tmp_path / "data"
    (d / "media").mkdir(parents=True)
    for name, body in (media or {}).items():
        (d / "media" / name).write_text(body)
    (d / "feed.json").write_text(json.dumps(
        {"format": "familia-appstore-feed", "version": 1, "items": items}))
    return d


# --- parsing --------------------------------------------------------------

def test_fixture_parses_and_is_clearly_fake():
    items, doc = appstore.load_feed_file(FIXTURE)
    assert doc.get("example") is True
    assert len(items) >= 3
    for it in items:
        assert "(example)" in it["app_name"]
        assert it["author_handle"].startswith("example_")
        assert it["app_link"].startswith("https://example.com/")
    dates = [it["date"] for it in items]
    assert dates == sorted(dates, reverse=True)


def test_missing_field_is_an_error():
    bad = item()
    del bad["app_pitch"]
    with pytest.raises(appstore.FeedError):
        appstore.parse_feed([bad])
    with pytest.raises(appstore.FeedError):
        appstore.parse_feed({"format": "other", "items": []})


def test_unsafe_links_and_media_are_dropped():
    it = appstore.parse_feed([item(
        app_link="javascript:alert(1)", url="data:text/html,x",
        media=[{"type": "image", "path": "../../etc/passwd"},
               {"type": "image", "path": "/abs.png"},
               {"type": "image", "path": "https://cdn.example.com/x.png"},
               {"type": "script", "path": "media/x.js"},
               {"type": "video", "path": "media/ok.mp4", "alt": "demo"}])])[0]
    assert it["app_link"] == "" and it["url"] == ""
    assert it["media"] == [{"type": "video", "path": "media/ok.mp4", "alt": "demo"}]
    assert it["author_handle"] == "x"


def test_terminal_text_strips_escapes_and_controls():
    it = appstore.parse_feed([item(text="hi\x1b[31mRED\x1b[0m\x07\nthere\x1b]0;title\x07")])[0]
    assert it["text"] == "hiRED there"


def test_lookup_release_first_then_fixture(tmp_path):
    items, base, label, notes = appstore.load()
    # The repo's release feed is empty, so the fixture shows with a note.
    assert label == "example fixture" and notes
    d = feed_dir(tmp_path, [item(app_name="Real App")])
    appdir = tmp_path / "AppDir"
    target = appdir / "usr" / "share" / "familia" / "appstore"
    target.mkdir(parents=True)
    shutil.copytree(d, target / "data")
    old = os.environ.get("FAMILIA_APPDIR")
    os.environ["FAMILIA_APPDIR"] = str(appdir)
    try:
        items, base, label, notes = appstore.load()
    finally:
        if old is None:
            os.environ.pop("FAMILIA_APPDIR", None)
        else:
            os.environ["FAMILIA_APPDIR"] = old
    assert label == "release" and [i["app_name"] for i in items] == ["Real App"]
    assert base == str(target / "data")


# --- gum / text view --------------------------------------------------------

def test_text_view_renders_fixture_app_first_and_ascii():
    r = run([PY, APP, "text"])
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert all(ord(c) < 128 for c in out)
    assert "familia app store" in out
    assert "source: example fixture" in out
    for it in appstore.load_feed_file(FIXTURE)[0]:
        assert it["app_name"] in out and it["app_link"] in out
        # app comes before its tweet
        assert out.index(it["app_name"]) < out.index("@" + it["author_handle"])
    for ln in out.splitlines():
        assert len(ln) <= 72, ln


def test_text_view_platform_filter_and_platforms():
    r = run([PY, APP, "platforms"])
    assert r.returncode == 0
    plats = r.stdout.split()
    assert "Android" in plats and "Web" in plats
    r = run([PY, APP, "text", "--platform", "Web"])
    assert "OneLine Cal (example)" in r.stdout
    assert "PaperNote (example)" not in r.stdout


def test_gum_script_without_tty_prints_plain_cards():
    r = run(["sh", SH, "--platform", "android"])
    assert r.returncode == 0, r.stderr
    assert "PaperNote (example)" in r.stdout and "FridgeChef (example)" in r.stdout
    assert "histotime (example)" not in r.stdout
    assert "\x1b" not in r.stdout
    h = run(["sh", SH, "--help"])
    assert h.returncode == 0 and "gum" in h.stdout


@pytest.mark.skipif(not shutil.which("gum"), reason="gum not installed")
def test_gum_print_renders_bordered_cards():
    r = run(["sh", SH, "--gum-print"])
    assert r.returncode == 0, r.stderr
    assert "PaperNote (example)" in r.stdout
    assert "\u256d" in r.stdout or "+" in r.stdout


# --- HTML view ------------------------------------------------------------

def test_html_renders_fixture_with_local_media_only(tmp_path):
    out = tmp_path / "site"
    r = run([PY, APP, "html", "--out", str(out)])
    assert r.returncode == 0, r.stderr
    page = (out / "index.html").read_text()
    for it in appstore.load_feed_file(FIXTURE)[0]:
        assert it["app_name"].replace("&", "&amp;") in page
    assert page.count("<article") == 5
    assert (out / "media" / "papernote.svg").is_file()
    assert 'src="media/papernote.svg"' in page
    # no remote loads: no src/href to http except anchor links
    for tag in ("<script src", "<link", "@import", "cdn"):
        assert tag not in page.lower()
    assert "default-src 'none'" in page


def test_html_escapes_tweet_text():
    hostile = item(text='<script>alert("x")</script> & <img src=x onerror=1>',
                   app_name="<b>App</b>", app_pitch='"quoted"')
    page = appstore.render_html(appstore.parse_feed([hostile]), "t", [])
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &lt;img src=x onerror=1&gt;" in page
    assert "&lt;b&gt;App&lt;/b&gt;" in page
    assert "<img src=x" not in page


def test_html_fixture_escapes_markup_in_tweet():
    page = appstore.render_html(appstore.load_feed_file(FIXTURE)[0], "example fixture", [])
    assert "&lt;b&gt;finally&lt;/b&gt;" in page
    assert "<b>finally</b>" not in page


# --- release pack -----------------------------------------------------------

def test_release_data_checksums_match():
    assert os.path.isfile(os.path.join(RELEASE, "feed.json"))
    assert os.path.isdir(os.path.join(RELEASE, "media"))
    assert appstore.verify_sums(RELEASE) == []


def test_checksum_mismatch_is_caught(tmp_path):
    d = feed_dir(tmp_path, [item()], media={"a.svg": "<svg/>"})
    (d / "SHA256SUMS").write_text(appstore.sums_text(str(d)))
    assert appstore.verify_sums(str(d)) == []
    (d / "media" / "a.svg").write_text("<svg>changed</svg>")
    assert appstore.verify_sums(str(d))


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_release_pack_includes_appstore_data(tmp_path):
    staged = tmp_path / "AppDir"
    r = subprocess.run(["bash", os.path.join(ROOT, "scripts", "build_appimage.sh"),
                        "--stage-only", str(staged)],
                       cwd=ROOT, capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, TMPDIR=str(tmp_path)))
    assert r.returncode == 0, r.stdout + r.stderr
    data = staged / "usr" / "share" / "familia" / "appstore" / "data"
    assert (data / "feed.json").is_file()
    assert (data / "SHA256SUMS").is_file()
    assert (data / "media").is_dir()
    assert appstore.verify_sums(str(data)) == []
    assert (staged / "usr" / "share" / "familia" / "examples" / "appstore" / "feed.sample.json").is_file()
