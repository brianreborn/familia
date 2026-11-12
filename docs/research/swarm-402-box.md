# Security focus for 0.3.0

Issue: https://github.com/brianreborn/familia/issues/402
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:59 PST
Approved-content-sha256: f4d70e2b77842d9a5d5463143447027eed228f997fa257f3a103b955194ffafb

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

Use plain ASCII markdown for this GitHub issue.

## Proposed approach

- **Security models (A)**: Use the security models from #236 (findings H1-H4, L13-L16, M17, and the private notes). These define the threat surface and the required controls. Implement them in the new security models for familia 0.3.0, and test them against the existing models.
- **Security applications (B)**: Apply the security controls to familia 0.3.0's applications. This includes the menus, catalog, MCP, and tooling. Ensure that each application (e.g., `familia-menu.sh`, `scripts/menu-items.txt`, guardian launch-test, `reach.mcp`, `test.offline-secbench`, `scripts/agent_reach.py mcp-example`, `scripts/hermes_harness.py`, `server_tools`) has the appropriate security features (e.g., API keys, guardians, pentest nodes).
- **Security tools (C)**: Use the security tools from #117 (`scripts/offline_secbench.py`, `scripts/agent_reach.py mcp-example`, `scripts/hermes_harness.py`, `server_tools`). These provide automated checks for secrets, MCP wiring, and harness behavior. Integrate them into the CI pipeline.
- **MCP / tool wiring (D)**: The existing approval gate still guards shell and MCP. Ensure that the new MCP (e.g., `scripts/agent_reach.py mcp-example`, `server_tools`) is wired correctly and that the approval gate remains active.

## Risks and test ideas

- **Test the security models**: Write a test that

-- swarm/box
