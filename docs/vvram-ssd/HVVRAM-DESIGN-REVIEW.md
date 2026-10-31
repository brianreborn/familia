# HVVRAM design-review package (pre-build)

— Other Grok Bot ASSIST · executor · 2026-10-31 (PT) · rev 3 (reviewer objections folded in)

**Status: for review. Nothing gets built, loaded, or installed until Brian approves each phase.** Firmware with on-drive processing is **phase PF, right after the P0 ZFS baseline** (see §6).

**Resources:** HVVRAM is critical but runs alongside other work. It never blocks a pre-release and never takes over all dev machines or reviewers: when they compete, HVVRAM yields to pre-release work.

**Hardware locations:** this doc makes no inventory claims. Parts move. Every hardware-dependent step starts with a fresh probe of the live host (`pciconf -lv`, `sysctl hw.model hw.physmem`, `camcontrol devlist`, `geom disk list`, `dmesg`), and the result goes in that step's log.

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

### 3.1 API hardening (from Senior Dev, Bootstraps, Platform, Boundary reviews)
- **Count:** the five rows above plus `hv_version()` and `hv_revoke()` = 7 calls.
- **Errors, all-or-nothing:** every call returns 0 or an errno: `EINVAL` (bad/unknown flag or enum, unaligned, `len==0`, `off+len` overflow checked with overflow builtins, out of region), `EBUSY` (conflicting owner), `EAGAIN`/`ETIMEDOUT` (contended, with an optional timeout), `ENOSPC` (tier full), `ESTALE` (generation changed), `EPERM` (not the owner), `EINTR` (signal; nothing changed). A transition never leaves a range half-moved; the doc states the state after every failure. `hv_place` reports its result via an out-param and `hv_stats`.
- **Lifetime and owner-death release:** ownership is tied to a handle (fd or region object). Close, exit or signal death releases every range the handle owns. `hv_revoke` lets the region owner reclaim; optional lease timeouts. Fork: handles are not inherited (`O_CLOEXEC`-like); a child must reacquire.
- **Versioning:** `hv_version()` / `HVIOC_GETINFO` returns ABI, tiers, features. Every struct carries size + version; unknown flags are rejected, never ignored.
- **N-ary state:** replace the 2-bit page state with a versioned state word: state, owner id, tier, generation counter, migrating bit, updated by CAS (the generation also stops ABA). Shared supports several readers.
- **Concurrency:** page/region alignment, overlap rules, CAS ordering across tiers, acquire/release memory ordering after `hv_acquire` returns, plus a fence for GPU visibility. A state-transition table lists illegal transitions → error.
- **Caller isolation:** the principal is the handle from `open()`; regions belong to the creating cred; no global names. `hv_stats` is per caller; global stats are root-only (timing side channel). Tier files are opened with `openat` under a dirfd, `O_NOFOLLOW|O_CREAT|O_EXCL`, generated ids only, mode 0600; one tier root with strict `${}` expansion so a missing variable never becomes an empty path. No SysV shm (`shm_use_phys` dropped); use `shm_open(SHM_ANON)` with fd passing.
- **Trust boundary:** P2's userspace directory is **advisory/cooperative only**; it is never the only thing protecting a page. Enforcement comes only in P3/P4.
- **:9931 per-instance key:** hv calls are in-process library calls from the llama runtime only, with no network/RPC surface. If one is ever added, it sits behind the familia :9931 per-instance key, forwarded on every hop (including recursive `operator()`), compared in constant time, fail-closed. No field derived from model output ever reaches `hv_*` arguments (no region names, paths or tiers from model text).
- **Lab ABI:** PLL/gate/IRQ/DMA_POST move to a separate module or are compiled out by default; when present they return `ENODEV`/`EOPNOTSUPP` unless loader tunable `hw.nvso.lab=1`, node mode 0600 root. No silent success.
- **Host scope:** FreeBSD first. Linux (RLIMIT_MEMLOCK), Windows (VirtualLock) and Termux/SELinux are out of scope until named.

