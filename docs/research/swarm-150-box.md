# Graph: multi-engine same-role instances + archetype auto-defaults

Issue: https://github.com/brianreborn/familia/issues/150
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:35 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

## Issue #150: Graph: multi-engine same-role instances + archetype auto-defaults

### Requirement (Brian [number] t757u)

Not just candidates. Users may run **several instances of the same role** on one host with **different engines** (e.g. one llama coder + one Cactus/other-engine coder) in tandem, competing, or specialized for different work.

Also: each host should **automatically get something sensible** from its purported role + archetype (phone / laptop / 1U server / ?), spanning engines ? llama covers most models but defaults must not be llama-only (Cactus STT, ONNX TTS, drex-dlm, lbref, ?).

### Design laws
- Node **TYPE** implies capability; host is placement only.
- No new host-prefixed unique node names (`angel-coder` style).
- Disambiguate multi-instances without breaking private type-named topologies (document scheme: e.g. role+engine suffix or instances map).

### Related in-flight
- Researcher branch `feat/lfm3-phone-defaults-matrix` (LFM3-1.7B phone chat/coder + multi-engine matrix doc).
- Private topologies (#145 merged).

### Owner / branch
- Primary: **Researcher** (graph)
- Review: Platform Reviewer (schema), Hermes Wiring (agents surface)
- Branch: `feat/lfm3-phone-defaults-matrix` (or follow-up if split)

### Acceptance
- [ ] Schema allows ?2 same-role nodes on one host with different `runtime`/engine

-- swarm/box
