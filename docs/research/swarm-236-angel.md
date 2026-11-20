# Security review (cross-team)

Issue: https://github.com/brianreborn/familia/issues/236
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:52 PST
Approved-content-sha256: 5614bc9ff1ddbaa8951e635fd20ab69426c22340853ad6a710960f4fc81e9af3

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue 236: Security Review (Cross-Team)

**Summary:**
Brian has requested a comprehensive security review of the familia project, covering all repositories, installers, supply chain, API, per-port keys, the cockpit, MCP, tool gating, swarm runners and CI, fleet hosts and phones, the assistant computers, connectors, and their access, and how the agents coordinate. The review will be conducted by both Grok Bot teams in parallel and coordinated here.

**Proposed Approach:**
1. **Define Scope:** Identify all repositories, installers, supply chain components (pins, checksums, prebuilts), API, per-port keys, the cockpit, MCP, tool gating, swarm runners and CI, fleet hosts and phones, the assistant computers, connectors, and their access, and how the agents coordinate.
2. **Parallel Review:** Conduct the review by both Grok Bot teams simultaneously.
3. **Coordination:** Ensure that the two teams coordinate their findings and report back to Brian.
4. **Security Concerns:** Regularly post security concerns by each agent to the issue.

**Files or Components Likely Involved:**
- All repositories
- Installers
- Supply chain components (pins, checksums, prebuilts)
- API
- Per-port keys
- Cockpit
- MCP
- Tool gating
- Swarm runners and CI
- Fleet hosts and phones
- Assistant computers
- Connectors
- Agent coordination

**Risks:**
- **Data Exposure:** Sensitive details may be exposed if not handled securely.
- **Insecure Practices:** Insecure practices may be missed if not thoroughly reviewed.
- **Resource Consumption:** The review process may consume significant

-- swarm/angel
