"""Tests for scripts/offline_queue.py (issue #332). Network and GitHub are mocked."""
from __future__ import annotations

import json
import os
import socket
import stat
import sys
import types
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import offline_queue as oq  # noqa: E402
import runtime_dir as rd  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    d = tmp_path / "state" / "familia" / "offline"
    d.mkdir(parents=True, mode=0o700)
    monkeypatch.setenv("FAMILIA_OFFLINE_DIR", str(d))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    return d


def test_state_dir_private_and_no_symlink(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    xdg.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg))
    monkeypatch.delenv("FAMILIA_OFFLINE_DIR", raising=False)
    got = oq.state_dir()
    assert got == xdg / "familia" / "offline"
    assert oct(got.stat().st_mode & 0o777) == "0o700"
    # planted symlink must be refused
    bad = tmp_path / "evil"
    bad.mkdir(mode=0o700)
    link = tmp_path / "link-offline"
    link.symlink_to(bad)
    monkeypatch.setenv("FAMILIA_OFFLINE_DIR", str(link))
    with pytest.raises((oq.OfflineQueueError, rd.RuntimeDirError, OSError)):
        oq.state_dir()


def test_run_context_one_mkdtemp_under_state_not_tmp(state, monkeypatch):
    seen = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def wrap_mkdtemp(*a, **kw):
        path = real_mkdtemp(*a, **kw)
        seen.append((kw.get("dir"), path))
        return path

    monkeypatch.setattr(oq.tempfile, "mkdtemp", wrap_mkdtemp)
    with oq.RunContext(state) as ctx:
        assert ctx.work is not None
        assert str(ctx.work).startswith(str(state))
        assert "/tmp/" not in str(ctx.work).replace(str(state), "")
        assert len(seen) == 1
        assert Path(seen[0][0]) == state
    assert ctx.work is None or not Path(seen[0][1]).exists()


def test_enqueue_and_list(state):
    with oq.RunContext(state) as ctx:
        e = oq.enqueue(
            "ping fleet",
            issue=332,
            repo="brianreborn/familia",
            state=ctx.state,
            work=ctx.work,
        )
        assert e["status"] == "queued"
        assert e["issue"] == 332
        path = oq._entry_path(ctx.state, e["id"])
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        rows = oq.list_entries(ctx.state)
        assert len(rows) == 1 and rows[0]["body"] == "ping fleet"


def test_enqueue_rejects_empty_and_bad_repo(state):
    with oq.RunContext(state) as ctx:
        with pytest.raises(oq.OfflineQueueError):
            oq.enqueue("  ", issue=332, state=ctx.state, work=ctx.work)
        with pytest.raises(oq.OfflineQueueError):
            oq.enqueue("x", issue=332, repo="noslash", state=ctx.state, work=ctx.work)


def test_ssh_probe_target_from_env_only(monkeypatch):
    monkeypatch.delenv("FAMILIA_OFFLINE_SSH_HOST", raising=False)
    monkeypatch.delenv("FAMILIA_SSH_HOST", raising=False)
    with pytest.raises(oq.OfflineQueueError):
        oq.ssh_probe_target({})
    monkeypatch.setenv("FAMILIA_OFFLINE_SSH_HOST", "CHANGE_ME")
    with pytest.raises(oq.OfflineQueueError):
        oq.ssh_probe_target()
    monkeypatch.setenv("FAMILIA_OFFLINE_SSH_HOST", "fleet-host.example")
    monkeypatch.setenv("FAMILIA_OFFLINE_SSH_PORT", "8022")
    assert oq.ssh_probe_target() == ("fleet-host.example", 8022)


def test_tcp_reachable_mocked():
    def ok_conn(addr, timeout=None):
        return types.SimpleNamespace(close=lambda: None)

    assert oq.tcp_reachable("h", 22, connector=ok_conn)[0] is True

    def bad_conn(addr, timeout=None):
        raise socket.timeout("timed out")

    ok, detail = oq.tcp_reachable("h", 22, connector=bad_conn)
    assert ok is False and "timed out" in detail


def test_termux_wifi_up_mocked():
    def run_up(cmd, capture_output=True, text=True, timeout=None):
        return types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"ssid": "Home", "ip": "10.0.0.2"}),
        )

    assert oq.termux_wifi_up(runner=run_up)[0] is True

    def run_off(cmd, capture_output=True, text=True, timeout=None):
        return types.SimpleNamespace(returncode=0, stdout="{}")

    assert oq.termux_wifi_up(runner=run_off)[0] is False

    def run_missing(cmd, capture_output=True, text=True, timeout=None):
        raise FileNotFoundError("nope")

    assert oq.termux_wifi_up(runner=run_missing)[0] is None


