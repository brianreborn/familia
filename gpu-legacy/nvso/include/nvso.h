/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * Copyright (c) 2026 familia / green-roomz R&D
 *
 * Shared ABI for nvso(4) — Independent SO Domains + SSD DMA (research).
 * Soft HVVRAM domain bookkeeping (ABI 2): create/map/gate/irq + soft
 * queue_export/dma_post succeed in-kernel without real G84/SandForce DMA.
 * Does NOT imply working hardware SO domains or open SandForce FW.
 */
#ifndef _NVSO_H_
#define _NVSO_H_

#include <stdint.h>
#include <sys/types.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NVSO_ABI_VERSION        2
#define NVSO_NAME_MAX           32
#define NVSO_MAX_DOMAINS        32
#define NVSO_MAX_DMA_DESCS      256
#define NVSO_MAX_MAPS_PER_DOM   64

/* Soft-path capability / result bits (documentation + nvsoctl). */
#define NVSO_CAP_SOFT_DOMAINS   0x0001u  /* in-kernel domain table */
#define NVSO_POST_SOFT          0x0001u  /* dma_post: accepted soft-only */

/* Domain flags (nvso_map / create) */
#define NVSO_DOM_PRIVATE        0x0001u
#define NVSO_DOM_CDC_SAFE       0x0002u
#define NVSO_DOM_PINNED         0x0004u
#define NVSO_DOM_POWER_GATED    0x0008u

/* Map flags */
#define NVSO_MAP_READ           0x0001u
#define NVSO_MAP_WRITE          0x0002u
#define NVSO_MAP_EXEC           0x0004u
#define NVSO_MAP_NVM            0x0008u  /* backed by exported SSD queue */

/* DMA direction */
#define NVGPU_DMA_H2D           1
#define NVGPU_DMA_D2H           2
#define NVGPU_DMA_PEER          3  /* GPU <-> SSD peer */

struct nvso_pll_cfg {
        uint32_t clock_khz;
        uint32_t voltage_uv;
        uint32_t flags;
        uint32_t reserved;
};

struct nvso_domain_create_req {
        uint32_t            abi_version;   /* NVSO_ABI_VERSION */
        uint32_t            domain_id;     /* in: preferred; out: assigned */
        struct nvso_pll_cfg pll;
        uint64_t            mmu_handle;    /* opaque; 0 = kernel alloc */
        uint32_t            flags;         /* NVSO_DOM_* */
        uint32_t            status;        /* out: errno-style */
};

struct nvso_map_req {
        uint32_t domain_id;
        uint32_t flags;          /* NVSO_MAP_* */
        uint64_t va;
        uint64_t size;
        uint64_t nvm_off;        /* if NVSO_MAP_NVM */
        uint32_t status;
        uint32_t pad;
};

struct nvssd_queue_geom {
        uint32_t queue_id;
        uint32_t depth;
        uint32_t sq_entry_bytes;
        uint32_t cq_entry_bytes;
        uint64_t raw_lba_base;
        uint64_t raw_lba_count;
        uint32_t flags;
        uint32_t pad;
};

struct nvssd_queue_export_req {
        uint32_t domain_id;
        uint32_t pad;
        struct nvssd_queue_geom geom;
        uint32_t status;
        uint32_t pad2;
};

struct nvgpu_dma_desc {
        uint64_t src;
        uint64_t dst;
        uint32_t len;
        uint32_t dir;            /* NVGPU_DMA_* */
        uint32_t flags;
        uint32_t pad;
};

struct nvgpu_dma_post_req {
        uint32_t domain_id;
        uint32_t ndesc;
        uint64_t desc_user_ptr;  /* pointer to nvgpu_dma_desc[ndesc] in user VA */
        uint32_t status;
        uint32_t soft_flags;     /* out: NVSO_POST_SOFT when soft path */
};

struct nvso_domain_gate_req {
        uint32_t domain_id;
        uint32_t enable;         /* 0=gate off (power down), 1=ungate */
        uint32_t flags;
        uint32_t status;
};

struct nvso_irq_attach_req {
        uint32_t domain_id;
        uint32_t irq_hint;
        uint64_t notify_user_ptr; /* optional eventfd-like cookie; FreeBSD: kevent later */
        uint32_t status;
        uint32_t pad;
};

#ifdef __cplusplus
}
#endif

#endif /* _NVSO_H_ */
