# LESSONS-LEARNED.md

> **Status note (2026-10-09):** earlier content was a coding agent's private session notes (artifact paths, tool names) and claimed files and regression tests that did not exist. It has been replaced with project lessons.

## L1. Renames leave a long tail (#16)
Renaming feeldznutts → familia left the installer, docs, log prefixes and the logo pointing at the old name. Grep for the old name in code *and* docs, and replace assets in the same change.

## L2. Agent context must match the server slot (#19)
hermes-agent with compression off sent ~18–21k-token requests to a 16,384-token `coder` slot and looped on HTTP 400. Fix: declare both in `graph.yaml`, require `context_length` == per-slot ctx, and launch hermes through `scripts/hermes.sh` with compression on.

## L3. Escaped quotes break shell scripts silently (#14)
A stray `\"` left `android_start.sh` unparseable. Run `sh -n` / shellcheck in CI.

## L4. Never pack a small host's RAM (2026-10-09)
miryam (7 GiB) hard-hung when the 64k coder server, an embed test and a compaction self-test ran together. Provisional guidance, not hard limits: `reserve_ram_mib: 3072`, ~2 GiB free after estimates, one heavy process at a time. They stay fuzzy guidance even now that idle load has been sampled and earlyoom, zram and the memcap scope are deployed on miryam (L-memcap). See `docs/ram-safety.md`.

