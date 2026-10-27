# DESCRIPTOR-FORMAT — `nvgpu_dma_desc` and CDC notes (design sketch)

**Status:** frozen sketch for Stage 1–3 software; hardware interpretation TBD with FW.

## Wire layout (userspace / copyin)

From `include/nvso.h` (ABI v1+):

```c
struct nvgpu_dma_desc {
    uint64_t src;     /* VA or device bus addr (flags decide) */
    uint64_t dst;
    uint32_t len;     /* bytes; 0 invalid */
    uint32_t dir;     /* NVGPU_DMA_H2D | D2H | PEER */
    uint32_t flags;   /* see below */
    uint32_t pad;
};
```

Posted via:

```c
struct nvgpu_dma_post_req {
    uint32_t domain_id;
    uint32_t ndesc;            /* 1..NVSO_MAX_DMA_DESCS */
    uint64_t desc_user_ptr;    /* user VA of desc[ndesc] */
    uint32_t status;           /* out */
    uint32_t pad;
};
```

### `flags` bits (sketch)

| Bit | Name | Meaning |
|-----|------|---------|
| 0 | `NVGPU_DESC_SRC_DEVICE` | `src` is device/bus address |
| 1 | `NVGPU_DESC_DST_DEVICE` | `dst` is device/bus address |
| 2 | `NVGPU_DESC_FENCE` | Completion fence after this desc |
| 3 | `NVGPU_DESC_CDC` | Cross clock-domain; ordering relaxed per CDC rules |
| 4 | `NVGPU_DESC_SOFT` | Stage 1: record-only; no bus transaction |

Stage 1 soft path sets `NVGPU_DESC_SOFT` (or treats all posts as soft) and logs counts.

## Directions

| `dir` | Intent |
|-------|--------|
| `NVGPU_DMA_H2D` | Host memory → device (SSD window or GPU) |
| `NVGPU_DMA_D2H` | Device → host |
| `NVGPU_DMA_PEER` | GPU ↔ SSD without host bounce (Stage 3 goal) |

## CDC / ordering (paper constraints)

From thread: CDC-safe fabric for atomics/barriers/signaling.

Sketch rules until silicon exists:

1. Descriptors in one `nvgpu_dma_post` are **FIFO within domain** unless `NVGPU_DESC_CDC` is set.
2. Across domains: no implicit order; userspace inserts fence descs + `nvso_irq_attach` notifications.
3. Soft path: preserve post order in kernel log ring for BENCH replay; no bus barriers.

## Bridge from gpu-legacy (qodesh)

`sm11_shim` historically posts small-model work through legacy CUDA/GL paths. Future bridge:

- Emit an array of `nvgpu_dma_desc` from a host-side translator (not in-kernel G84 SO).
- FreeBSD `nvgpu_dma_post` validates domain + geom; Stage 3 HW consumes PEER descs.
- **Do not** require full llama CUDA on 256 MiB G84.

## Soft post algorithm (Stage 1 — implement now)

1. Validate `domain_id` exists and is not gated off.
2. `ndesc` in `1..NVSO_MAX_DMA_DESCS`.
3. `copyin` descriptors; reject `len==0`.
4. Increment softc counters: `posts`, `bytes`, `peer_descs`.
5. Set `status=0`; return 0.

No IOMMU map, no SSD doorbell — that is Stage 2–3.

## Versioning

- Changing field sizes ⇒ bump `NVSO_ABI_VERSION` and document in `nvsoctl -n`.
- Adding flag bits is backward compatible if unknown bits are rejected with `EINVAL`.

## Bench hooks

Record per post: domain_id, ndesc, sum(len), dir histogram, soft vs hard, latency_us (ioctl). See [BENCH.md](./BENCH.md).
