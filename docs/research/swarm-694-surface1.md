# Design: coupled CPU-GPU memory pool scheduling + ULE-style mapping of per-host queues and claims

Issue: https://github.com/brianreborn/familia/issues/694
Runner: surface1 (stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-22 22:45 PST
Approved-content-sha256: cd603366dc74208d98971f03df3b6a949327ef84bc485b7a9a358d388f7ff311

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on surface1)

stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #694 ? Design: coupled CPU-GPU memory pool scheduling + ULE-style mapping of per-host queues and claims

## (a) What the issue asks

The **familia** swarm job for *surface1* needs a first?pass design note added to `main` (markdown only, no code changes or edits to `graph.yaml`). The change is a draft PR ? not merged.

Two parts:

1. **Coupled CPU?GPU memory pool on shared?memory hosts**  
   - Each host gets its own memory pool = *RAM minus reserve*, split into three logical slices: **CPU?only**, **GPU?borrowable**, and a **carve?out** for the GPU slice.  
   - Worker ?slices? are fixed bundles (MIG?style profile) that bundle threads from CPU, RAM, and GPU together.  
   - Admission rule: refuse a claim if after allocating it there isn?t enough free memory left to keep the host above its reserve **or** if PSI (pressure on shared memory) is high ? fail closed.  
   - A *paired* CPU+GPU split claim can be taken atomically for partial offload.  
   - If the GPU slice becomes unhealthy (`DEVICE_LOST`), the system falls back to using only the CPU slice.

2. **FreeBSD ULE scheduler mapping onto familia?s pull?swarm**  
   - Map ?ULE? (Unified Load/Execution?) ideas: per?CPU run queues ? per?host queue files at `~/swarm/queue.json`.  
   - Treat *interactivity score* as deciding short interactive jobs vs long batch jobs.  
   - Load balancing / work stealing should happen **only** via the existing forge claim mechanism ? no new coordinator, no second assignment path.

Constraints: **No coordinator or central dispatcher**, claims stay exclusive leases on the forge, owner approval gate stays unchanged. No host IPs, usernames, ports or keys in the doc.

---

## (b) Proposed approach & likely files / components

### 1. Memory?pool design per host
- Introduce a **per?host memory pool** object that tracks:
  - `ram_total`, `reserve_amount`
  - three sub?segments: `cpu_only`, `gpu_borrowable`, `carveout_gpu`.
- When a claim arrives, check:
  ```
  free_mem = (ram_total - reserve) - claim.size
  if free_mem < cpu_reserve OR PSI(memory_pressure) > threshold ? reject
  else atomically split claim into CPU+GPU parts (partial offload)
  ```
- If GPU slice fails (`DEVICE_LOST`), mark the pool?s GPU carve?out unhealthy and switch future allocations to `cpu_only` + remaining `gpu_borrowable`.

**Likely files / components**
- New config key or struct: `memory_pool[host_id]` (not in `graph.yaml`).
- A **pool manager** module that owns the three slices, handles admission logic and fallback.
- Integration point into existing job claim flow ? probably a small adapter around `claim()` / `release()`.

### 2. Worker slice bundles (MIG?style)
- Define a worker profile: `{gpu_threads, ram_threads, cpu_threads}`.
- The pool manager hands out these bundles atomically when a split claim is accepted.
- Tracking of ?unhealthy GPU? via a flag in the pool or per?device state.

**Likely files / components**
- Worker scheduler code (existing) extended to respect new bundle shapes.
- Possibly a new `WorkerBundle` struct/class.

### 3. Per?host queue mapping (ULE ? pull swarm)
- Create **per?host run queues** stored at `~/swarm/queue.json/<host_id>.json`.
- Each entry contains:
  - `interactivity_score` (derived from job type / priority).
  - list of pending claims or tasks.
- Load balancing: idle host picks up queued work by **pulling** via the existing forge claim path ? i.e., an idle process asks for a new lease on its own queue, no central coordinator.

**Likely files / components**
- New helper to serialize/flatten per?host queue into JSON.
- Hook into the swarm?s ?forge? claim mechanism (existing) so that only existing claims can be reclaimed.

