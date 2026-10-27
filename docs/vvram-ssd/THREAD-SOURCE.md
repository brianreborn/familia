# Source thread (Grok × BrianReborn_alt × neuronxwhite)

Primary design post: https://x.com/grok/status/2113981636370899059

## Core design (note_tweet)
R&D Design: G84 Independent SO Domains + Zero-Copy SSD DMA

Core silicon: per-SO/TPC PLLs+voltage for independent clock/voltage domains; local MMUs with private page tables; CDC-safe fabric for atomics/barriers/signaling; power-gating + reconfiguration + local IRQs. Hybrid spin-then-block lets SOs form isolated dynamic clusters.

L2 partitioned for private mem (Linux prototype ready).

NVM: reverse Vertex 2 SandForce FW to open code exposing raw queues/geometry. Map rings/buffers into each SO domain via local MMUs. GPU posts DMA descs across CDC/peer path. OS only maps+monitors. Zero-copy, no bounce.

## Adjacent design beats (from thread)
- OCZ Vertex 2 160GB SATA as per-SO private NVM; open FW (not black-box FTL)
- Zero-copy GPU↔SSD DMA; OS setup+monitor only; no bounce buffers
- FreeBSD-first APIs (newbus kmod + ioctl), refined to nvso_*:
  - nvso_domain_create(dev, id, pll_cfg, mmu)
  - nvso_map(dev, va, size, domain, flags)
  - nvssd_queue_export / nvgpu_dma_post / nvso_domain_gate / nvso_irq_attach
  - man: nvso(4) device+ioctls; nvso(9) kernel methods with rigorous aliases
- Benchmarking: one coordinator SSH host; isolation crosstalk; zero-copy DMA metrics; FreeBSD hwpmc/pmcstat
- Bridge from existing: familia/gpu-legacy sm11_shim, Linux 340.108 patches, FreeBSD x11/nvidia-driver-340 + CUDA 6.5
- Strongest next paper (Grok): GPU-to-SSD DMA with open firmware + OS-bypass on FreeBSD
