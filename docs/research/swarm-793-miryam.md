# 0.5.0 graph catalog: expose all declared routes and capabilities

Issue: https://github.com/brianreborn/familia/issues/793
Runner: miryam (stamp v=1 host=miryam role=swarm-pull prog=swarm-pull@0.2.7-live mode=live)
Generated: 2026-11-27 08:26 PST
Approved-content-sha256: 3f0cc59062e0035dba2ddcb6b55882a1794d708a05fee62f6e2844237e2e2c72

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on miryam)

stamp v=1 host=miryam role=swarm-pull prog=swarm-pull@0.2.7-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Work Note #793 - Familia 0.5.0 Graph Catalog Update

## (a) Issue Summary
The `/v1/models` endpoint on the Green RoomZ public API needs to accurately reflect all graph-backed aliases defined in the system. Currently, it is missing critical metadata regarding which models are available and which are not. The goal is to ensure clients can distinguish between ready routes and unavailable ones with clear reasons. Additionally, this update must avoid exposing backend nodes directly; instead, the catalog should be managed via a public API route that handles routing logic safely.

## (b) Proposed Approach & Components
**Approach:**
1.  **Catalog Update:** Iterate through existing model metadata to populate the `/v1/models` endpoint with status for every declared alias.
2.  **Status Handling:** Mark unavailable aliases as `unavailable` and include a specific reason field in the response.
3.  **Routing Type Reuse:** Utilize existing routing types rather than creating new branches per model name to maintain consistency across the codebase.
4.  **Public API Constraint:** Ensure no backend node is directly accessible via `/v1/models`. All logic must remain within the public route layer.

**Files/Components Involved:**
*   `models/` directory (likely contains metadata definitions).
*   `catalogs/` or similar configuration for graph aliases.
*   Green RoomZ adapter implementation (`green-roomz`).
*   Public API routing logic handling `/v1/models`.
*   Existing model metadata structures.

**Unknown:**
*   Exact format of the "reason" string for unavailable models (unknown).
*   Specific file paths for where graph aliases are defined (unknown).
*   Whether existing `model-name-specific branches` should be removed or modified (unknown).

## (c) Risks & Test Ideas
**Risks:**
1.  **Backward Compatibility:** If the catalog structure changes unexpectedly, clients relying on specific field names might break.
2.  **Backend Exposure:** There is a risk if this update inadvertently exposes backend logic via the public API route. This must be strictly prevented by ensuring all routing happens within the adapter layer.
3.  **Data Consistency:** Ensuring that unavailable aliases are marked correctly without breaking the graph's internal state.

**Test Ideas:**
1.  **Availability Check:** Send a request to `/v1/models` for an unavailable alias and verify it returns an error before backend dispatch occurs.
2.  **Capability Validation:** Verify that ready routes return correct input/output capabilities in the response.
3.  **Direct Access Prevention:** Ensure no direct access to backend nodes is possible via the public API route (e.g., no `/v1/models` calls bypassing adapter logic).

## (d) Open Questions
*   What specific format should be used for the "reason" field in unavailable models?
*   Is there a standard mechanism in Familia's routing types to indicate model status, or does this require new definitions?
*   How will the catalog interact with existing `model-name-specific branches` if they are removed?

---
**Status:** Draft Pending Review

-- swarm/miryam
