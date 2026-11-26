# v0.3.0 release 4/4: final release-notes review, version bump, tag and publish

Issue: https://github.com/brianreborn/familia/issues/555
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 08:10 PST

Status: Exploratory first-pass tracking note. Section 1 is a read-only probe.
Section 2 outlines the pre-release gates and release requirements.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Release Sequence & Verification Gates

### Dependencies (Order of Execution)
1. Issue #552 (Smoke tests on primary Unix platforms): Linux, FreeBSD, Android Termux.
2. Issue #553 (Default model graphs per platform tier).
3. Issue #554 (App Store thin client / frontend).
4. Issue #555 (Final release notes review, version bump, tag and publish).

### Scope & Requirements for Final Release Push
- Finalize `docs/releases/v0.3.0.md` (via PR #470).
- Keep open security items (#415, #416, #419, #546, #404) documented in Known Issues.
- Product version consistency: align `ROADMAP.md`, `TESTING.md`, `SPRINT.md`, and references.
- Platform scope: Linux, FreeBSD (first reference platform), Android Termux; Windows supported/out of scope; macOS community testing wanted.
- Tag and publish: Requires explicit final approval from repository owner (Brian) on #555. This tracking PR does NOT bump versions, tag, or publish.

-- swarm/box
