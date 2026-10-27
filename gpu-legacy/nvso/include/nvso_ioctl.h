/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * nvso(4) ioctl numbers — keep in sync with include/nvso.h structs.
 */
#ifndef _NVSO_IOCTL_H_
#define _NVSO_IOCTL_H_

#include "nvso.h"

#ifdef __FreeBSD__
#include <sys/ioccom.h>
#else
/* Host-side stubs when compiling headers on Linux box (docs / cross-check). */
#ifndef _IOWR
#define _IOC(inout,group,num,len) (((inout)<<30)|((group)<<8)|(num)|((len)<<16))
#define _IOWR(g,n,t) _IOC(3u,(g),(n),sizeof(t))
#define _IOW(g,n,t)  _IOC(1u,(g),(n),sizeof(t))
#define _IOR(g,n,t)  _IOC(2u,(g),(n),sizeof(t))
#endif
#endif

#define NVSO_IOC_GROUP          'N'

/* Userspace names ↔ kernel methods (see nvso(9) aliases). */
#define NVSO_DOMAIN_CREATE      _IOWR(NVSO_IOC_GROUP, 1, struct nvso_domain_create_req)
#define NVSO_MAP                _IOWR(NVSO_IOC_GROUP, 2, struct nvso_map_req)
#define NVSSD_QUEUE_EXPORT      _IOWR(NVSO_IOC_GROUP, 3, struct nvssd_queue_export_req)
#define NVGPU_DMA_POST          _IOWR(NVSO_IOC_GROUP, 4, struct nvgpu_dma_post_req)
#define NVSO_DOMAIN_GATE        _IOWR(NVSO_IOC_GROUP, 5, struct nvso_domain_gate_req)
#define NVSO_IRQ_ATTACH         _IOWR(NVSO_IOC_GROUP, 6, struct nvso_irq_attach_req)

/* Method-name aliases (documentation / binder glue) */
#define nvso_domain_create      NVSO_DOMAIN_CREATE
#define nvso_map                NVSO_MAP
#define nvssd_queue_export      NVSSD_QUEUE_EXPORT
#define nvgpu_dma_post          NVGPU_DMA_POST
#define nvso_domain_gate        NVSO_DOMAIN_GATE
#define nvso_irq_attach         NVSO_IRQ_ATTACH

#endif /* _NVSO_IOCTL_H_ */
