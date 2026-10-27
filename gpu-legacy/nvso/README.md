# nvso — FreeBSD-first SO domain + SSD DMA scaffold

Research ABI for the Grok design thread (G84 independent SO domains + zero-copy SSD DMA).
**Stage 1 soft domains in progress; Stages 2–4 still need custom FW + silicon.** Does not claim working SO domains on stock G84 or open SandForce FW.

Design sketches: `docs/vvram-ssd/HVVRAM-ARCHITECTURE.md`, `FIRMWARE-PLAN.md`, `DESCRIPTOR-FORMAT.md`.

Design notes: `/workspace/familia-install-notes/vvram-ssd/` (INGEST, LAYER, G84-BRIDGE, BENCH).

## Layout

| Path | Purpose |
|------|---------|
| `include/nvso.h` | Shared structs / flags |
| `include/nvso_ioctl.h` | `_IOWR` ioctls + name aliases |
| `sys/nvso.c` | newbus stub + `/dev/nvso0` |
| `sys/nvso_ssd.c` | `nvssd_queue_export` → EOPNOTSUPP |
| `sys/nvso_gpu.c` | `nvgpu_dma_post` → EOPNOTSUPP |
| `sys/nvso_if.h` | method table |
| `man/man4/nvso.4` | device + ioctls |
| `man/man9/nvso.9` | kernel methods + aliases |
| `tools/nvsoctl.c` | ABI smoker (`-n` dry-run) |

## Build

```sh
# Anywhere (Linux box OK): userspace dry-run
make tools
./tools/nvsoctl -n

# angel FreeBSD (when SSH up):
make kmod        # requires bsd.kmod.mk; may need root to kldload
sudo kldload ./nvso.ko   # only for ABI bring-up
```

## Software track (angel Nanbeige)

Use mmap + swap + spill — see LAYER.md. That path does **not** require `nvso.ko`.

## Bridge

`nvso_gpu.c` is the eventual peer of `gpu-legacy` sm11 descriptor posting on qodesh; see G84-BRIDGE.md.
