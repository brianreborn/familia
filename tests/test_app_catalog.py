"""scripts/app_catalog.py (#397): app list, cached public search (hit / expired / 304 / offline)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import app_catalog as ac  # noqa: E402

ITEM = {"repository_url": "https://api.github.com/repos/brianreborn/familia", "number": 397,
        "title": "App catalog: virtual app store menu item", "html_url": "https://github.com/brianreborn/familia/issues/397",
        "body": "Add a new menu item \u2014 the app store"}


@pytest.fixture(autouse=True)
def cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("FAMILIA_APP_CATALOG_TTL", raising=False)
    monkeypatch.delenv("FAMILIA_APP_CATALOG_TOKEN", raising=False)
    return tmp_path


class Fake:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(items=(ITEM,), etag='W/"abc"'):
    return 200, {"etag": etag}, json.dumps({"items": list(items)}).encode()


def test_first_fetch_writes_cache_and_query_is_public_only(cache_home):
    f = Fake(ok())
    items, note = ac.fetch(get=f, now=1000)
    assert note == "" and items[0]["repo"] == "brianreborn/familia" and items[0]["number"] == 397
    url = f.calls[0][0]
    assert "is%3Apublic" in url and "label%3Aapplications" in url and "user%3Abrianreborn" in url
    c = json.loads((cache_home / "familia" / "app-catalog.json").read_text())
    assert c["etag"] == 'W/"abc"' and c["fetched_at"] == 1000 and c["ttl_s"] == 45 * 60


def test_cache_hit_makes_no_request():
    ac.fetch(get=Fake(ok()), now=1000)
    f = Fake()
    items, note = ac.fetch(get=f, now=1000 + 60)
    assert f.calls == [] and items and note == ""


def test_expired_cache_revalidates_with_etag_and_304_keeps_items(cache_home):
    ac.fetch(get=Fake(ok()), now=1000)
    f = Fake((304, {}, b""))
    items, note = ac.fetch(get=f, now=1000 + 46 * 60)
    assert f.calls[0][1].get("If-None-Match") == 'W/"abc"'
    assert items[0]["number"] == 397 and note == ""
    c = json.loads((cache_home / "familia" / "app-catalog.json").read_text())
    assert c["fetched_at"] == 1000 + 46 * 60


def test_refresh_bypasses_ttl():
    ac.fetch(get=Fake(ok()), now=1000)
    f = Fake(ok(items=()))
    items, _ = ac.fetch(refresh=True, get=f, now=1001)
    assert len(f.calls) == 1 and items == []


def test_offline_shows_stale_cache_with_note():
    ac.fetch(get=Fake(ok()), now=1000)
    items, note = ac.fetch(get=Fake(OSError("down")), now=1000 + 3 * 3600)
    assert items and "stale" in note and "180 min ago" in note
    items, note = ac.fetch(offline=True, now=1000 + 3 * 3600)
    assert items and note.startswith("offline")


def test_offline_without_cache_and_rate_limited():
    items, note = ac.fetch(get=Fake(OSError("down")), now=1)
    assert items == [] and "no cache" in note
    ac.fetch(get=Fake(ok()), now=1000)
    items, note = ac.fetch(get=Fake((403, {}, b"rate limited")), now=1000 + 99999)
    assert items and "403" in note


def test_no_token_sent_unless_opted_in(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    f = Fake(ok())
    ac.fetch(get=f, now=1)
    assert "Authorization" not in f.calls[0][1]
    monkeypatch.setenv("FAMILIA_APP_CATALOG_TOKEN", "1")
    f = Fake(ok())
    ac.fetch(refresh=True, get=f, now=2)
    assert f.calls[0][1]["Authorization"] == "Bearer t0k"


def test_ttl_env_minutes(monkeypatch):
    monkeypatch.setenv("FAMILIA_APP_CATALOG_TTL", "5")
    assert ac.ttl_s() == 300


def test_apps_point_at_real_menu_items_and_scripts():
    keys = {l.split("|")[0] for l in (ROOT / "scripts" / "menu-items.txt").read_text(encoding="utf-8").splitlines()
            if l and not l.startswith("#")}
    ids = [a[0] for a in ac.APPS]
    assert len(ids) == len(set(ids))
    for i, _, kind, target in ac.APPS:
        if kind == "menu":
            assert target in keys, i
        else:
            assert (ROOT / target.split()[1]).exists(), i


def cli(*args, **env):
    e = dict(os.environ, FAMILIA_NO_TTY="1", FAMILIA_APP_CATALOG_API="http://127.0.0.1:9/none", **env)
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "app_catalog.py"), *args], cwd=ROOT,
                          capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL, timeout=60)


def test_cli_list_and_run_dry_run():
    r = cli("list")
    assert r.returncode == 0 and "web-ui" in r.stdout and "\033[" not in r.stdout
    r = cli("run", "web-ui", "--dry-run")
    assert r.returncode == 0 and "[dry-run] sh scripts/open_ui.sh" in r.stdout
    r = cli("run", "skills", "--dry-run")
    assert r.returncode == 0 and "[dry-run]" in r.stdout and "skills.py menu" in r.stdout
    assert cli("run", "nope").returncode == 1


def test_cli_search_offline_is_ascii_and_soft(cache_home):
    ac.fetch(get=Fake(ok()), now=1)  # stale cache
    r = cli("search", "app", XDG_CACHE_HOME=str(cache_home))
    assert r.returncode == 0, r.stderr
    r.stdout.encode("ascii")
    assert "NOTE:" in r.stdout and "#397" in r.stdout
    r = cli("search", "zzzz-nomatch", "--offline", XDG_CACHE_HOME=str(cache_home))
    assert "(public): 0" in r.stdout
