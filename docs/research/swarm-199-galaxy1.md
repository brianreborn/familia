# Router R&D sprint: routing is a no-op in many cases

Issue: https://github.com/brianreborn/familia/issues/199
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-26 05:04 PST
Approved-content-sha256: 2a1155108872acd741db94b3b09fd97c5349180b9f0f61059187b5fdab19eeb5

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

[Issue #199]

(a) **What the issue asks**

The issue reports that routing in the project (likely the *familia* router / llama-server infrastructure) is a no?op in many scenarios: requests arrive at the default model even when they should be routed, and the tools/capabilities offered to router children are inconsistent. It calls for a dedicated R&D sprint to:

- Find and catalogue every case where routing does nothing (e.g., graph?launched vs self?launched `llama-server`, router mode, single?node fallback).
- Define the expected routing behavior per node type (coder, chat, embed, ?) based only on host placement.
- Add explicit `--tools` flags on every `llama-server` process, router, and children.
- Build a routing test suite (using the ?Routing Test Designer?) that gates merges.
- Deliver proposal and fixes as swarm PRs.

(b) **Proposed approach & likely files/components**

- **Scope of investigation** ? Compare the routing logic paths for:
  - `graph-launched llama-server`
  - `self-launched llama-server`
  - Router mode vs. non?router mode
  - Single?node fallback paths.
- **Define expected routing per node type** ? A mapping document (or code comments) that states, for each node type (coder, chat, embed, ?), which host/placement should receive the request, and whether it should go through the router at all.
- **Explicit `--tools` flag** ? Ensure every `llama-server` process (including router and its children) is started with `--tools` on each child.
- **Tooling** ? Use the existing **Routing Test Designer** tool to write automated tests that verify routing outcomes.
- **Files/Components likely involved**:
  - Router source files (e.g., `router.py`, `router/child.py`, etc.)
  - `llama-server` launch scripts / entry points.
  - Code?bootstraps?llama.cpp notes on tool distribution (mentioned in issue).
  - Any existing ?router?no?tools? patch that was dropped.
  - Test suite files (to be created under `tests/routing/` or similar).

(c) **Risks & test ideas**

*Risks*
- **Scope creep** ? Need to cover many launch modes; missing one case could re?introduce the no?op.
- **Tool flag side?effects** ? Adding `--tools` may change behavior for processes that previously ran without it.
- **Cross?platform differences** ? ?install on all supported platforms? is priority after this; ensure tests run on the relevant OSes.
- **Stateful routing** ? If routing relies on prior state (e.g., node placement), tests must reset state.

*Test ideas*
- Write a small harness that launches `llama-server` in each mode (graph vs self) with `--tools` and asserts that the request is forwarded to the correct node type.
- Use the **Routing Test Designer** to define expected destinations for each node type and run it as a CI gate.
- Add integration tests that check the presence of tool flags in the process arguments (`ps -ef | grep llama-server` or similar).
- Verify that children of the router receive the `--tools` flag (inspect child processes).

(d) **Open questions**

- Which exact code paths handle ?default model? fallback when routing should apply? (Need to see the router dispatch logic.)
- How is the ?single?node fallback? implemented, and does it bypass routing entirely?
- What is the current behavior of `--tools` on router children vs. the router itself?
- Are there platform?specific differences in how `llama-server` is launched (e.g., entry points, environment variables)?
- What is the definition of ?node TYPE? (coder, chat, embed, ?) and how does it map to host placement?
- Is there an existing test harness for routing that can be extended, or do we need to build one from scratch?

-- swarm/galaxy1
