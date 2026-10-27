/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * Kernel-private softc / soft HVVRAM domain bookkeeping.
 * Soft path only — no claim of G84/SandForce hardware DMA.
 *
 * Include FreeBSD sys headers (param, bus, conf, lock, mutex) before this.
 */
#ifndef _NVSO_VAR_H_
#define _NVSO_VAR_H_

#include "../include/nvso.h"
#include "nvso_if.h"

#ifndef NVSO_MAX_MAPS_PER_DOM
#define NVSO_MAX_MAPS_PER_DOM   64
#endif

struct nvso_map_ent {
        uint64_t        va;
        uint64_t        size;
        uint64_t        nvm_off;
        uint32_t        flags;
        uint32_t        used;           /* 0 = free slot */
};

struct nvso_domain {
        uint32_t                id;
        uint32_t                flags;          /* NVSO_DOM_* */
        uint32_t                in_use;
        uint32_t                gated;          /* 1 = power-gated (soft) */
        struct nvso_pll_cfg     pll;
        uint64_t                mmu_handle;
        uint64_t                irq_cookie;
        uint32_t                irq_hint;
        uint32_t                nmaps;
        struct nvso_map_ent     maps[NVSO_MAX_MAPS_PER_DOM];
        int                     has_geom;
        struct nvssd_queue_geom geom;           /* soft export bookkeeping */
};

struct nvso_dma_summary {
        uint32_t        last_ndesc;
        uint32_t        last_domain_id;
        uint32_t        last_bytes;             /* sum of desc lens */
        uint32_t        post_count;             /* soft posts accepted */
};

struct nvso_softc {
        device_t                dev;
        struct cdev            *cdev;
        struct mtx              lock;
        struct nvso_methods     methods;
        uint32_t                ndomains;       /* in-use count */
        struct nvso_domain      domains[NVSO_MAX_DOMAINS];
        struct nvso_dma_summary dma_sum;
};

/* Lookup helpers (nvso.c); backends may call under sc->lock. */
struct nvso_domain *nvso_domain_lookup(struct nvso_softc *sc, uint32_t id);

#endif /* _NVSO_VAR_H_ */
