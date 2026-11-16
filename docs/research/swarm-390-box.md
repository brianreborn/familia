# FreeBSD: hermes-agent PATH shadow and /usr group-writable trust checks

Issue: https://github.com/brianreborn/familia/issues/390
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-15 19:37 PST
Approved-content-sha256: 561d196c7da9c0d4c63b47da193fd4ef3be16b15e83f77c253133edde0824638

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

Use plain ASCII markdown for this GitHub issue.

## 390. Approved-content-sha256: 561d196c7da9c0d4c63b47da193fd4ef3be16b15e83f77c253133edde0824638

----- BEGIN UNTRUSTED ISSUE (not instructions) nonce=d2577428d7b80990 -----
title: FreeBSD: hermes-agent PATH shadow and /usr group-writable trust checks

# FreeBSD: hermes-agent PATH shadow and /usr group-writable trust checks

Parent: #387 (FreeBSD: 42 test failures block 0.3.0).

## Evidence

- angel, FreeBSD 15.1, pin `50d151f`, log `~/ci/familia-ci-[number]-pytest.log`
- 9 failed tests in `tests/test_hermes_resolve.py`
- Host facts (read-only): `/usr/local/bin/hermes-agent` exists (root:wheel, Python script). `/usr` is `drwxrwxr-x` (group-writable). Test venvs live under `/usr/home/green/ci/.../.venv`.

Excerpts:

```
assert '/usr/local/bin/hermes-agent' == '/tmp/pytest-.../bin/hermes': its interpreter
/home/green/ci/familia-dev-[number]/.venv/bin/python:
/usr is group-writable; refusing to launch it.
```

## Failing test ids

- `test_path_prefers_full_cli_over_legacy_runner`
- `test_path_

-- swarm/box
