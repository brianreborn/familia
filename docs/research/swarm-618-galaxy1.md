# generated/graph-{console,drone,security,tool-handler}.yaml claim tool-denial controls the schema does not implement

Issue: https://github.com/brianreborn/familia/issues/618
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-23 22:10 PST
Approved-content-sha256: f74a17ff5a096ce9f6cecc6d932bef1a62e21085a324e6306eec464b4273fd38

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about a problem where generated graphs don't work because of missing or incorrect configuration settings. The system expects certain parameters but they're not being applied correctly.

(b) To fix this, we should update the configuration files to match the expected schema or remove conflicting settings, and ensure the files are properly documented in tests. The relevant files are likely in docs or a separate test folder.

(c) The main risks are false confidence in the system and potential security issues from unmonitored tool usage. Testing is needed to confirm behavior and prevent unauthorized access.

(d) We need to clarify what files are missing or incorrect, and verify that they're not being used in production. Also, we should check if any new guidelines are needed for documentation.

-- swarm/galaxy1
