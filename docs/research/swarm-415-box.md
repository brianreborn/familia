# escalation_proxy accepts unauthenticated loopback callers and injects the instance key

Issue: https://github.com/brianreborn/familia/issues/415
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 07:20 PST
Approved-content-sha256: 4c741ebe4077e54a9482bf530b7bcf384604d3a568481e5bd4f60a6fcf985c53

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

Write in plain ASCII markdown for this GitHub issue.

## Suggested fix (not in #414)

Add the caller's key to the proxy, the same `keys_match` check `scripts/graph_router.py` uses for caller auth (every endpoint except `/health` if that should stay public). Do not inject the instance key into a request that arrived with no key. Add tests that an unauthenticated loopback call is 401 and is not forwarded.

This is not a named local-development-tool exception. The proxy is a standing service.

Do not publish keys, request bodies, or exploit recipes.

-- Other Grok Bot ASSIST
----- END SUGGESTED FIX -----

## Suggested fix (not in #414)

Add the caller's key to the proxy, the same `keys_match` check `scripts/graph_router.py` uses for caller auth (every endpoint except `/health` if that should stay public). Do not inject the instance key into a request that arrived with no key. Add tests that an unauthenticated loopback call is 401 and is not forwarded.

This is not a named local-development-tool exception. The proxy is a standing service.

Do not publish keys, request bodies, or exploit recipes.

-- Other Grok Bot ASSIST
----- END SUGGESTED FIX -----

## Suggested fix (not in #414)

Add the caller's key to the proxy, the same `keys_match` check `scripts/graph_router.py` uses for caller auth (every endpoint except `/health` if that should stay public). Do not inject the instance key into a request that arrived with

-- swarm/box
