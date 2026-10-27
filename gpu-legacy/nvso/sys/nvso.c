/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * Copyright (c) 2026 familia / green-roomz R&D
 *
 * nvso(4) soft HVVRAM domain bookkeeping — FreeBSD-first research.
 * Soft path: domain_create / map / gate / irq_attach + soft SSD/GPU
 * bookkeeping succeed without claiming real G84/SandForce DMA.
 *
 * Build on FreeBSD: make -f Makefile.kmod
 * On Linux (Grok Bot box): headers + nvsoctl dry-run only; kmod skipped.
 */
#include <sys/param.h>

#ifdef __FreeBSD__

#include <sys/systm.h>
#include <sys/kernel.h>
#include <sys/module.h>
#include <sys/bus.h>
#include <sys/conf.h>
#include <sys/malloc.h>
#include <sys/lock.h>
#include <sys/mutex.h>
#include <sys/fcntl.h>
#include <sys/uio.h>
#include <sys/ioccom.h>

#include "../include/nvso.h"
#include "../include/nvso_ioctl.h"
#include "nvso_if.h"
#include "nvso_var.h"

struct nvso_domain *
nvso_domain_lookup(struct nvso_softc *sc, uint32_t id)
{
        uint32_t i;

        if (sc == NULL || id >= NVSO_MAX_DOMAINS)
                return (NULL);
        for (i = 0; i < NVSO_MAX_DOMAINS; i++) {
                if (sc->domains[i].in_use && sc->domains[i].id == id)
                        return (&sc->domains[i]);
        }
        return (NULL);
}

static int
nvso_soft_domain_create(struct nvso_softc *sc, struct nvso_domain_create_req *r)
{
        struct nvso_domain *d;
        uint32_t i, prefer, assigned;

        if (r == NULL)
                return (EINVAL);
        if (r->abi_version != NVSO_ABI_VERSION) {
                r->status = EINVAL;
                return (EINVAL);
        }
        if (sc->ndomains >= NVSO_MAX_DOMAINS) {
                r->status = ENOSPC;
                return (ENOSPC);
        }

        prefer = r->domain_id;
        assigned = ~0u;

        /* Prefer requested id if free and in range. */
        if (prefer < NVSO_MAX_DOMAINS &&
            nvso_domain_lookup(sc, prefer) == NULL) {
                assigned = prefer;
        } else {
                for (i = 0; i < NVSO_MAX_DOMAINS; i++) {
                        if (!sc->domains[i].in_use) {
                                assigned = i;
                                break;
                        }
                }
        }
        if (assigned == ~0u) {
                r->status = ENOSPC;
                return (ENOSPC);
        }

        d = &sc->domains[assigned];
        bzero(d, sizeof(*d));
        d->in_use = 1;
        d->id = assigned;
        d->flags = r->flags;
        d->pll = r->pll;
        d->mmu_handle = r->mmu_handle;
        d->gated = (r->flags & NVSO_DOM_POWER_GATED) ? 1 : 0;
        sc->ndomains++;

        r->domain_id = assigned;
        r->status = 0;
        return (0);
}

static int
nvso_soft_map(struct nvso_softc *sc, struct nvso_map_req *r)
{
        struct nvso_domain *d;
        struct nvso_map_ent *m;
        uint32_t i;

        if (r == NULL)
                return (EINVAL);
        d = nvso_domain_lookup(sc, r->domain_id);
        if (d == NULL) {
                r->status = EINVAL;
                return (EINVAL);
        }
        if (r->size == 0) {
                r->status = EINVAL;
                return (EINVAL);
        }
        if (d->nmaps >= NVSO_MAX_MAPS_PER_DOM) {
                r->status = ENOSPC;
                return (ENOSPC);
        }
        /* Soft only: record VA range; no wire / no IOMMU yet. */
        for (i = 0; i < NVSO_MAX_MAPS_PER_DOM; i++) {
                if (!d->maps[i].used) {
                        m = &d->maps[i];
                        m->used = 1;
                        m->va = r->va;
                        m->size = r->size;
                        m->nvm_off = r->nvm_off;
                        m->flags = r->flags;
                        d->nmaps++;
                        r->status = 0;
                        return (0);
                }
        }
        r->status = ENOSPC;
        return (ENOSPC);
}

static int
nvso_soft_gate(struct nvso_softc *sc, struct nvso_domain_gate_req *r)
{
        struct nvso_domain *d;

        if (r == NULL)
                return (EINVAL);
        d = nvso_domain_lookup(sc, r->domain_id);
        if (d == NULL) {
                r->status = EINVAL;
                return (EINVAL);
        }
        d->gated = (r->enable == 0) ? 1 : 0;
        if (d->gated)
                d->flags |= NVSO_DOM_POWER_GATED;
        else
                d->flags &= ~NVSO_DOM_POWER_GATED;
        r->status = 0;
        return (0);
}

