# GPU / CPU binary + library layout (Platform sketch)

Branch: `swarm/platform/vulkan-cuda-miryam`. Partner: Race `swarm/race/miryam-perf` (#83/#82) and reconnect #149 (Race primary, not GPU).

**Win:** deferred this cut (agree with Race). No `serve.ps1` empty-env work here.

Scope: Platform owns discover order, RPATH/`LD_LIBRARY_PATH`/ICD seatbelts, Termux `PREFIX`, wrong-`.so` refusal. Race owns spawn TOCTOU, oversubscribe, `ngl:0` CPU/`--no-op-offload`, ngram opt-in. Restarts only with `DETACH_MODE=screen-attached`.

## Discover order (per process, not shell-global)

1. **Node `offload.backend` + `ngl`** from graph (authoritative).
2. **Runtime `bin`** from `runtimes.*.bin` (absolute or repo-relative). Never PATH-hunt a different pack.
3. **Sibling `lib/`** next to `bin/` (or `$ORIGIN/../lib` if RPATH set). Refuse start if NEEDED sonames missing / ABI skew (see A57 galaxy2: `grz-runtime/lib` ≠ working `bin` pack).
4. **Backend libs only when intended:**
   - `ngl > 0` + `backend: vulkan` → allow Vulkan ICD + `libggml-vulkan.so`
   - `ngl == 0` → prefer **CPU-only binary**; if stuck on a Vulkan prebuilt, set `GGML_VK_VISIBLE_DEVICES=` (empty) and prefer `--no-op-offload` (Race #83)
   - `backend: cuda*` → CUDA pack only; never mix Vulkan prebuilt `.so` into CUDA tree

## Canonical env + search paths by host class

### miryam (Linux laptop, HD 620 Mesa Vulkan)

| Intent | Binary | Env | Notes |
|--------|--------|-----|-------|
| Decision / small Vulkan (`ngl: 99`) | `runtimes.llama-b11541-linux-vulkan.bin` (or pinned vulkan prebuilt under `code-bootstraps-llama.cpp/bin/llama-b*-linux-x64-vulkan/`) | default ICD (Mesa Intel); do **not** clear `GGML_VK_VISIBLE_DEVICES` | HD 620 slower than CPU on SmolLM2; value is freeing CPU for coder (L8) |
| Coder / CPU-intended (`ngl: 0`) | **CPU build** preferred (Race #83). If Vulkan build reused: `GGML_VK_VISIBLE_DEVICES=` via `serve.sh` / `validate_graph.server_env` (L-vkshm) + `--no-op-offload` | Empty VK visible devices; do not unset Mesa ICD **globally** | Vulkan build + `ngl 0` still op-offloads to iGPU and burns ~1.8 GiB shmem without empty `GGML_VK_VISIBLE_DEVICES` |
| Lib path | `dirname(bin)` first on `LD_LIBRARY_PATH`; never pull Termux or Win packs | Pack atomicity: ship `bin`+matching `libggml-*.so` together | |

### angel / fam-gpu (FreeBSD desktop)

| Intent | Binary | Env | Notes |
|--------|--------|-----|-------|
| CPU mmap / large RAM | graph runtime on angel (CPU) | no Vulkan required today (`gpus: null` until measured) | CUDA “fam-gpu” only if a measured NVIDIA path lands; not miryam Vulkan |
| Lib path | runtime dir only | — | FreeBSD loader ≠ Linux `LD_LIBRARY_PATH` semantics; document any `LD_LIBRARY_PATH` / rpath separately when CUDA appears |

### Termux A57 (phone7/phone8, Xclipse 550)

| Intent | Binary | Env | Notes |
|--------|--------|-----|-------|
| Vulkan offload | Termux `llama-server` on PATH **or** `$HOME/grz-runtime/bin/llama-server` | `LD_LIBRARY_PATH=$HOME/.vk` where `.vk/{libvulkan.so,libvulkan.so.1}` → `/system/lib64/libvulkan.so` (L7 / `install/termux/install.sh`) | Termux `$PREFIX` loader alone → llvmpipe only |
| CPU-only node | same binary OK if `ngl: 0` + empty `GGML_VK_VISIBLE_DEVICES` **or** CPU-only Termux build if packaged | Keep `.vk` off `LD_LIBRARY_PATH` for pure CPU if a Vulkan ggml backend still attaches | Also: `grz-runtime/lib` must match `bin` pack (PF-RT1…4); galaxy2 break was mismatched ggml/llama `.so` |
| `PREFIX` | `$PREFIX` = Termux usr (`$HOME/../usr`); never assume `/usr` | SELinux `untrusted_app`; no exec from `/data/local/tmp` for product | |

### Win (qodesh / shalom) — **out of this cut**

PowerShell 5.1 cannot hold empty `GGML_VK_VISIBLE_DEVICES`. Existing rule: CPU build for `ngl: 0`. Vulkan pack on disk ≠ usable device on 8600. Defer path docs to a later Win platform PR.

## ICD isolation without breaking same-host `ngl > 0`

**Yes — per-process spawn env, not login-shell export.**

- Same host may run decision (`ngl: 99`, needs ICD) and coder (`ngl: 0`, must not see Vulkan devices / must not op-offload).
- Seatbelt already: `scripts/serve.sh` + `validate_graph.server_env` set `GGML_VK_VISIBLE_DEVICES=` only for that child’s env when `ngl == 0` (unless already set). Explicit non-empty in env wins.
- Do **not** `unset VK_ICD_FILENAMES` or wipe Mesa ICD in the user profile — that breaks concurrent Vulkan nodes.
- Optional stronger isolate (future): CPU-only binary so `libggml-vulkan.so` is never loaded (`dlopen` never happens). Race prefers this for #83.
- `VK_ICD_FILENAMES` pointing at a stub empty set is **not** recommended as global; if used, only in the CPU child’s env and only when CPU binary unavailable.

## Wrong-`.so` refuse (Platform seatbelt)

Before exec:

1. Resolve realpath of `llama-server`.
2. `ldd` / `readelf -d` NEEDED; every `libggml-*.so` / `libllama.so` must resolve under the runtime’s own dir (or documented `lib/`), not a random `PATH`/`PREFIX` hit.
3. Checksum or soname pair file for the pack (install-time). Peer sync must copy **bin+lib** together.

## Race wiring hooks

| Hook | Platform provides | Race uses |
|------|-------------------|-----------|
| `server_env(graph, node, env)` | empty `GGML_VK_VISIBLE_DEVICES` when `ngl==0` | keep; add `--no-op-offload` / CPU runtime select for #83 |
| Runtime `bin` pin | graph `runtimes.*` | TOCTOU: re-stat bin+lib mtime/inode at spawn vs health |
| Thread budget | host `threads` / reserve | refuse oversubscribe when Vulkan path + CPU threads fight |
| Spec | — | `#82` ngram-simple opt-in / prefer ngram-mod |

## Status

- Sketch only on this branch; implement refuse/`lib` atomicity in follow-up commits once Race confirms hooks.
- Mirror: `/workspace/reviews/gpu-path-layout-miryam.md`
