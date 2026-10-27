# LAYER — Software SSD→VVRAM (shippable today)

No new silicon. Goal: run **one** Nanbeige4.3-33B Q4_K_M (~18.7 GiB) node on angel’s **24 GiB RAM** by treating fast SSD as overflow for weights + KV, without pretending we have G84 SO domains.

## Budget (angel)

| Item | MiB (approx) |
|------|--------------|
| Host RAM | 24442 |
| `reserve_ram_mib` | 4096 |
| Usable for llama | ~20346 |
| Weights Q4_K_M | ~19149 (18.7 GiB) |
| KV @ ctx 32768, q8_0, parallel 1 | hundreds–low thousands (measure on activate) |
| `cache_ram_mib` (graph) | 512 |

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

## Proposed schema (not wired — document only)

Optional node fields (would need `graph_types.py` + `validate_graph.py` + serve argv):

```yaml
spill_path: ~/.cache/familia/spill/angel-coder   # --slot-save-path or future kv spill
swap_budget_mib: 24576                           # ops gate: refuse activate if swapinfo free < budget
cache_type_v: q8_0                               # if split K/V types become first-class
```

Until then: encode path + budget in `note` / host `notes`; keep `load_mode: mmap` + `slot_save` when ready.

### Patch proposal (small)

1. `scripts/graph_types.py` nodes: `spill_path: opt("str")`, `swap_budget_mib: opt("int", min=0)`.
2. `validate_graph.py`: if `swap_budget_mib` set and `--check-swap` (host-local only), warn/fail when swap total < budget.
3. serve argv: if `spill_path` or `slot_save`, pass `--slot-save-path` expanded path.
4. Docs: `docs/vvram-ssd/README.md` points here.

## What NOT to claim

- This layer is **not** zero-copy GPU↔SSD DMA.
- This layer is **not** independent SO domains or open SandForce queues.
- mmap page faults ≠ CDC-safe fabric.
- Shipping `nvso` stubs does not make angel’s SSD a peer of a G84.

## Activate checklist (angel)

1. Verify GGUF path + sha256 (`nanbeige43-33b-q4km`).
2. `swapinfo` shows ≥ ~20–24 GiB usable swap on SSD (or measured smaller with proven RSS).
3. Spill dir exists; optionally `slot_save: true`.
4. Activate **one** of `angel-coder` / `angel-chat`.
5. Smoke with `enable_thinking` appropriate to card; record pp/tg + RSS + swap in registry.
