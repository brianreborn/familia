# nvso — FreeBSD-first SO domain + soft HVVRAM bookkeeping

Research ABI for the Grok design thread (G84 independent SO domains + zero-copy SSD DMA).

**Soft domain path (ABI 2):** in-kernel domain table — `domain_create` / `map` / `gate` /
`irq_attach` return 0; `nvssd_queue_export` and `nvgpu_dma_post` accept geom/descriptors
into softc summaries (`NVSO_POST_SOFT`). **Does not claim working hardware SO domains,
open SandForce FW, or real GPU↔SSD DMA.**

Design notes: `docs/vvram-ssd/` — [HVVRAM-ARCHITECTURE.md](../../docs/vvram-ssd/HVVRAM-ARCHITECTURE.md),
[FIRMWARE-PLAN.md](../../docs/vvram-ssd/FIRMWARE-PLAN.md),
[DESCRIPTOR-FORMAT.md](../../docs/vvram-ssd/DESCRIPTOR-FORMAT.md),
[G84-BRIDGE.md](../../docs/vvram-ssd/G84-BRIDGE.md), [LAYER.md](../../docs/vvram-ssd/LAYER.md).

Also mirrored under `/workspace/familia-install-notes/vvram-ssd/` when present.

## Layout

| Path | Purpose |
|------|---------|
| `include/nvso.h` | Shared structs / flags (ABI 2) |
| `include/nvso_ioctl.h` | `_IOWR` ioctls + name aliases (numbers stable) |
| `sys/nvso_var.h` | softc + domain / map tables (kernel private) |
| `sys/nvso.c` | newbus + `/dev/nvso0` + soft domain ops |
| `sys/nvso_ssd.c` | `nvssd_queue_export` → soft geom store |
| `sys/nvso_gpu.c` | `nvgpu_dma_post` → soft copyin + summary |
| `sys/nvso_if.h` | method table |
| `man/man4/nvso.4` | device + ioctls |
| `man/man9/nvso.9` | kernel methods + aliases |
| `tools/nvsoctl.c` | ABI smoker (`-n`) + soft round-trip |

## Build and userspace smoke

```sh
# Linux or anywhere with a C compiler. Does not build nvso.ko.
make tools
./tools/nvsoctl -n          # exit 0: ABI and ioctl numbers
sh smoke-userspace.sh       # or: make smoke
```

`nvsoctl -n` prints the ABI and returns before `open`. A missing device without
`-n` exits 2. A round-trip step whose ioctl fails, or whose `status` is
non-zero, exits 3. `-h` exits 0. An unknown option exits 1.

`make all` is the same userspace build as `make tools`. `depend` is a no-op.
`make -f Makefile.kmod` is the FreeBSD module build. `make kmod` on a host
without `bsd.kmod.mk` prints a skip and exits 0 without producing `nvso.ko`;
that exit is not a module build. The userspace smoke does not run either kmod
target.

Passing `CFLAGS=` on the `make` command line used to drop `-Iinclude` (GNU
make does not append to command-line variables). The Makefile now forces that
include path with `override`.

## Evidence

Three different claims stay separate.

**Userspace CI.** `.github/workflows/nvso-userspace-smoke.yml` runs
`smoke-userspace.sh` on pull requests into `development`. It builds
`tools/nvsoctl` with `-Wall -Wextra -Werror`, checks `nvsoctl -n` against the
header ioctl numbers (the FreeBSD `_IOWR` layout for these structs), and
checks client exit codes. The dry-run is run under a preload that aborts if
`open` or `ioctl` is called. The non-dry failure checks use a missing path, or
a regular file whose `ioctl` is answered inside the test process. That is not
a kernel domain, not `/dev/nvso0`, and not a module load.

**FreeBSD build note.** Commit `c3d9834` (2026-10-26,
`docs(nvso): note angel FreeBSD 15.1 nvso.ko build success`) records that
`make -f Makefile.kmod` produced `nvso.ko` on FreeBSD 15.1. The repository
contains that commit message and the paragraph it added. It does not contain
the compiler log or a `kldstat` transcript.

**Live integration still pending.** Loading `nvso.ko`, the presence of
`/dev/nvso0`, and a create→map→gate round-trip against a live softc are not
established by `c3d9834`. Issue #365 says a module was loaded and a domain was
created on a FreeBSD host. The issue body does not name the host, the path, or
the branch, so that report stays unverified. This CI and doc pass does not
complete #365.

Soft ABI 2 stores domain, map, queue-geometry, and descriptor summaries in the
softc (`NVSO_POST_SOFT` on the DMA post path). SandForce/Vertex2 firmware and
GPU↔SSD DMA are not implemented by that bookkeeping.

## Software track (angel Nanbeige)

Use mmap + swap + spill — see LAYER.md. That path does **not** require `nvso.ko`.

## What the FreeBSD sources return 0 for (soft)

These are the in-tree softc handlers. The userspace CI does not execute them.

| Op | Soft behavior |
|----|---------------|
| `NVSO_DOMAIN_CREATE` | Allocate domain id; store pll/flags |
| `NVSO_MAP` | Record VA/size/flags/nvm_off (no wire) |
| `NVSO_DOMAIN_GATE` | Toggle gated flag |
| `NVSO_IRQ_ATTACH` | Store cookie/hint |
| `NVSSD_QUEUE_EXPORT` | Store geom on domain |
| `NVGPU_DMA_POST` | copyin descs; update `dma_sum`; `soft_flags=NVSO_POST_SOFT` |

## Bridge

`nvso_gpu.c` is the eventual peer of `gpu-legacy` sm11 descriptor posting on qodesh; see G84-BRIDGE.md.

## Angel kmod notes

`Makefile.kmod` lists `device_if.h` `bus_if.h` in `SRCS` so `bsd.kmod.mk` generates them.
Without those entries, compile fails with:

```
sys/bus.h: fatal error: 'device_if.h' file not found
```

Kernel sources (`/usr/src/sys`) and `bsd.kmod.mk` are required on the FreeBSD
build host.

The FreeBSD 15.1 `nvso.ko` result recorded in `c3d9834` is a build note. A
later `kldload` and `nvsoctl` round-trip on that host are live integration,
still pending, and are not part of the userspace smoke above.

