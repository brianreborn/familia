# G84-BRIDGE — Implementation plan (FreeBSD-first nvso + gpu-legacy)

Status: **scaffolding landed in-repo** (`familia/gpu-legacy/nvso/`). Live compile/test waits for angel SSH / qodesh online. Software Nanbeige path is [LAYER.md](./LAYER.md) and does not block on this.

## Goal chain

1. **Today:** angel Nanbeige via mmap+swap+spill (LAYER).
2. **Near:** FreeBSD `nvso(4)` kmod + ioctl ABI compiling as stub on angel (headers + empty softc).
3. **Next paper path:** open SandForce/Vertex2 FW + GPU↔SSD DMA descriptors; OS maps+monitors.
4. **Bridge:** reuse lessons from `gpu-legacy` sm11_shim (qodesh) and nvidia 340 / CUDA 6.5 ports — **not** full llama CUDA on 256 MiB.

## In-repo file layout (concrete)

```
familia/gpu-legacy/nvso/
  README.md                 # build + scope
  include/nvso.h            # userspace + shared ioctl ABI
  include/nvso_ioctl.h      # _IOWR defs
  sys/nvso_if.h             # kernel method table sketch (nvso(9))
  sys/nvso.c                # stub newbus driver (compiles with #if 0 / empty softc)
  sys/nvso_ssd.c            # queue export stubs (nvssd_*)
  sys/nvso_gpu.c            # dma post stubs (nvgpu_*) — G84 peer later
  man/man4/nvso.4           # device + ioctls
  man/man9/nvso.9           # kernel methods + aliases
  tools/nvsoctl.c           # userspace ioctl smoker (no device → exit 2)
  Makefile                  # FreeBSD kmod + tools (no-op on Linux with message)
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

Man aliases (rigorous): see `nvso.4` / `nvso.9` — e.g. `NVSO_DOMAIN_CREATE` ioctl name ↔ `nvso_domain_create(9)` method.

## Next compile steps (when hosts up)

### angel (FreeBSD) — primary

```sh
cd ~/familia/gpu-legacy/nvso   # or repo path
make -C . depend all           # builds nvso.ko stub + nvsoctl
# load only when intentional:
# sudo kldload ./nvso.ko
./tools/nvsoctl -n             # dry-run: print ioctl numbers; no /dev/nvso → exit 2
```

Expect: stub driver attaches as `nvso0` if `nvso_load` enabled; all ioctls return `ENXIO` or `EOPNOTSUPP` until SSD/GPU backends filled.

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
