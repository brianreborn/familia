"""Research bucket (docs/research-bucket.md): `research` issues stay out of
swarm intake and the app store search until promoted."""
import tempfile
import unittest
from pathlib import Path

import test_swarm_pull_543 as base


class ResearchBucketTest(unittest.TestCase):
    def test_research_label_blocks_swarm_intake(self):
        with tempfile.TemporaryDirectory() as home:
            mod = base.load_mod(Path(home))
            issue = {"number": 9001, "title": "rt-idea: x",
                     "labels": [{"name": "swarm-approved"}, {"name": "Research"}]}
            self.assertEqual(mod.issue_blocked("brianreborn/familia", issue),
                             "block-label:research")

    def test_promoted_issue_is_not_blocked_by_bucket(self):
        with tempfile.TemporaryDirectory() as home:
            mod = base.load_mod(Path(home))
            issue = {"number": 9002, "title": "rt-idea: x",
                     "labels": [{"name": "swarm-approved"}, {"name": "rt-idea"}]}
            self.assertEqual(mod.issue_blocked("brianreborn/familia", issue), "")


if __name__ == "__main__":
    unittest.main()