static int
nvso_soft_irq(struct nvso_softc *sc, struct nvso_irq_attach_req *r)
{
        struct nvso_domain *d;

        if (r == NULL)
                return (EINVAL);
        d = nvso_domain_lookup(sc, r->domain_id);
        if (d == NULL) {
                r->status = EINVAL;
                return (EINVAL);
        }
        d->irq_hint = r->irq_hint;
        d->irq_cookie = r->notify_user_ptr;
        r->status = 0;
        return (0);
}

static d_ioctl_t nvso_ioctl;

static struct cdevsw nvso_cdevsw = {
        .d_version = D_VERSION,
        .d_ioctl   = nvso_ioctl,
        .d_name    = "nvso",
};

static int
nvso_ioctl(struct cdev *dev, u_long cmd, caddr_t data, int fflag, struct thread *td)
{
        struct nvso_softc *sc = dev->si_drv1;
        int error = 0;

        (void)fflag; (void)td;
        if (sc == NULL)
                return (ENXIO);

        mtx_lock(&sc->lock);
        switch (cmd) {
        case NVSO_DOMAIN_CREATE:
                error = sc->methods.domain_create(sc,
                    (struct nvso_domain_create_req *)(void *)data);
                break;
        case NVSO_MAP:
                error = sc->methods.map(sc, (struct nvso_map_req *)(void *)data);
                break;
        case NVSSD_QUEUE_EXPORT:
                error = sc->methods.queue_export(sc,
                    (struct nvssd_queue_export_req *)(void *)data);
                break;
        case NVGPU_DMA_POST:
                error = sc->methods.dma_post(sc,
                    (struct nvgpu_dma_post_req *)(void *)data);
                break;
        case NVSO_DOMAIN_GATE:
                error = sc->methods.domain_gate(sc,
                    (struct nvso_domain_gate_req *)(void *)data);
                break;
        case NVSO_IRQ_ATTACH:
                error = sc->methods.irq_attach(sc,
                    (struct nvso_irq_attach_req *)(void *)data);
                break;
        default:
                error = ENOTTY;
                break;
        }
        mtx_unlock(&sc->lock);
        return (error);
}

static int
nvso_probe(device_t dev)
{
        device_set_desc(dev, "nvso soft HVVRAM domain + SSD DMA research");
        return (BUS_PROBE_NOWILDCARD);
}

static int
nvso_attach(device_t dev)
{
        struct nvso_softc *sc = device_get_softc(dev);

        bzero(sc, sizeof(*sc));
        sc->dev = dev;
        mtx_init(&sc->lock, "nvso", NULL, MTX_DEF);
        sc->methods.domain_create = nvso_soft_domain_create;
        sc->methods.map = nvso_soft_map;
        sc->methods.queue_export = nvso_ssd_queue_export;
        sc->methods.dma_post = nvso_gpu_dma_post;
        sc->methods.domain_gate = nvso_soft_gate;
        sc->methods.irq_attach = nvso_soft_irq;
        sc->ndomains = 0;

        sc->cdev = make_dev(&nvso_cdevsw, 0, UID_ROOT, GID_WHEEL, 0600, "nvso0");
        if (sc->cdev == NULL)
                return (ENOMEM);
        sc->cdev->si_drv1 = sc;
        device_printf(dev,
            "soft domains attached (ABI %d); SSD/GPU DMA still soft bookkeeping\n",
            NVSO_ABI_VERSION);
        return (0);
}

static int
nvso_detach(device_t dev)
{
        struct nvso_softc *sc = device_get_softc(dev);

        if (sc->cdev != NULL) {
                sc->cdev->si_drv1 = NULL;
                destroy_dev(sc->cdev);
                sc->cdev = NULL;
        }
        mtx_destroy(&sc->lock);
        return (0);
}

static device_method_t nvso_methods_table[] = {
        DEVMETHOD(device_probe,  nvso_probe),
        DEVMETHOD(device_attach, nvso_attach),
        DEVMETHOD(device_detach, nvso_detach),
        DEVMETHOD_END
};

static driver_t nvso_driver = {
        "nvso",
        nvso_methods_table,
        sizeof(struct nvso_softc),
};

DRIVER_MODULE(nvso, nexus, nvso_driver, NULL, NULL);
MODULE_VERSION(nvso, 2);

#else /* !__FreeBSD__ */

/* Intentionally empty translation unit on non-FreeBSD. */
int nvso_linux_stub_anchor = 0;

#endif /* __FreeBSD__ */
