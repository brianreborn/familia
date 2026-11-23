# Mini-sprint: complete default LFM3-family graph and contingency nodes

Issue: https://github.com/brianreborn/familia/issues/667
Runner: surface1 (stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-22 23:02 PST
Approved-content-sha256: c637bdd83b9178b24e381dfe8acfca517516abd24179ba72e797561adf241b3d

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on surface1)

stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

## (a) Issue Summary

Issue #667 asks to finish the **default LFM3-family graph mini-sprint**. Specifically:

- Complete coverage of default nodes and contingency nodes for the LFM3 family using verified weights, runtimes, resource budgets, and optional fail-closed addons.
- Keep text/chat/coder/decision/embed placement explicit and verified; ensure 64K context where supported; preserve CPU fallback and host-specific checks.
- Preserve the existing `llama.cpp` pinned runtime convention.
- The work is about **graph construction** (host graphs) ? not live GPU driver changes, package installs, reboots, or benchmark runs.

## (b) Proposed Approach

1. **Identify nodes to cover**:  
   - Default node(s): text/general chat, coding, decision-making, embed placement.  
   - Contingency nodes: LFM3-VL (vision only), LFM3-Omni (vision+audio opt-in with boundaries), LFM3-Audio (opt-in audio), STT/TTS separate nodes, Image-out after verified runtime/license, Vision/media remain opt-in.

2. **Use verified weights/runtimes/resource budgets**:  
   - For each node, confirm available verified weight files and runtimes for the host platform.  
   - Ensure 64K context is supported; if not, use an explicit smaller override measured per node.

3. **Preserve existing conventions**:  
   - Keep `llama.cpp` runtime pinned as-is.  
   - Maintain CPU fallback and host-specific resource checks.

4. **Implement fail-closed optional addons** (e.g., Guardian/pentest nodes) only once weights/hash/placement are ready ? not silently enable on launch.

5. **Files/components likely involved**:  
   - Graph definition files for LFM3 family (default and contingency node wiring).  
   - Host graph generation scripts / tooling that builds host graphs from verified components.  
   - Resource/budget checkers for CPU, memory, GPU limits per node.  
   - Node-specific runtime/weight verification steps.

## (c) Risks & Test Ideas

**Risks**:
- Missing weights or runtimes for a node ? silent fallback instead of actionable diagnostics.
- Contingency nodes may be opt-in only; ensure they aren?t accidentally enabled as defaults.
- Resource budgets might exceed host limits on some platforms, causing failures at launch.
- Security addons (Guardian/pentest) not yet ready ? must remain disabled until weights/authorization complete.

**Test ideas**:
- **Unit tests**: Verify each node?s wiring exists and references correct verified weight paths; check context size overrides are explicit where needed.
- **End-to-end tests**:  
  - Launch menus/launchers distinguish text, vision, audio, image-out, security actions.  
  - Simulate missing weights ? expect diagnostics, not silent fallback.  
  - Verify CPU fallback and host-specific resource checks run before node activation.  
  - Confirm fail-closed behavior: if a required addon (e.g., security) is enabled but incomplete, it should refuse to start.
- **Resource refusal tests**: Run on target hosts with limited memory/CPU; ensure nodes that need more than budget are rejected or use smaller overrides.

## (d) Open Questions

- Unknown specifics: exact file paths for default and contingency node definitions, current state of verified weights/runtimes for each node, host graph generation scripts, and resource budgets per node.
- Need to confirm whether vision/media nodes should stay strictly opt-in until a separate runtime/license is measured (per "Image-out" note).
- Clarify the exact role wiring for embed placement and decision nodes ? are they already pinned or need verification?
- Whether STT/TTS nodes require separate pinned runtimes once a runtime exists.
- No measurements, file contents, or results provided; assume we must gather them from repo state.

---

**Bottom line**: Complete graph construction for LFM3 family covering default and contingency nodes with verified components, preserving existing conventions, and ensuring fail-closed behavior. No live GPU/reboot actions needed.

-- swarm/surface1
