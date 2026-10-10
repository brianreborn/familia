# LESSONS-LEARNED.md

> **Status note (2026-10-09):** earlier content was a coding agent's private session notes (artifact paths, tool names) and claimed files and regression tests that did not exist. It has been replaced with project lessons.

## L1. Renames leave a long tail (#16)
Renaming feeldznutts → familia left the installer, docs, log prefixes and the logo pointing at the old name. Grep for the old name in code *and* docs, and replace assets in the same change.

## L2. Agent context must match the server slot (#19)
hermes-agent with compression off sent ~18–21k-token requests to a 16,384-token `coder` slot and looped on HTTP 400. Fix: declare both in `graph.yaml`, require `context_length` == per-slot ctx, and launch hermes through `scripts/hermes.sh` with compression on.

## L3. Escaped quotes break shell scripts silently (#14)
A stray `\"` left `android_start.sh` unparseable. Run `sh -n` / shellcheck in CI.

## L4. Never pack a small host's RAM (2026-10-09)
miryam (7 GiB) hard-hung when the 64k coder server, an embed test and a compaction self-test ran together. Keep `reserve_ram_mib: 3072`, ~2 GiB free after estimates, and one heavy process at a time. See `docs/ram-safety.md`.

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

