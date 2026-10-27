# PHASES — HVVRAM checklist (complete sketch)

| Phase | Name | Needs custom FW? | Code today | Next concrete artifact |
|-------|------|------------------|------------|------------------------|
| 0 | Software VVRAM | No | LAYER + graph spill/swap | angel-coder health + BENCH JSONL |
| 1 | Soft HVVRAM domains | No | nvso softc + nvsoctl | create/map/gate/post soft = 0 |
| 2 | Open SSD queues | **Yes** | geom structs only | UART identify FW on donor drive |
| 3 | Peer DMA | **Yes** + CDC path | desc format | one PEER completion counter |
| 4 | Independent SO domains | Research silicon | paper | emulator or FPGA SO stand-in |

**Remember:** Phase 2+ does not start until Phase 1 soft path is boringly reliable and FIRMWARE-PLAN donor hardware is identified.
