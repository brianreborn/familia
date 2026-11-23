# Repository pin update proposals

Familia records repository revisions in `pins.txt` as full commit IDs and HTTPS origins. The pin-integrity CI job checks that each pinned commit is fetchable from its declared origin; it does not update pins.

The **Propose code-bootstraps pin updates** workflow runs weekly and can also be started manually. It only operates on the canonical repository's `main` ref. It reads the default branch name and current commit of `brianreborn/code-bootstraps-llama.cpp` through GitHub's public API, then independently fetches that exact full commit ID from the repository and verifies that Git recognizes it as a commit. It refuses the forbidden `b1b770d` revision. If the pin is already current, it exits without opening a proposal.

When the pin differs, the workflow changes only the `code-bootstraps-llama.cpp` row in `pins.txt` and pushes a uniquely named proposal branch. It opens a normal pull request against `main`, including the old and candidate revisions and the workflow run link. Repeated runs for the same candidate use the same branch name, so an already-pushed proposal cannot silently create a second branch or overwrite a reviewer’s changes.

The job receives only `contents: write` and `pull-requests: write`; there is no `pull_request` or `pull_request_target` trigger, third-party action, secret-bearing checkout, or merge permission. It never enables auto-merge and never merges a proposal. Reviewers must inspect the upstream diff, verify the repository pin checks and other required CI, and obtain Brian's explicit approval before merging. A human may instead update `pins.txt` manually through the normal review process.
