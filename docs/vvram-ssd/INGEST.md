# INGEST — G84 Independent SO Domains + Zero-Copy SSD DMA

Source: https://x.com/grok/status/2113981636370899059 (2026-10-24 PT)  
Thread dump: [THREAD-SOURCE.md](./THREAD-SOURCE.md)  
In-repo scaffold: `familia/gpu-legacy/nvso/`  
Ship-today software layer: [LAYER.md](./LAYER.md)  
Bridge + compile plan: [G84-BRIDGE.md](./G84-BRIDGE.md)  
Bench method: [BENCH.md](./BENCH.md)

## Design summary (silicon + NVM)

| Layer | Intent |
|-------|--------|
| Per-SO/TPC PLL + voltage | Independent clock/voltage domains per Streaming Multiprocessor / Texture Processing Cluster |
| Local MMUs + private page tables | Isolate address spaces; map NVM rings into SO domains |
| CDC-safe fabric | Atomics, barriers, signaling across clock domains |
| Power-gate + reconfig + local IRQs | Form dynamic SO clusters; hybrid spin-then-block |
| Partitioned L2 | Private memory per domain (Linux prototype called “ready” in thread) |
| Open SandForce / OCZ Vertex 2 FW | Expose raw queues + geometry (not black-box FTL) |
| Zero-copy GPU↔SSD DMA | GPU posts DMA descriptors across CDC/peer path; OS maps+monitors only; no bounce buffers |

## Map onto familia hosts (honest)

| Host | Role in this R&D | Today | This scaffold |
|------|------------------|-------|---------------|
| **angel** (FreeBSD, i5-4570, 24 GiB, 4T) | Nanbeige4.3-33B Q4_K_M (~18.7 GiB); SSD swap/mmap/spill | Nodes `angel-coder` / `angel-chat` **planned**; runtime `llama-b11669-freebsd` | **Software VVRAM layer** (LAYER.md) + FreeBSD **nvso** kmod/ioctl stubs (compile when SSH up) |
| **gabriel** | Same class FreeBSD desktop (twin / follow-on) | Not in graph yet | Same LAYER policy; share nvso when host facts land |
| **qodesh** (Win, G84 8600 GT, CC 1.1, ~256 MiB) | Verified `gpu-legacy` sm11 path; CUDA 6.5 / nvidia 340 era | Offline; CPU llama for GGUF; sm11 for stories15M/SmolLM | **G84 bridge** only — do not claim SO domains on stock silicon; queue Worker checklist |
| **centos10-bigram** | Same G84 profile on Linux | nouveau owns card; 340.108 built but unbound | Linux prototype notes only; FreeBSD-first APIs preferred |
| **miryam** (Intel HD 620 Vulkan) | iGPU hang path for decision SmolLM | Vulkan ICD present; **vulkan llama-server bin + SmolLM path missing** last probe | Unstick plan in G84-BRIDGE §miryam; not VVRAM |
| **box** (Grok Bot VM) | CPU dogfood multi-size | No `/dev/dri` / nvidia; SmolLM+Qwen2B healthy | Perf harness only |

## What we claim vs what we do not

**Claim now:** software SSD-as-working-set for 33B on 24 GiB (mmap + swap + optional spill dir); FreeBSD-first **API surface** and man pages for `nvso_*`; bridge plan from `gpu-legacy` sm11.

**Do not claim:** stock G84 has independent SO domains, open SandForce FW on angel’s SSD, or working zero-copy GPU↔SSD DMA. Those need silicon/FW/OS work tracked in G84-BRIDGE.

## Related thread artifacts

- Prize inventory: `/workspace/familia-install-notes/prize-inventory-angel.md`
- Nanbeige ingest: `/workspace/familia-install-notes/nanbeige/`
- Box swap notes: `/workspace/familia-install-notes/swap-box.md`
- Perf: `/workspace/familia-install-notes/perf/2026-10-26-box-multi-size.json`
