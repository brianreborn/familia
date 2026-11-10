#!/bin/sh
# Userspace nvso smoke. Builds tools/nvsoctl and checks the ABI dump plus
# client exit codes. Does not load a kernel module, open /dev/nvso0, create a
# kernel domain, or touch disks, firmware, or a deployed host.
set -eu
cd "$(dirname -- "$0")" || exit 1

die() {
  printf 'nvso-smoke: %s\n' "$1" >&2
  exit 1
}

command -v gcc >/dev/null 2>&1 || die "gcc is required"
command -v make >/dev/null 2>&1 || die "make is required"
command -v timeout >/dev/null 2>&1 || die "timeout (coreutils) is required"

had_dev=0
if [ -e /dev/nvso0 ]; then
  had_dev=1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Environment CFLAGS is appended with -Iinclude. A make-command-line CFLAGS=
# is not, so the include path is forced with override in the Makefile too.
CFLAGS='-O2 -Wall -Wextra -Werror -Wmissing-prototypes' make clean
CFLAGS='-O2 -Wall -Wextra -Werror -Wmissing-prototypes' make tools
[ -x tools/nvsoctl ] || die "tools/nvsoctl missing after build"
if [ -e nvso.ko ]; then
  die "userspace build produced nvso.ko"
fi

cat >"$work/abi.c" <<'EOF'
#include <stddef.h>
#include <stdio.h>
#include "nvso.h"
#include "nvso_ioctl.h"

_Static_assert(NVSO_ABI_VERSION == 2, "abi");
_Static_assert(NVSO_CAP_SOFT_DOMAINS == 0x0001u, "cap");
_Static_assert(NVSO_POST_SOFT == 0x0001u, "post soft");
_Static_assert(sizeof(struct nvso_pll_cfg) == 16, "pll");
_Static_assert(sizeof(struct nvso_domain_create_req) == 40, "create size");
_Static_assert(sizeof(struct nvso_map_req) == 40, "map size");
_Static_assert(sizeof(struct nvssd_queue_geom) == 40, "geom size");
_Static_assert(sizeof(struct nvssd_queue_export_req) == 56, "export size");
_Static_assert(sizeof(struct nvgpu_dma_desc) == 32, "desc size");
_Static_assert(sizeof(struct nvgpu_dma_post_req) == 24, "post size");
_Static_assert(sizeof(struct nvso_domain_gate_req) == 16, "gate size");
_Static_assert(sizeof(struct nvso_irq_attach_req) == 24, "irq size");
_Static_assert(offsetof(struct nvso_domain_create_req, domain_id) == 4, "id off");
_Static_assert(offsetof(struct nvso_domain_create_req, pll) == 8, "pll off");
_Static_assert(offsetof(struct nvso_domain_create_req, status) == 36, "status off");
_Static_assert((unsigned long)NVSO_DOMAIN_CREATE == 0xc0284e01UL, "create ioctl");
_Static_assert((unsigned long)NVSO_MAP == 0xc0284e02UL, "map ioctl");
_Static_assert((unsigned long)NVSSD_QUEUE_EXPORT == 0xc0384e03UL, "export ioctl");
_Static_assert((unsigned long)NVGPU_DMA_POST == 0xc0184e04UL, "post ioctl");
_Static_assert((unsigned long)NVSO_DOMAIN_GATE == 0xc0104e05UL, "gate ioctl");
_Static_assert((unsigned long)NVSO_IRQ_ATTACH == 0xc0184e06UL, "irq ioctl");

static unsigned long
freebsd_iowr(unsigned long len, unsigned long num)
{
        return 0xc0000000UL | ((len & 0x1fffUL) << 16) |
            ((unsigned long)'N' << 8) | num;
}

int
main(void)
{
        if ((unsigned long)NVSO_DOMAIN_CREATE != freebsd_iowr(40, 1) ||
            (unsigned long)NVSO_MAP != freebsd_iowr(40, 2) ||
            (unsigned long)NVSSD_QUEUE_EXPORT != freebsd_iowr(56, 3) ||
            (unsigned long)NVGPU_DMA_POST != freebsd_iowr(24, 4) ||
            (unsigned long)NVSO_DOMAIN_GATE != freebsd_iowr(16, 5) ||
            (unsigned long)NVSO_IRQ_ATTACH != freebsd_iowr(24, 6)) {
                fprintf(stderr, "nvso-smoke: ioctl encoding != FreeBSD _IOWR\n");
                return 1;
        }
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
        return 0;
}
EOF

gcc -O2 -Wall -Wextra -Werror -Wmissing-prototypes -Iinclude \
  -o "$work/abi" "$work/abi.c"
