/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * Copyright (c) 2026 familia / green-roomz R&D
 *
 * nvso(4) stub newbus driver — FreeBSD-first research scaffold.
 * All backend ops return EOPNOTSUPP until SSD/GPU pieces land.
 *
 * Build on FreeBSD: make -C gpu-legacy/nvso
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

static MALLOC_DEFINE(M_NVSO, "nvso", "nvso(4) softc");

struct nvso_softc {
        device_t                dev;
        struct cdev            *cdev;
        struct mtx              lock;
        struct nvso_methods     methods;
        uint32_t                ndomains;
};

/* Forward: backends in nvso_ssd.c / nvso_gpu.c */
int     nvso_ssd_queue_export(struct nvso_softc *, struct nvssd_queue_export_req *);
int     nvso_gpu_dma_post(struct nvso_softc *, struct nvgpu_dma_post_req *);

static int
nvso_stub_domain_create(struct nvso_softc *sc, struct nvso_domain_create_req *r)
{
        (void)sc;
        if (r->abi_version != NVSO_ABI_VERSION)
                return (EINVAL);
        r->status = EOPNOTSUPP;
        return (EOPNOTSUPP);
}

static int
nvso_stub_map(struct nvso_softc *sc, struct nvso_map_req *r)
{
        (void)sc; (void)r;
        r->status = EOPNOTSUPP;
        return (EOPNOTSUPP);
}

static int
nvso_stub_gate(struct nvso_softc *sc, struct nvso_domain_gate_req *r)
{
        (void)sc;
        r->status = EOPNOTSUPP;
        return (EOPNOTSUPP);
}

static int
nvso_stub_irq(struct nvso_softc *sc, struct nvso_irq_attach_req *r)
{
        (void)sc;
        r->status = EOPNOTSUPP;
        return (EOPNOTSUPP);
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
        device_set_desc(dev, "nvso SO-domain + SSD DMA research stub");
        return (BUS_PROBE_NOWILDCARD);
}

static int
nvso_attach(device_t dev)
{
        struct nvso_softc *sc = device_get_softc(dev);

        sc->dev = dev;
        mtx_init(&sc->lock, "nvso", NULL, MTX_DEF);
        sc->methods.domain_create = nvso_stub_domain_create;
        sc->methods.map = nvso_stub_map;
        sc->methods.queue_export = nvso_ssd_queue_export;
        sc->methods.dma_post = nvso_gpu_dma_post;
        sc->methods.domain_gate = nvso_stub_gate;
        sc->methods.irq_attach = nvso_stub_irq;
        sc->ndomains = 0;

        sc->cdev = make_dev(&nvso_cdevsw, 0, UID_ROOT, GID_WHEEL, 0600, "nvso0");
        if (sc->cdev == NULL)
                return (ENOMEM);
        sc->cdev->si_drv1 = sc;
        device_printf(dev, "stub attached (ABI %d); backends EOPNOTSUPP\n",
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
MODULE_VERSION(nvso, 1);

#else /* !__FreeBSD__ */

/* Intentionally empty translation unit on non-FreeBSD. */
int nvso_linux_stub_anchor = 0;

#endif /* __FreeBSD__ */
