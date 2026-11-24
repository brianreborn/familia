# Security MCPs for 0.3.0: inventory, tool boundaries, and allowlist

Issue: https://github.com/brianreborn/familia/issues/407
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-23 21:45 PST
Approved-content-sha256: 11b0ec19ea3a15576926b33b76eba07b84e8a052bb512e8a9e27b492869b0704

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about ensuring the security of the familya project's MCPs (Multi-Component Platforms) in the new 0.3.0 release. It focuses on how to properly handle inventory, tool boundaries, and allowlists, especially in light of recent changes and vulnerabilities.

(b) A possible approach would involve reviewing the current MCP configurations, checking for any misconfigurations or overlooked rules, and ensuring that tool boundaries are correctly set. Likely components include the `familya` codebase, MCP scripts, and the authentication setup.

(c) Risks could include potential security gaps, misconfigured tool boundaries, or incorrect inventory data leading to unauthorized access. Testing would involve simulating various scenarios to see if the system behaves as expected under different conditions.

(d) Open questions include: What specific tool boundaries need adjustment? How can we verify that the inventory matches the expected setup? Are there any edge cases or scenarios that haven't been thoroughly tested?

-- swarm/galaxy1
