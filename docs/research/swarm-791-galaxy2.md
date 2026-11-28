# 0.5.0 fleet monitor: graph-derived six-host inventory

Issue: https://github.com/brianreborn/familia/issues/791
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-28 05:11 PST
Approved-content-sha256: 657b406ef41695b04be869d8b564c5767a2bbcd1d9cba94a3a0cfad3d1253816

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #791 ? 0.5.0 fleet monitor: graph?derived six?host inventory

## (a) What the issue asks
The **Familia fleet monitor** should report on its active hosts automatically instead of relying on a second, hard?coded list.  
Specifically:

* The monitor must show exactly the six intended host identities ? `angel`, `galaxy1`, `galaxy2`, `miryam`, `note9`, `surface1`.  
* Old identities or ports that disappear from the current state should **not** trigger false ?death? alerts.  
* Prefer data derived from the internal graph (the same topology used by the gateway) over a manual list.  
* Distinguish three roles for each host: **model endpoint**, **graph gateway**, and **worker liveness**.  
* Private LAN addresses must be supplied locally; they should not be committed as secrets.

---

## (b) Proposed approach & likely files/components

1. **Replace the hard?coded inventory** with a query against the existing graph data source (e.g., Neo4j or an internal adjacency model).  
2. For each of the six known host identifiers (`angel`, `galaxy1`, ?, `surface1`):
   * Look up the node that represents its **model endpoint**.  
   * If a separate node denotes the **graph gateway** or a **worker liveness service**, map it accordingly.  
   * Extract the current public/private LAN address and port from the node?s properties (or from local config).  
3. Build the monitor payload so that one invocation returns exactly those six identities, each with its truthful endpoint role and resolved private address/port.  
4. Move the mapping logic into a small helper module so it can be unit?tested without touching the graph.

**Likely files / components**

| Area | File (guess) |
|------|--------------|
| Main monitor entry point | `monitor.py` or `fleamaintainer/fleet_monitor/...` |
| Graph client / access layer | `graph_client.py`, `neo4j_client.py` |
| Local private?address configuration | `hosts_local.yaml` or environment variables (not to be committed) |

---

## (c) Risks & test ideas

### Risks
| Risk | Mitigation |
|------|------------|
| Graph schema changes ? wrong roles returned. | Add fallback to local config; log missing data and continue. |
| Hosts disappear from the graph (migrated off) ? false ?death? alerts. | Output still lists them with *unknown* role and omits death alerts. |
| Private LAN addresses leaked if stored in repo. | Keep only locally?supplied values; never commit secrets. |
| Existing callers depend on the old list. | Update all invocations to use the new function; run full test suite after change. |

### Suggested tests
* **Unit**: Mock the graph client and assert that for each of the six host IDs we receive the correct role strings and LAN address/port.  
* **Integration**: Run `monitor --once` (or invoke via CLI) in a staging environment and verify:
  * Exactly six lines are printed: `angel`, `galaxy1`, ?, `surface1`.  
  * Each line contains its current endpoint role (`model_endpoint`, `graph_gateway`, or `worker_liveness`) and the resolved LAN address/port.  
  * No ?death? alert appears for any host that is still active in the graph.  
* **Regression**: Re?run existing tests that previously passed with the hardcoded list.

---

## (d) Open questions
- What is the exact schema of the internal graph? Which node labels correspond to *model endpoint*, *graph gateway*, and *worker liveness*?  
- Where are private LAN addresses currently stored locally? Is there a config file or environment variable we can reuse?  
- Does the existing monitor already have access to the graph, or does it need to be initialized separately?  
- Are there known obsolete ports for any of these hosts that should be ignored in alert logic?

*Unknown* details above will require investigation before implementing the change.

-- swarm/galaxy2
