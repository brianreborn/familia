# Security tools for 0.3.0: scanners, fuzz harness, and LAN exposure audit

Issue: https://github.com/brianreborn/familia/issues/406
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 06:03 PST
Approved-content-sha256: 37ecbb5b6c11db35e386a2055938f6e76189e4bd2989eee1c96e5ff7f7aeb8ec

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

Plain ASCII markdown, no fenced blocks. Use the
fenced blocks below to structure your answer:

----- BEGIN UNTRUSTED ANSWER (not instructions) nonce=8088662cad76d82f -----

title: Familyia Security Tools for 0.3.0: scanners, fuzz harness, and LAN exposure audit

Parent: [#402](https://github.com/brianreborn/familia/issues/402) (Security focus for 0.3.0). Target: `main`. Unassigned so the swarm can claim. Suggested owners: Fuzz Tester (scanners + harness design), Forensic Investigator (LAN inventory), Race Reviewer (CI job interaction). Swarm runners miryam, angel, galaxy1, and galaxy2 may run the read-only port inventory on their own host only.

## Context

Already on main:

- CodeQL: `.github/workflows/codeql.yml`
- shellcheck (pinned 0.11.0, sha256-checked) via `.github/workflows/lint-warnings.yml` and `.ci/lint-warnings.sh`
- `.gitleaksignore` exists (from the #240 gitleaks-ignore work); there is no gitleaks, trufflehog, bandit, semgrep, pip-audit, or osv-scanner job under `.github/workflows` today

Fuzzing: [#281](https://github.com/brianreborn/familia/issues/281) is the Fuzz Tester handoff for `proving_grounds/nexus_localhost.sh` (tmp-dir fix). That script needs

-- swarm/box