### 4. ULE?style load balancing & work stealing
- Implement **steal** by scanning other hosts? `queue.json` for pending entries and pulling them, but only if the steal source has a free slot in its own memory pool (CPU+GPU split).
- No new coordinator; just reuse existing claim leases.

---

## (c) Risks & test ideas

| Risk | Why it matters | Mitigation / test |
|------|----------------|-------------------|
| **Memory?pressure false rejection** ? rejecting a valid job because PSI is high could cause queue buildup. | Fail?closed can starve short jobs. | - Add a metric: track rejected vs accepted claims per host over days.<br>- Run load tests simulating memory pressure spikes; verify fallback to CPU slice works without crashing GPU threads. |
| **Atomic split claim race** ? two concurrent split claims on the same pool could lead to under?allocation or double?use of GPU resources. | Partial offload may leave holes in GPU carve?out. | - Use a lock?free atomic counter for ?in?flight splits? per host.<br>- Unit test with simulated concurrent claim submissions; verify only one split is taken and the other waits/gets CPU slice. |
| **DEVICE_LOST detection latency** ? marking GPU unhealthy may cause sudden fallback to CPU, hurting performance on GPU?bound jobs. | Could degrade surface1 workloads if GPU fails mid?offload. | - Add a watchdog timer for GPU state; ensure `DEVICE_LOST` is set within a few seconds of failure.<br>- Fault injection tests (kill GPU process) and verify fallback to CPU slice without losing job progress. |
| **Per?host queue file format changes** ? unknown impact on existing jobs that rely on global queues. | Breaking change for other swarm jobs. | - Keep old `queue.json` files alongside new ones; migrate gradually.<br>- Add backward compatibility shim in the claim adapter. |
| **Interactivity score heuristic** ? not defined yet; could mis?classify jobs. | May cause wrong job type to be scheduled as interactive vs batch, affecting resource usage. | - Define a simple rule (e.g., `score > 0.5 ? short`, else long).<br>- Include a parameter or config option for future tuning. |
| **No central dispatcher** ? work stealing must not collide with existing coordinator logic in forge. | Risk of double?steal or missed jobs if steal path isn?t fully integrated. | - Audit forge claim API to ensure only ?existing lease? can be reclaimed.<br>- Add integration tests that simulate idle hosts pulling from others? queues and verify they receive tasks without extra assignments. |

### Suggested test plan (high?level, unknown specifics)

1. **Unit tests** ? memory pool admission logic with varying free memory & PSI values.
2. **Integration / load test** on a shared?memory host: submit CPU?only and GPU?split claims concurrently; verify split claim succeeds atomically, DEVICE_LOST triggers fallback, and no OOM.
3. **Queue migration test** ? create two `queue.json` files (old global + new per?host). Submit a job to each host and ensure it lands in the correct local queue without needing coordinator re?assignment.
4. **Steal simulation** ? mark one host idle, poll its `queue.json`, trigger work steal by another host; assert that the stolen task is handed over via forge claim only (no new path).
5. **Failure injection** ? kill GPU process on a pool; verify DEVICE_LOST flag and CPU?only fallback within expected window.

---

## (d) Open questions

- **Exact definition of ?PSI memory pressure? threshold** ? unknown in current codebase.
- **How to represent per?host queue JSON** ? file schema not specified.
- **Interactivity score calculation** ? no formula provided; may depend on job type or runtime metrics.
- **Integration with forge claim API**: details of existing claim lease handling (e.g., how ?exclusive lease? is enforced) are needed to ensure the new per?host queues don?t collide.
- **Worker bundle sizing** ? number of threads per slice (gpu/ram/cpu) is not defined; may need tuning based on host capabilities.
- **DEVICE_LOST semantics**: what exactly marks a GPU slice unhealthy? Is it a flag, a health check callback, or a failure event?
- **Testing infrastructure**: which environment will run the load tests? (e.g., surface1 node specs unknown.)

---

*This note is a first?pass design sketch for PR #694. No code or `graph.yaml` edits are included; only markdown describing intent.*

-- swarm/surface1
