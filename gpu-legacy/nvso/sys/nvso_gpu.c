/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * nvgpu_dma_post backend stub — bridge from gpu-legacy sm11 descriptor ideas.
 */
#include <sys/param.h>

#ifdef __FreeBSD__

#include <sys/systm.h>
#include <sys/errno.h>

#include "../include/nvso.h"
#include "nvso_if.h"

struct nvso_softc;

int
nvso_gpu_dma_post(struct nvso_softc *sc, struct nvgpu_dma_post_req *r)
{
        (void)sc;
        if (r == NULL)
                return (EINVAL);
        if (r->ndesc == 0 || r->ndesc > NVSO_MAX_DMA_DESCS)
                return (EINVAL);
        /* Future: post descs across CDC/peer; OS monitors only. */
        r->status = EOPNOTSUPP;
        return (EOPNOTSUPP);
}

#else
int nvso_gpu_linux_anchor = 0;
#endif