def test_probe_connectivity_online_offline(monkeypatch):
    monkeypatch.setenv("FAMILIA_OFFLINE_SSH_HOST", "fleet-host.example")
    monkeypatch.setenv("FAMILIA_OFFLINE_SSH_PORT", "22")

    def ok_conn(addr, timeout=None):
        return types.SimpleNamespace(close=lambda: None)

    r = oq.probe_connectivity(connector=ok_conn, skip_wifi=True)
    assert r["online"] is True and r["ssh"]["ok"] is True

    def bad_conn(addr, timeout=None):
        raise ConnectionRefusedError("refused")

    r2 = oq.probe_connectivity(connector=bad_conn, skip_wifi=True)
    assert r2["online"] is False


def test_backoff_schedule():
    assert oq.backoff_seconds(0) == 0
    assert oq.backoff_seconds(1, base=5, cap=300) == 5
    assert oq.backoff_seconds(2, base=5, cap=300) == 10
    assert oq.backoff_seconds(10, base=5, cap=300) == 300


def test_format_and_parse_marker():
    body = oq.format_comment_body("12345678-1234-1234-1234-123456789abc", "do the thing")
    assert "do the thing" in body
    assert oq.parse_marker(body) == "12345678-1234-1234-1234-123456789abc"
    assert oq.parse_marker("no marker here") is None


