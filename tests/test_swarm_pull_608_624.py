#!/usr/bin/env python3
"""Triage mode, review mode, draft cooldown, and hollow re-pick (#608 #616 #624)."""
from __future__ import print_function

import os
import re
import unittest
from unittest import mock

import pytest

from test_swarm_pull_543 import PASSING_DRAFT, load_mod

SHA = "ab" * 20
OTHER = "cd" * 20
BASE = "ef" * 20


def _user(login, typ="User"):
    return {"login": login, "type": typ}


def _gh_commit(sha, login):
    """Shape of GET /repos/{owner}/{repo}/commits/{sha}. author.login is
    top-level. commit.author is name and email, and has no login."""
    person = None if not login else {"login": login, "id": 9, "type": "User"}
    return {
        "sha": sha,
        "html_url": "https://github.com/brianreborn/familia/commit/" + sha,
        "commit": {
            "message": "swarm/box: first pass\n",
            "author": {"name": "Swarm", "email": "s@example.com", "date": "2026-11-17T00:00:00Z"},
            "committer": {"name": "Swarm", "email": "s@example.com", "date": "2026-11-17T00:00:00Z"},
        },
        "author": person,
        "committer": person,
        "parents": [],
    }


def _pr(number=700, sha=SHA, draft=True, ref="swarm/box/616", title=None, body=None,
        repo="brianreborn/familia", login="swarm-bot"):
    """Shape of GET /repos/{owner}/{repo}/pulls. head has no commit object.
    head.user is the head repo owner, not the commit author."""
    owner = repo.split("/")[0]
    return {
        "number": number,
        "draft": draft,
        "title": title or "swarm/box: first pass for #616",
        "body": body or "Refs #616\n",
        "user": _user(login),
        "head": {
            "label": "%s:%s" % (owner, ref),
            "ref": ref,
            "sha": sha,
            "user": _user(owner),
            "repo": {"full_name": repo, "name": repo.split("/")[-1], "private": False},
        },
        "base": {
            "label": "brianreborn:main",
            "ref": "main",
            "sha": BASE,
            "repo": {"full_name": "brianreborn/familia", "name": "familia", "private": False},
        },
    }


def _good_patch():
    return "\n".join("+" + line if line else "+" for line in PASSING_DRAFT.splitlines())


