# G84-BRIDGE — Implementation plan (FreeBSD-first nvso + gpu-legacy)

Status: **in-tree soft bookkeeping (ABI 2)** in `gpu-legacy/nvso/`. The FreeBSD sources return 0 from domain create/map/gate/irq and from soft queue-export / DMA-post bookkeeping. SandForce firmware and GPU↔SSD DMA are still later — see [HVVRAM-ARCHITECTURE.md](./HVVRAM-ARCHITECTURE.md), [FIRMWARE-PLAN.md](./FIRMWARE-PLAN.md), [DESCRIPTOR-FORMAT.md](./DESCRIPTOR-FORMAT.md). The software Nanbeige path is [LAYER.md](./LAYER.md).

Evidence stays split, including where an older line in this file disagrees with the code:

- **Userspace CI** (`.github/workflows/nvso-userspace-smoke.yml`) builds `nvsoctl` and checks `nvsoctl -n` plus client exit codes. It does not load a module or open `/dev/nvso0`.
- **FreeBSD build note:** commit `c3d9834` records that `make -f Makefile.kmod` produced `nvso.ko` on FreeBSD 15.1. The repo has the note, not the compiler log or a `kldstat` transcript.
- **Live integration pending:** `kldload`, a live `/dev/nvso0`, and a host round-trip are not established by that note. Issue #365 reports a load and a domain create without a host, path, or branch, so the report stays unverified. Older drafts called the driver an empty `#if 0` softc and said `nvsoctl -n` exits 2. The sources use `#ifdef __FreeBSD__` with a softc; `-n` exits 0, and a missing device without `-n` exits 2.

## Goal chain

1. **Today:** angel Nanbeige via mmap+swap+spill (LAYER).
2. **Near:** FreeBSD `nvso(4)` soft bookkeeping is in tree (ABI 2). Live `kldload` and a host round-trip are still pending (see the evidence split above).
3. **Next paper path:** open SandForce/Vertex2 FW + GPU↔SSD DMA descriptors; OS maps+monitors.
4. **Bridge:** reuse lessons from `gpu-legacy` sm11_shim (qodesh) and nvidia 340 / CUDA 6.5 ports — **not** full llama CUDA on 256 MiB.

## In-repo file layout (concrete)

```
familia/gpu-legacy/nvso/
  README.md                 # build + scope
  include/nvso.h            # userspace + shared ioctl ABI
  include/nvso_ioctl.h      # _IOWR defs
  sys/nvso_if.h             # kernel method table sketch (nvso(9))
  sys/nvso.c                # FreeBSD softc + /dev/nvso0; non-FreeBSD TU is an anchor
  sys/nvso_ssd.c            # soft geom store (nvssd_queue_export)
  sys/nvso_gpu.c            # soft copyin + summary (nvgpu_dma_post)
  man/man4/nvso.4           # device + ioctls
  man/man9/nvso.9           # kernel method names + ioctl aliases
  tools/nvsoctl.c           # -n exits 0; missing device without -n exits 2
  Makefile                  # `all`/`tools` build nvsoctl; kmod is Makefile.kmod
```

Install-notes mirrors (this directory): INGEST, LAYER, G84-BRIDGE, BENCH, THREAD-SOURCE.

Optional pointer: `familia/docs/vvram-ssd/README.md` → these notes + nvso path.

## ioctl / API surface (refined names)

| Symbol | Role |
|--------|------|
| `nvso_domain_create` | Create SO/domain id with pll_cfg + mmu handle |
| `nvso_map` | Map VA range into domain (flags: private, CDC, pinned) |
| `nvssd_queue_export` | Export NVM queue pair / geometry to domain |
| `nvgpu_dma_post` | Post DMA descriptor list (GPU→SSD or peer) |
| `nvso_domain_gate` | Power-gate / reconfigure domain |
| `nvso_irq_attach` | Attach local IRQ / notification |

`nvso.4` / `nvso.9` pair ioctl names with method names. In the sources the lowercase names in `nvso_ioctl.h` (`nvso_domain_create` and the rest) are macros for the ioctl numbers. The softc stores function pointers (`nvso_soft_domain_create`, `nvso_ssd_queue_export`, `nvso_gpu_dma_post`, and the gate/irq handlers). `nvso_if.h` is a sketch and says it is not a generated kobj interface yet.

## Next compile steps (when hosts up)

### angel (FreeBSD) — primary

```sh
cd gpu-legacy/nvso
make tools
./tools/nvsoctl -n             # exit 0: ABI + ioctl numbers; does not open a device
sh smoke-userspace.sh          # same checks as the development CI job
# FreeBSD module build (host with bsd.kmod.mk), not this CI job:
# make -f Makefile.kmod
```

`make depend all` does not build `nvso.ko`: `depend` is a no-op and `all` builds `nvsoctl` only. `make kmod` without `bsd.kmod.mk` prints a skip and exits 0 without a module. The FreeBSD sources are written so a loaded soft driver attaches as `nvso0` and the bookkeeping ioctls return 0. This tree does not record that attach. Hardware SSD/GPU DMA is not in the sources.

### qodesh (Windows, G84) — Worker only when connected

Sole-worker rule: **do not** parallel machineId Shell on qodesh from this agent while another Worker owns it.

Queued checklist for qodesh Worker:

1. Confirm `gpu-legacy` stories15M / SmolLM sm11 path still builds (`build-gcc.bat`).
2. Record free VRAM with desktop on (historically 56–91 MiB free of 256).
3. Do **not** attempt full llama CUDA; keep GGUF on CPU llama.
4. Optional: document peer-DMA fantasy vs WDDM reality in LESSONS — WDDM bounce is why OS-bypass FreeBSD matters.
5. When FreeBSD nvso SSD side exists, define a **descriptor format** shared with `nvgpu_dma_post` that sm11_shim could one day emit (out of scope until angel stub loads).

### centos10-bigram

Probe whether 340.108 can bind (nouveau conflict). Linux prototype for partitioned L2 is thread lore only — do not block FreeBSD ABI on it.

## miryam Vulkan unstick (iGPU hang — parallel, not VVRAM)

Last probe: Intel HD 620 ICD present; **vulkan** `llama-server` binary and SmolLM path for `miryam-gpu-decision` missing; existing server listed 0 devices (CPU-only build).

Plan:

1. Locate or restore `llama-b11374-linux-x64-vulkan` / `llama-b11539-linux-x64-vulkan` under `code-bootstraps-llama.cpp/bin/`.
2. Place SmolLM2-135M Q4 under path in `models.smollm2-135m-q4-miryam`.
3. Short smoke: `-ngl 99` on decision node; compare to CPU (historically Vulkan slower on HD 620 for SmolLM — still hang for coverage).
4. If `vulkaninfo` needs sudo: note blocker; use existing ICD path from prior verified runs.

## Separation of tracks

| Track | Blocks Nanbeige? | Owner host |
|-------|------------------|------------|
| LAYER mmap/swap | **Yes** (ops gate) | angel |
| nvso stub compile | No | angel |
| Open SandForce FW | No | lab SSD |
| sm11 cuda path | No | qodesh |
| miryam Vulkan | No | miryam |
