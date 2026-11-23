# angel / Uriel — fleet coordinator bring-up

**Role:** FreeBSD host `angel` (aka **Uriel**) is a fleet coordinator and SSH hub for benches (see `docs/vvram-ssd/BENCH.md`). Nanbeige is a catalog-only research candidate, not a deployable Angel workload.

**Reachability:** use the configured SSH alias `angel`; its address belongs in the private host inventory, not tracked documentation.

## Golden path once online

1. Confirm the host is reachable using `ssh angel`.
2. Update the Familia checkout and build the pinned FreeBSD llama.cpp runtime using the current `code-bootstraps-llama.cpp` pin.
3. Generate `generated/graph-angel.yaml`; validate runtime, model files, native context, RAM reserve, and swap before activation.
4. Keep model nodes planned until the complete documented context passes those checks.
5. Run `python3 scripts/start_graph.py --graph generated/graph-angel.yaml --host angel --dry-run` before starting any service.

## Graph

- `hosts.angel.local_names` includes `uriel` / `Uriel`
- Angel model nodes `angel-coder` and `angel-chat` are **planned** pending full-context capacity qualification.
