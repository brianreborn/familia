# HVVRAM architecture — staged design sketch

**Status:** Stages 0–1 shippable — Stage 1 soft domains implemented in `gpu-legacy/nvso` (ABI 2).  
**Not claimed / does not work yet:** hardware HVVRAM, custom SSD firmware, G84 independent SO domains, or zero-copy GPU↔SSD DMA.

## One picture

```
┌─────────────────────────────────────────────────────────────────┐
│ Stage 0 — Software VVRAM (LAYER.md)                             │
│  llama mmap GGUF + OS swap + spill_path slot-save               │
│  Host: angel Nanbeige. No nvso.ko required.                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ bookkeeping API
┌────────────────────────────▼────────────────────────────────────┐
│ Stage 1 — Soft HVVRAM domains (nvso(4) softc)                   │
│  Domain table + VA/NVM map records + queue geom + DMA desc log  │
│  /dev/nvso0 ioctls succeed in soft mode; no peer DMA wire.      │
└────────────────────────────┬────────────────────────────────────┘
                             │ needs open FW
┌────────────────────────────▼────────────────────────────────────┐
│ Stage 2 — Custom SSD firmware (FIRMWARE-PLAN.md)                │
│  Open SandForce / Vertex2-class FW: raw queues, geometry,       │
│  doorbells, LBA windows exported to OS (not black-box FTL).     │
└────────────────────────────┬────────────────────────────────────┘
                             │ needs CDC/peer path
┌────────────────────────────▼────────────────────────────────────┐
│ Stage 3 — OS-bypass DMA (DESCRIPTOR-FORMAT.md)                  │
│  GPU posts nvgpu_dma_desc across CDC; OS maps+monitors only.    │
│  Bridge from gpu-legacy sm11_shim ideas; FreeBSD-first.         │
└────────────────────────────┬────────────────────────────────────┘
                             │ needs silicon (or FPGA stand-in)
┌────────────────────────────▼────────────────────────────────────┐
│ Stage 4 — Independent SO domains (paper path)                   │
│  Per-SO PLL/voltage, local MMU, partitioned L2, power-gate.     │
│  Stock G84 does NOT provide this — research silicon / emulator. │
└─────────────────────────────────────────────────────────────────┘
```

## Naming

| Term | Meaning here |
|------|----------------|
| **Software VVRAM** | Stage 0 — SSD as overflow for weights/KV via mmap/swap/spill |
| **Soft HVVRAM** | Stage 1 — kernel domain/map bookkeeping without DMA |
| **HVVRAM** | Stages 2–3 target — NVM-backed domain memory with posted DMA |
| **SO domain** | Stage 4 — independent Streaming Multiprocessor domain (silicon) |

## Non-goals (explicit)

- Do not pretend nvidia 340 / CUDA 6.5 on 256 MiB G84 equals SO domains.
- Do not load stock SSD FTL and call it “open queues.”
- Do not require nvso.ko for Nanbeige dogfood (Stage 0 stays primary for fleet).
- Do not parallel sole-worker hosts while implementing.

## Host roles (unchanged honesty)

| Host | Stages | Notes |
|------|--------|-------|
| angel / Uriel | 0 (now), 1 (soft ABI 2 in-tree), 2 (FW lab), 3–4 candidate | FreeBSD coordinator; i5-4570 (VT-d), **G84 8600 GT installed**; see [HARDWARE-INVENTORY](../HARDWARE-INVENTORY.md) |
| qodesh | 3 bridge experiments (Windows) | Its own 8600 GT + gpu-legacy (Windows); sole Worker |
| miryam | Stage 0 adjacent (Vulkan iGPU) | Not HVVRAM |
| box | Stage 0 dogfood / docs / userspace build | No DRI |

## ABI spine

Userspace ↔ kernel: `include/nvso.h` + `nvso_ioctl.h`  
Methods: `nvso_domain_create`, `nvso_map`, `nvssd_queue_export`, `nvgpu_dma_post`, `nvso_domain_gate`, `nvso_irq_attach`  
Docs: [G84-BRIDGE.md](./G84-BRIDGE.md), [FIRMWARE-PLAN.md](./FIRMWARE-PLAN.md), [DESCRIPTOR-FORMAT.md](./DESCRIPTOR-FORMAT.md), man `nvso(4)` / `nvso(9)`.

## Success criteria by stage

| Stage | Done when |
|-------|-----------|
| 0 | angel-coder loads Nanbeige via mmap; swap+spill measured (BENCH) |
| 1 | `kldload nvso`; `nvsoctl` create→map→gate (+ soft export/post) returns 0 soft — **code landed ABI 2**; angel kmod compile is the remaining host gate |
| 2 | Lab FW exposes ≥1 SQ/CQ pair + LBA window; `nvssd_queue_export` binds real geom |
| 3 | One posted peer DMA completes without bounce; counters in BENCH |
| 4 | Emulated or research SO domain isolation metrics published |

## Related

Thread: [THREAD-SOURCE.md](./THREAD-SOURCE.md) · Ship-today: [LAYER.md](./LAYER.md) · Bench: [BENCH.md](./BENCH.md)
