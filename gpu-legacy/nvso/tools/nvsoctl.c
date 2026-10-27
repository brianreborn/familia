/*-
 * SPDX-License-Identifier: BSD-2-Clause
 * nvsoctl — print ABI / ioctl numbers; optional open of /dev/nvso0.
 * Builds on Linux and FreeBSD (no kmod required for -n).
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "../include/nvso.h"
#include "../include/nvso_ioctl.h"

static void
usage(const char *argv0)
{
        fprintf(stderr,
            "usage: %s [-n] [-d /dev/nvso0]\n"
            "  -n   dry-run: print ABI and ioctl numbers only\n"
            "  -d   device path (default /dev/nvso0)\n", argv0);
}

int
main(int argc, char **argv)
{
        const char *dev = "/dev/nvso0";
        int opt, dry = 0, fd;

        while ((opt = getopt(argc, argv, "nd:h")) != -1) {
                switch (opt) {
                case 'n': dry = 1; break;
                case 'd': dev = optarg; break;
                case 'h': default: usage(argv[0]); return opt == 'h' ? 0 : 1;
                }
        }

        printf("nvso ABI %d\n", NVSO_ABI_VERSION);
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

        if (dry)
                return 0;

        fd = open(dev, O_RDWR);
        if (fd < 0) {
                fprintf(stderr, "nvsoctl: open %s: %s\n", dev, strerror(errno));
                return 2;
        }
        close(fd);
        printf("opened %s OK (no ioctl issued)\n", dev);
        return 0;
}
