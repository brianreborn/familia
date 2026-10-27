/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * nvssd_queue_export — soft bookkeeping only.
 * Accepts queue geom into the domain table; does NOT program SandForce/Vertex2
 * doorbells or claim open firmware DMA.
 */
#include <sys/param.h>

#ifdef __FreeBSD__

#include <sys/systm.h>
#include <sys/bus.h>
#include <sys/conf.h>
#include <sys/lock.h>
#include <sys/mutex.h>
#include <sys/errno.h>

#include "../include/nvso.h"
#include "nvso_if.h"
#include "nvso_var.h"

int
nvso_ssd_queue_export(struct nvso_softc *sc, struct nvssd_queue_export_req *r)
{
        struct nvso_domain *d;

        if (sc == NULL || r == NULL)
                return (EINVAL);
        d = nvso_domain_lookup(sc, r->domain_id);
        if (d == NULL) {
                r->status = EINVAL;
                return (EINVAL);
        }
        if (r->geom.depth == 0 || r->geom.sq_entry_bytes == 0) {
                r->status = EINVAL;
                return (EINVAL);
        }
        /* Soft: store geom on domain; no hardware queue bind. */
        d->geom = r->geom;
        d->has_geom = 1;
        r->status = 0;
        return (0);
}

#else
int nvso_ssd_linux_anchor = 0;
#endif
