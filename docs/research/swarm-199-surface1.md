# Router R&D sprint: routing is a no-op in many cases

Issue: https://github.com/brianreborn/familia/issues/199
Runner: surface1 (stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-23 22:21 PST
Approved-content-sha256: 2a1155108872acd741db94b3b09fd97c5349180b9f0f61059187b5fdab19eeb5

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on surface1)

stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

- **(a) What the issue asks:**  
  The issue calls for a focused research and development sprint to fix a bug where routing in the router is often a no-op (i.e., requests go to the default model even when they should be routed). It wants us to identify cases where routing does nothing, understand why router children's tools/capabilities are inconsistent across code-bootstraps-llama.cpp and missing patches like `router-child-no-tools`, and produce a plan: reproduce/catalogue no-op cases, define per-node-type routing expectations (host placement only), explicitly enable `--tools` on every llama-server process/router/children, build a routing test suite gated by merges, and deliver proposal + fixes as swarm PRs.

- **(b) Proposed approach & likely files/components:**  
  - **Reproduce/catalogue no-op cases**: Run the router under different modes (graph-launched vs self-launched `llama-server`, single-node fallback) and inspect request flow. Identify where routing children get tools/capabilities inconsistently.  
  - **Define expected routing per node type** (coder, chat, embed, ?): Based on host placement only ? i.e., decide which router child should handle a given input based solely on the model/host?s role/type, not ad-hoc logic.  
  - **Explicit `--tools` flag**: Ensure every `llama-server` process, router instance, and each child process has `--tools` enabled so tooling/capabilities are consistent. This likely touches:  
    - `router.py` / router entry points (where `--tools` flags are passed).  
    - `llama-server` launch scripts or main loops that spawn children.  
    - Code-bootstraps-llama.cpp modules referenced in note #26 and the missing `router-child-no-tools` patch.  
  - **Routing test suite**: Build a ?Routing Test Designer? (a new/updated test harness) that exercises routing across node types, modes, and fallbacks; gate PR merges on its pass.  
  - **Swarm PRs**: Split fixes into small, related PRs.

- **(c) Risks & test ideas:**  
  - *Risk*: Changing tooling flags may affect runtime behavior for non-tooled models or legacy paths. Need to verify backward compatibility.  
  - *Risk*: Misclassifying node types could break existing routing expectations; must align with host placement semantics.  
  - **Test ideas (unknown specifics, but high-level):**  
    - Write unit/integration tests that launch a router for each node type and assert the correct child is selected for given input.  
    - Simulate different `llama-server` launch modes and confirm routing isn?t bypassed.  
    - Check that every spawned child process receives `--tools` (or equivalent) flag; add logging/assertions to catch missing flags.  
    - Run existing ?code-bootstraps-llama.cpp? scenarios and compare tool/capability propagation before/after fix.  
    - Single-node fallback path: ensure routing still applies when no multi-node setup.

- **(d) Open questions:**  
  - Exact code paths in `router-child-no-tools` patch and how it interacts with graph-launched vs self-launched `llama-server`.  
  - Whether enabling `--tools` on children is sufficient or if additional capability flags are needed per node type.  
  - How to define ?host as placement only? for routing ? does host IP/port determine role, or is it a separate config?  
  - What specific test suite (?Routing Test Designer?) components exist and how they?re gated; need details on its current state.  
  - Impact of single-node fallback on routing logic (e.g., does the router even get invoked?).  

(No measurements, file contents, or results invented ? ?unknown? where appropriate.)

-- swarm/surface1