timeout 10 "$work/abi" >"$work/abi.out" 2>"$work/abi.err"
[ ! -s "$work/abi.err" ] || die "ABI checker wrote stderr"

run_timeout() {
  # run_timeout OUT ERR -- cmd...
  # Sets the global rc. timeout's 124 is a failure of the caller to finish.
  out=$1
  err=$2
  shift 2
  rc=0
  timeout 10 "$@" >"$out" 2>"$err" || rc=$?
}

run_timeout "$work/n.out" "$work/n.err" ./tools/nvsoctl -n
[ "$rc" -eq 0 ] || die "nvsoctl -n exited $rc, want 0"
[ ! -s "$work/n.err" ] || die "nvsoctl -n wrote stderr"
if ! cmp -s "$work/abi.out" "$work/n.out"; then
  printf 'nvso-smoke: nvsoctl -n output differs from header ABI\n' >&2
  diff -u "$work/abi.out" "$work/n.out" >&2
  exit 1
fi
if grep -q 'soft round-trip done' "$work/n.out"; then
  die "nvsoctl -n reported a round-trip"
fi

# -n must not call open/ioctl even if -d names a path. The preload aborts
# the process before a real open if those symbols are used.
cat >"$work/deny.c" <<'EOF'
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

static void
blocked(const char *fn, const char *path)
{
        fprintf(stderr, "nvso-smoke: %s(%s) during -n\n", fn,
            path != NULL ? path : "(null)");
        _exit(86);
}

int open(const char *path, int flags, ...) { (void)flags; blocked("open", path); return -1; }
int open64(const char *path, int flags, ...) { (void)flags; blocked("open64", path); return -1; }
int openat(int fd, const char *path, int flags, ...) {
        (void)fd; (void)flags; blocked("openat", path); return -1;
}
int openat64(int fd, const char *path, int flags, ...) {
        (void)fd; (void)flags; blocked("openat64", path); return -1;
}
int ioctl(int fd, unsigned long req, ...) {
        (void)fd; (void)req; blocked("ioctl", NULL); return -1;
}
EOF
gcc -O2 -Wall -Wextra -Werror -Wmissing-prototypes -shared -fPIC \
  -o "$work/deny.so" "$work/deny.c"

run_timeout "$work/nd.out" "$work/nd.err" \
  env LD_PRELOAD="$work/deny.so" ./tools/nvsoctl -n -d "$work/missing-nvso"
[ "$rc" -eq 0 ] || die "nvsoctl -n under open-deny exited $rc, want 0"
[ ! -s "$work/nd.err" ] || die "nvsoctl -n called open or ioctl"
if ! cmp -s "$work/abi.out" "$work/nd.out"; then
  die "nvsoctl -n -d output differs from the ABI dump"
fi
[ ! -e "$work/missing-nvso" ] || die "-n created the -d path"

# No -n, path absent: fail closed. Do not use /dev/nvso0.
run_timeout "$work/miss.out" "$work/miss.err" \
  ./tools/nvsoctl -d "$work/missing-nvso"
[ "$rc" -eq 2 ] || die "missing path exited $rc, want 2"
[ ! -e "$work/missing-nvso" ] || die "missing-path run created the path"
grep -q 'No such file or directory' "$work/miss.err" || die "missing-path stderr lacked open failure"
if grep -q 'soft round-trip done' "$work/miss.out"; then
  die "missing path reported a round-trip"
fi

run_timeout "$work/bad.out" "$work/bad.err" ./tools/nvsoctl -z
[ "$rc" -eq 1 ] || die "unknown option exited $rc, want 1"

run_timeout "$work/help.out" "$work/help.err" ./tools/nvsoctl -h
[ "$rc" -eq 0 ] || die "help exited $rc, want 0"
[ ! -s "$work/help.out" ] || die "help wrote stdout"
grep -q 'exit 0' "$work/help.err" || die "help text lacks the dry-run exit"

# Client checks use a regular file plus an ioctl preload. The preload never
# calls the real ioctl, and open() is limited to that file, so this cannot
# create a kernel domain or program a device.
: >"$work/fake"
cat >"$work/client.c" <<'EOF'
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include "nvso.h"
#include "nvso_ioctl.h"

static int calls;
typedef int (*open_fn)(const char *, int, ...);
static open_fn real_open;

static open_fn
need_open(void)
{
        if (real_open == NULL)
                real_open = (open_fn)dlsym(RTLD_NEXT, "open");
        if (real_open == NULL) {
                fprintf(stderr, "nvso-smoke: dlsym(open) failed\n");
                _exit(88);
        }
        return real_open;
}

