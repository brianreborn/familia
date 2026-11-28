# 0.5.0 fleet monitor: graph-derived six-host inventory

Issue: https://github.com/brianreborn/familia/issues/791
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-28 05:03 PST
Approved-content-sha256: 657b406ef41695b04be869d8b564c5767a2bbcd1d9cba94a3a0cfad3d1253816

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Work note for GitHub Issue #791

## (a) What the issue asks

The Familia **fleet monitor** (v0.5.0) currently does not correctly report the six active host identities: **angel, galaxy1, galaxy2, miryam, note9, surface1**.  
- It may still show old identities or flag obsolete ports as ?dead? even though those hosts are alive.  
- The goal is to repair the inventory so that one monitor invocation returns exactly these six identities with their true current endpoint roles (model endpoint, graph gateway, worker liveness).  
- Old identities / port configurations should not produce misleading death alerts.  
- Prefer **graph?derived** host and endpoint data over a second hardcoded list.  
- Private LAN addresses and host?specific secrets must be supplied locally (not committed).

## (b) Proposed approach & likely files/components

1. **Replace the static six?host list** with dynamic discovery from the internal graph service that tracks:
   - Host identity ? endpoint mapping,
   - Graph gateway role,
   - Worker liveness status.

2. **Graph data sources** (unknown specifics):
   - `graph/hosts.json` or similar ? maps host names to local LAN addresses and ports.
   - `graph/gateways.json` ? defines the *model endpoint*, *graph gateway*, and worker nodes.
   - Possibly a live query API for liveness/health of workers.

3. **Local secret handling**:
   - Read per?host private LAN IPs and any required secrets from environment variables or config files that are already used elsewhere (e.g., `FAMILIA_HOST_IP`, `FAMILIA_SECRET_KEY`).

4. **Implementation sketch** (high?level):
   - In the monitor?s main loop, call a function like `discover_hosts(graph_data)` that returns the current active hosts.
   - For each discovered host, resolve its endpoint role by consulting the graph gateway mapping:
     - If the node is marked as *model endpoint* ? label ?model?.
     - If it?s part of the *graph gateway* ? label ?gateway?.
     - If it?s a worker node and liveness check passes ? label ?worker?alive?.
   - Emit alerts only for hosts whose expected ports are obsolete or have died; otherwise, report them as active.

5. **Components to touch** (unknown exact paths):
   - `monitor/familia/monitor.py` ? main monitor logic.
   - Graph data ingestion module (`graph_loader.py`) ? parses and caches graph JSON files.
   - Configuration loader for local addresses/secrets.
   - Possibly a new service or query client to the live graph API.

## (c) Risks & test ideas

| Risk | Why it matters |
|------|----------------|
| **Missing hosts** ? If discovery fails to find one of the six known identities, the monitor may report fewer than six. | Acceptance requires exactly those six. |
| **Stale graph data** ? Graph changes over time; using cached data could show a host as dead when it?s actually alive again. | Need periodic refresh or live checks. |
| **Port/endpoint mapping errors** ? Mis?mapping model endpoint vs gateway vs worker could cause wrong role labels and misleading alerts. | Unknown internal definitions; must verify against `graph/gateways.json`. |
| **Leak of private LAN addresses** ? If we still hardcode them, they become commit?able secrets. | Must read from env vars or local config at runtime. |
| **Performance / latency** ? Graph queries may be slow if not cached; could affect monitor invocation time. | Keep change small to avoid regressions. |

**Suggested tests (unknown specifics):**

- Run the current monitor binary and capture its output for each of the six identities.
- Mock `graph_data` with known host/endpoint mappings and verify that roles are reported correctly.
- Simulate an obsolete port on one of the hosts and ensure a death alert is emitted only for that host.
- Verify that environment variables (`FAMILIA_...`) supply correct private LAN IPs; confirm no hard?coded values appear in the diff.

## (d) Open questions

1. **Graph data format** ? What exactly are the files/keys under `graph/`? Need to inspect or ask the team.
2. **Definitions of ?model endpoint?, ?graph gateway?, and ?worker liveness?** ? How are these labels assigned in the graph?
3. **Source of private LAN addresses** ? Are they stored locally (e.g., `/etc/familia/hosts.conf`) or fetched from a service? Which env vars should be used?
4. **Exact location of hardcoded list** ? In which file(s) is the six?host list currently defined, and what are those ports/identities?
5. **Liveness checking mechanism** ? Is worker liveness checked via an HTTP endpoint or a separate health service? How does it differ from ?death alert??

*Items marked ?unknown? should be clarified before committing changes.*

-- swarm/galaxy1
