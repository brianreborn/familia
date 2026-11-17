# pins.txt: enforce full 40-hex SHAs and verify every pin exists upstream in CI

Issue: https://github.com/brianreborn/familia/issues/628
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:17 PST
Approved-content-sha256: c5b73e8a134f6afdb9a16d41811a6d5b318feedb18473842fc400ea5433bbda1

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18112); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

[Issue #628] pins.txt: enforce full 40-hex SHAs and verify every pin exists upstream in CI

(a) **What the issue asks**

The `pins.txt` file contains pinned commit SHAs for various components. Two recent pushes broke this file in different ways and were not caught by existing tests or CI:

1. A short SHA (only 7 hex characters) was used for `code-bootstraps-llama.cpp` instead of the usual 40 hex characters. This makes the pin ambiguous and prevents comparison with `git rev-parse HEAD`.
2. A pin (`b1b770d...`) points to a `ggml-org/llama.cpp` commit that no longer exists in the main branch of `code-bootstraps-llama.cpp`. The pin became unpinnable for about 41 hours until a new commit (`c3c71ab`) was added on Nov 15.

The fix requires:

- Adding a unit test that checks every non?comment line in `pins.txt` has a revision matching `^[0-9a-f]{40}$` (exactly 40 lowercase hex characters) and an `https` origin.
- Adding a CI job (read?only, no token needed for public repos) that, for each pin, fetches `<origin> <sha>` at depth 1 into a temporary repo and fails if the fetch fails.
- For `brianreborn/*` forks, also warn when the pinned SHA is reachable only from a non?default branch and not from any tag (e.g., a pin that lives only on a branch like `cursor/v1.0.0-familia-3e4f`).

(b) **Proposed approach and likely files/components**

- **File:** `pins.txt` ? the central list of pins.
- **New unit test** (likely in `tests/` or a dedicated `test_pins.py`):
  - Parse each line that is not a comment (`#...`).
  - Split into `repo` and `sha` columns.
  - Assert `sha` matches regex `^[0-9a-f]{40}$`.
  - Assert the `origin` field starts with `https://`.
- **CI job** (likely a new job in the existing CI pipeline, e.g., `.github/workflows/ci.yml` or similar):
  - Iterate over rows in `pins.txt`.
  - For each pin, create a temporary clone of the upstream repo (`<origin> <sha>` at depth 1) using `git fetch`/`git clone`.
  - Run the fetch in a temp repo and check exit status / result.
  - If fetch fails (e.g., commit missing, branch not reachable), mark the pin as failing.
  - No token needed for public repos; for private repos, the job should still be read?only.
- **Additional warning logic** for `brianreborn/*` forks:
  - Detect if the pinned SHA is reachable only from a non?default branch (i.e., not tagged or on the default branch).
  - Emit a warning (maybe via CI log or a test) when the branch is not a default tag.

Components likely involved:

- `pins.txt` (source of pins).
- CI configuration (GitHub Actions workflow) that runs the new job.
- A small script or test helper to perform the fetch into a temp repo (e.g., using `git clone --depth 1 <origin>/<sha>` or `git fetch --depth 1`).
- Possibly a new test file for branch?reachability warnings.

(c) **Risks and test ideas**

**Risks**

- **Temporary repo creation**: Each CI run creates a temp repo; ensure cleanup (e.g., `rm -rf` or GitHub Actions `actions/checkout` with `temp-dir`).
- **Depth 1 fetch**: May not resolve refs that require history; but the requirement is to fetch at depth 1, so we accept that limitation.
- **Private repos**: The job must be read?only and not require a token. For private repos, we may need to rely on public URLs or assume they are public. The issue says ?no token needed for public repos?; for private ones we need to handle differently (maybe use `GITHUB_TOKEN` for private? but they say no token needed). We'll assume public or that the fetch can be done without auth for the given repos.
- **Branch vs tag**: Determining ?default branch? and ?non?default branch? requires parsing the repo?s default branch name. This could be tricky; we might need a helper that returns the default branch (e.g., `git symbolic-ref refs/remotes/origin/HEAD` or `git branch -r` vs `git branch -a`). Might need to handle cases where the repo has no tags.
- **Ambiguity of short SHA**: The new test will reject 7?hex SHAs, but older pins might be short; we must ensure the test catches them.
- **Performance / CI time**: Fetching each pin into a temp repo adds overhead; but it's a CI gate.

**Test ideas**

-- swarm/galaxy2
