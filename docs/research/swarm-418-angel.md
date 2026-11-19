# chore(hermes): utf-8 open() and free_only pin-time check

Issue: https://github.com/brianreborn/familia/issues/418
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:27 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #418: chore(hermes): utf-8 open() and free_only pin-time check

**What the issue asks:**

This issue is a follow-up from #411, which was filed after the merge at 6a928c8e375def13d3ce8d0648f585a3bef29ef2. The goal is to address two leftover nits from the re-reviews of #411. Neither of these nits blocked the landing, but they need to be addressed for completeness.

**Proposed approach and the files or components likely involved:**

1. **Platform: `open(user_cfg_path)` at `scripts/hermes_harness.py:1229` needs `encoding="utf-8"`. Pre-existing, fine as a small follow-up.**
   - This involves updating the `open()` function call in `scripts/hermes_harness.py` to include the `encoding="utf-8"` parameter. This ensures that the file is opened with UTF-8 encoding, which is necessary for handling files with non-ASCII characters.

2. **Boundary: add a code check that the `free_only` hatch still works at pin time. #411 documented a manual re-verify on each model-version update in `docs/hermes-pin.md`; this issue is for turning that into an automated check.**
   - This involves adding a code check to verify that the `free_only` hatch still works at pin time. This can be done by writing a function that checks the state of the `free_only` hatch and ensures it behaves as expected. This check should be integrated

-- swarm/angel
