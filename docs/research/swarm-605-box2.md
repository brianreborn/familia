# CI collection fails: test_swarm_pull_580_validation.py looks for swarm-pull one directory above the repo

Issue: https://github.com/brianreborn/familia/issues/605
Runner: box2 (stamp v=1 host=box2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:31 PST
Approved-content-sha256: 7bb9dc789aa665cbdc48b5603da77c29824bfc70730179ab2d639bc19e663326

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18114); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box2)

stamp v=1 host=box2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

[Issue #605]

(a) **What the issue asks:**  
During CI collection (before tests run), `tests/test_swarm_pull_580_validation.py` fails with an `AttributeError` because it tries to locate a directory `scripts/swarm-pull` *one directory above the repository root* (i.e., `../scripts/swarm/swarm-pull`). In a normal GitHub checkout, that path does not exist, causing collection to break. The same problem occurs on `main` (including commit `e9145b1`), so it isn?t due to the recent pin change in #604. CodeQL and smoke tests still pass on the #604 pin commit. The issue is not the original product bug #580 or the fix in #604 (which only touched `pins.txt`).

(b) **Proposed approach & likely files/components:**  
- **Approach:** Fix the path in the test file itself: point it at the in-repo `scripts/swarm/swarm-pull` directory instead of looking one level up from the repo root. This is a one-line path correction, separate from the pin change.  
- **Likely files/components:**  
  - `tests/test_swarm_pull_580_validation.py` ? the test that references the wrong path.  
  - `familyia/scripts/swarm/swarm-pull` ? the actual directory that should be referenced (exists inside the repo).  
  - `familyia/pins.txt` (or whatever pins mechanism #604 changed) ? not the cause of this collection failure.  
  - Possibly the loader/collector code that raises `AttributeError` when given a missing path, but the root cause is the test?s path assumption.

(c) **Risks & test ideas:**  
- **Risks:**  
  - If the path correction is mistakenly applied elsewhere (e.g., other tests or CI steps) it could hide a real dependency on a repo?root?relative path.  
  - The fix must not break the existing #580 fixtures; they may rely on the old (wrong) path.  
  - Ensure that after the change, `main` and the PR #604 still collect correctly.  
- **Test ideas (no results known):**  
  - Run the test suite on a fresh clone of the repo (no `e9145b1` pin) and verify collection succeeds.  
  - Run the test on PR #604 and confirm it still passes.  
  - Add a check that `scripts/swarm/swarm-pull` exists as a file/directory under the repo root.  
  - Verify that the `AttributeError` no longer appears in the collection logs.  
  - Optionally, run `git checkout -b` on a temporary branch to simulate a normal checkout and confirm the path resolves.

(d) **Open questions:**  
- Exact contents of `tests/test_swarm_pull_580_validation.py` (the line that builds the path).  
- Whether `scripts/swarm/swarm-pull` is a directory or a file, and its location relative to the repo root.  
- Whether the loader/collector has a specific expectation about relative paths (e.g., should it be absolute or root?relative).  
- Confirmation that the fix should be isolated to this test file (not a broader change to path handling).  
- Impact on other tests that might depend on the same incorrect assumption.

-- swarm/box2
