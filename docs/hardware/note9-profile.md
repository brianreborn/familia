# Samsung Galaxy Note 9 (SM-N960U/F) Deployment & Sizing Profile

- **Hardware Target:** Snapdragon 845 (4x Kryo 385 Gold @ 2.8GHz, 4x Kryo 385 Silver @ 1.7GHz), Adreno 630 GPU.
- **RAM Constraint:** 6 GiB physical RAM (system Android baseline consumes ~3.5 GiB; free headroom is ~2.0 - 2.5 GiB).
- **Architecture Sizing Strategy (Fit Over Benchmark):**
  - **Chat / Node Role:** `SmolLM2-135M-Instruct.Q4_0` (87.5 MiB weight file) or `Qwen2.5-0.5B-Instruct-Q4_K_M` (379 MiB).
  - **Context Window:** Capped at 2048 (`-c 2048`).
  - **KV Cache:** `f16` or `q8_0` (approx 12-24 MiB total KV overhead).
  - **Threads:** 4 threads (`-t 4`) bound to the high-efficiency Kryo cluster.
  - **Memory Load Mode:** `-lm none` or `mmap` with single slot (`-np 1`).
  - **Peak RSS:** Total inference footprint stays strictly below **550 MiB**, completely eliminating Android low-memory-killer (LMK) eviction risks.
