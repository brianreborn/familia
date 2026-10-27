# SSD → VVRAM / HVVRAM notes

Honest staged R&D for Nanbeige-on-angel (software) and G84+open-FW DMA (hardware).

| Doc | Role |
|-----|------|
| [HVVRAM-ARCHITECTURE.md](./HVVRAM-ARCHITECTURE.md) | **Stage map** 0→4 (software → soft domains → FW → DMA → SO silicon) |
| [LAYER.md](./LAYER.md) | Stage 0 ship-today mmap/swap/spill |
| [FIRMWARE-PLAN.md](./FIRMWARE-PLAN.md) | **Custom SSD FW** requirements (still required; not shipped) |
| [DESCRIPTOR-FORMAT.md](./DESCRIPTOR-FORMAT.md) | `nvgpu_dma_desc` + CDC notes |
| [G84-BRIDGE.md](./G84-BRIDGE.md) | Compile/bridge plan + sm11 |
| [BENCH.md](./BENCH.md) | Coordinator methodology |
| [THREAD-SOURCE.md](./THREAD-SOURCE.md) | Upstream Grok design thread |
| [INGEST.md](./INGEST.md) | Host mapping + claim/non-claim |
| [ANGEL-OPERATOR.md](./ANGEL-OPERATOR.md) | Uriel sync/start (multi-node, not limp) |
| [URIEL-COORDINATOR.md](./URIEL-COORDINATOR.md) | Coordinator bring-up |

Code: `familia/gpu-legacy/nvso/`.

**Remember:** custom firmware and peer-DMA are **not** done — sketches define them so stubs do not linger without a target.
