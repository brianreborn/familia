/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * nvgpu_dma_post — soft path: validate + copyin descriptors, update summary.
 * Does NOT post peer DMA to G84 or SSD; see DESCRIPTOR-FORMAT.md.
 */
#include <sys/param.h>

#ifdef __FreeBSD__

#include <sys/systm.h>
#include <sys/bus.h>
#include <sys/conf.h>
#include <sys/lock.h>
#include <sys/mutex.h>
#include <sys/errno.h>
#include <sys/malloc.h>

#include "../include/nvso.h"
#include "nvso_if.h"
#include "nvso_var.h"

int
nvso_gpu_dma_post(struct nvso_softc *sc, struct nvgpu_dma_post_req *r)
{
        struct nvso_domain *d;
        struct nvgpu_dma_desc *descs;
        size_t bytes;
        uint32_t i, sum;
        int error;

        if (sc == NULL || r == NULL)
                return (EINVAL);
        d = nvso_domain_lookup(sc, r->domain_id);
        if (d == NULL) {
                r->status = EINVAL;
                r->soft_flags = 0;
                return (EINVAL);
        }
        if (r->ndesc == 0 || r->ndesc > NVSO_MAX_DMA_DESCS) {
                r->status = EINVAL;
                r->soft_flags = 0;
                return (EINVAL);
        }
        if (r->desc_user_ptr == 0) {
                r->status = EINVAL;
                r->soft_flags = 0;
                return (EINVAL);
        }

        bytes = (size_t)r->ndesc * sizeof(struct nvgpu_dma_desc);
        descs = malloc(bytes, M_TEMP, M_WAITOK | M_ZERO);
        if (descs == NULL) {
                r->status = ENOMEM;
                r->soft_flags = 0;
                return (ENOMEM);
        }

        error = copyin((const void *)(uintptr_t)r->desc_user_ptr, descs, bytes);
        if (error != 0) {
                free(descs, M_TEMP);
                r->status = error;
                r->soft_flags = 0;
                return (error);
        }

        sum = 0;
        for (i = 0; i < r->ndesc; i++) {
                if (descs[i].dir != NVGPU_DMA_H2D &&
                    descs[i].dir != NVGPU_DMA_D2H &&
                    descs[i].dir != NVGPU_DMA_PEER) {
                        free(descs, M_TEMP);
                        r->status = EINVAL;
                        r->soft_flags = 0;
                        return (EINVAL);
                }
                sum += descs[i].len;
        }

        /* Soft success: record summary; no hardware DMA. */
        sc->dma_sum.last_ndesc = r->ndesc;
        sc->dma_sum.last_domain_id = r->domain_id;
        sc->dma_sum.last_bytes = sum;
        sc->dma_sum.post_count++;

        free(descs, M_TEMP);
        r->status = 0;
        r->soft_flags = NVSO_POST_SOFT;
        return (0);
}

#else
int nvso_gpu_linux_anchor = 0;
#endif
