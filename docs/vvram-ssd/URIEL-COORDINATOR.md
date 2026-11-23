# angel / Uriel — fleet coordinator bring-up

**Role:** FreeBSD host `angel` (aka **Uriel**) is the fleet coordinator: named large model prize + SSH hub for benches (see `docs/vvram-ssd/BENCH.md`).

**Reachability (miryam SSH config):** `Host angel gabriel` → `192.168.4.25`  
**Status 2026-10-26 9:30 PM PT:** LAN IP **192.168.4.25** (was 192.168.1.3). Reachable from miryam; `~/familia` on `main` @ `02c45f2`.

## Golden path once online

1. Power + network on Uriel/angel; confirm `ping 192.168.4.25` and `ssh angel`.
2. On angel: `git clone`/`pull` brianreborn/familia → tip `8273c5a`+; spill dirs + swap per `docs/vvram-ssd/LAYER.md`.
3. Confirm GGUF: `~/.local/share/gguf/models/general/large model-UNCENSORED-Q4_K_M.gguf`
4. FreeBSD llama-server build (`llama-b11669-freebsd` / source build).
5. `./start.sh --host angel` → **only** `removed-large-coder` (port **18200**); do not co-start `removed-large-chat`.
6. Health: `curl -sS http://127.0.0.1:18200/health`
7. From miryam: use `ssh angel` as coordinator for fleet smokes (phones when up, miryam Vulkan, qodesh via Worker).

## Graph

- `hosts.angel.local_names` includes `uriel` / `Uriel`
- `nodes.removed-large-coder` status **active**
