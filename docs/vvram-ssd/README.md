# VVRAM / SSD DMA R&D

Working install-notes copy also at `/workspace/familia-install-notes/vvram-ssd/`.

| Doc | Purpose |
|-----|---------|
| [INGEST.md](INGEST.md) | Grok design → host map |
| [LAYER.md](LAYER.md) | Software SSD spill/mmap/swap for angel Nanbeige (**ship today**) |
| [G84-BRIDGE.md](G84-BRIDGE.md) | FreeBSD nvso + gpu-legacy bridge + compile plan |
| [BENCH.md](BENCH.md) | One-coordinator SSH methodology |
| [THREAD-SOURCE.md](THREAD-SOURCE.md) | Source tweet digest |
| [MIRYAM-VULKAN.md](MIRYAM-VULKAN.md) | iGPU hang blockers (2026-10-26) |

Scaffold: [`../../gpu-legacy/nvso/`](../../gpu-legacy/nvso/) (`nvsoctl -n` works on Linux; kmod on angel FreeBSD).
