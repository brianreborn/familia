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

## Build

```sh
# Anywhere (Linux box OK): userspace
make tools
./tools/nvsoctl -n

# angel FreeBSD (when SSH up):
make -f Makefile.kmod
sudo kldload ./nvso.ko   # soft bring-up only
./tools/nvsoctl          # DOMAIN_CREATE + MAP + GATE round-trip
```

## Software track (angel Nanbeige)

Use mmap + swap + spill — see LAYER.md. That path does **not** require `nvso.ko`.

## What returns 0 now (soft)

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

Kernel sources (`/usr/src/sys`) and `bsd.kmod.mk` are required on the build host.

### Verified on angel (FreeBSD 15.1)

`make -f Makefile.kmod` produces `nvso.ko` (soft domains ABI 2). Load with
`sudo kldload ./nvso.ko` only for ABI bring-up; then `./tools/nvsoctl` for the
soft create→map→gate round-trip. **Not hardware HVVRAM.**

