# FreeBSD: hermes-agent PATH shadow and /usr group-writable trust checks

Issue: https://github.com/brianreborn/familia/issues/390
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-12 18:05 PST
Approved-content-sha256: 561d196c7da9c0d4c63b47da193fd4ef3be16b15e83f77c253133edde0824638

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli qwen2.5-coder-0.5b-instruct-q4_k_m.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(e) the expected outcome.

### (a) What the issue asks

The issue asks for a proposed fix to ensure that the `/usr` directory is not world-writable, group-writable, or untrusted, and that the installed `/usr/local/bin/hermes-agent` is isolated from fixtures.

### (b) Proposed approach and the files or components likely involved

To solve the issue, we need to isolate the `/usr` directory from fixtures and ensure that the installed `/usr/local/bin/hermes-agent` is on PATH and wins over the fixture bin the tests create. We also need to verify that the trust walker flags `/usr` as group-writable. On this FreeBSD host that is the stock `root:wheel` 775 layout, and `/usr/home` sits under `/usr`, so even a fixture script whose interpreter is the CI venv is refused.

### (c) Risks and test ideas

There are no known risks to this fix. However, we need to ensure that the installed `/usr/local/bin/hermes-agent` is isolated from fixtures and that the trust walker flags `/usr` as group-writable.

### (d) Open questions

There are no open questions to this issue.

### (e) the expected outcome

The expected outcome is that the `/usr` directory is not world-writable, group-writable, or untrusted, and that the installed `/usr/local/bin/hermes-agent` is isolated from fixtures.

---

### (a) What the issue asks

The issue asks for a proposed fix to ensure that the `/usr` directory is not world-writable, group-writable, or untrusted, and that the installed `/usr/local/bin/hermes-agent`

-- swarm/angel
