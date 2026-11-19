# TR-4 (must-land v0.4.0) at the graph layer: node.role overrides a fail-closed model for tools and routing

Issue: https://github.com/brianreborn/familia/issues/621
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:07 PST
Approved-content-sha256: 48771557588a9fe818993f93afb2a3306d4a73c70bcbab2c6a8c33162cf8b4da

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about ensuring that only nodes with a specific role that matches a fail-closed model type can be used in certain parts of the graph, especially when interacting with tools and routing. It highlights a conflict between how the system handles role-based overrides and how validation works.

(b) The proposed approach would involve adding a helper function to check if a node's role is consistent with a fail-closed model, and integrating this check into existing components like tool_policy, tool_route, and graph_router. This would likely involve modifying or extending scripts and possibly adding tests to validate behavior.

(c) Risks include potential false positives or negatives in role validation, breaking existing integrations, and introducing complexity in handling role overrides. Test ideas would involve creating scenarios with different role values and verifying if the system behaves as expected.

(d) Open questions include how to accurately detect and handle role mismatches, whether the current validation logic needs adjustment, and how to ensure compatibility with future updates or changes in the graph model.

-- swarm/galaxy1