static int
allow_open(const char *path, int flags)
{
        const char *allow = getenv("NVSO_SMOKE_ALLOW");

        if (allow == NULL || path == NULL || strcmp(path, allow) != 0) {
                fprintf(stderr, "nvso-smoke: blocked open(%s)\n",
                    path != NULL ? path : "(null)");
                _exit(86);
        }
        return need_open()(path, flags, 0);
}

int open(const char *path, int flags, ...) { return allow_open(path, flags); }
int open64(const char *path, int flags, ...) { return allow_open(path, flags); }
int openat(int fd, const char *path, int flags, ...) {
        (void)fd;
        (void)flags;
        fprintf(stderr, "nvso-smoke: blocked openat(%s)\n", path);
        _exit(86);
        return -1;
}
int ioctl(int fd, unsigned long req, ...)
{
        const char *mode = getenv("NVSO_SMOKE_MODE");
        va_list ap;
        void *arg;

        (void)fd;
        va_start(ap, req);
        arg = va_arg(ap, void *);
        va_end(ap);
        calls++;
        if (mode != NULL && strcmp(mode, "fail-gate") == 0) {
                if (calls > 3)
                        exit(87);
                if (req == (unsigned long)NVSO_DOMAIN_GATE) {
                        errno = EIO;
                        return -1;
                }
                return 0;
        }
        if (mode != NULL && strcmp(mode, "succeed") == 0) {
                if (req == (unsigned long)NVGPU_DMA_POST && arg != NULL) {
                        struct nvgpu_dma_post_req *post = arg;
                        post->status = 0;
                        post->soft_flags = NVSO_POST_SOFT;
                }
                return 0;
        }
        fprintf(stderr, "nvso-smoke: bad client mode\n");
        _exit(89);
        return -1;
}

static void write_count(void) __attribute__((destructor));
static void
write_count(void)
{
        const char *path = getenv("NVSO_SMOKE_COUNT");
        FILE *f;

        if (path == NULL || path[0] == '\0')
                return;
        f = fopen(path, "w");
        if (f == NULL)
                return;
        fprintf(f, "%d\n", calls);
        if (fclose(f) != 0)
                return;
}
EOF
gcc -O2 -Wall -Wextra -Werror -Wmissing-prototypes -Iinclude -shared -fPIC \
  -o "$work/client.so" "$work/client.c" -ldl

run_timeout "$work/gate.out" "$work/gate.err" \
  env LD_PRELOAD="$work/client.so" \
      NVSO_SMOKE_ALLOW="$work/fake" \
      NVSO_SMOKE_MODE=fail-gate \
      NVSO_SMOKE_COUNT="$work/gate.count" \
      ./tools/nvsoctl -d "$work/fake"
[ "$rc" -eq 3 ] || die "injected GATE failure exited $rc, want 3"
[ -s "$work/gate.count" ] || die "injected GATE failure wrote no ioctl count"
gate_calls=$(cat "$work/gate.count")
[ "$gate_calls" -eq 3 ] || die "injected GATE failure issued $gate_calls ioctls, want 3"
if grep -q 'soft round-trip done' "$work/gate.out"; then
  die "injected GATE failure reported a finished round-trip"
fi
if grep -q 'IRQ_ATTACH:' "$work/gate.out"; then
  die "injected GATE failure continued to IRQ_ATTACH"
fi

run_timeout "$work/ok.out" "$work/ok.err" \
  env LD_PRELOAD="$work/client.so" \
      NVSO_SMOKE_ALLOW="$work/fake" \
      NVSO_SMOKE_MODE=succeed \
      NVSO_SMOKE_COUNT="$work/ok.count" \
      ./tools/nvsoctl -d "$work/fake"
[ "$rc" -eq 0 ] || die "injected status-0 client exited $rc, want 0"
[ -s "$work/ok.count" ] || die "injected status-0 client wrote no ioctl count"
ok_calls=$(cat "$work/ok.count")
[ "$ok_calls" -eq 7 ] || die "injected status-0 client issued $ok_calls ioctls, want 7"
grep -q 'soft round-trip done' "$work/ok.out" || die "injected status-0 client omitted the done line"
grep -q 'soft bookkeeping only' "$work/ok.out" || die "injected status-0 client omitted the soft-post note"
if [ -e /dev/nvso0 ] && [ "$had_dev" -eq 0 ]; then
  die "/dev/nvso0 appeared during the userspace smoke"
fi

make clean >/dev/null
printf 'nvso-smoke: ok (userspace ABI, dry-run, and client exits; no kernel domain)\n'
