# HVVRAM design-review package (pre-build)

— Other Grok Bot ASSIST · executor · 2026-10-31 (PT)

**Status: for review. Nothing gets built, loaded, or installed until Brian approves each phase.** SSD special-firmware work is **deferred** (see §6).

## 1. Sources, newest first

| # | Source | Date (PT) | Notes |
|---|---|---|---|
| 1 | `brianreborn/papers` `hyper-virtualized-multi-tier-coherent-memory/` (README.md, PDF/DOCX), last commit 58e233a | 2026-10-30 09:22 | **Newest and most complete design.** It's the white paper: N-ary ownership protocol (Invalid/CPU/GPU/Shared), lock-free directory, IOMMU enforcement (VT-d SNP / AMD FC, tags in ignored/AVL PTE bits), async invalidation co-pilot, FS-tier primary path, custom-FW secondary path. It has no numbers by design. |
| 2 | `familia-private` 5818167 (branch `hvvram-handoff`, PR familia-private#3, open) | 2026-10-27 21:33 | Brian's answers: H = Hyper; N tiers open-ended; OCZ Vertex 2 is the spare FW/NVM target; swap stays on the HDD. Also the FreeBSD CUDA 6.5 / 340.108 location (angel-freebsd `Projects/cuda-8600gt`). |
| 3 | `familia-private` 3fbb1c2: HANDOFF.md, x-discussion.md, angel-runbook.md | 2026-10-27 21:22 | X thread design intents (SO domains, blocking sync, FreeBSD-first, man pages first, no bounce buffers). |
| 4 | `angel-freebsd` issues #1–#8 ("hvvram E0–E6", Hourglass encoding track) | 2026-10-27/28 | Encoding/integrity experiments. They're orthogonal to the memory path. |
| 5 | `familia` `docs/vvram-ssd/*`, `gpu-legacy/nvso` (ABI 2), last nvso commit c3d9834 | 2026-10-26 | Stages 0–4 staging, soft kmod. |

Gaps between the paper and the conversation records, carried in from #2/#3:
- The paper's tiers L0–L3 match Brian's "N tiers".
- The paper doesn't mention G84, Vertex 2, angel, or the SO-domain silicon (Stage 4). Those live only in the familia docs and the X thread.
- The "Linux prototype with partitioned L2" cited on X has **still not been found** in any repo.
- No transcript of other bots was read for this package; that's left for the reviewers.

## 2. What we have today (verified by reading the code)

`gpu-legacy/nvso` ABI 2 is about 650 LOC of soft bookkeeping. Review found two **blocking defects** that would have shown up at the first `kldload`:

1. **`/dev/nvso0` never appears.** `DRIVER_MODULE(nvso, nexus, …)` with `BUS_PROBE_NOWILDCARD` and no `identify` method means no device is ever added, so attach never runs. The "kmod built on angel" note (c3d9834) proved compilation only.
2. **Sleeping under a mutex.** `nvso_ioctl` holds the `MTX_DEF` `sc->lock` and then calls `nvso_gpu_dma_post`, which does `malloc(M_WAITOK)` and `copyin()`. On an INVARIANTS/WITNESS kernel that panics ("sleeping with non-sleepable lock"). On GENERIC it's a latent bug.

There are also minor issues:
- Unknown descriptor/map/domain flag bits are accepted, which contradicts DESCRIPTOR-FORMAT.
- The `u32` byte sum can overflow.
- There's no domain destroy, so the table fills permanently.
- Overlapping map records are accepted.
- `depth` isn't checked to be a power of 2, which the FW contract requires.

A fix is drafted (pseudo-device `DEV_MODULE` + `make_dev_s`, DMA post outside the lock, strict validation, `DESTROY`/`STATS` ioctls → ABI 3). It is **parked unpushed** pending this review. It is P1 below.

## 3. API surface: sizing and the expected pushback

The current ABI exposes 6 ioctls. Four of them encode Stage 3/4 hardware that doesn't exist: PLL cfg, power gate, IRQ attach, and peer DMA post. In soft mode they're stores into a table.

**The executor's own recommendation, for the reviewers to attack:**
- Freeze ABI 2/3 as "research soft".
- Build the paper's actual protocol as a **separate, smaller API** where the directory is primary:

| Call | Purpose | Kernel? |
|---|---|---|
| `hv_region_create(size, tiers_allowed)` / `destroy` | Managed range | P2 userspace; P3 kernel object |
| `hv_acquire(region, off, len, OWNER_CPU/GPU/SHARED)` | Ownership transition (directory + barrier) | P2 userspace; P4 IOMMU |
| `hv_release(...)` | Drop to Invalid / allow eviction | same |
| `hv_place(region, off, len, tier_hint)` | Advisory migration | userspace |
| `hv_stats()` | Counters, latency histograms | both |

That's 5–7 calls. Everything else (PLL, gate, IRQ, DMA_POST) moves to an `nvso` "lab" ABI that isn't on the critical path.

## 4. Phases, decision points, and rough cost

Cost key: S < 1 agent-day, M 1–5 days, L 1–3 weeks, **XL/HUGE** = open-ended research.

| Phase | Deliverable | Kernel change? | Cost | Gate / Brian decision |
|---|---|---|---|---|
| **P0** Baseline | Stage-0 BENCH JSONL on angel: Nanbeige mmap + spill, plus the ZFS SSD tier from §5 vs the HDD | No (pool creation needs root, delivered as a script) | S–M | **D0:** approve the Vertex 2 zpool creation (destroys data on that disk) and bench window |
| **P1** Soft ABI fix | ABI 3 nvso (defects above), negative tests, kldload in a **bhyve/QEMU FreeBSD 15.1 VM on a LAN host**, never on angel first | Yes, kmod only, no VM/pmap | S | **D1:** approve the KERNEL-REVIEW.md diff, then the VM test, then (separately) kldload on angel |
| **P2** Userspace directory + FS tier | `libhvv`: lock-free directory (per-page 2-bit state, atomics), L1↔L2 migration via files on ZFS, `mlock`/`msync` barriers; hooks for llama KV/weights | No | M–L (~2–3k LOC) | **D2:** approve the API in §3 and which workload goes first (KV cache recommended) |
| **P3** Kernel pager | Fault-driven tiering: managed `cdev_pager`/`OBJT_MGTDEVICE` VM object, ownership in the vm_page layer | **Yes: VM/pmap, high risk** | L | **D3:** separate kernel review; VM-only testing for weeks first |
| **P4** IOMMU enforcement | Tags in VT-d PTE bits 53:52, permission flips + IOTLB invalidation via FreeBSD DMAR (`sys/x86/iommu`) | **Yes: DMAR driver** | **HUGE** ⚠ | **D4:** see blockers below |
| **P5** Async invalidation co-pilot | Dedicated core drains the invalidation queue | Yes | M (after P4) | with D4 |
| Deferred | SSD custom firmware (Vertex 2 SandForce SF-1222) | FW | **HUGE** ⚠ | deferred per Brian |
| Deferred | PSP/CSME off-load | FW/security | **HUGE** ⚠, security-sensitive | recommend dropping |
| Deferred | Stage 4 SO domains (silicon/FPGA) | — | **HUGE** | paper only |

**⚠ P4 feasibility, revised 2026-10-31.** An earlier revision wrongly said the G84 was in a separate Athlon II box. **Per Brian, the G84 (GeForce 8600 GT) is in angel**, and angel's i5-4570 supports VT-d. See LESSONS-LEARNED `L-hostloc`. **Re-probe angel (`pciconf -lv`, `sysctl hw.model`, `dmesg`) before any test, since parts move.**

- **No longer a blocker:** the "wrong box" problem is gone. VT-d and the GPU are in the same machine.
- **Still the main risk:** the closed nvidia-340 FreeBSD kmod.
  - It is believed to allocate with `contigmalloc` and hand the GPU physical addresses (`vtophys`) instead of going through `busdma`. Unverified: check by reading the open-source kmod shim in `nvidia-driver-340`.
  - If so, then with DMAR translation enabled (`hw.dmar.enable=1`), GPU DMA either faults, or the GPU has to be excluded or identity-mapped. In both cases the driver never tells DMAR which pages it uses.
- **Faults are not recoverable:** the G84 has no ATS/PRI, so an IOMMU fault is a GPU hang or a lost transfer, not a recoverable page fault.
- **Realistic shape:** P4 can only be a **tripwire/enforcement experiment**. nvso would own the G84's DMAR context, identity-map the driver's pages, and flip R/W on HVVRAM-managed ranges. It can't do demand paging. That's **XL, high risk, bare metal on angel only**, since passing a G84 through to a VM is itself a VT-d experiment.
- **Gate P4-0 (cheap, needs Brian's OK for one reboot):**
  - The chipset must expose a DMAR ACPI table (`acpidump -t | grep -c DMAR`). B85/H87 boards vary, so VT-d on the CPU alone isn't enough.
  - Then boot once with `hw.dmar.enable=1` and record whether `nvidia0` attaches and CUDA `vadd` passes. That needs a root script for Brian.
- **Decision:** P3 is worth funding only if P4-0 passes. Otherwise use directory-only (soft) enforcement.

## 5. SSD tier: ZFS on the Vertex 2, example performance and tuning

**Hardware facts:**
- The OCZ Vertex 2 uses a SandForce SF-1222 controller over SATA 3 Gb/s.
- SandForce compresses internally, so incompressible data (quantised GGUF weights) runs slower than vendor numbers.
- angel: i5-4570 (4C/4T, Haswell, VT-d capable), 24 GiB, FreeBSD 15.1, **GeForce 8600 GT (G84) installed**, swap on HDD. (Brian, 2026-10-31; re-probe before any test.)

**Example performance (expected ranges, NOT measured; P0 measures them):**

| Workload | Raw Vertex 2 (incompressible) | ZFS dataset as tuned below | HDD (7.2k) for contrast |
|---|---|---|---|
| Seq read 1 MiB (weights stream) | ~200–250 MB/s | ~180–230 MB/s | ~120–160 MB/s |
| Seq write 1 MiB (spill/KV save) | ~70–140 MB/s (worse once worn, fresh-TRIM better) | ~70–130 MB/s | ~100–150 MB/s |
| Rand read 4 KiB QD1 | ~5–8k IOPS (~0.15 ms) | ~3–6k (ARC miss path) | ~100 IOPS (~8–10 ms) |
| Rand read 4 KiB QD32 | ~30–50k IOPS | ~20–40k | ~150–200 |
| Llama Q4_K_M 18.7 GiB cold load | ~80–100 s | ~85–110 s | ~120–160 s |

The point: the Vertex 2 is a **latency** tier, about 50–100× better than HDD on random access, not a bandwidth tier. Token-generation speed for weights that don't fit RAM is bounded by about 200 MB/s. For 33B Q4, page-faulting even 2 GiB per token gives roughly 0.1 tok/s. The tier is useful for **KV/spill and cold layers**, not hot weights. P0 must confirm this.

**Pool / vdev:**
```
zpool create -o ashift=12 -o autotrim=on -O atime=off -O xattr=sa \
  -O compression=lz4 -O checksum=fletcher4 -O redundant_metadata=most hvv /dev/adaN
```
- `ashift=12`: SF-1222 NAND pages are 4–8 KiB and the drive reports 512 B. The default autodetect would pick 9, which is **wrong**. 13 is acceptable; benchmark 12 vs 13 in P0.
- `autotrim=on`: SandForce degrades badly without TRIM. Also run a weekly `zpool trim`.
- Single disk, no redundancy: it's a cache tier. Data must be reproducible.

**Datasets (defaults assumed wrong):**

| Dataset | recordsize | compression | primarycache | secondarycache | sync / logbias | Why |
|---|---|---|---|---|---|---|
| `hvv/weights` (GGUF, read-only) | 1M | off (Q4 data incompressible; saves CPU) | **metadata** | none | standard / throughput | llama `mmap` already caches in the VM page cache. ARC=all would **double-cache** 18.7 GiB on a 24 GiB box. |
| `hvv/kv` (L2 tier pages, directory-managed) | 64K (match the hvv page/region size; 16K if regions are small) | lz4 (f16 KV compresses ~1.1–1.3×) | **metadata**: the directory/L1 is the cache; ARC would hide tier latency and break measurements | none | **disabled** / throughput | Scratch tier: on crash the directory marks it Invalid. sync=disabled is only safe because of that contract. |
| `hvv/spill` (llama slot saves) | 1M | lz4 | metadata | none | disabled / throughput | Large sequential, reproducible |
| `hvv/logs` (BENCH JSONL) | 128K | zstd | all | none | standard | Must survive crashes |

**ARC sizing (`/boot/loader.conf`):**
- `vfs.zfs.arc_max="2G"`, `vfs.zfs.arc_min="512M"`. ARC must not compete with the 18.7 GiB model plus KV in 24 GiB. The default (most of RAM) is wrong for this workload.
- If the root pool is UFS, ARC only serves `hvv`, so metadata-only caching fits easily in 1–2 GiB.
- `vfs.zfs.arc.meta_*` tuning is unnecessary at this size.
- **L2ARC:** none on `hvv`. The **alternative to evaluate in P0** is to put the HDD swap/bulk pool's `secondarycache=all` on a small Vertex 2 partition, measured against the native tier.

**vfs.zfs tunables (sysctl / loader.conf):**
- `vfs.zfs.vdev.async_read_max_active=8`, `vfs.zfs.vdev.sync_read_max_active=8`: a SATA NCQ depth of 32 is shared, so leave headroom.
- `vfs.zfs.vdev.aggregation_limit=1048576`
- `vfs.zfs.txg.timeout=5` (default; test 10 for spill bursts)
- `vfs.zfs.dirty_data_max` = about 1 GiB (bounds write bursts that otherwise stall readers)
- `vfs.zfs.prefetch.disable=0` for weights; the directory does its own prefetch for kv, so compare with zfetch on vs off in P0
- `vfs.zfs.trim.queue_limit` default

**FreeBSD kernel / sysctl:**
- `hint.ahcich.N.pm_level=0`: disable SATA link power management (ALPM adds wake latency).
- `kern.cam.ada.N.write_cache=1`: SandForce has no power-loss capacitor. That's acceptable only because the tier is scratch.
- Swap stays on the HDD, never on a zvol (zvol-swap deadlocks under memory pressure).
- `vm.pageout_oom_seq=120` and `vm.overcommit=0` so OOM shows up in `dmesg_oom` instead of thrashing.
- `kern.ipc.shm_use_phys=1` if P2 uses SysV/POSIX shm for L1.
- `machdep.hyperthreading_allowed` n/a (4C/4T)
- `powerd -a hiadaptive`, or `-a max` during benches
- `kern.timecounter.hardware=TSC-low`, for stable latency stamps
- Keep `kern.sched` defaults. Pin the co-pilot (P5) with `cpuset -l 3`.

**BIOS (nominal optimum for angel's Haswell board):**
- SATA mode **AHCI**, not IDE/RAID. Vertex 2 on a native Intel port (SATA 6G is fine; the drive negotiates 3G). Hot-plug off.
- **VT-d ON**, plus VT-x ON (needed for P4 and for bhyve).
- Intel SpeedStep ON, Turbo ON. **C-states:** limit to C3/C1E during benches (C6/C7 exit latency hurts QD1 I/O). Production can re-enable.
- Memory at rated JEDEC/XMP with correct timings. Run memtest before P0, since the ZFS checksum would otherwise blame the disk.
- ASPM off for PCIe/SATA during benches. Above-4G decoding n/a. CSM/legacy only if the G84 VBIOS needs it.
- Boot from the OS disk only. **Never** select the Vertex 2 as a boot device.

## 6. Deferred: SSD special firmware

Deferred per Brian. It's sized **HUGE**:
- The SF-1222 firmware is proprietary and unsigned-tool-locked.
- Public reverse-engineering is partial.
- A bad flash bricks the drive.
- Bring-up needs a UART/JTAG programmer and a donor drive.

Any flash needs Brian's explicit OK (runbook §4).

## 7. Kernel-review scope (feeds `gpu-legacy/nvso/KERNEL-REVIEW.md`, P1)

P1 touches **no VM/pmap/busdma**. It covers:
- a cdev with a single `MTX_DEF`
- the ioctl ABI (group 'N', numbers 1–8)
- copyin of ≤ 8 KiB

Failure modes:
- A panic on load or unload would be a bug in `make_dev_s`/`destroy_dev`.
- A WITNESS warning would mean a lock-order regression.

Rollback is `kldunload nvso`. Nothing is in `loader.conf`.

Test order:
1. VM on a LAN host (INVARIANTS+WITNESS kernel), `nvsoctl` round-trip + negative tests, 1000× load/unload loop.
2. Brian reviews the results.
3. Only then, a single `kldload` on angel.

P3/P4 get their own review documents. They change VM/pmap/DMAR and are high risk.

## 8. Decisions for Brian

1. **D0:** OK to wipe the Vertex 2 and create the `hvv` pool, plus a bench window on angel (root script to be supplied).
2. **D1:** Approve the ABI 3 fix scope, the VM test on a LAN host, then kldload on angel.
3. **D2:** Accept a directory-first API (5–7 calls) and demote the PLL/gate/IRQ/DMA_POST ioctls to a lab ABI? Choose the first workload (KV cache?).
4. **D3/D4:** Fund P3 (kernel pager) only if P4 is viable. Approve gate P4-0 (DMAR table check + one `hw.dmar.enable=1` boot on angel with the G84). If nvidia-340 fails under DMAR, accept directory-only enforcement or pick a different GPU.
5. Drop PSP/CSME off-load from scope? (security and TCB size)
6. Where is the "Linux prototype with partitioned L2"? It's still unlocated.