def test_flush_posts_via_injected_poster(state):
    with oq.RunContext(state) as ctx:
        e = oq.enqueue(
            "need status",
            issue=332,
            state=ctx.state,
            work=ctx.work,
            entry_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        posted = []

        def poster(repo, issue, body):
            posted.append((repo, issue, body))
            assert "familia-offline-queue:id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in body
            assert "need status" in body
            # Ensure no token-looking strings accidentally appear in body from env
            assert "gho_" not in body and "ghp_" not in body
            return {
                "id": 99,
                "html_url": "https://example.invalid/c/99",
                "created_at": "2026-11-09T17:00:00Z",
            }

        updated = oq.flush_queue(ctx.state, ctx.work, poster=poster)
        assert len(updated) == 1
        assert updated[0]["status"] == "posted"
        assert updated[0]["comment_id"] == 99
        assert len(posted) == 1
        # reload
        again = oq.load_entry(ctx.state, e["id"])
        assert again["status"] == "posted"


def test_pull_responses_stores_later_comments(state):
    eid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    with oq.RunContext(state) as ctx:
        e = oq.enqueue("q", issue=332, state=ctx.state, work=ctx.work, entry_id=eid)
        e["status"] = "posted"
        e["comment_id"] = 10
        e["posted_at"] = "2026-11-09T17:00:00Z"
        oq.save_entry(ctx.state, e, ctx.work)

        def getter(repo, issue, since):
            assert repo == "brianreborn/familia" and issue == 332
            return [
                {
                    "id": 10,
                    "body": oq.format_comment_body(eid, "q"),
                    "created_at": "2026-11-09T17:00:00Z",
                    "user": {"login": "phone"},
                    "html_url": "https://example.invalid/c/10",
                },
                {
                    "id": 11,
                    "body": "re: familia-offline-queue:id=%s\nhere is the answer" % eid,
                    "created_at": "2026-11-09T17:05:00Z",
                    "user": {"login": "brianreborn"},
                    "html_url": "https://example.invalid/c/11",
                },
            ]

        updated = oq.pull_responses(ctx.state, ctx.work, getter=getter)
        assert updated[0]["status"] == "responded"
        assert updated[0]["response_comment_ids"] == [11]
        rfile = oq.responses_dir(ctx.state) / ("%s.json" % eid)
        assert rfile.is_file()
        data = json.loads(rfile.read_text(encoding="utf-8"))
        assert "here is the answer" in data["responses"][0]["body"]
        assert oct(rfile.stat().st_mode & 0o777) == "0o600"


def test_post_issue_comment_rest_never_logs_token(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "gho_TESTTOKEN_NEVER_LOG")
    calls = {}

    class FakeResp:
        def read(self):
            return b'{"id": 7, "html_url": "https://example.invalid/c/7"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls["auth"] = req.get_header("Authorization")
        calls["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(oq.urllib.request, "urlopen", fake_urlopen)

    # Force REST path: pretend gh is missing
    def no_gh(*a, **k):
        raise FileNotFoundError("gh")

    out = oq.post_issue_comment(
        "brianreborn/familia",
        332,
        "hello",
        gh_runner=no_gh,
    )
    assert out["id"] == 7
    assert calls["auth"] == "Bearer gho_TESTTOKEN_NEVER_LOG"
    captured = capsys.readouterr()
    assert "gho_TESTTOKEN_NEVER_LOG" not in captured.out
    assert "gho_TESTTOKEN_NEVER_LOG" not in captured.err


def test_post_http_error_omits_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_SECRET")

    def no_gh(*a, **k):
        raise FileNotFoundError("gh")

    def boom(req, timeout=None):
        raise oq.urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", hdrs=None, fp=None
        )

    monkeypatch.setattr(oq.urllib.request, "urlopen", boom)
    with pytest.raises(oq.OfflineQueueError) as ei:
        oq.post_issue_comment("brianreborn/familia", 332, "x", gh_runner=no_gh)
    assert "ghp_SECRET" not in str(ei.value)
    assert "401" in str(ei.value)


def test_cli_enqueue_status_flush_pull_with_mocks(state, monkeypatch, capsys):
    monkeypatch.setenv("FAMILIA_OFFLINE_SSH_HOST", "fleet-host.example")
    monkeypatch.setenv("FAMILIA_OFFLINE_ISSUE", "332")

    def ok_conn(addr, timeout=None):
        return types.SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(oq, "tcp_reachable", lambda *a, **k: (True, "tcp ok"))
    monkeypatch.setattr(oq, "termux_wifi_up", lambda **k: (None, "skipped"))

    rc = oq.main(["enqueue", "--issue", "332", "--", "hello from phone"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    eid = out["id"]

    rc = oq.main(["status"])
    assert rc == 0
    st = json.loads(capsys.readouterr().out)
    assert st["counts"]["queued"] == 1

    def poster(repo, issue, body):
        return {"id": 42, "html_url": "u", "created_at": "2026-11-09T18:00:00Z"}

    monkeypatch.setattr(oq, "post_issue_comment", lambda *a, **k: poster(*a[:3]))
    rc = oq.main(["flush", "--force", "--no-wifi"])
    assert rc == 0
    flushed = json.loads(capsys.readouterr().out)
    assert flushed["flushed"][0]["status"] == "posted"

    def getter(repo, issue, since=None):
        return [
            {
                "id": 42,
                "body": oq.format_comment_body(eid, "hello from phone"),
                "created_at": "2026-11-09T18:00:00Z",
                "user": {"login": "phone"},
                "html_url": "u",
            },
            {
                "id": 43,
                "body": "ack " + eid,
                "created_at": "2026-11-09T18:01:00Z",
                "user": {"login": "brianreborn"},
                "html_url": "u2",
            },
        ]

    monkeypatch.setattr(
        oq,
        "list_issue_comments",
        lambda repo, issue, since=None, **k: getter(repo, issue, since),
    )
    rc = oq.main(["pull", "--force", "--no-wifi"])
    assert rc == 0
    pulled = json.loads(capsys.readouterr().out)
    assert pulled["pulled"][0]["status"] == "responded"


def test_flock_serializes_two_contexts(state):
    """Second RunContext blocks on flock; we only check the lock file exists and is ours."""
    lock = state / "offline.lock"
    with oq.RunContext(state) as ctx:
        assert lock.is_file()
        assert oct(lock.stat().st_mode & 0o777) == "0o600"
        assert not lock.is_symlink()
        # non-blocking lock from another open should fail while held
        import fcntl

        fd = rd.open_lock(str(lock))
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)



def test_default_issue_is_332(monkeypatch):
    monkeypatch.delenv("FAMILIA_OFFLINE_ISSUE", raising=False)
    assert oq.resolve_issue_number(None) == 332
    assert oq.DEFAULT_ISSUE == 332


def test_issue_env_and_flag_override(monkeypatch):
    monkeypatch.setenv("FAMILIA_OFFLINE_ISSUE", "400")
    assert oq.resolve_issue_number(None) == 400
    assert oq.resolve_issue_number(401) == 401  # CLI wins
    with pytest.raises(oq.OfflineQueueError):
        oq.resolve_issue_number(0)
    with pytest.raises(oq.OfflineQueueError):
        oq.parse_positive_issue(-3)
    with pytest.raises(oq.OfflineQueueError):
        oq.parse_positive_issue("nope")
    with pytest.raises(oq.OfflineQueueError):
        oq.parse_positive_issue("3.5")
    monkeypatch.setenv("FAMILIA_OFFLINE_ISSUE", "0")
    with pytest.raises(oq.OfflineQueueError):
        oq.resolve_issue_number(None)


def test_cli_enqueue_defaults_to_332(state, monkeypatch, capsys):
    monkeypatch.delenv("FAMILIA_OFFLINE_ISSUE", raising=False)
    rc = oq.main(["enqueue", "--", "default issue path"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["issue"] == 332


def test_cli_enqueue_rejects_non_positive_issue(state, capsys):
    with pytest.raises(SystemExit) as ei:
        oq.main(["enqueue", "--issue", "0", "--", "x"])
    assert ei.value.code == 2


def test_quotes_marker_helper():
    eid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert oq.quotes_marker("see <!-- familia-offline-queue:id=%s -->" % eid, eid)
    assert oq.quotes_marker("ack %s" % eid, eid)
    assert not oq.quotes_marker("unrelated later comment", eid)
    assert not oq.quotes_marker("", eid)


def test_pull_ignores_later_comments_without_marker_quote(state):
    eid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    with oq.RunContext(state) as ctx:
        e = oq.enqueue("q", issue=332, state=ctx.state, work=ctx.work, entry_id=eid)
        e["status"] = "posted"
        e["comment_id"] = 10
        e["posted_at"] = "2026-11-09T17:00:00Z"
        oq.save_entry(ctx.state, e, ctx.work)

        def getter(repo, issue, since):
            return [
                {
                    "id": 10,
                    "body": oq.format_comment_body(eid, "q"),
                    "created_at": "2026-11-09T17:00:00Z",
                    "user": {"login": "phone"},
                    "html_url": "u10",
                },
                {
                    "id": 11,
                    "body": "noise without quoting the marker",
                    "created_at": "2026-11-09T17:05:00Z",
                    "user": {"login": "brianreborn"},
                    "html_url": "u11",
                },
                {
                    "id": 12,
                    "body": "real reply quoting %s" % eid,
                    "created_at": "2026-11-09T17:06:00Z",
                    "user": {"login": "brianreborn"},
                    "html_url": "u12",
                },
            ]

        updated = oq.pull_responses(ctx.state, ctx.work, getter=getter)
        assert updated[0]["status"] == "responded"
        assert updated[0]["response_comment_ids"] == [12]
        assert "noise" not in json.dumps(updated[0])


def test_pull_ignores_other_enqueue_shaped_comments(state):
    eid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    other = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
    with oq.RunContext(state) as ctx:
        e = oq.enqueue("q", issue=332, state=ctx.state, work=ctx.work, entry_id=eid)
        e["status"] = "posted"
        e["comment_id"] = 10
        e["posted_at"] = "2026-11-09T17:00:00Z"
        oq.save_entry(ctx.state, e, ctx.work)

        def getter(repo, issue, since):
            return [
                {
                    "id": 10,
                    "body": oq.format_comment_body(eid, "q"),
                    "created_at": "2026-11-09T17:00:00Z",
                    "user": {"login": "phone"},
                    "html_url": "u10",
                },
                {
                    "id": 11,
                    "body": oq.format_comment_body(other, "another queued cmd"),
                    "created_at": "2026-11-09T17:05:00Z",
                    "user": {"login": "phone"},
                    "html_url": "u11",
                },
            ]

        updated = oq.pull_responses(ctx.state, ctx.work, getter=getter)
        # still posted — no quoting reply yet
        assert updated[0]["status"] == "posted"
        assert updated[0]["response_comment_ids"] == []


def test_no_tracked_secrets_in_module_source():
    """Privacy scan of the added module: no real IPs, tokens, or phone hostnames."""
    src = Path(oq.__file__).read_text(encoding="utf-8")
    # placeholders / examples only
    assert "CHANGE_ME" in src or "example" in src
    for needle in (
        "192.168.",
        "10.0.0.",
        "gho_",
        "ghp_",
        "github_pat_",
        "phone7",
        "phone8",
        "galaxy1",
        "galaxy2",
        "nexus",
        "@brian",
    ):
        # allow documented DEFAULT_REPO owner and marker text; block hostnames/IPs/tokens
        if needle in ("@brian",):
            continue
        if needle.startswith("gho_") or needle.startswith("ghp_"):
            assert needle + "TEST" not in src
            # the REST error-test lives in tests, not the module
            assert "gho_TESTTOKEN" not in src
        if needle in ("phone7", "phone8", "galaxy1", "galaxy2", "nexus"):
            assert needle not in src
        if needle.endswith("."):
            assert needle not in src


def test_source_has_no_antigravity_hotfile_edits():
    """Sanity: this feature is a new file only in scripts/ + tests/."""
    # Import path is the new module; hot files must remain untouched by our change set.
    hot = [
        "familia_home.sh",
        "proto_chat.sh",
        "open_ui.sh",
        "ui_bridge.py",
        "graph.yaml",
    ]
    for name in hot:
        # just ensure we did not replace them with wrappers that import us
        path = Path(ROOT) / "scripts" / name
        if not path.exists():
            path = Path(ROOT) / name
        if path.exists() and path.suffix in (".py", ".sh", ".yaml"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "offline_queue" not in text
