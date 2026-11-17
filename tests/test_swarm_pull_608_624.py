#!/usr/bin/env python3
"""Triage mode, review mode, draft cooldown, and hollow re-pick (#608 #616 #624)."""
from __future__ import print_function

import os
import unittest
from unittest import mock

import pytest

from test_swarm_pull_543 import PASSING_DRAFT, load_mod

SHA = "ab" * 20
OTHER = "cd" * 20
BASE = "ef" * 20


def _user(login, typ="User"):
    return {"login": login, "type": typ}


def _pr(number=700, sha=SHA, draft=True, ref="swarm/box/616", title=None, body=None,
        repo="brianreborn/familia", login="swarm-bot"):
    return {
        "number": number,
        "draft": draft,
        "title": title or "swarm/box: first pass for #616",
        "body": body or "Refs #616\n",
        "user": _user(login),
        "head": {
            "ref": ref,
            "sha": sha,
            "repo": {"full_name": repo},
        },
        "base": {"ref": "main", "sha": BASE},
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
                               side_effect=lambda *a, **k: posted.append(a) or (None, 201, {}, "")):
            self.assertEqual(self.sp.triage_one("brianreborn/familia", pr), "posted")
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
        self.assertEqual(diff.call_args[0][1], BASE)
        self.assertEqual(diff.call_args[0][2], SHA)
        self.assertEqual(len(seen), 1)
        method, path, data = seen[0]
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
        api.assert_not_called()
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
        self.assertTrue(self.sp.cooldown_active(
            "brianreborn/familia", 616, now=now + self.sp.timedelta(hours=5)))
        self.assertFalse(self.sp.cooldown_active(
            "brianreborn/familia", 616, now=now + self.sp.timedelta(hours=7)))
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "nonce", now=now)["delay_h"], 12)
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "short", now=now)["delay_h"], 24)
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "short", now=now)["delay_h"], 48)
        self.assertEqual(
            self.sp.record_draft_cooldown("brianreborn/familia", 616, "short", now=now)["delay_h"], 48)
        self.sp.record_draft_cooldown("brianreborn/familia", 616, "short")
        with mock.patch.object(self.sp, "candidate_issues", return_value=[{"number": 616}]), \
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
        api.assert_not_called()

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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