class SwarmModes(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        self.addCleanup(self._env.stop)
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory(prefix="swarm-pull-608-")
        self.home = Path(self.tmp.name)
        self.sp = load_mod(self.home)
        os.environ["SWARM_JOB_LOCK"] = str(self.home / "job.lock")
        os.environ["SWARM_RUNNER_LOGINS"] = "swarm-bot,box"
        os.environ["SWARM_LEASE_JITTER_SEC"] = "0"
        self.sp._FORCED_DRY = False
        self.sp._FORGE_DATE_OK = True
        self._real_fetch = self.sp.fetch_commit
        self._fetch = mock.patch.object(
            self.sp, "fetch_commit",
            side_effect=lambda repo, sha: _gh_commit(sha, "swarm-bot"))
        self._fetch.start()
        self.addCleanup(self._fetch.stop)
        self.sp._VIEWER_CACHE.clear()
        self.sp._OWNER_CACHE["brianreborn/familia"] = {
            "login": "brianreborn", "id": 1, "fetched": True}
        self.addCleanup(self.tmp.cleanup)

    def _triage(self):
        os.environ["SWARM_MODE"] = "triage"
        self.sp._FORCED_DRY = False

    def _review(self):
        os.environ["SWARM_MODE"] = "review"
        self.sp._FORCED_DRY = False

    def test_high_effort_is_three_passes_with_thinking(self):
        calls = []

        def fake(prompt, max_tokens=700, thinking=False):
            calls.append((prompt, thinking))
            return "class: hollow\nwhy: empty note\n", "stub"

        os.environ["SWARM_MODEL_PASSES"] = "3"
        os.environ["SWARM_MODEL_THINK"] = "1"
        with mock.patch.object(self.sp, "model_draft", side_effect=fake):
            _text, how, nonce = self.sp.model_high_effort("classify this", 80)
        self.assertTrue(nonce)
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0][1])
        self.assertIn("Think step by step", calls[0][0])
        self.assertIn("Self-critique", calls[1][0])
        self.assertIn("Refine", calls[2][0])
        self.assertIn("high-effort", how)
        self.assertNotIn("<think>", _text)

    def test_signed_note_has_host_and_runner_only(self):
        os.environ["SWARM_MODE"] = "triage"
        body = self.sp.signed_note(
            "swarm-triage v=1 head=%s class=hollow" % SHA, "why: ok")
        body.encode("ascii")
        self.assertIn("host=testhost", body)
        self.assertIn("runner=box", body)
        self.assertIn("role=swarm-pull", body)
        self.assertFalse(self.sp.note_has_identifying_fields(body))
        for banned in ("user=", "uid=", "pid=", "session=", "node=", "/dev/pts"):
            self.assertNotIn(banned, body)

    def test_structural_failure_forces_hollow(self):
        with mock.patch.object(
                self.sp, "model_high_effort",
                return_value=("class: useful-notes\nwhy: looks long\n", "stub")):
            scored = self.sp.classify_draft_text("BEGIN UNTRUSTED\n" + ("word " * 50))
        self.assertEqual(scored["class"], "hollow")
        self.assertEqual(scored["structural"], "fence")
        self.assertEqual(scored["model"], "useful-notes")

    def test_triage_posts_one_comment_and_nothing_else(self):
        self._triage()
        pr = _pr()
        posted = []
        files = [{"filename": "docs/research/swarm-616-box.md", "patch": _good_patch()}]
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "get_pr_files", return_value=files), \
             mock.patch.object(self.sp, "get_pull", return_value=pr), \
             mock.patch.object(self.sp, "model_high_effort",
                               return_value=("class: useful-notes\nwhy: real notes\n", "stub")), \
             mock.patch.object(self.sp, "post_comment",
                               side_effect=lambda *a, **k: posted.append(a) or (None, 201, {"id": 1}, "")), \
             mock.patch.object(self.sp, "release_score_lease") as drop_lease, \
             mock.patch.object(self.sp, "del_label") as unlabel, \
             mock.patch.object(self.sp, "deliver") as deliver, \
             mock.patch.object(self.sp, "claim_issue") as claim, \
             mock.patch.object(self.sp, "release_issue") as release:
            self.assertEqual(self.sp.triage_one("brianreborn/familia", pr), "posted")
        bodies = [p[2] for p in posted]
        self.assertTrue(any(b.startswith("stamp ") and "swarm-lease v=1" in b for b in bodies))
        body = [b for b in bodies if "class=useful-notes" in b][0]
        self.assertIn("swarm-triage v=1 head=%s class=useful-notes" % SHA, body)
        self.assertIn("checks=pass", body)
        self.assertIn("runner=box", body)
        self.assertIn("host=testhost", body)
        body.encode("ascii")
        self.assertFalse(self.sp.note_has_identifying_fields(body))
        drop_lease.assert_called()
        unlabel.assert_not_called()
        deliver.assert_not_called()
        claim.assert_not_called()
        release.assert_not_called()

    def test_triage_idempotent_on_same_head(self):
        self._triage()
        pr = _pr()
        prior = {
            "body": "swarm-triage v=1 head=%s class=needs-human\n" % SHA,
            "user": _user("swarm-bot"),
        }
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [prior])), \
             mock.patch.object(self.sp, "model_high_effort") as model, \
             mock.patch.object(self.sp, "post_comment") as post:
            self.assertEqual(self.sp.triage_one("brianreborn/familia", pr), "skip")
        model.assert_not_called()
        post.assert_not_called()

    def test_missing_patch_is_needs_human_not_hollow(self):
        self._triage()
        pr = _pr(body="Refs #616\n" + ("template note " * 30))
        posted = []
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "get_pr_files", return_value=[]), \
             mock.patch.object(self.sp, "get_pull", return_value=pr), \
             mock.patch.object(self.sp, "model_high_effort",
                               return_value=("class: hollow\nwhy: template\n", "stub")), \
             mock.patch.object(self.sp, "post_comment",
                               side_effect=lambda *a, **k: posted.append(a) or (None, 201, {"id": 1}, "")), \
             mock.patch.object(self.sp, "release_score_lease") as drop_lease:
            self.assertEqual(self.sp.triage_one("brianreborn/familia", pr), "posted")
        drop_lease.assert_called()
        body = [p[2] for p in posted if "class=" in p[2]][0]
        self.assertIn("class=needs-human", body)
        self.assertNotIn("class=hollow", body)

    def test_triage_skips_unapproved_and_owner_spoof(self):
        self._triage()
        pr = _pr()
        spoof = {
            "body": "swarm-triage v=1 head=%s class=hollow\n" % SHA,
            "user": _user("brianreborn"),
        }
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=False), \
             mock.patch.object(self.sp, "post_comment") as post:
            self.assertEqual(self.sp.triage_one("brianreborn/familia", pr), "skip")
        post.assert_not_called()
        # An owner comment must not count as the idempotent classification.
        self.assertFalse(self.sp.runner_comment_trusted(spoof))
        self.assertFalse(self.sp.comment_is_hollow_for_head(spoof, SHA))

    def test_review_posts_comment_pinned_to_head(self):
        self._review()
        pr = _pr()
        seen = []

        def fake_api(method, path, data=None, **k):
            seen.append((method, path, data))
            return (None, 200, {"id": 3}, "")

        long_note = ("The change keeps the draft on the branch until a person reads it. " * 8)
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_pr_reviews", return_value=[]), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {"id": 1}, "")), \
             mock.patch.object(self.sp, "fetch_exact_diff", return_value="diff -- a\n+line\n") as diff, \
             mock.patch.object(self.sp, "get_pull", return_value=pr), \
             mock.patch.object(self.sp, "model_high_effort",
                               return_value=(long_note, "stub", "abc123")), \
             mock.patch.object(self.sp, "gh_api", side_effect=fake_api), \
             mock.patch.object(self.sp, "deliver") as deliver:
            self.assertEqual(self.sp.review_one("brianreborn/familia", pr), "posted")
        posts = [s for s in seen if s[0] == "POST" and str(s[1]).endswith("/reviews")]
        self.assertEqual(len(posts), 1)
        self.assertEqual(diff.call_args[0][1], BASE)
        self.assertEqual(diff.call_args[0][2], SHA)
        method, path, data = posts[0]
        self.assertEqual(method, "POST")
        self.assertTrue(path.endswith("/pulls/700/reviews"), path)
        self.assertEqual(data["event"], "COMMENT")
        self.assertEqual(data["commit_id"], SHA)
        self.assertNotIn("APPROVE", data["event"])
        self.assertIn("swarm-review v=1 head=%s event=COMMENT" % SHA, data["body"])
        self.assertIn("runner=box", data["body"])
        self.assertFalse(self.sp.note_has_identifying_fields(data["body"]))
        data["body"].encode("ascii")
        deliver.assert_not_called()
        self.assertEqual(self.sp.REVIEW_EVENT, "COMMENT")

    def test_review_skips_when_head_moves_or_already_reviewed(self):
        self._review()
        pr = _pr()
        moved = _pr(sha=OTHER)
        long_note = ("The change keeps the draft on the branch until a person reads it. " * 8)
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_pr_reviews", return_value=[]), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {"id": 1}, "")), \
             mock.patch.object(self.sp, "fetch_exact_diff", return_value="diff\n"), \
             mock.patch.object(self.sp, "get_pull", return_value=moved), \
             mock.patch.object(self.sp, "model_high_effort", return_value=(long_note, "stub", "")), \
             mock.patch.object(self.sp, "gh_api") as api:
            self.assertEqual(self.sp.review_one("brianreborn/familia", pr), "skip")
        self.assertFalse(any(c.args[0] == "POST" and str(c.args[1]).endswith("/reviews") for c in api.call_args_list))
        self.assertTrue(any(c.args[0] == "DELETE" for c in api.call_args_list))
        prior = {"body": "swarm-review v=1 head=%s event=COMMENT\n" % SHA, "user": _user("swarm-bot")}
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_pr_reviews", return_value=[prior]), \
             mock.patch.object(self.sp, "fetch_exact_diff") as diff, \
             mock.patch.object(self.sp, "gh_api") as api:
            self.assertEqual(self.sp.review_one("brianreborn/familia", pr), "skip")
        diff.assert_not_called()
        api.assert_not_called()

    def test_review_refuses_unapproved(self):
        self._review()
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=False), \
             mock.patch.object(self.sp, "fetch_exact_diff") as diff, \
             mock.patch.object(self.sp, "gh_api") as api:
            self.assertEqual(self.sp.review_one("brianreborn/familia", _pr()), "skip")
        diff.assert_not_called()
        api.assert_not_called()

    def test_modes_require_their_env(self):
        os.environ["SWARM_MODE"] = "live"
        self.assertEqual(self.sp.cmd_triage(), 2)
        self.assertEqual(self.sp.cmd_review(), 2)

    def test_triage_identity_refuses_owner_token(self):
        os.environ["SWARM_MODE"] = "triage"
        self.sp._FORCED_DRY = False
        self.sp._VIEWER_CACHE.clear()
        with mock.patch.object(self.sp, "forge_viewer",
                               return_value={"login": "brianreborn", "id": 1, "type": "User"}), \
             mock.patch.object(self.sp, "repo_owner_record",
                               return_value={"login": "brianreborn", "id": 1, "fetched": True}):
            self.assertEqual(self.sp.enforce_live_identity("brianreborn/familia"), "dry-run")
        self.assertEqual(self.sp.mode(), "dry-run")
        self.assertEqual(self.sp.cmd_triage(), 2)

    def test_non_owner_stays_in_triage(self):
        os.environ["SWARM_MODE"] = "triage"
        self.sp._FORCED_DRY = False
        self.sp._VIEWER_CACHE.clear()
        with mock.patch.object(self.sp, "forge_viewer",
                               return_value={"login": "swarm-bot", "id": 9, "type": "User"}), \
             mock.patch.object(self.sp, "repo_owner_record",
                               return_value={"login": "brianreborn", "id": 1, "fetched": True}):
            self.assertEqual(self.sp.enforce_live_identity("brianreborn/familia"), "triage")
        self.assertEqual(self.sp.mode(), "triage")

    def test_hollow_repick_only_when_every_open_pr_is_hollow(self):
        pr = _pr()
        hollow = {
            "body": "swarm-triage v=1 head=%s class=hollow checks=fail\n" % SHA,
            "user": _user("swarm-bot"),
        }
        self.assertTrue(self.sp.hollow_repick_ok(616, [pr], lambda n: [hollow]))
        useful = {
            "body": "swarm-triage v=1 head=%s class=useful-notes\n" % SHA,
            "user": _user("swarm-bot"),
        }
        self.assertFalse(self.sp.hollow_repick_ok(616, [pr], lambda n: [useful]))
        owner = {"body": hollow["body"], "user": _user("brianreborn")}
        self.assertFalse(self.sp.hollow_repick_ok(616, [pr], lambda n: [owner]))
        stale = {
            "body": "swarm-triage v=1 head=%s class=hollow\n" % OTHER,
            "user": _user("swarm-bot"),
        }
        self.assertFalse(self.sp.hollow_repick_ok(616, [pr], lambda n: [stale]))
        other = _pr(number=701, sha=OTHER, draft=False, ref="feature/x", title="also #616")
        self.assertFalse(self.sp.hollow_repick_ok(616, [pr, other], lambda n: [hollow]))

    def _candidates(self, refs, hollow):
        issue = {"number": 616, "created_at": "2026-11-10T20:00:00Z",
                 "labels": [{"name": "swarm-approved"}], "assignees": [],
                 "title": "gate", "body": "body"}
        dt = self.sp.parse_iso("2026-11-17T00:00:00Z")
        with mock.patch.object(self.sp, "gh_api_pages", return_value=(dt, [issue])), \
             mock.patch.object(self.sp, "gh_api", return_value=(dt, 200, {"items": []}, "")), \
             mock.patch.object(self.sp, "open_pr_refs", return_value=set(refs)), \
             mock.patch.object(self.sp, "hollow_repick_issues", return_value=set(hollow)), \
             mock.patch.object(self.sp, "repo_owner_login", return_value="brianreborn"), \
             mock.patch.object(self.sp, "issue_admin_approved", return_value=True):
            return [i["number"] for i in self.sp.candidate_issues("brianreborn/familia")]

    def test_candidate_repicks_hollow_issue(self):
        self.assertEqual(self._candidates([616], [616]), [616])
        self.assertEqual(self._candidates([616], []), [])

    def test_cooldown_doubles_and_pick_skips(self):
        now = self.sp.parse_iso("2026-11-17T00:00:00Z")
        row = self.sp.record_draft_cooldown("brianreborn/familia", 616, "nonce", now=now)
        self.assertEqual(row["delay_h"], 6)
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [])) as fetched:
            self.assertTrue(self.sp.cooldown_active(
                "brianreborn/familia", 616, now=now + self.sp.timedelta(hours=5),
                comments=[]))
            self.assertFalse(self.sp.cooldown_active(
                "brianreborn/familia", 616, now=now + self.sp.timedelta(hours=7),
                comments=[]))
            self.assertEqual(fetched.call_count, 0)
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "nonce", now=now)["delay_h"], 12)
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "short", now=now)["delay_h"], 24)
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "short", now=now)["delay_h"], 48)
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "short", now=now)["delay_h"], 48)
        self.sp.record_draft_cooldown("brianreborn/familia", 616, "short")
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "candidate_issues", return_value=[{"number": 616}]), \
             mock.patch.object(self.sp, "claim_issue") as claim:
            n, _c = self.sp.pick_next("brianreborn/familia")
        self.assertIsNone(n)
        claim.assert_not_called()

    def test_gate_off_lets_nonce_draft_reach_deliver(self):
        os.environ["SWARM_MODE"] = "live"
        os.environ["SWARM_DRAFT_GATE"] = "0"
        os.environ["SWARM_DRAFT_GATE_OFF_I_KNOW"] = "box"
        self.sp._GATE_LOGGED = False
        gate = self.sp.ApprovalResult(True, reason="approved", body="approved body", title="t")

        def fake(prompt, n, thinking=False):
            import re
            m = re.search(r"nonce=([0-9a-fA-F]+)", prompt)
            return ("leaked %s\n" % m.group(1)) + ("pad " * 40), "stub"

        with mock.patch.object(self.sp, "get_issue", return_value=(None, {"number": 999, "state": "open"})), \
             mock.patch.object(self.sp, "approval_status", return_value=gate), \
             mock.patch.object(self.sp, "model_draft", side_effect=fake), \
             mock.patch.object(self.sp, "recheck_gate", return_value=gate), \
             mock.patch.object(self.sp, "deliver", return_value={"new_pr": False}) as dl:
            self.sp.job("brianreborn/familia", 999, 1)
        dl.assert_called_once()

    def test_probe_only_fallback_skips_the_gate(self):
        os.environ["SWARM_MODE"] = "dry-run"
        gate = self.sp.ApprovalResult(True, reason="approved", body="approved body", title="t")
        with mock.patch.dict(self.sp.PROBES, {383: lambda: "measured probe\n"}), \
             mock.patch.object(self.sp, "get_issue", return_value=(None, {"number": 383, "state": "open"})), \
             mock.patch.object(self.sp, "approval_status", return_value=gate), \
             mock.patch.object(self.sp, "model_draft", side_effect=self.sp.ForgeError("down")):
            out = self.sp.job("brianreborn/familia", 383, 1)
        self.assertTrue(out.get("dry"))
        work = self.home / "work" / "brianreborn_familia" / "383"
        self.assertIn("local model unavailable", (work / "draft.md").read_text())
        self.assertFalse((work / "draft.rejected.md").exists())

    def test_fleet_cooldown_from_reject_comment(self):
        now = self.sp.parse_iso("2026-11-17T12:00:00Z")
        comment = {
            "body": "SUPERSEDED draft rejected: fence\nstamp v=1\n",
            "updated_at": "2026-11-17T11:00:00Z",
            "user": _user("swarm-bot"),
        }
        with mock.patch.object(self.sp, "get_comments", return_value=(now, [comment])):
            self.assertTrue(self.sp.cooldown_active(
                "brianreborn/familia", 616, now=now))
        later = now + self.sp.timedelta(hours=7)
        with mock.patch.object(self.sp, "get_comments", return_value=(later, [comment])):
            self.assertFalse(self.sp.cooldown_active(
                "brianreborn/familia", 616, now=later))

    def test_cooldown_is_saved_before_release(self):
        os.environ["SWARM_MODE"] = "live"
        self.sp._FORCED_DRY = False
        order = []
        self.sp.save_state({
            "repo": "brianreborn/familia", "number": 9, "runner": "box",
            "claim": {"ok": True, "gen": 1, "comment_id": 1, "until": "2099-01-01T00:00:00Z"},
        })
        disarmed = self.home / "disarmed"

        def rec(*a, **k):
            order.append("cooldown")
            return {"delay_h": 6}

        def rel(*a, **k):
            order.append("release")

        with mock.patch.object(self.sp, "flush_outbox"), \
             mock.patch.object(self.sp, "get_issue", return_value=(None, {"number": 9})), \
             mock.patch.object(self.sp, "issue_admin_approved", return_value=True), \
             mock.patch.object(self.sp, "confirm_claim_still_first", return_value=True), \
             mock.patch.object(self.sp, "load_gate", return_value=""), \
             mock.patch.object(self.sp, "heartbeat_issue", return_value="2099-01-01T00:00:00Z"), \
             mock.patch.object(self.sp, "record_draft_cooldown", side_effect=rec), \
             mock.patch.object(self.sp, "release_issue", side_effect=rel), \
             mock.patch.object(self.sp, "job", side_effect=self.sp.DraftRejected("fence", "draft contains untrusted fence markers")), \
             mock.patch.object(self.sp.time, "sleep", side_effect=lambda s: disarmed.write_text("x")):
            self.sp.cmd_loop()
        self.assertEqual(order[:2], ["cooldown", "release"])

    def test_hollow_cap_and_agreement(self):
        pr = _pr()
        one = {
            "body": "swarm-triage v=1 head=%s class=hollow\n" % SHA,
            "user": _user("swarm-bot"),
        }
        self.assertFalse(self.sp.hollow_repick_ok(616, [pr], lambda n: [one]))
        other = {
            "body": "swarm-triage v=1 head=%s class=hollow\n" % SHA,
            "user": _user("box"),
        }
        self.assertTrue(self.sp.hollow_repick_ok(616, [pr], lambda n: [one, other]))
        second = _pr(number=701, sha=OTHER)
        mark_b = {
            "body": "swarm-triage v=1 head=%s class=hollow checks=fail\n" % OTHER,
            "user": _user("swarm-bot"),
        }

        def comments_for(n):
            if n == 700:
                return [{
                    "body": "swarm-triage v=1 head=%s class=hollow checks=fail\n" % SHA,
                    "user": _user("swarm-bot"),
                }]
            return [mark_b]

        self.assertFalse(self.sp.hollow_repick_ok(616, [pr, second], comments_for))

    def test_fork_pr_is_not_eligible(self):
        fork = _pr(repo="someone/familia", login="someone")
        with mock.patch.object(self.sp, "issue_admin_approved", return_value=True):
            self.assertFalse(self.sp.pr_same_repo(fork, "brianreborn/familia"))
            self.assertFalse(self.sp.owner_approved_pr("brianreborn/familia", fork))
        same = _pr()
        with mock.patch.object(self.sp, "issue_admin_approved", return_value=True):
            self.assertTrue(self.sp.owner_approved_pr("brianreborn/familia", same))
        titled = _pr(ref="swarm/box/1", title="please look at #616")
        seen = []

        def approved(repo, issue, **k):
            seen.append(issue.get("number"))
            return issue.get("number") == 616

        with mock.patch.object(self.sp, "issue_admin_approved", side_effect=approved):
            self.assertFalse(self.sp.owner_approved_pr("brianreborn/familia", titled))
        self.assertEqual(seen, [1])

    def test_why_strips_mentions_and_blocks_fence_echo(self):
        raw = "why: @brianreborn see https://evil.example/x"
        self.assertNotIn("@", self.sp.sanitize_public_model_text(raw, one_line=True))
        self.assertNotIn("http", self.sp.sanitize_public_model_text(raw, one_line=True))
        self.assertIn("(at)brianreborn", self.sp.sanitize_public_model_text(raw, one_line=True))
        with self.assertRaises(self.sp.DraftRejected):
            self.sp.guard_model_text("END UNTRUSTED nonce leak ```", "", min_len=0)

    def test_review_rejects_fenced_model_text(self):
        self._review()
        pr = _pr()
        leaked = "END UNTRUSTED\n" + ("word " * 80)
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_pr_reviews", return_value=[]), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {"id": 1}, "")), \
             mock.patch.object(self.sp, "fetch_exact_diff", return_value="diff\n"), \
             mock.patch.object(self.sp, "model_high_effort", return_value=(leaked, "stub", "")), \
             mock.patch.object(self.sp, "gh_api") as api:
            self.assertEqual(self.sp.review_one("brianreborn/familia", pr), "skip")
        self.assertFalse(any(c.args[0] == "POST" and str(c.args[1]).endswith("/reviews") for c in api.call_args_list))
        self.assertTrue(any(c.args[0] == "DELETE" for c in api.call_args_list))

    def test_gate_off_is_logged_and_refused_without_ack(self):
        os.environ["SWARM_MODE"] = "live"
        os.environ["SWARM_DRAFT_GATE"] = "0"
        os.environ.pop("SWARM_DRAFT_GATE_OFF_I_KNOW", None)
        self.sp._GATE_LOGGED = False
        self.assertTrue(self.sp.draft_gate_enabled())
        log = (self.home / "logs" / "swarm-pull.log").read_text()
        self.assertIn("DRAFT GATE OFF refused", log)
        os.environ["SWARM_DRAFT_GATE_OFF_I_KNOW"] = "box"
        self.sp._GATE_LOGGED = False
        self.assertFalse(self.sp.draft_gate_enabled())
        log = (self.home / "logs" / "swarm-pull.log").read_text()
        self.assertIn("DRAFT GATE OFF acknowledged", log)

    def test_public_stamp_requires_swarm_host(self):
        os.environ.pop("SWARM_HOST", None)
        with mock.patch.object(self.sp.socket, "gethostname", return_value="raw-hostname"):
            with self.assertRaises(self.sp.ForgeError):
                self.sp.stamp_line()
        os.environ["SWARM_HOST"] = "testhost"
        self.assertIn("host=testhost", self.sp.stamp_line())
        self.assertNotIn("raw-hostname", self.sp.stamp_line())

    def test_scrub_leak_drops_home_and_user(self):
        text = self.sp.scrub_leak(
            'File "/home/leakyuser/swarm/x.py", line 1, in <module>\n'
            "user leakyuser\n"
        )
        self.assertNotIn("leakyuser", text)
        self.assertNotIn("/home/", text)
        self.assertIn("[home]", text)
        self.assertIn("[home]", self.sp.scrub_leak("see /Users/leakyuser/Library/x"))
        self.assertIn("[home]", self.sp.scrub_leak(r"C:\Users\leakyuser\AppData\x"))
        self.assertNotIn("leakyuser", self.sp.scrub_leak("log /srv/leakyuser/run.log"))

    def test_runner_name_does_not_use_hostname(self):
        os.environ.pop("SWARM_RUNNER", None)
        os.environ["HOST"] = "from-host-env"
        os.environ["SWARM_HOST"] = "from-swarm-host"
        with mock.patch.object(self.sp.socket, "gethostname", return_value="raw-hostname"):
            self.assertEqual(self.sp.runner_name(), "from-swarm-host")
            os.environ.pop("SWARM_HOST", None)
            with self.assertRaises(self.sp.ForgeError):
                self.sp.runner_name()
        os.environ["SWARM_RUNNER"] = "box"
        self.assertEqual(self.sp.runner_name(), "box")

    def test_gate_off_requires_ack_in_triage(self):
        os.environ["SWARM_MODE"] = "triage"
        os.environ["SWARM_DRAFT_GATE"] = "0"
        os.environ.pop("SWARM_DRAFT_GATE_OFF_I_KNOW", None)
        self.sp._GATE_LOGGED = False
        self.assertTrue(self.sp.draft_gate_enabled())
        log = (self.home / "logs" / "swarm-pull.log").read_text()
        self.assertIn("DRAFT GATE OFF refused", log)
        self.assertNotIn("acknowledged", log)

    def test_hollow_history_on_one_pr_hits_the_cap(self):
        pr = _pr()
        comments = []
        for sha in (SHA, OTHER, "ab" * 20):
            comments.append({
                "body": "swarm-triage v=1 head=%s class=hollow checks=fail\n" % sha,
                "user": _user("swarm-bot"),
            })
        # SHA is repeated as the third; two distinct heads are enough.
        comments.append({
            "body": "swarm-triage v=1 head=%s class=hollow checks=fail\n" % ("12" * 20),
            "user": _user("swarm-bot"),
        })
        self.assertFalse(self.sp.hollow_repick_ok(616, [pr], lambda n: comments))

    def test_electrobrian_on_galaxy1_is_eligible(self):
        os.environ["SWARM_RUNNER_LOGINS"] = "electrobrian"
        pr = _pr(number=800, ref="swarm/galaxy1/476", login="electrobrian",
                 title="swarm/galaxy1: first pass for #476", body="Refs #476\n")
        with mock.patch.object(self.sp, "issue_admin_approved", return_value=True):
            self.assertTrue(self.sp.pr_branch_trusted(pr))
            self.assertTrue(self.sp.owner_approved_pr("brianreborn/familia", pr))
        stranger = _pr(ref="swarm/galaxy1/476", login="someone-else")
        self.assertFalse(self.sp.pr_branch_trusted(stranger))

    def test_fork_pr_does_not_block_the_issue(self):
        fork = _pr(repo="someone/familia", login="electrobrian",
                   title="also #616", body="Refs #616\n")
        same = _pr()
        with mock.patch.object(self.sp, "list_open_pulls", return_value=[fork, same]):
            refs = self.sp.open_pr_refs("brianreborn/familia")
        self.assertIn(616, refs)
        with mock.patch.object(self.sp, "list_open_pulls", return_value=[fork]):
            self.assertEqual(self.sp.open_pr_refs("brianreborn/familia"), set())

    def test_release_keeps_label_when_comment_edit_fails(self):
        self._live() if hasattr(self, "_live") else None
        os.environ["SWARM_MODE"] = "live"
        self.sp._FORCED_DRY = False
        self.sp._VIEWER_CACHE.update({"login": "swarm-bot", "id": 9})
        claim = {
            "id": 4,
            "body": "stamp v=1\n-- box claim gen 1 lease-until 2099-01-01T00:00:00Z\n",
            "user": _user("swarm-bot"),
        }
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [claim])), \
             mock.patch.object(self.sp, "edit_comment", side_effect=self.sp.ForgeError("HTTP 500")), \
             mock.patch.object(self.sp, "del_label") as label, \
             mock.patch.object(self.sp, "get_issue", return_value=(None, {"number": 9, "labels": []})), \
             mock.patch.object(self.sp, "repo_owner_login", return_value="brianreborn"):
            self.sp.release_issue("brianreborn/familia", 9, "draft rejected: fence", claim=None)
        label.assert_not_called()

    def test_instructions_stay_outside_the_fence(self):
        prompts = []

        def fake(prompt, max_tokens=700, thinking=False):
            prompts.append(prompt)
            return "class: useful-notes\nwhy: fine\n", "stub"

        with mock.patch.object(self.sp, "model_draft", side_effect=fake):
            self.sp.model_high_effort(
                "INSTRUCTION-LINE", 40, untrusted="DRAFT-BODY", kind="DRAFT")
        self.assertIn("INSTRUCTION-LINE", prompts[0])
        self.assertLess(prompts[0].index("INSTRUCTION-LINE"), prompts[0].index("BEGIN UNTRUSTED"))
        self.assertIn("DRAFT-BODY", prompts[0].split("BEGIN UNTRUSTED", 1)[1])
        withheld, _nonce = self.sp._fenced_or_withheld("BEGIN UNTRUSTED\nstuff", "DIFF")
        self.assertIn("withheld", withheld)

    def test_why_neutralizes_markup(self):
        raw = '<img src=//host/p> www.host other/repo#12 **x**'
        clean = self.sp.sanitize_public_model_text(raw, one_line=True)
        self.assertNotIn("<", clean)
        self.assertNotIn("//", clean)
        self.assertNotIn("www.host", clean)
        self.assertNotIn("other/repo#12", clean)
        self.assertNotIn("**", clean)

    def test_collaborator_head_does_not_repick(self):
        pr = _pr()
        self.assertNotIn("commit", pr["head"])
        hollow = {
            "body": "swarm-triage v=1 head=%s class=hollow checks=fail\nrunner=box\n" % SHA,
            "user": _user("swarm-bot"),
        }
        with mock.patch.object(
                self.sp, "fetch_commit",
                side_effect=lambda repo, sha: _gh_commit(sha, "collaborator")):
            self.assertFalse(self.sp.hollow_repick_ok(616, [pr], lambda n: [hollow]))
        os.environ["SWARM_HOLLOW_FROM_COLLAB"] = "1"
        self.assertTrue(self.sp.hollow_repick_ok(616, [pr], lambda n: [hollow]))
        os.environ.pop("SWARM_HOLLOW_FROM_COLLAB", None)
        self.assertFalse(self.sp.hollow_from_collab())

    def test_fresh_own_lease_is_reused(self):
        self._review()
        self.sp._VIEWER_CACHE.update({"login": "swarm-bot", "id": 9})
        lease = {
            "id": 5,
            "body": "swarm-lease v=1 head=%s kind=review runner=box\n" % SHA,
            "user": _user("swarm-bot"),
            "created_at": "2099-01-01T00:00:00Z",
            "updated_at": "2099-01-01T00:00:00Z",
        }
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [lease])), \
             mock.patch.object(self.sp, "post_comment") as post, \
             mock.patch.object(self.sp, "strike_own_comment") as strike:
            held = self.sp.acquire_score_lease("brianreborn/familia", 700, SHA, "review")
        self.assertEqual(held, 5)
        post.assert_not_called()
        strike.assert_not_called()

    def test_lease_without_id_does_not_score(self):
        self._review()
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {}, "")):
            held = self.sp.acquire_score_lease("brianreborn/familia", 700, SHA, "review")
        self.assertIsNone(held)

    def test_fence_in_issue_text_is_not_a_draft_cooldown(self):
        os.environ["SWARM_MODE"] = "live"
        self.sp._FORCED_DRY = False
        gate = self.sp.ApprovalResult(
            True, reason="approved", body="see BEGIN UNTRUSTED in the notes", title="t")
        with mock.patch.object(self.sp, "get_issue", return_value=(None, {"number": 999, "state": "open"})), \
             mock.patch.object(self.sp, "approval_status", return_value=gate), \
             mock.patch.object(self.sp, "record_draft_cooldown") as cool, \
             mock.patch.object(self.sp, "deliver") as dl:
            with self.assertRaises(self.sp.NotApproved):
                self.sp.job("brianreborn/familia", 999, 1)
        cool.assert_not_called()
        dl.assert_not_called()

    def test_other_runner_lease_is_not_ours(self):
        self._review()
        self.sp._VIEWER_CACHE.update({"login": "swarm-bot", "id": 9})
        lease = {
            "id": 5,
            "body": "swarm-lease v=1 head=%s kind=review runner=galaxy1\n" % SHA,
            "user": _user("swarm-bot"),
            "created_at": "2099-01-01T00:00:00Z",
            "updated_at": "2099-01-01T00:00:00Z",
        }
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [lease])), \
             mock.patch.object(self.sp, "post_comment") as post, \
             mock.patch.object(self.sp, "strike_own_comment") as strike:
            held = self.sp.acquire_score_lease("brianreborn/familia", 700, SHA, "review")
        self.assertIsNone(held)
        post.assert_not_called()
        strike.assert_not_called()

    def test_stale_other_lease_does_not_delete_ours(self):
        self._review()
        self.sp._VIEWER_CACHE.update({"login": "swarm-bot", "id": 9})
        stale = {
            "id": 1,
            "body": "swarm-lease v=1 head=%s kind=review runner=galaxy1\n" % SHA,
            "user": _user("swarm-bot"),
            "updated_at": "2020-01-01T00:00:00Z",
        }
        calls = {"n": 0}

        def comments(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                return (None, [stale])
            return (None, [stale, {
                "id": 8,
                "body": "swarm-lease v=1 head=%s kind=review runner=box\n" % SHA,
                "user": _user("swarm-bot"),
                "updated_at": "2099-01-01T00:00:00Z",
            }])

        with mock.patch.object(self.sp, "get_comments", side_effect=comments), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {"id": 8}, "")) as post, \
             mock.patch.object(self.sp, "strike_own_comment") as strike:
            held = self.sp.acquire_score_lease("brianreborn/familia", 700, SHA, "review")
        self.assertEqual(held, 8)
        body = post.call_args[0][2]
        self.assertIn("swarm-lease v=1 head=%s kind=review runner=box" % SHA, body)
        struck = [c.args[1] for c in strike.call_args_list]
        self.assertIn(1, struck)
        self.assertNotIn(8, struck)

    def test_missing_forge_clock_does_not_treat_lease_as_stale(self):
        self._review()
        self.sp._FORGE_DATE_OK = False
        lease = {
            "id": 5,
            "body": "swarm-lease v=1 head=%s kind=review runner=box\n" % SHA,
            "user": _user("swarm-bot"),
            "updated_at": "2099-01-01T00:00:00Z",
        }
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [lease])), \
             mock.patch.object(self.sp, "post_comment") as post, \
             mock.patch.object(self.sp, "strike_own_comment") as strike:
            held = self.sp.acquire_score_lease("brianreborn/familia", 700, SHA, "review")
        self.assertIsNone(held)
        post.assert_not_called()
        strike.assert_not_called()

    def test_commit_api_not_pulls_head(self):
        pr = _pr(login="swarm-bot")
        self.assertNotIn("commit", pr["head"])
        self.assertEqual(pr["head"]["user"]["login"], "brianreborn")
        seen = []

        def api(method, path, **_k):
            seen.append((method, path))
            return (None, 200, _gh_commit(SHA, "swarm-bot"), "")

        with mock.patch.object(self.sp, "fetch_commit", self._real_fetch), \
             mock.patch.object(self.sp, "gh_api", side_effect=api):
            self.assertTrue(self.sp.head_commit_owned("brianreborn/familia", pr))
        self.assertEqual(seen, [("GET", "repos/brianreborn/familia/commits/" + SHA)])
        self.sp.reset_api_budget()
        nameless = _gh_commit(SHA, None)
        nameless["commit"]["author"]["name"] = "swarm-bot"

        def api_name(method, path, **_k):
            return (None, 200, nameless, "")

        with mock.patch.object(self.sp, "fetch_commit", self._real_fetch), \
             mock.patch.object(self.sp, "gh_api", side_effect=api_name):
            self.assertFalse(self.sp.head_commit_owned("brianreborn/familia", pr))

    def test_pushed_sha_owns_the_head(self):
        pr = _pr()
        with mock.patch.object(self.sp, "fetch_commit", side_effect=self.sp.ForgeError("no")):
            self.assertFalse(self.sp.head_commit_owned("brianreborn/familia", pr))
            self.sp.record_pushed_sha("brianreborn/familia", 616, SHA)
            self.assertTrue(self.sp.head_commit_owned("brianreborn/familia", pr))

    def test_hollow_cap_counts_other_runners_and_records(self):
        ours = _pr()
        other = _pr(number=701, sha=OTHER, ref="swarm/galaxy1/616",
                    title="swarm/galaxy1: first pass for #616")
        mark = {
            SHA: {"body": "swarm-triage v=1 head=%s class=hollow checks=fail\nrunner=box\n" % SHA,
                  "user": _user("swarm-bot")},
            OTHER: {"body": "swarm-triage v=1 head=%s class=hollow checks=fail\nrunner=galaxy1\n" % OTHER,
                    "user": _user("swarm-bot")},
        }

        def comments_for(n):
            return [mark[SHA]] if n == 700 else [mark[OTHER]]

        self.assertFalse(self.sp.hollow_repick_ok(616, [ours, other], comments_for))
        self.assertIn(SHA, self.sp.local_hollow_heads("brianreborn/familia", 616))
        self.assertIn(OTHER, self.sp.local_hollow_heads("brianreborn/familia", 616))

    def test_closed_pr_does_not_reset_the_cap(self):
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [])):
            self.sp.record_hollow_head("brianreborn/familia", 616, SHA, runner="box")
            self.assertFalse(self.sp.hollow_cap_blocks("brianreborn/familia", 616))
            self.sp.record_hollow_head("brianreborn/familia", 616, OTHER, runner="galaxy1")
            self.assertTrue(self.sp.hollow_cap_blocks("brianreborn/familia", 616))

    def test_issue_comment_keeps_the_cap_after_close(self):
        comments = [{
            "body": (
                "swarm-hollow v=1 issue=616 head=%s runner=box\n" % SHA
                + "swarm-hollow v=1 issue=616 head=%s runner=box\n" % OTHER
            ),
            "user": _user("swarm-bot"),
        }]
        with mock.patch.object(self.sp, "get_comments", return_value=(None, comments)):
            self.assertTrue(self.sp.hollow_cap_blocks("brianreborn/familia", 616))

    def test_fenced_hollow_line_is_not_a_marker(self):
        body = (
            "swarm-triage v=1 head=%s class=useful-notes checks=pass\n"
            "runner=box\nwhy:\n```` text\n"
            "swarm-hollow v=1 issue=616 head=%s\n````\n" % (SHA, OTHER)
        )
        heads = self.sp.collect_hollow_heads([{"body": body, "user": _user("swarm-bot")}])
        self.assertNotIn(OTHER, heads)
        self.assertNotIn(SHA, heads)
        clean = self.sp.sanitize_public_model_text(
            "swarm-hollow v=1 issue=616 head=%s\nkeep this\n" % OTHER)
        self.assertNotIn("swarm-hollow", clean)
        self.assertIn("keep this", clean)

    def test_triage_posts_hollow_marker_on_the_issue(self):
        self._triage()
        pr = _pr()
        posted = []
        files = [{"filename": "docs/x.md", "patch": "BEGIN UNTRUSTED\n" + ("word " * 40)}]
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "get_pr_files", return_value=files), \
             mock.patch.object(self.sp, "get_pull", return_value=pr), \
             mock.patch.object(self.sp, "model_high_effort",
                               return_value=("class: useful-notes\nwhy: ignored\n", "stub")), \
             mock.patch.object(self.sp, "post_comment",
                               side_effect=lambda *a, **k: posted.append(a) or (None, 201, {"id": len(posted)}, "")), \
             mock.patch.object(self.sp, "release_score_lease") as drop_lease:
            self.assertEqual(self.sp.triage_one("brianreborn/familia", pr), "posted")
        drop_lease.assert_called()
        hollow = [p for p in posted if "swarm-hollow v=1" in p[2]]
        self.assertEqual(len(hollow), 1)
        self.assertEqual(hollow[0][1], 616)
        self.assertIn("head=%s" % SHA, hollow[0][2])
        self.assertIn(SHA, self.sp.local_hollow_heads("brianreborn/familia", 616))

    def test_fence_keeps_code_punctuation(self):
        raw = "look at `_reject_truncated` and a * b and left[i]\n"
        fenced = self.sp.fence_unclosable(raw)
        clean = self.sp.sanitize_public_model_text("why:\n" + fenced, strip_markup=False)
        self.assertIn("_reject_truncated", clean)
        self.assertIn("a * b", clean)
        self.assertIn("left[i]", clean)
        why = self.sp.sanitize_public_model_text("**bold** _name_ <img>", one_line=True)
        self.assertNotIn("*", why)
        self.assertNotIn("_", why)
        self.assertNotIn("<", why)

    def test_review_does_not_dismiss(self):
        self._review()
        pr = _pr()
        calls = {"n": 0}

        def reviews(*_a, **_k):
            calls["n"] += 1
            if calls["n"] < 3:
                return []
            return [{
                "id": 4,
                "body": "swarm-review v=1 head=%s event=COMMENT\n" % SHA,
                "user": _user("swarm-bot"),
                "commit_id": SHA,
            }]

        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_pr_reviews", side_effect=reviews), \
             mock.patch.object(self.sp, "get_comments", return_value=(None, [])), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {"id": 1}, "")), \
             mock.patch.object(self.sp, "fetch_exact_diff", return_value="diff\n"), \
             mock.patch.object(self.sp, "model_high_effort",
                               return_value=(("word " * 80), "stub", "abc")), \
             mock.patch.object(self.sp, "get_pull", return_value=pr), \
             mock.patch.object(self.sp, "gh_api") as api, \
             mock.patch.object(self.sp, "post_pr_review") as post:
            self.assertEqual(self.sp.review_one("brianreborn/familia", pr), "skip")
        post.assert_not_called()
        for c in api.call_args_list:
            path = str(c.args[1]) if len(c.args) > 1 else ""
            self.assertNotIn("/events", path)
            self.assertNotIn("/dismissals", path)

    def test_cooldown_read_error_blocks(self):
        with mock.patch.object(self.sp, "get_comments", side_effect=self.sp.ForgeError("HTTP 500")):
            self.assertTrue(self.sp.cooldown_active("brianreborn/familia", 616))

    def test_scrub_does_not_eat_urls_or_stall(self):
        import time
        with mock.patch("getpass.getuser", return_value="brian"):
            os.environ["USER"] = "brian"
            os.environ["LOGNAME"] = "brian"
            text = self.sp.scrub_leak(
                "https://github.com/brianreborn/familia/x /opt/models/brian-7b.gguf"
            )
        self.assertIn("github.com/brianreborn/familia", text)
        self.assertIn("brian-7b.gguf", text)
        t0 = time.time()
        self.sp.scrub_leak("/" * 40000)
        self.assertLess(time.time() - t0, 1.0)

    def test_pinned_runners_include_the_fleet(self):
        from pathlib import Path
        for name in ("box", "box2", "box3", "miryam", "angel", "galaxy1", "galaxy2", "surface1"):
            self.assertIn(name, self.sp.known_runner_names())
        path = Path(__file__).resolve().parents[1] / ".github" / "swarm-runner-logins.txt"
        text = path.read_text()
        for name in ("box", "box2", "box3", "miryam", "angel", "galaxy1", "galaxy2", "surface1"):
            self.assertIn("runner %s" % name, text)
        os.environ["SWARM_RUNNER_LOGINS_FILE"] = str(path)
        os.environ["SWARM_RUNNER_LOGINS"] = "electrobrian"
        pr = _pr(ref="swarm/box2/605", login="electrobrian",
                 title="swarm/box2: first pass for #605")
        self.assertTrue(self.sp.pr_branch_trusted(pr))
        pr616 = _pr(ref="swarm/box2/616", login="electrobrian",
                    title="swarm/box2: first pass for #616")
        self.assertTrue(self.sp.pr_branch_trusted(pr616))

    def test_one_nonce_for_the_pass(self):
        prompts = []

        def fake(prompt, max_tokens=700, thinking=False):
            prompts.append(prompt)
            return "class: useful-notes\nwhy: fine\n", "stub"

        with mock.patch.object(self.sp, "model_draft", side_effect=fake):
            _text, _how, nonce = self.sp.model_high_effort(
                "INSTRUCTION-LINE", 40, untrusted="BEGIN  UNTRUSTED\nstuff", kind="DRAFT")
        self.assertTrue(nonce)
        found = set()
        for prompt in prompts:
            found.update(re.findall(r"nonce=([0-9a-fA-F]+)", prompt))
        self.assertEqual(found, {nonce})
        self.assertIn("withheld", prompts[0])

    def test_parsers_ignore_fenced_markers(self):
        fenced = (
            "``` text\n"
            "swarm-triage v=1 head=%s class=hollow checks=fail\n"
            "swarm-review v=1 head=%s\n"
            "swarm-lease v=1 head=%s kind=review runner=box\n"
            "```\n" % (SHA, SHA, SHA)
        )
        comment = {"body": fenced, "user": _user("swarm-bot")}
        self.assertEqual(self.sp.comment_triage_head(comment), "")
        self.assertIsNone(self.sp._triage_match(comment))
        self.assertFalse(self.sp.review_exists([comment], SHA))
        real = {"body": "swarm-triage v=1 head=%s class=hollow checks=fail\n" % SHA,
                "user": _user("swarm-bot")}
        self.assertEqual(self.sp.comment_triage_head(real), SHA)

    def test_edited_or_runnerless_lease_is_stale(self):
        self._review()
        edited = {
            "id": 5,
            "body": "swarm-lease v=1 head=%s kind=review runner=box\n" % SHA,
            "user": _user("swarm-bot"),
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2099-01-01T00:00:00Z",
        }
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [edited])), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {"id": 8}, "")) as post, \
             mock.patch.object(self.sp, "strike_own_comment") as strike:
            held = self.sp.acquire_score_lease("brianreborn/familia", 700, SHA, "review")
        self.assertEqual(held, 8)
        self.assertIn(5, [c.args[1] for c in strike.call_args_list])
        post.assert_called()
        missing = {
            "id": 6,
            "body": "swarm-lease v=1 head=%s kind=review\n" % SHA,
            "user": _user("swarm-bot"),
            "updated_at": "2099-01-01T00:00:00Z",
        }
        with mock.patch.object(self.sp, "get_comments", return_value=(None, [missing])), \
             mock.patch.object(self.sp, "post_comment", return_value=(None, 201, {"id": 9}, "")) as post, \
             mock.patch.object(self.sp, "strike_own_comment") as strike:
            held = self.sp.acquire_score_lease("brianreborn/familia", 700, SHA, "review")
        self.assertEqual(held, 9)
        self.assertIn(6, [c.args[1] for c in strike.call_args_list])
        post.assert_called()
        self.assertTrue(self.sp._comment_edited({"updated_at": "2099-01-01T00:00:00Z"}))
        self.assertTrue(self.sp._comment_edited({
            "created_at": "2099-01-01T00:00:00Z",
            "updated_at": "2099-01-01T00:00:01Z",
        }))
        self.assertFalse(self.sp._comment_edited({
            "created_at": "2099-01-01T00:00:00Z",
            "updated_at": "2099-01-01T00:00:00Z",
        }))

    def test_hollow_marker_checks_issue_and_sha_end(self):
        comment = {"body": "swarm-hollow v=1 issue=999 head=%s runner=box\n" % SHA,
                   "user": _user("swarm-bot")}
        self.assertEqual(self.sp.collect_hollow_rows([comment], issue=616), [])
        self.assertEqual(
            self.sp.collect_hollow_rows([comment], issue=999)[0][0], SHA)
        longer = SHA + "ab"
        bad = {"body": "swarm-hollow v=1 issue=616 head=%s runner=box\n" % longer,
               "user": _user("swarm-bot")}
        self.assertEqual(self.sp.collect_hollow_rows([bad], issue=616), [])

    def test_commit_fetch_is_cached_and_leaves_release_budget(self):
        self.sp.reset_api_budget()
        seen = []

        def api(method, path, **_k):
            seen.append(path)
            return (None, 200, _gh_commit(SHA, "swarm-bot"), "")

        pr = _pr()
        with mock.patch.object(self.sp, "fetch_commit", self._real_fetch), \
             mock.patch.object(self.sp, "gh_api", side_effect=api):
            self.assertTrue(self.sp.head_commit_owned("brianreborn/familia", pr))
            self.assertTrue(self.sp.head_commit_owned("brianreborn/familia", pr))
        self.assertEqual(len(seen), 1)
        self.sp.reset_api_budget()
        self.sp._API_CALLS = self.sp.api_budget_cap() - self.sp.api_release_floor()
        with mock.patch.object(self.sp, "fetch_commit", self._real_fetch), \
             mock.patch.object(self.sp, "gh_api") as api:
            with self.assertRaises(self.sp.ForgeError):
                self.sp.fetch_commit("brianreborn/familia", SHA)
        api.assert_not_called()
        self.sp.reset_api_budget()
        calls = {"n": 0}

        def down(*_a, **_k):
            calls["n"] += 1
            raise self.sp.ForgeError("HTTP 500 down")

        with mock.patch.object(self.sp, "fetch_commit", self._real_fetch), \
             mock.patch.object(self.sp, "gh_api", side_effect=down):
            with self.assertRaises(self.sp.ForgeError):
                self.sp.fetch_commit("brianreborn/familia", OTHER)
            with self.assertRaises(self.sp.ForgeError):
                self.sp.fetch_commit("brianreborn/familia", OTHER)
        self.assertEqual(calls["n"], 2)

    def test_dismiss_and_merge_are_outside_the_token_scope(self):
        with self.assertRaises(self.sp.ForgeError):
            self.sp.gh_api(
                "PUT", "repos/brianreborn/familia/pulls/1/reviews/2/dismissals")
        with self.assertRaises(self.sp.ForgeError):
            self.sp.gh_api("PUT", "repos/brianreborn/familia/pulls/1/merge")
        with self.assertRaises(self.sp.ForgeError):
            self.sp.gh_api("POST", "repos/brianreborn/familia/merges")
        with self.assertRaises(self.sp.ForgeError):
            self.sp.gh_api("PATCH", "repos/brianreborn/familia/pulls/1", data={"state": "closed"})
        with self.assertRaises(self.sp.ForgeError):
            self.sp.gh_api("DELETE", "repos/brianreborn/familia/git/refs/heads/swarm/box/1")

    def test_candidate_reads_comments_once(self):
        issue = {"number": 616, "created_at": "2026-11-10T20:00:00Z",
                 "labels": [{"name": "swarm-approved"}], "assignees": [],
                 "title": "gate", "body": "body"}
        dt = self.sp.parse_iso("2026-11-17T00:00:00Z")
        calls = {"n": 0}

        def comments(*_a, **_k):
            calls["n"] += 1
            return (dt, [])

        with mock.patch.object(self.sp, "gh_api_pages", return_value=(dt, [issue])), \
             mock.patch.object(self.sp, "gh_api", return_value=(dt, 200, {"items": []}, "")), \
             mock.patch.object(self.sp, "open_pr_refs", return_value=set()), \
             mock.patch.object(self.sp, "get_comments", side_effect=comments), \
             mock.patch.object(self.sp, "repo_owner_login", return_value="brianreborn"), \
             mock.patch.object(self.sp, "issue_admin_approved", return_value=True):
            self.assertEqual(
                [i["number"] for i in self.sp.candidate_issues("brianreborn/familia")],
                [616])
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
