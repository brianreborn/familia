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


def _pr(number=700, sha=SHA, draft=True, ref="swarm/box/616", title=None, body=None):
    return {
        "number": number,
        "draft": draft,
        "title": title or "swarm/box: first pass for #616",
        "body": body or "Refs #616\n",
        "head": {"ref": ref, "sha": sha},
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
        os.environ["SWARM_RUNNER_LOGINS"] = "swarm-bot"
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
            _text, how = self.sp.model_high_effort("classify this", 80)
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
        self.assertEqual(len(posted), 1)
        body = posted[0][2]
        self.assertIn("swarm-triage v=1 head=%s class=useful-notes" % SHA, body)
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
        self.assertIn("class=needs-human", posted[0][2])
        self.assertNotIn("class=hollow", posted[0][2])

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

        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_pr_reviews", return_value=[]), \
             mock.patch.object(self.sp, "fetch_exact_diff", return_value="diff -- a\n+line\n") as diff, \
             mock.patch.object(self.sp, "get_pull", return_value=pr), \
             mock.patch.object(self.sp, "model_high_effort",
                               return_value=("notes only, not an approval\n", "stub")), \
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
        with mock.patch.object(self.sp, "owner_approved_pr", return_value=True), \
             mock.patch.object(self.sp, "get_pr_reviews", return_value=[]), \
             mock.patch.object(self.sp, "fetch_exact_diff", return_value="diff\n"), \
             mock.patch.object(self.sp, "get_pull", return_value=moved), \
             mock.patch.object(self.sp, "model_high_effort", return_value=("notes\n", "stub")), \
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
            "body": "swarm-triage v=1 head=%s class=hollow\n" % SHA,
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
