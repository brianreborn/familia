# LAYER — Software SSD→VVRAM (shippable today)

No new silicon. Goal: run **one** Nanbeige4.3-33B Q4_K_M (~18.7 GiB) node on angel’s **24 GiB RAM** by treating fast SSD as overflow for weights + KV, without pretending we have G84 SO domains.

## Budget (angel)

| Item | MiB (approx) |
|------|--------------|
| Host RAM | 24442 |
| `reserve_ram_mib` | 4096 |
| Usable for llama | ~20346 |
| Weights Q4_K_M | ~19149 (18.7 GiB) |
| KV @ ctx 65536, q8_0, parallel 1 | ~2× vs 32K (measure on activate; heavier SSD spill) |
| `cache_ram_mib` (graph) | >= per-slot KV (angel-coder: 3584 baseline; advisory ~2× at 64K) |

Weights alone nearly fill usable RAM → **mmap load + measured swap/spill required before `status: active`.**

Do **not** co-activate `angel-coder` and `angel-chat`.

## Knobs that exist in graph today

| Field | Use for VVRAM layer |
|-------|---------------------|
| `load_mode: mmap` | Map GGUF from SSD; OS page cache = soft VRAM |
| `cache_ram_mib` | Prompt-cache budget (`--cache-ram`) |
| `kv_type: q8_0` + `flash_attn: true` | Shrink KV vs f16 |
| `ctx` / `threads` | Cap working set; angel uses threads: 2 |
| `slot_save: true` (optional) | `--slot-save-path` under cache dir |
| `note` | Human ops: spill path, swap budget (no schema yet) |

llama.cpp also: `--cache-type-k` / `--cache-type-v` (graph `kv_type` today applies as shared type via serve path — verify on FreeBSD pin).

## FreeBSD (angel / gabriel) — do this before activate

```sh
# Measure disk + RAM (no root needed for readouts)
sysctl hw.physmem hw.pagesize vfs.zfs 2>/dev/null
swapinfo -k
df -h ~/.local/share/gguf /var/tmp /usr/home

# Root: dedicated swap on fast SSD (example sizes — measure free first)
# Prefer a partition or ZFS vol; file-backed swap works for dogfood:
dd if=/dev/zero of=/usr/swap/familia-nanbeige.swap bs=1M count=24576   # 24 GiB example
chmod 600 /usr/swap/familia-nanbeige.swap
mdconfig -a -t vnode -f /usr/swap/familia-nanbeige.swap   # or swapctl -a path per local practice
# Persist via /etc/fstab swap entry; set vm.swappiness-equivalent carefully (FreeBSD: vm.swap_enabled=1)

# Huge pages / wired: avoid mlock of full 18.7 GiB on 24 GiB host
# Prefer mmap without mlock; do NOT set load_mode that wires all weights
```

Spill directory (userspace “VRAM spill” — slot/prompt cache on SSD):

```sh
mkdir -p ~/.cache/familia/spill/angel-coder
# When activating with slot_save, point --slot-save-path there (graph slot_save: true)
```

## Linux (box / miryam / centos) — parallel policy

See `/workspace/familia-install-notes/swap-box.md` and `docs/ram-safety.md`: zram first, then lower-prio SSD swapfile. Box has **0 swap** today (needs root).

## Schema (wired)

Node fields in `graph_types.py` / `graph.yaml`:

```yaml
spill_path: ~/.cache/familia/spill/angel-coder   # → llama-server --slot-save-path
swap_budget_mib: 24576                           # ops gate: validate_graph --check-swap
slot_save: true                                  # or just set spill_path (either enables argv)
# cache_type_v: q8_0                             # not first-class yet; kv_type applies to K+V
```

- `server_args`: `spill_path` or `slot_save` → `--slot-save-path` (spill_path wins over `~/.cache/familia/slots/<node>`).
- `validate_graph.py --check-swap [--host angel]`: fail if host swap total MiB < any active node's `swap_budget_mib`.
- Docs: this directory + `ANGEL-OPERATOR.md`.


## Coherent 64K / RAM policy (fleet)

Hermes `MINIMUM_CONTEXT_LENGTH` is **64000**. Nodes that serve hermes must set `ctx >= 64000` (miryam `coder` and angel `angel-coder` use **65536**).

| Situation | Required path | Launch outcome |
|-----------|---------------|----------------|
| Estimated weights+KV+cache+256 ≤ `ram_mib − reserve_ram_mib` | RAM-fit: `load_mode: none` (or mmap) is fine; `spill_path`/`slot_save` optional for prompt cache | READY when server healthy |
| Estimate exceeds usable RAM | Software VVRAM: **`load_mode: mmap` + (`spill_path` or `slot_save`) + `swap_budget_mib`**, then `validate_graph --check-swap` on that host | Else validate ERROR / `LAUNCH_FAILED` `LF_NEED_SPILL` — never silent OOM |

`scripts/ctx_vvram.py` (via `validate_graph.check_vvram_policy`) enforces the table. `admit_peak_mib` (used by `serve.sh` memcap) charges mmap+swap_budget nodes **KV + cache_ram + 1536 MiB working set**, not the full GGUF, so angel’s Nanbeige does not starve the fleet ledger. **`reserve_ram_mib` stays** (OS + companions); do not lower it to “make room” for mmap spill — spill goes to SSD swap/slot files instead.

Labels stay model+quant (never a hash). Status lines follow `docs/protocol/launch-status.md`.

## What NOT to claim

- This layer is **not** zero-copy GPU↔SSD DMA.
- This layer is **not** independent SO domains or open SandForce queues.
- mmap page faults ≠ CDC-safe fabric.
- Shipping `nvso` stubs does not make angel’s SSD a peer of a G84.

## Activate checklist (angel)

1. Verify GGUF path + sha256 (`nanbeige43-33b-q4km`).
2. `swapinfo` shows ≥ ~20–24 GiB usable swap on SSD (or measured smaller with proven RSS).
3. Spill dir exists (`mkdir -p` spill_path); `slot_save: true` or spill_path set.
4. Activate **one** of `angel-coder` / `angel-chat`.
5. Smoke with `enable_thinking` appropriate to card; record pp/tg + RSS + swap in registry.
