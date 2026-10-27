/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * nvssd_queue_export backend stub — open SandForce/Vertex2 path lives here later.
 */
#include <sys/param.h>

#ifdef __FreeBSD__

#include <sys/systm.h>
#include <sys/errno.h>

#include "../include/nvso.h"
#include "nvso_if.h"

/* softc defined in nvso.c */
struct nvso_softc;

int
nvso_ssd_queue_export(struct nvso_softc *sc, struct nvssd_queue_export_req *r)
{
        (void)sc;
        if (r == NULL)
                return (EINVAL);
        /* Future: bind raw queue geom from open FW into domain MMU. */
        r->status = EOPNOTSUPP;
        return (EOPNOTSUPP);
}

#else
int nvso_ssd_linux_anchor = 0;
#endif
