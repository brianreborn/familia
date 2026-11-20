# escalation_proxy accepts unauthenticated loopback callers and injects the instance key

Issue: https://github.com/brianreborn/familia/issues/415
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.7-live mode=live)
Generated: 2026-11-19 16:28 PST
Approved-content-sha256: 4c741ebe4077e54a9482bf530b7bcf384604d3a568481e5bd4f60a6fcf985c53

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18114); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=[user] role=swarm-pull prog=swarm-pull@0.2.7-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

[Familia Project - Issue #415]

(a) **What the issue asks:**  
Issue #415 reports a security gap in the `escalation_proxy.py` script (around line 703). The proxy binds to `127.0.0.1` without requiring caller authentication. When it processes an outbound request, it calls `familia_auth.auth_headers` and **adds the instance key** even if the inbound request had no key. This means any local process or user on the same machine can reach the proxy and get keyed access to the nodes, violating the design's security rule (DESIGN.md). The behavior existed before PR #414, which only documented it as a gap rather than fixing it.

(b) **Proposed approach & files/components:**  
- **Fix:** In `scripts/escalation_proxy.py`, modify the `serve()` function so that the instance key is **only added to outbound headers** when the inbound request did **not** already contain a key.  
- **Implementation:** Require the caller's key on the proxy, using the same `keys_match` check that `scripts/graph_router.py` uses for caller authentication on every endpoint (except possibly `/health`).  
- **Files likely involved:**  
  - `scripts/escalation_proxy.py` (around line 703) ? main change.  
  - `scripts/graph_router.py` ? reference for the existing `keys_match` logic.  
  - `familia_auth.auth_headers` ? to understand how headers are built and where the instance key is currently injected.  
- **Scope:** This is not a tool-specific exception; the proxy is a standing service and must enforce caller key authentication.

(c) **Risks & test ideas:**  
- **Risks:**  
  - An unauthenticated local loopback caller (e.g., a local script or user hitting `127.0.0.1`) would previously receive keyed (authenticated) responses. After the fix, it should get a 401 Unauthorized and the key should not be injected into the request/response.  
  - Existing clients that rely on the proxy forwarding unauthenticated loopback traffic could break.  
  - Other parts of the system that assume the proxy adds the instance key automatically might need adjustment.  
- **Test ideas (unknown specifics, but general suggestions):**  
  - Write a test that starts `escalation_proxy.py` in loopback mode, makes an HTTP request to `http://127.0.0.1:port/...` without sending an auth key in the request headers, and asserts the response status is **401** and the instance key is **not** present in the outbound headers.  
  - Ensure that a request **with** a valid caller key still gets keyed access (i.e., behavior unchanged for authenticated callers).  
  - Verify that all endpoints except `/health` (if kept public) enforce the same `keys_match` check as in `graph_router.py`.  
  - Run a local process (e.g., `python -m pytest`) to confirm that a local process can now reach the proxy and get keyed access before the fix, and after the fix it should be blocked or return 401.  

(d) **Open questions:**  
- Exact location and condition of the `keys_match` check in `graph_router.py` ? need to confirm it applies to all endpoints except `/health`.  
- Whether the `/health` endpoint should remain public without key authentication.  
- How `familia_auth.auth_headers` determines whether a request had a key (e.g., header presence, token, etc.).  
- Whether the instance key should be injected into outbound headers for **all** outbound calls or only in specific scenarios.  
- Impact on existing tests for the proxy and escalation flow.  
- Whether the fix should also cover the reverse direction (i.e., inbound requests to the proxy from outside the machine) or only local loopback.  

[Note: No file contents, measurements, or results invented; details above are based solely on the issue text.]

-- swarm/box
