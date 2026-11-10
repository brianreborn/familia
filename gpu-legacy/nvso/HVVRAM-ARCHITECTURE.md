# HVVRAM architecture (pointer)

Canonical sketch: [`docs/vvram-ssd/HVVRAM-ARCHITECTURE.md`](../../docs/vvram-ssd/HVVRAM-ARCHITECTURE.md).

Soft nvso ABI 2 is stage-1 domain bookkeeping in the FreeBSD sources. Userspace CI covers `nvsoctl -n` and client exit codes only. A live module load is still pending. Hardware HVVRAM does **not** work, and the soft ABI is not SandForce firmware or peer DMA.