## L5. SSH passwords
Use key-only SSH to the phones; the android scripts read addr/user/port from graph.yaml (or ANDROID_HOST/USER/PORT) and never take passwords or disable host-key checking (#18).

## L6. Use ASCII in names and code
Non-breaking hyphens (U+2011) in file names and Python expressions break copy-paste. Keep identifiers ASCII.

## L7. Android Vulkan needs the system loader
Termux's Vulkan loader only sees llvmpipe. llama.cpp finds the phone GPU (Xclipse 550) only when LD_LIBRARY_PATH holds both libvulkan.so and libvulkan.so.1 linked to /system/lib64/libvulkan.so; familia-start does this. On the A57, SmolLM2-135M Vulkan -ngl 99 gives tg 66-79 t/s against 30 t/s on 3 CPU threads (#34).

## L8. Phones drop off Wi-Fi during long runs
Both A57s left the LAN (no route to host) minutes into a detached benchmark. Take termux-wake-lock and keep the screen-off Wi-Fi policy in mind before long runs, write results to a log on the phone, and poll with backoff instead of holding one SSH session open.

## L9. Same hardware is not same software
phone7 had Termux llama-cpp 0.5.0 while a fresh install on phone8 pulled 0.6.0. Record the runtime version with every benchmark before comparing phones.

## L10. A small iGPU can be slower than the CPU
On miryam the HD 620 runs SmolLM2-135M at 46 t/s tg, versus 101 on 2 CPU threads. Its value is offloading the decision model so the CPU stays free for the coder. When both ran together, though, the Vulkan side fell from 46 to 17 t/s tg, while the CPU coder held about 14 t/s (#24).


## L11. Measure once, look it up afterwards (model + hardware registry)
Each tuning round re-learned facts we already had: the A57 Vulkan loader fix, the iGPU being slower than miryam's CPU, contention on shared memory. Every measured result now goes into `registry/records.jsonl` (append-only, labelled measured or estimated), and the hardware setup facts go into shareable `registry/hardware/` profiles. `registry.py suggest` proposes a placement from those records instead of a new sweep, and `match` gives identical hardware the known-good setup. Watts are spec-sheet upper bounds until measured. See `docs/model-registry.md`.

## L12. LittleBit sub-1-bit models (#28, 2026-10-09)
- **QAT is not optional.** Upstream init alone (Dual-SVID, even with LittleBit-2 ITQ) on stories15M gives PPL 2.6e5–2.7e14 vs dense 1.88 (0% top-1). Per-layer relative output error at eff 1.0: 0.82 SVD-only, 0.68 ITQ. 300 CPU self-distillation steps (~6 min, 4 threads) bring it to PPL 6.31 (eff 1.0) and 6.98 (eff 0.1). Those numbers are a pipeline exercise on same-distribution text, not paper-grade.
- **At small widths the scales dominate.** eff 0.1 on 288-wide layers clamps to rank 8 and stores 0.224 bpw, because the F32 scales outweigh the signs. On K2-Horizon-0.9B-sized layers 0.1 really is ~0.11 bpw.
- **The dense parts decide the size.** After LittleBit, the embedding and an untied head are most of the file (stories15M: 71 of 71.3 MiB; K2-Horizon: 2×188 MiB f16 vs 11.6 MiB of linears). Plan the head's quant and placement first.
- **Keep upstream's bit layout** (int32, LSB first, bit 1 = −1). Conversion is then word copies, and the q/k rope permute only moves whole packed rows plus u1.
- **License:** upstream is CC BY-NC 4.0, so familia imports a user-supplied checkout and vendors nothing.
- **No public sub-1-bit checkpoints** from Samsung. "littlebit-qwen3-4b" GGUFs on HF are ordinary Q4/Q5/Q8.
- `rg PATTERN` with no path in a non-tty shell reads stdin and hangs. Always pass a path.

## L13. A57 sweep: what matters (phone8, llama-cpp 0.6.0, 2026-10-10)
With Vulkan -ngl 99 on SmolLM2-135M: Q4_0 gives the best tg (102 t/s, against 89 for Q8_0 and 83 for Q4_K_M). Flash-attn raises pp about 11% at equal tg. Threads 1, 2 and 3 are within noise once the GPU holds all layers. Batch and ubatch sizes stay within noise from 128 up (64 is about 15% slower on pp). Partial offload is worse than full: -ngl 24 gives 7 t/s tg, 16 gives 2.8, 8 gives 1.5. -ngl 0 with the Vulkan build loaded collapses to 0.2-0.8 t/s tg, so always use -ngl 99. Four back-to-back runs showed no thermal drift (tg128 80-82 t/s). Qwen2.5-0.5B Q4_K_M fits: tg 31-34 t/s, pp128 508, MemAvailable never below 1.9 GiB.

## L14. DHCP can swap phone addresses
After a reconnect, phone8 answered on phone7's old address with phone8's host key, and ssh refused it as a "changed host key". Confirm a device by its known host key plus its Termux user, and connect with HostKeyAlias, never by deleting known_hosts entries. Give the phones DHCP reservations.

## L-miryam-perf. On a 2-core laptop, use 2 threads, and the iGPU costs RAM (2026-10-10)
llama-bench on miryam (i5-7200U, 2C/4T, HD 620), Qwen3.5-2B Q4_K_M, CPU only, fa on, 2 reps, spread shown as +/-:

| setting | pp256 t/s | tg32 t/s |
|---|---|---|
| b11374, -t 4 | 29.4 +/-1.3 | 5.86 +/-0.27 |
| b11540 CPU, -t 4 | 31.6 +/-1.7 | 5.82 +/-0.18 |
| b11541 (Vulkan build, -dev none), -t 4 | 30.6 +/-0.9 | 6.26 +/-0.34 |
| b11541, **-t 2** | 32.4 +/-0.4 | **8.44 +/-0.06** |

LFM2.5-1.2B Q4_K_M: -t 2 pp 50.7 / tg 17.1; -t 3 47.4 / 15.2; -t 4 49.3 / 14.2.

- **Threads = physical cores.** Hyperthreads add contention on the shared FPU and memory path: -t 2 is +35% decode for the coder (+20% for LFM) and slightly faster prefill. The coder node now sets `threads: 2`.
- **Builds:** b11374, b11540 and b11541 are within noise. The coder stays on b11374, which is verified for qwen35.
- **KV type** (-d 1024, tg): f16 / q8_0 / q4_0 for K and V all land within 6.3-8.0 t/s at -t 4. That is inside the -t 4 noise, because Qwen3.5 is hybrid and has few full-attention layers. q8_0 stays for the 64k config. fa off was no faster (6.8).
- **ubatch** 128 / 256 / 512 at b 512: 32.3 / 33.0 / 32.9 t/s pp. No change from the default.
- **mmap flag:** this build renamed `-mmp` to `-lm` (load_mode), so it wasn't swept.
- **CPU clock:** it sits at 2.5 GHz on all cores under load, down from 3.1 GHz idle turbo. That's the 15 W limit. no_turbo=0, and turbo can't be adjusted without root.
- **iGPU and RAM:** every Vulkan run of the 2B coder (op-offload with -ngl 0, or -ngl 99) dropped MemAvailable from about 3.2 to 2.2-2.6 GiB. That tripped the 3 GiB guard within seconds, so the runs were killed before they produced numbers. On a shared-memory iGPU the driver allocates its own buffers in addition to the mmapped weights. Under the 3 GiB-free rule, the coder can't use the iGPU on miryam at all. Smaller models (LFM, embed) are tested for iGPU roles separately.
- **iGPU clock cap:** gt_max_freq_mhz (1000 MHz, min 300) isn't writable without root, and intel_gpu_top isn't installed, so a capped iGPU clock wasn't tested.


## numpy and pre-x86-64-v2 CPUs (qodesh, Athlon II X2), 2026-10-10
- numpy 2.4+ wheels crashed on import with 0xc000001d (illegal instruction). NumPy 2.4.0 raised the default x86 `cpu-baseline` to X86_V2 (SSE3, SSSE3, SSE4.1, SSE4.2, POPCNT, CX16, LAHF; see https://numpy.org/doc/stable/release/2.4.0-notes.html). The Athlon II X2 (K10) has SSE3, POPCNT and LAHF, but no SSSE3 and no SSE4.1/4.2, so it is v1.
- The cutoff is 2.4, not 2.0. NumPy 2.0-2.3 used an SSE3 baseline: **numpy 2.3.5 imports and passes all familia tests on qodesh (91 passed, 19 skipped).**
- `scripts/cpu_level.py` detects the level (`/proc/cpuinfo` flags, CPUID on Windows, sysctl on macOS). Non-x86 reports n/a. All three installers pick the numpy spec from the level alone: v0/v1 get `numpy<2.4`, everything else gets `numpy`. There are no OS-, host- or GPU-specific pins.
- numpy 2.4+ can still be built for v1 with `-Dcpu-baseline=none`. **Built 2026-10-10 on qodesh: numpy 2.5.3, MSYS2 ucrt64 gcc 16.2, `-Dcpu-baseline=none -Dcpu-dispatch=max -Dblas=none -Dlapack=none`, `CFLAGS=-mlong-double-64`** (`scripts/build_numpy_wheel.ps1`, wheel `numpy-2.5.3-cp312-cp312-win_amd64.whl` on the v0.1.0-rc2 release). It loads with a clean PATH (no MSYS2 DLLs needed) and reports baseline `[]`, dispatch found `[]`.
- Results in a throwaway venv (the user's numpy 2.3.5 untouched): familia's pytest 101 passed, 11 skipped, 0 failed (2 bash-dependent tests need Git's bash on PATH). numpy's own suite per file (`-m "not slow"`): linalg, random, lib, fft and ma all pass; most of `_core` passes (multiarray 14260 passed, 1 failed). **No illegal instruction (0xc000001d) anywhere.**
- **Caveat: long double math crashes (0xc0000005 access violation).** `np.longdouble` / `np.clongdouble` scalar `**`, `%`, `//`, `as_integer_ratio` and similar call mingw-w64's `*l` libm functions, which assume an 80-bit x87 long double, while `-mlong-double-64` (needed to match MSVC CPython) makes it 64-bit. This takes down test_array_coercion, test_numeric, test_scalarmath, test_scalar_methods, test_ufunc, test_umath and test_index_tricks partway. numpy itself warns "MINGW-W64 ... experimental". familia uses only float16/float32/float64/int, so this is acceptable for us; don't use the wheel for anything that uses longdouble. A real fix would be an MSVC (clang-cl) build, or numpy's npymath fallbacks instead of mingw's `*l` functions.
- Installers: `cpu_level.py --numpy-candidates` lists our wheel first when the level is v0/v1 **and** this Python's wheel tag matches (today only win_amd64-cp312), then `numpy<2.4`. The level alone decides whether the old-CPU path is taken; the tag only chooses which file. Each candidate is pip-installed and must `import numpy` before it counts.

## L-miryam-igpu. On miryam the iGPU loses to the CPU, even when it fits in RAM (2026-10-10)
A provisional guard killed any run that dropped free RAM below 3.5 GiB. That 3.5 GiB line is fuzzy guidance (see docs/ram-safety.md), so runs it killed were cautious stops, not proven unsafe. "delta" is how much free RAM fell during the run. Idle MemAvailable was only 3.7-4.2 GiB (desktop, Grok Bot app, other workers), so the room was 200-700 MiB.

| config | prompt t/s | generate t/s | RSS MiB | delta MiB | under 3.5 GiB? |
|---|---|---|---|---|---|
| SmolLM2-135M, CPU, -t 2 | 340 | **110** | 253 | 55 | no |
| SmolLM2-135M, iGPU, -lm mmap, ub 128 | 331 | 51 | 194 | 136 | no |
| SmolLM2-135M, iGPU, -lm none, ub 128 | 332 | 50 | 116 | 144 | no |
| embeddinggemma-2 Q8, CPU, -t 2 | 195 | - | 741 | 360 | no |
| embeddinggemma-2 Q8, iGPU (4 variants) | - | - | 209-504 | 362-545 | 3 of 4 killed |
| LFM2.5-1.2B, iGPU or partial offload, -lm none, q4_0 KV, ub 128 | - | - | 111 | 644-900 | killed |
| LFM2.5-1.2B or Qwen3.5-2B, CPU alone | - | - | 1283 / 1604 | 258-533 | killed |
| CPU model + SmolLM2 on the iGPU (both combos) | - | - | - | 107-199 | killed (3.54-3.58 GiB) |
| Qwen3.5-2B, CPU, -t 2, server, no speculation | - | 8.7 | - | - | within target, min 3.48 GiB |
| same, `--spec-type ngram-mod` | - | 16.3 | - | - | within target, min 3.43 GiB |
| same, `--spec-type ngram-simple` | - | **17.4** | - | - | within target, min 3.44 GiB |

- **`-lm none` (no mmap) and the iGPU:** with no mmap, process RSS drops (116 vs 194 MiB for SmolLM2), but the free-RAM delta is the same. The driver's copy replaces the page-cache copy and doesn't add to it. A smaller ubatch saves about 40 MiB.
- **Speed:** the HD 620 is about half the CPU's decode speed even on a 135M model. That's consistent with decode being memory-bound on the shared DDR4 and 15 W budget, though nothing measured bandwidth or power directly. Every iGPU role tested was slower than the same work on the CPU, and none of them fit the coder within the 3.5 GiB target. The useful roles left are background prompt or embedding work with a tiny model while the CPU is otherwise idle.
- **Clock cap:** gt_max_freq_mhz isn't writable without root, so a capped clock wasn't testable.
- **Speculation:** n-gram lookup costs no weights and no measurable RAM. It doubled decode on a copy-heavy prompt, which is the best case. `coder-ngram` in graph.yaml is now `ngram-simple` and stays `planned` until it's measured on real hermes edits. The three server runs bottomed out at 3.43-3.48 GiB free. That counts as **within** the fuzzy ~3.5 GiB target, not a violation.
- **Draft-model speculation:** Qwen3.5-0.8B as a draft would cost about 530 MiB more, which breaks the floor. Not run.

## L-kvq8. Quantized KV on the A57 is a loss, and llama-bench changes its table shape (2026-10-10)
- Quantized V cache requires flash-attn. With `-fa 0 -ctv q8_0` llama.cpp refuses to create the context.
- With `-fa 1`, q8_0 KV works but is slower at 135M on Xclipse 550: tg 69.5 vs 101.6 t/s, pp 1225 vs 1468. Keep f16 KV on phones unless ctx RAM forces it.
- The earlier "silent" q8_0 failure was mostly our parser: when the KV type isn't f16, llama-bench adds `type_k`/`type_v` columns, so fixed-column parsing dropped those rows. Use `-o csv`/`-o json` and parse by column name.
- Sustained 5 min tg128 on phone8 drifts from ~85 to ~75 t/s after ~4 min (mild throttle). Thermal zones aren't readable from Termux. `termux-battery-status` hangs without the Termux:API app (the pkg alone isn't enough).
- Identify phones by host key plus boot_id, not address. Termux sshd ignores the login name, so the user isn't a reliable identifier.

## L-memcap. Cap model servers with a user scope; earlyoom and zram need one sudo paste (2026-10-10)
- `scripts/serve.sh <node>` wraps llama-server in `systemd-run --user --scope` with MemoryHigh 2200M, MemoryMax 2600M, MemorySwapMax 0 and oom_score_adj 800. No root is needed. It's on by default on miryam; `FAMILIA_MEMCAP=0` turns it off. It was verified on miryam with a SmolLM2 server.
- On miryam, sudo needs a password, so earlyoom and zram wait for the user's paste block in docs/ram-safety.md.
- systemd-oomd was already active as an Ubuntu default. We didn't configure it.
- The old swap was a 16 MiB partition, and it was full.
- **Correction:** I earlier suspected that miryam suspends when idle. It doesn't. The idle sampler logged 60 samples at a steady 10 s over 10 minutes. The agent's "offline" drops come from the app connection; local jobs keep running.
- **Idle load (10 min, normal desktop use):** MemAvailable min / median / max 4119 / 4281 / 4330 MiB, page cache about 4.2 GiB, Shmem about 0.7 GiB, swap 16 MiB and full. Biggest processes: Grok Bot app 0.33-0.44 GiB (growing), snap-store 0.34, gnome-shell 0.19. Loading the coder (a short bench) took MemAvailable down to 3631 MiB, and after unload it recovered to 4211 MiB.
- **n-gram speculation on real edits** (memcapped server, -t 2, 4 hermes-style full-file rewrites, 400 tokens each): none 8.2-8.4, **ngram-simple 17.9-18.4** (2.2x), ngram-mod 17.5-18.0 tok/s. Every draft was accepted, because full-file rewrites are mostly copying. With the server running, MemAvailable bottomed out at 2.89 GiB. That's within the fuzzy guidance, and the scope cap held the server to 2.6 GiB.
- **Deployed after the user's sudo paste (13:40 PT):** earlyoom (prefers llama-*) and zram (zstd, 1.8 GiB). Idle with zram: MemAvailable 4026 / 4190 / 4216 MiB (min / median / max), zram unused. It's a cushion for spikes, not extra idle headroom. coder-ngram (ngram-simple) is now `active`. `scripts/bench_parse.py` reads llama-bench output by column name: column positions moved between builds, and positional awk read the wrong fields in the first sweep.

## L-wifi. The phone "drops" were Wi-Fi switched off, not sleep (2026-10-10)
- The repeated phone7/phone8 disappearances were caused by Wi-Fi being disabled on the phones, not by Android sleep or Doze. termux-wake-lock is still worth holding during runs, but it doesn't fix a radio that's off.
- When a phone pings but doesn't answer on its SSH port, Termux sshd isn't running (seen on phone7 at 16:20 PT). Run `sshd` in Termux. You can't start it remotely.
- Without the Termux:API app, nothing about power can be read on the A57 (Android 16): /sys/class/power_supply, /proc/loadavg and dumpsys are all denied. Install the app from github.com/termux/termux-api/releases, because add-ons must share GitHub Termux's signature.


## L-vkshm. Vulkan builds bloat shmem even with -ngl 0 (2026-10-10)
- On miryam, llama-server from llama-b11374-linux-x64-vulkan with `-ngl 0` still allocated about 1.83 GB of Vulkan host buffers in shared memory. Shmem counts against the familia memcap scope (MemoryHigh 2200M / MemoryMax 2600M), so the coder hit memory.high 31,678 times, PSI full was about 48%, and it stalled until it was killed.
- Restarting with `GGML_VK_VISIBLE_DEVICES=` (empty) fixed it: 0 memory.high events, about 1.18 GB used, about 3.0 GiB free.
- Fix: `scripts/serve.sh`, `hermes_harness.py` (via `validate_graph.server_env`) and code-bootstraps `scripts/serve.sh` export `GGML_VK_VISIBLE_DEVICES=` when the node's ngl is 0, unless it's already set. Windows `serve.ps1` is unchanged: PowerShell 5.1 can't hold an empty env var.

## L-escalation (2026-10-10): escalate on evidence, ask before crossing hosts

A slow heavy model on the same box (Qwen3.5-2B on qodesh, 0.91 t/s) is rarely
the best escalation target when a faster copy exists elsewhere (miryam coder,
17.4 t/s). Rank targets from measured registry speeds, not declaration order,
send a compact handoff instead of full history, and never auto-open a
cross-host edge without recorded consent (docs/escalation.md).

## HANDOFF — 2026-10-10
Credits cut mid-sprint. Public resume index: [`docs/HANDOFF.md`](docs/HANDOFF.md) (issues #39–#48, label `handoff-2026-10-10`). Offline commands: [`docs/offline-test-plan.md`](docs/offline-test-plan.md). Private transcript/ops: `brianreborn/familia-private` `logs/2026-10-10-familia-sprint.md` + `HANDOFF.md`.


## L-nvidia340. Legacy NVIDIA 340.108 driver on Linux 6.12 / CentOS Stream 10 (2026-10-17)

**Relevant repo:** [`brianreborn/nvidia-340.108-updated`](https://github.com/brianreborn/nvidia-340.108-updated)

This project adapts the legacy NVIDIA 340.108 driver (for GeForce 8600 GT / G84) to
build and install on Linux kernel 6.12 with DKMS, and documents the full display stack
for CentOS Stream 10.

### Key findings

- **DKMS build:** The upstream 340.108 source required patches to compile on 6.12.
  See the repo's `Makefile` and `dkms.conf` for details. `dkms install --force` was
  needed to override the existing `nvidia/615.71.09` entry.

- **CUDA driver test passed:** `cuInit(0) = 0`, `cuDeviceGetCount = 1`, device detected as
  "GeForce 8600 GT, Compute Capability 1.1, Total Memory: 255 MB". The legacy userspace
  stack was installed via `make post-install` (runs the `.run` installer with
  `--no-kernel-module --no-x-check --no-check-for-alternate-installs`).

- **GSP firmware warning is harmless:** The open-source `nvidia.ko` (from nvidia-615
  package) logs `NVRM: GPU ... not supported ... does not include the required GPU System
  Processor (GSP)`. This is expected — the G84 does not use GSP. Our DKMS module is what
  actually drives the card.

- **CentOS Stream 10 dropped native Xorg:** `xorg-x11-server-Xorg` is not available in
  any EL10 repo. GDM can only do Wayland (or Xwayland for legacy X11 apps). Trying to
  force Xorg mode in GDM causes a crash loop ("Session never registered, failing").

- **Weston (pixman renderer) works as a lightweight display:** GDM was masked; Weston
  14.0.1 runs as a user-level systemd service (`~/.config/systemd/user/weston.service`)
  with `--backend=drm --renderer=pixman` (software renderer — no EGL/Mesa required).
  `loginctl enable-linger` keeps it running at boot. Keyboard, mouse, and DRM output
  all detected correctly.

- **EGL / GBM not available out of box:** `weston --backend=drm` (hardware GL) fails with
  "EGL does not support gbm platform" until proper Mesa DRI is installed. The pixman
  fallback requires zero GPU support and is sufficient for a functional desktop when
  performance is not needed.

## L-memcg (2026-10-19): Memory caps and the OOM killer: what not to do

- **Don't set hard per-launch cgroup limits (`systemd-run -p MemoryMax`) from a measured peak +15%.** On a 23 GiB box with ~12 GiB available, the kernel memcg OOM killer killed engines using only ~65 MB, every minute. Evidence: `Memory cgroup out of memory ... CONSTRAINT_MEMCG` inside our own `run-*.scope`; systemd-oomd and earlyoom were inactive.
- **Don't use `MemorySwapMax=0` by default;** it removes the swap safety net.
- **Prefer headroom-based soft limits** (`MemoryHigh`, MemAvailable minus a reserve) and clean reclamation: unload the idle/lowest-priority model via API before any kill.
- **Before blaming RAM, read the kill line:** memcg constraint vs global OOM vs oomd/earlyoom tell different stories.
- **Don't oversubscribe CPU:** concurrent jobs whose summed `-t` exceeded the core count (load 15 on 4 cores) slowed launches and confused health checks. Use a fleet-wide thread budget.
- **Kill/watch scripts must be tested:** gawk reserves `log` as a builtin; a watcher that dies silently records nothing.
- **Unvalidated tight caps produce phantom "crashes"** indistinguishable from engine bugs. Classify every death (bad params / memcg cap / OOM / engine bug) before fixing.
- **Validated work isn't done until pushed and verified on origin/main.**

## L-model-neutral-improvement. Improvement eligibility is not a model role

Do not disable an improvement subsystem just because the selected model has a particular
role. If the user engages the subsystem, it should be available across model types; model
selection is a separate choice. Keep opt-in, consent and target-specific safety checks at
the subsystem boundary rather than using model metadata as a proxy for user intent.

## L-screen. Always start servers in screen so we can attach (2026-10-27)
Agents and automation must **never** start llama-server / familia graph servers in non-screen mode (`foreground`, `nohup`, bare background). Default is `DETACH_MODE=screen-attached` (starts attached; reattach with `screen -r familia-server`). Attaching is critical for ops on angel/Uriel and other desktop hosts. Override only when the operator explicitly asks.

## L-start-timeout. Do not wall-clock-fail slow model loads (2026-10-27)
`familia-graph` used to abort with “did not become ready within 240 seconds” while Nanbeige mmap-loaded under nightly I/O. Node ready-wait now defaults to **unlimited** (`FAMILIA_START_TIMEOUT=0`); it only fails if the child exits. Set a positive value only when you want a hard cap.

## L-server-tools. `--tools` is launch-only; git fix ≠ live argv (2026-10-27)

M0 empty llama-ui Server Tools was fixed in `15d67b1` by setting `angel-coder.server_tools: all` so `validate_graph --args` / `serve.sh` emit `--tools all`. **It came back after that commit** whenever angel-coder exited and the replacement process was started without that flag (crash + emergency hand-start, starting from a stale `generated/graph-*.yaml` that predates `server_tools` / omits `angel-coder`, or judging “fixed” from graph.yaml while the running argv still lacked `--tools`).

- **Symptom:** llama-ui Server Tools panel empty; `GET /tools` → 403 `feature_disabled`. `/v1/models` staying `capabilities:["completion"]` is normal and is not the check.
- **Why:** llama.cpp enables server tools only at process start. Graph YAML does not hot-patch a live or crashed server.
- **Prevent:** always start via `DETACH_MODE=screen-attached` + `start.sh` / `serve.sh` against **live** `graph.yaml` (not a stale `generated/graph-angel.yaml`). After every restart, confirm `ps` argv contains `--tools` and `GET http://127.0.0.1:<port>/tools` returns 200. Regenerate host graphs after schema changes. Do not hand-build llama-server argv without copying `validate_graph.py --args <node>` output.

## L-node-type. Node type implies capability; placement is host: (2026-10-27)

Early fleet `graph.yaml` used **host-prefixed unique node ids** (`angel-coder`,
`box-coder`, `miryam-pentest`, `qodesh-smol-cpu`, …). That was a fundamental design
error: the node **type/role** (coder, chat, embed, decision, pentest) should imply
what the node has; **placement** is the `host:` field (plus bind/port), not the key.

Schema today still uses a unique-key map, so one fleet file cannot hold two `coder`
entries. The operator path is **private topologies**:
`python3 scripts/generate_graph.py HOST` → `generated/graph-HOST.yaml` with
type-named nodes only (`coder`, `chat`, …) for that host. `start.sh --host HOST`
prefers that private graph (pass `--fleet` for the transitional fleet file).
`modify_graph.py --host HOST --assign-model coder=<models-key>` assigns by type
and syncs the matching fleet key when present.

Do not invent new host-prefixed node names. Prefer `role:` on nodes and private
graphs. Full fleet reshape (type+host identity without fake unique names) is the
follow-on schema change.


## L-box-archetypes. Form factor, not virtualization (2026-10-27)

Box/platform `hosts.*.kind` values are physical or dedicated form factors
(`desktop`, `phone`, `tablet`, `notebook`, `laptop`, `1U`/`2U`/`3U`, `console`,
`appliance`, `drone`, `watch`). They are **not** hypervisors — `vm` is obsolete
and fails loud. Each kind has a default graph shape in
`scripts/box_archetypes.py` (starter roles, reserve hint, transports); 
`generate_graph.py` applies that shape then overrides. 1U=small / 2U=medium /
3U=large server. Do not invent rack units for tower/desktop hosts.

## L-190. Rapid build coordination on #190 (2026-10-28)
Source: [#190](https://github.com/brianreborn/familia/issues/190), PRs #186/#187, cbl #46, tags.

1. **The issue became a dump.** Teammates posted long status, verify and review comments on #190, and each one restated blockers, PR tables and test commands. Commands that pointed at a tag that no longer exists (`v0.0.0-pre-alpha`) were left in older comments. Readers could not tell the current state without reading everything.
   *Rule:* the issue body is the single summary. One owner edits it in place (state, blockers, held PRs, test command). Comments are append-only evidence, and a third party folds them into the body afterward.
2. **Held PRs were merged.** #190 listed familia #186 and #187 and cbl #46 as "held for Brian". All three were merged at 11:38 PT (18:38 UTC) by the shared `brianreborn` account, within 15 seconds of each other. The shared account hides which agent did it. Nothing in GitHub enforced the hold, which lived only in a table in a comment.
   *Rule:* mark held PRs with a `held` label or a draft state, and never merge a PR that carries that label. Agents record their own name in the merge commit message.
3. **The tag was named without checking existing tags.** `v0.0.0-pre-alpha` was cut while both repos already had `v0.1.0`, so it sorted below an older release. It was renamed to `v0.2.0-pre-alpha` (same commits, familia 5ed49c7, cbl 2d7108e) and the old tag was deleted.
   *Rule:* run `git tag --sort=-v:refname | head` on every affected repo before naming a tag.
4. **Blockers were found late.** The following only surfaced in the fresh-clone test on the day of the build:
   - an undeclared host started nothing
   - `INSTALL_ACK=yes` ran `sudo apt-get` and did not accept licenses
   - a missing registry entry broke every declared host
   - the release JSON was still at b11669, which can't load lfm3

   *Rule:* run a fresh-clone install, unattended, on an unlisted host, with no sudo, before calling anything "testable". Keep it as a CI or swarm job.
5. **The failure baseline drifts.** pytest on main had 35 known failures (it had been 33), and they were accepted as "same as baseline" rather than fixed.
   *Rule:* track the baseline in an issue with the failing list. It may shrink but never grow, and a change to it must be called out.
6. **Box restarts lose work.** An end-to-end source-build run on the box was lost when the box restarted, so `BUILD=1` was not re-verified for the tag.
   *Rule:* write long runs' logs and results to a persistent path (familia-private or the repo) and not to scratch, and note what was not re-run.
