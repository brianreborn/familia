# FIRMWARE-PLAN — Custom SSD firmware for HVVRAM (design sketch)

**Status:** sketch only. No custom FW binary is in this repo.  
**Premise (thread):** reverse / reimplement Vertex 2–class SandForce FW to expose **raw queues and geometry**, not a black-box FTL.

## Why FW is on the critical path

Stage 1 soft domains can record a `nvssd_queue_geom`, but **HVVRAM** needs the device to actually:

1. Own submission/completion queues the OS can map into an SO/soft domain.
2. Accept DMA descriptors (or NVMe-like commands) targeting those LBA windows.
3. Signal completion without bouncing through a hidden FTL that remaps everything.

Stock consumer SSD firmware will not give that. Hence: **custom firmware is still required** — this document defines what it must look like before anyone writes flash.

## Target class (lab)

| Item | Sketch target | Notes |
|------|---------------|-------|
| Platform | OCZ Vertex 2–class / SandForce SF-1200 era (or FPGA stand-in) | Prefer disposable lab NAND |
| Host OS | FreeBSD on angel first | newbus + ioctl already sketched |
| Interface | AHCI/SATA or emulated NVMe over virt for bring-up | Real SATA last; virt first if safer |
| Safety | Offline air-gapped programmer; never brick fleet boot disk | Angel OS disk ≠ FW victim |

## Must expose (userspace/kernel contract)

Aligned with `struct nvssd_queue_geom` / `nvssd_queue_export`:

| Field / capability | FW responsibility |
|--------------------|-------------------|
| `queue_id` | Stable ID for SQ/CQ pair |
| `depth` | Power-of-two queue depth |
| `sq_entry_bytes` / `cq_entry_bytes` | Fixed entry sizes |
| `raw_lba_base` / `raw_lba_count` | **Identity-mapped** LBA window (no silent remaps inside window) |
| Doorbell registers | MMIO or BAR offsets published in geom.flags / companion ioctl later |
| Completion IRQ / MSI | Enough for `nvso_irq_attach` cookie |
| Admin channel | Separate from data queues: identify, reset, scrub |

### Command sketch (data plane)

Minimal opcode set for Stage 2→3:

| Opcode | Meaning |
|--------|---------|
| `NVM_NOP` | Latency probe |
| `NVM_READ` | Host→buffer from LBA window |
| `NVM_WRITE` | Buffer→LBA window |
| `NVM_DMA_PEER` | Accept GPU-originated desc (Stage 3); may start as host-mediated |

FTL **outside** the exported window may still exist for wear-leveling of other regions; the exported window is the HVVRAM contract.

## Threat model (sketch)

| Risk | Mitigation |
|------|------------|
| Brick lab drive | Socketed donor; recover via UART/JTAG programmer |
| Data exfil via open queues | Lab-only; no secrets on victim media |
| Host crash on bad doorbell | Soft domain validates geom; hard map behind `nvso_map` flags |
| Fleet boot disk confusion | Checklist: confirm `ada*` identity before any flash |

## Bring-up order

1. **Document + geom structs** (this file + nvso headers) — now.
2. **Soft export** — `nvssd_queue_export` stores geom without talking to hardware (Stage 1) — **done in ABI 2**.
3. **UART/identify stub FW** on donor — prints geom; no flash write yet.
4. **Read-only LBA window** — host DMA read path; BENCH counters.
5. **Write path + wear policy** outside HVVRAM window.
6. **Peer DMA opcode** — only after DESCRIPTOR-FORMAT frozen.

## Non-goals

- Shipping FW blobs in familia git.
- Supporting every SandForce SKU.
- Replacing NVMe on modern SSDs for general storage.
- Claiming angel’s current system disk is the Vertex 2 victim.

## Interface to OS

```
FW identify
   → geom filled
      → NVSSD_QUEUE_EXPORT (domain_id, geom)
         → NVSO_MAP(..., NVSO_MAP_NVM, nvm_off)
            → later NVGPU_DMA_POST
```

See [DESCRIPTOR-FORMAT.md](./DESCRIPTOR-FORMAT.md) for DMA desc layout and [HVVRAM-ARCHITECTURE.md](./HVVRAM-ARCHITECTURE.md) for stage gates.
