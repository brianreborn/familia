# Scale-down track: speculative backend ? Perez Hourglass (Fibonacci/? codes, PHAM), benchmark-gated vs LittleBit and llama-quantize

Issue: https://github.com/brianreborn/familia/issues/28
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:57 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #28: Scale-down track: speculative backend

**What it is:** The issue asks for the `feat/scale-down` branch to expose a compression backend registry. Each backend should register as `encode/decode` (weights, `memory_index` vectors, KV payloads) along with its measured cost. The proposed backends are `llama-quantize` (Q8_) and `Perez Hourglass` (PHAM).

**Proposed approach:**

1. **Define the Backend Interface:**
   - Create a `Backend` interface with methods `encode` and `decode`.
   - Implement `llama-quantize` and `Perez Hourglass` as concrete backends.

2. **Register Backends:**
   - Use a registry to store and manage backends.
   - Each backend should register itself with the registry.

3. **Measure Backend Costs:**
   - Implement a cost measurement mechanism for each backend.
   - Store the measured cost in the backend registry.

4. **Expose Backend Registry:**
   - Create a `BackendRegistry` class to expose the registered backends.
   - Provide methods to retrieve backends by name or cost.

**Files or components likely involved:**

- `Backend.py`
- `llama_quantize.py`
- `perez_hourglass.py`
- `BackendRegistry.py`
- `backend_registry.py`

**Risks:**

1. **Unvalidated Claims:**
   - The claims made by Perez Hourglass and the Journal version are unproven. This could lead to skepticism and potential issues with the design.

2. **Complexity:**
   - Implementing and managing multiple backends could introduce complexity, especially if

-- swarm/angel
