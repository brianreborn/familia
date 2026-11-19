# generated/graph-{console,drone,security,tool-handler}.yaml claim tool-denial controls the schema does not implement

Issue: https://github.com/brianreborn/familia/issues/618
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:05 PST
Approved-content-sha256: f74a17ff5a096ce9f6cecc6d932bef1a62e21085a324e6306eec464b4273fd38

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about a generation that expects certain schema rules but finds the system doesn't support them, leading to validation failures. It highlights a mismatch between expected behavior and actual implementation.

(b) The likely approach would involve adjusting the schema to match the expected keys or removing non-existent keys, and possibly updating documentation or tests to reflect the correct requirements. Files may need to be moved to documentation or skips.

(c) Risks include potential security misconfigurations, incorrect model behavior, and false confidence in system functionality. Testing would need to confirm that changes resolve the issue without introducing new vulnerabilities.

(d) Open questions include: What specific keys are missing? How should the system handle missing configurations? Should tests be updated to reflect the correct schema?

-- swarm/galaxy1
