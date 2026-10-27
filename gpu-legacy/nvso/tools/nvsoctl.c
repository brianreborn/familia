/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * nvsoctl — ABI dump + soft domain round-trip against /dev/nvso0.
 * Builds on Linux and FreeBSD (no kmod required for -n).
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdint.h>

#include "../include/nvso.h"
#include "../include/nvso_ioctl.h"

#ifdef __linux__
#include <sys/ioctl.h>
#endif
#ifdef __FreeBSD__
#include <sys/ioctl.h>
#endif

static void
usage(const char *argv0)
{
        fprintf(stderr,
            "usage: %s [-n] [-d /dev/nvso0]\n"
            "  -n   dry-run: print ABI and ioctl numbers only\n"
            "  -d   device path (default /dev/nvso0)\n"
            "Without -n: DOMAIN_CREATE + MAP + GATE (+ soft QUEUE_EXPORT/DMA_POST)\n"
            "round-trip. Soft path only — not hardware HVVRAM.\n", argv0);
}

static void
print_abi(void)
{
        printf("nvso ABI %d (soft domains CAP 0x%x)\n",
            NVSO_ABI_VERSION, NVSO_CAP_SOFT_DOMAINS);
        printf("  NVSO_DOMAIN_CREATE   0x%lx  alias nvso_domain_create\n",
            (unsigned long)NVSO_DOMAIN_CREATE);
        printf("  NVSO_MAP             0x%lx  alias nvso_map\n",
            (unsigned long)NVSO_MAP);
        printf("  NVSSD_QUEUE_EXPORT   0x%lx  alias nvssd_queue_export\n",
            (unsigned long)NVSSD_QUEUE_EXPORT);
        printf("  NVGPU_DMA_POST       0x%lx  alias nvgpu_dma_post\n",
            (unsigned long)NVGPU_DMA_POST);
        printf("  NVSO_DOMAIN_GATE     0x%lx  alias nvso_domain_gate\n",
            (unsigned long)NVSO_DOMAIN_GATE);
        printf("  NVSO_IRQ_ATTACH      0x%lx  alias nvso_irq_attach\n",
            (unsigned long)NVSO_IRQ_ATTACH);
}

int
main(int argc, char **argv)
{
        const char *dev = "/dev/nvso0";
        int opt, dry = 0, fd, rc;
        struct nvso_domain_create_req creq;
        struct nvso_map_req mreq;
        struct nvso_domain_gate_req greq;
        struct nvso_irq_attach_req ireq;
        struct nvssd_queue_export_req qreq;
        struct nvgpu_dma_post_req preq;
        struct nvgpu_dma_desc descs[2];

        while ((opt = getopt(argc, argv, "nd:h")) != -1) {
                switch (opt) {
                case 'n': dry = 1; break;
                case 'd': dev = optarg; break;
                case 'h': default: usage(argv[0]); return opt == 'h' ? 0 : 1;
                }
        }

        print_abi();
        if (dry)
                return 0;

        fd = open(dev, O_RDWR);
        if (fd < 0) {
                fprintf(stderr, "nvsoctl: open %s: %s\n", dev, strerror(errno));
                fprintf(stderr,
                    "hint: load soft kmod on FreeBSD (sudo kldload ./nvso.ko)\n");
                return 2;
        }

        memset(&creq, 0, sizeof(creq));
        creq.abi_version = NVSO_ABI_VERSION;
        creq.domain_id = 0; /* prefer 0 */
        creq.pll.clock_khz = 400000;
        creq.pll.voltage_uv = 1000000;
        creq.flags = NVSO_DOM_PRIVATE;
        rc = ioctl(fd, NVSO_DOMAIN_CREATE, &creq);
        printf("DOMAIN_CREATE: ioctl=%d errno=%s status=%u id=%u\n",
            rc, rc < 0 ? strerror(errno) : "0", creq.status, creq.domain_id);
        if (rc < 0 || creq.status != 0) {
                close(fd);
                return 3;
        }

        memset(&mreq, 0, sizeof(mreq));
        mreq.domain_id = creq.domain_id;
        mreq.flags = NVSO_MAP_READ | NVSO_MAP_WRITE;
        mreq.va = 0x10000000ULL;
        mreq.size = 0x1000ULL;
        rc = ioctl(fd, NVSO_MAP, &mreq);
        printf("MAP:            ioctl=%d errno=%s status=%u va=0x%llx size=0x%llx\n",
            rc, rc < 0 ? strerror(errno) : "0", mreq.status,
            (unsigned long long)mreq.va, (unsigned long long)mreq.size);
        if (rc < 0 || mreq.status != 0) {
                close(fd);
                return 3;
        }

        memset(&greq, 0, sizeof(greq));
        greq.domain_id = creq.domain_id;
        greq.enable = 0; /* gate off */
        rc = ioctl(fd, NVSO_DOMAIN_GATE, &greq);
        printf("GATE(off):      ioctl=%d errno=%s status=%u\n",
            rc, rc < 0 ? strerror(errno) : "0", greq.status);
        greq.enable = 1; /* ungate */
        rc = ioctl(fd, NVSO_DOMAIN_GATE, &greq);
        printf("GATE(on):       ioctl=%d errno=%s status=%u\n",
            rc, rc < 0 ? strerror(errno) : "0", greq.status);

        memset(&ireq, 0, sizeof(ireq));
        ireq.domain_id = creq.domain_id;
        ireq.irq_hint = 1;
        ireq.notify_user_ptr = 0;
        rc = ioctl(fd, NVSO_IRQ_ATTACH, &ireq);
        printf("IRQ_ATTACH:     ioctl=%d errno=%s status=%u\n",
            rc, rc < 0 ? strerror(errno) : "0", ireq.status);

        memset(&qreq, 0, sizeof(qreq));
        qreq.domain_id = creq.domain_id;
        qreq.geom.queue_id = 1;
        qreq.geom.depth = 64;
        qreq.geom.sq_entry_bytes = 64;
        qreq.geom.cq_entry_bytes = 16;
        qreq.geom.raw_lba_base = 0;
        qreq.geom.raw_lba_count = 1024;
        rc = ioctl(fd, NVSSD_QUEUE_EXPORT, &qreq);
        printf("QUEUE_EXPORT:   ioctl=%d errno=%s status=%u (soft geom)\n",
            rc, rc < 0 ? strerror(errno) : "0", qreq.status);

        memset(descs, 0, sizeof(descs));
        descs[0].src = 0x1000;
        descs[0].dst = 0x2000;
        descs[0].len = 4096;
        descs[0].dir = NVGPU_DMA_PEER;
        descs[1].src = 0x3000;
        descs[1].dst = 0x4000;
        descs[1].len = 512;
        descs[1].dir = NVGPU_DMA_H2D;
        memset(&preq, 0, sizeof(preq));
        preq.domain_id = creq.domain_id;
        preq.ndesc = 2;
        preq.desc_user_ptr = (uint64_t)(uintptr_t)descs;
        rc = ioctl(fd, NVGPU_DMA_POST, &preq);
        printf("DMA_POST:       ioctl=%d errno=%s status=%u soft_flags=0x%x\n",
            rc, rc < 0 ? strerror(errno) : "0", preq.status, preq.soft_flags);
        if (preq.soft_flags & NVSO_POST_SOFT)
                printf("  (soft bookkeeping only — no hardware DMA)\n");

        close(fd);
        printf("soft round-trip done on %s\n", dev);
        return 0;
}
