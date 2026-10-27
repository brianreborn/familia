/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * Kernel method table sketch for nvso(9). Not a generated kobj interface yet.
 */
#ifndef _NVSO_IF_H_
#define _NVSO_IF_H_

struct nvso_softc;

typedef int (*nvso_domain_create_fn)(struct nvso_softc *, struct nvso_domain_create_req *);
typedef int (*nvso_map_fn)(struct nvso_softc *, struct nvso_map_req *);
typedef int (*nvssd_queue_export_fn)(struct nvso_softc *, struct nvssd_queue_export_req *);
typedef int (*nvgpu_dma_post_fn)(struct nvso_softc *, struct nvgpu_dma_post_req *);
typedef int (*nvso_domain_gate_fn)(struct nvso_softc *, struct nvso_domain_gate_req *);
typedef int (*nvso_irq_attach_fn)(struct nvso_softc *, struct nvso_irq_attach_req *);

struct nvso_methods {
        nvso_domain_create_fn   domain_create;  /* alias: nvso_domain_create */
        nvso_map_fn             map;            /* alias: nvso_map */
        nvssd_queue_export_fn   queue_export;   /* alias: nvssd_queue_export */
        nvgpu_dma_post_fn       dma_post;       /* alias: nvgpu_dma_post */
        nvso_domain_gate_fn     domain_gate;    /* alias: nvso_domain_gate */
        nvso_irq_attach_fn      irq_attach;     /* alias: nvso_irq_attach */
};

#endif /* _NVSO_IF_H_ */