## 4. Phases, decision points, and rough cost

Cost key: S < 1 agent-day, M 1–5 days, L 1–3 weeks, **XL/HUGE** = open-ended research.

| Phase | Deliverable | Kernel change? | Cost | Gate / Brian decision | Exit / kill / rollback |
|---|---|---|---|---|---|
| **P0** ZFS baseline | Live-host probe; stock-firmware raw bench + SMART + identity dump; ZFS tier from §5 vs HDD; smaller model first, `rctl` memory cap | No (pool creation by a reviewed root script) | **M** | **D0:** wipe-by-serial (§5.0), bench window, each persistent change approved separately | **Go/no-go for the project:** if KV spill on the SSD doesn't beat recompute/HDD by a set margin, stop before P2. Rollback: `zpool destroy`, revert script |
| **PF** Firmware with on-drive processing | §6 sub-phases PF-sel → PF0 (emulated NVMe) → PF1 donor → PF2 target | FW + host command channel | **HUGE ⚠** (many months) | **D-PF:** the 8 pre-flash gates in §6 | Kill criteria in §6 |
| **P1** Soft ABI fix | ABI 3 nvso, negative tests + fuzz, kldload in an INVARIANTS/WITNESS FreeBSD 15.1 VM on an idle LAN host, never on angel first | kmod only | **M** (VM image, harness, 1000× loop) | **D1:** KERNEL-REVIEW.md diff → VM test → separately kldload on angel | Rollback `kldunload`; no loader.conf/devd/rc autoload |
| **P2** Userspace directory + FS tier | `libhvv` (§3.1), KV cache first; llama.cpp patch costed separately on a pinned version | No | **L** (+ model checker / stress harness for the lock-free code) | **D2** API + **D2-sec** security review (first multi-process surface) | Correctness gate before D2 |
| **P3a** Read-only pager spike | `cdev_pager`, no ownership | VM | L | after D4 | |
| **P3** Kernel pager | Fault-driven tiering, ownership in vm_page | **VM/pmap, high risk** | **XL/HUGE ⚠**, needs a FreeBSD VM expert | **D3** blocked until D4 | weeks VM-only first |
| **P4** IOMMU enforcement | Tripwire only (see below); PTE bits 53:52 must be checked against VT-d spec and `sys/x86/iommu` users | DMAR | **XL/HUGE ⚠** | **D4** decided **before P2 design** | |
| **P5** Async invalidation | co-pilot core | Yes | M, contingent on P4 | with D4 | |
| Dropped | PSP/CSME off-load | — | — | recommend dropping (TCB we can't audit) | |
| Paper only | Stage 4 SO domains | — | HUGE | — | |

**Order:** P0 → PF-sel (cheap) → P1 (parallel, idle LAN host) → D4 → PF0… → P2 (KV first) → P3a → P3/P4 only if D4 says yes. Total: many months, not weeks.

**⚠ P4 feasibility.** Brian said on 2026-10-31 that the G84 is in angel. That is a hint, not an inventory claim: re-probe before any test (see header). Fault handling and what happens to pages owned by a dead process go in the P3/P4 review docs.

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
- Target host: whatever the live probe shows. Last reported (hint only, not inventory): Haswell i5 with VT-d, ~24 GiB, FreeBSD 15.1, G84, swap on HDD.

### 5.0 Safety rules for P0 (from all four reviews)
- **Wipe by serial allowlist.** The D0 root script takes the drive **serial + model** Brian supplies, resolves the device via `camcontrol identify` / `geom disk list`, and refuses if: the serial isn't on the allowlist, it is the boot disk, it is mounted, it is in any pool, or it holds partitions/labels not on the allowlist. Dry-run by default, typed confirmation, then GPT-partition and use `gpt/hvv0`, never `adaN`. The script is reviewed before D0, not "to be supplied".
- **Archive first:** stock FW rev, `camcontrol identify`, SMART (wear/life + reallocated) before and after; write budget per bench; abort on wear threshold.
- **Encryption:** KV/spill hold prompts and outputs. `hvv/kv` and `hvv/spill` use `encryption=aes-256-gcm, keyformat=raw` with a per-boot ephemeral key (reboot = crypto-erase). Swap on the HDD uses GELI onetime (`.eli`). No plaintext KV on any tier. BENCH logs are classified and scrubbed of prompts.
- **sync:** `sync=disabled` only on a dataset that is pure scratch **and** wiped/recreated at boot. `hvv/kv` stays `sync=standard` until P2 has a persisted pool-generation id checked at startup. On a single no-PLP SandForce disk a power cut can lose the whole pool, so `hvv/logs` lives on the OS disk/HDD, not this pool, and `write_cache=1` is bench-only.
- **Readers** treat EIO/checksum errors as a cache miss, never fall back to unverified data. `hvv/weights`: `readonly=on` after population, `exec=off setuid=off devices=off`, GGUF hash checked on load.
- **Persistent changes** (loader.conf, sysctl, zpool, trim, powerd, BIOS) are each approved separately, live in one `/boot/loader.conf.d/hvv.conf` + `sysctl.conf.d` snippet with an undo script, and are recorded before → after (`sysctl -a` snapshot). BIOS changes need a person at the machine. CPU mitigations stay at default.
- **Tunables:** verify every name with `sysctl -d` on 15.1 and fail on unknown names. Use `vfs.zfs.arc.max/min`. `vm.overcommit=0` and `pm_level=0` are defaults (not tuning); `pageout_oom_seq=120` *delays* OOM; `vfs.zfs.trim.queue_limit` likely doesn't exist; `pm_level`/`write_cache` are loader-only; check TSC-low in `kern.timecounter.choice`. Drop `shm_use_phys`.
- **Swap (Brian 2026-10-31):** swap gets its own zvol `hvv/swap` in the pool (16G default; volblocksize=4K, compression=off, sync=always, primarycache=metadata, logbias=throughput, one-time encryption key). Known FreeBSD risk: swap on a zvol can deadlock under severe memory pressure because ZFS needs memory to page out. So the HDD `ada0s1b` stays as a GELI-onetime fallback, used as bridge swap during the P0 wipe so there is never a no-swap window. Persistent zvol swap (fstab/rc) is a separate approval. This supersedes "swap stays on the HDD, never on a zvol" below.
- **A/B in P0:** `primarycache=all` vs `metadata` and recordsize 128K vs 1M under real mmap faulting (1M records with metadata-only caching may re-read 1 MiB per 4 KiB fault); lz4 on vs off on top of SandForce compression; ashift 12 vs 13 means creating the pool twice; autotrim **or** periodic trim, not both. The L2ARC "HDD pool" alternative is dropped (swap is a raw partition). Pin llama mmap flags. BENCH JSONL in C locale, UTC offsets, BIOS and powerd state recorded.

The table and settings below are the **pre-review starting point**; where 5.0 conflicts, 5.0 wins.

**Example performance (estimates only, NOT measured; P0 measures them):**

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
| `hvv/kv` (L2 tier pages, directory-managed) | 64K (match the hvv page/region size; 16K if regions are small) | lz4 (f16 KV compresses ~1.1–1.3×) | **metadata**: the directory/L1 is the cache; ARC would hide tier latency and break measurements | none | **standard** / throughput, encrypted (§5.0) | sync=disabled only after P2 has a persisted generation id checked at boot. |
| `hvv/spill` (llama slot saves) | 1M | lz4 | metadata | none | disabled only if wiped at boot / throughput, encrypted | Large sequential, reproducible |
| ~~`hvv/logs`~~ | — | — | — | — | — | Moved off this pool to the OS disk/HDD (§5.0) |

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

## 6. Phase PF: SSD firmware with on-drive processing (next after the P0 baseline)

Brian: on-drive processing is a priority and comes right after the ZFS baseline. It is not deferred. It is also the riskiest phase.

**Note on a reviewer conflict:** the Senior Developer follow-up (at `70cbd85`) says Brian chose "firmware replacement *instead of* ZFS". Resolved by Brian on 2026-10-31: both ZFS and custom firmware are in scope, ZFS first (see §8, D-PF0). Its firmware findings apply either way.

**Target problem.** The Vertex 2 (SF-1222, SATA) is close to a dead end for computational storage: closed, encrypted/obfuscated vendor images, no SDK, no documented spare compute, ~15-year-old MLC, and NVMe computational-storage commands (TP4091 family) don't exist on SATA. It also is the P0 tier, so flashing it would destroy the baseline. So the Vertex 2 is the ZFS tier, and the firmware target is chosen by a scorecard.

| Sub-phase | Work | Cost |
|---|---|---|
| **PF-sel** | Drive-selection scorecard (toolchain openness, recovery path, compute headroom, cost, licensing) across Vertex 2, a community-reversed controller, and an open platform (OpenSSD-class FPGA, open-channel/ZNS). Named offload candidate (e.g. KV-page compression/filter) with a measured host bottleneck from P0. Licensing note. | M |
| **PF0** | **Emulated NVMe first:** QEMU NVMe / FEMU with a NAND model. Host command channel, FTL state machine, fault injection, power-cut simulation in CI. No hardware. | XL |
| **PF1** | Toolchain bring-up and **recovery demonstrated on a donor** (brick on purpose, restore stock) | HUGE ⚠, may stop here |
| **PF2** | FTL + kernels on the donor: soak, thousands of relay power cuts | XL |
| **PF3** | Target drive, then integration as an HVVRAM tier | L–XL |

**Design requirements.**
- **FTL:** written state machine before code; CoW mapping with journalled/checkpointed metadata, atomic commit records with sequence numbers, recovery scan proven for a cut at any point, FLUSH/FUA strict, host write cache off until power-cut tests pass; TLA+ model of the metadata protocol. Vendor NAND/ECC parameters read from stock behaviour; erase counts, ECC histogram, bad blocks via log page/SMART; retirement threshold; retention bake.
- **End-to-end integrity:** host-side CRC32C/xxh3 per 4 KiB + LBA + generation, verified on every read, mismatch → Invalid; periodic scrub. Logs and bench results never on the drive.
- **Trust:** the drive is untrusted. Host encrypts before data reaches it (§5.0); plaintext offload is a named per-dataset opt-in. Never boot from it, no secrets, no auto-flash. Reproducible image, hash reviewed by two people, recorded privately. Flash only on an isolated host with no other disks. Treat the drive as untrusted-for-confidentiality forever; physical destruction at decommission. Any future PCIe/NVMe target only with IOMMU confinement.
- **Command channel:** CAM pass-through tool (no kmod) or nvso extension; versioned device ABI separate from nvso; version/caps/submit/poll/abort; job size/duration limits, timeouts, error codes, idempotent reset, defined media state after a half job; root-only, no jails, no generic pass-through exposed to hv callers.
- **Donor/spares:** at least two identical spares (controller, NAND, board revision): one for RE/recovery, one flashed first. Budget for losing both.
- **Licensing:** written note before PF1: which tools are licensed, whether derived work can be redistributed, DMCA §1201 exposure if the boot ROM verifies signatures (if it does, custom code is out of scope). No vendor blobs, keys, dumps or bypass details in any public repo; stock images and checksums go to familia-private only; clean-room docs for anything published.

**Recovery:** a stock image, identity, serial and factory/calibration data backed up off-host before any write; restore path rehearsed on the donor. If recovery can't be shown, Brian signs off on the exact wording "drive is consumable".

**Kill criteria (stop PF):** boot ROM requires a signature we can't legally satisfy; recovery can't be demonstrated and Brian declines "consumable"; emulator FTL can't pass power-cut tests; the offload can't beat the host path measured in P0 (≈200 MB/s SATA ceiling); both spares lost.

**The 8 gates before the first real flash (all required):**
1. Fresh hardware probe of the live host and target drive; controller, FW, NAND, board rev match the donor.
2. P0 stock baseline published.
3. Legal/licensing note done; no proprietary material in a public repo.
4. Recovery demonstrated on an identical donor, or Brian signed "drive is consumable".
5. Emulator + donor pass criteria met (≥10× capacity write/read/verify, N thousand power cuts with zero mapping loss, results bit-identical to host reference, SMART stable).
6. Host-side checksums implemented and verified.
7. Reproducible image, two-person hash review, flash script selects by serial allowlist with dry-run.
8. Brian's explicit OK for that specific flash, with a person physically present.

## 7. Kernel-review scope (feeds `gpu-legacy/nvso/KERNEL-REVIEW.md`, P1)

P1 touches no VM/pmap/busdma. Checklist (Platform, Boundary, Senior Dev, Bootstraps):
- **Unload with open handles / in-flight ioctls:** `destroy_dev` drain, `MOD_QUIESCE` refuses while busy, DMA-post work drained.
- **DESTROY vs DMA_POST race** (new now that post runs outside the lock): refcount domains against in-flight posts; destroy only by owner (domains carry creator cred/fd).
- **devfs perms and jail visibility:** `make_dev_s` UID_ROOT, mode 0600 (or a dedicated group), hidden in jails via devfs ruleset; `priv_check` on mutating ioctls; securelevel behaviour.
- **ABI size checks:** every command listed with its `_IOWR` size; group 'N' checked for collisions; ABI-2 callers fail cleanly against ABI 3; size validated **before** allocation; u64 overflow-safe sums; unknown flags rejected.
- **Signal / exit cleanup:** per-fd state released on close and on signal death (cdevpriv destructor).
- **Info leak:** bzero structs before copyout, including STATS.
- **Resource limits:** per-user domain-table caps, malloc caps; no stored user pointers.
- **Concurrency:** many-thread ioctls under WITNESS.
- **Fuzz:** random-ioctl fuzzer (or syzkaller) for N hours on the INVARIANTS VM, a gate before D1.
- **Rollback:** `kldunload`; also confirm no loader.conf/devd/rc autoload, plus a reboot test.

Test order: VM on an idle LAN host (instructions: `docs/vvram-ssd/HVVRAM-P1-LAN-INSTRUCTIONS.md`) → Brian reviews → only then one `kldload` on angel. P3/P4 docs are scoped now: vm_object/vm_page busy and locking, pmap invalidation, DMAR context teardown and IOTLB ordering, ATS/device bypass, GEOM/CAM/ZFS path from the fault handler, fault handling and dead-owner pages.

## 8. Decisions for Brian

1. **D-PF0: RESOLVED (Brian, 2026-10-31 9:14 AM PT):** "We're doing both ZFS and custom firmware but trying to unblock the ZFS stuff before we can make the firmware". Both are in scope; the order is ZFS baseline (P0) first, then firmware (PF). The "firmware *instead of* ZFS" reading is withdrawn.
2. **D0:** OK to wipe the Vertex 2 by serial allowlist (you supply serial + model), the bench window, and each persistent change separately.
3. **D1:** ABI 3 fix scope; OK to run the P1 build + VM test on an idle LAN host (which host?); later and separately, kldload on angel.
4. **D2 / D2-sec:** accept the hardened 7-call directory-first API (§3.1), KV cache first, lab ioctls split out.
5. **D4 (before P2):** run gate P4-0 (DMAR ACPI table check + one `hw.dmar.enable=1` boot) or accept software-only (advisory) enforcement / a different GPU. D3 waits on it.
6. **D-PF:** fund PF-sel (cheap) now; buy at least two identical donor/spare drives; licensing note owner.
7. Drop PSP/CSME off-load.
8. Encryption: ephemeral-key ZFS encryption for kv/spill and GELI onetime swap.
9. Where is the "Linux prototype with partitioned L2"? Still unlocated.
