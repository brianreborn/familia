# Offline test plan (no Grok Bot)

Run locally on the target host. Prefer **coarse binary search**: test ends + midpoint of each setting with one short run; keep the better half; only increase reps/tokens when two options are within noise. Label registry notes `coarse` / `binary-search`.

## Prerequisites
- `git pull` familia main + matching code-bootstraps pin (`pins.txt`).
- One heavy llama-server at a time on miryam; earlyoom + zram recommended (#43 for disk swapfile).
- For `-ngl 0` on Vulkan runtimes, confirm empty `GGML_VK_VISIBLE_DEVICES` (#40).

## A. Prompt-cache reuse (#41 / code-bootstraps #16)
```bash
# start coder (or resident) with default cache-ram — no CACHE_RAM override
./scripts/serve.sh coder   # or your node launcher
# same ~2k-token prompt twice; expect faster PP / no "skipping" cache warning on turn 2
# control: CACHE_RAM=0 should re-process fully
```

## B. Hermes compaction (#42)
```bash
./scripts/hermes.sh --selftest-compaction
# expect PASS
```

## C. Vulkan ngl0 shmem (#40)
```bash
# node with gpu_layers: 0 using Vulkan runtime
# check: env GGML_VK_VISIBLE_DEVICES is empty; memory.high == 0 under memcap; ~1.2GB class RSS
```

## D. Escalation proxy unit + dry hermes (#39)
```bash
python3 -m pytest tests/test_escalation.py tests/test_escalation_proxy.py -q
# live (needs hermes-agent): pass --light to a node that has escalates_to
python3 scripts/hermes_harness.py --escalate --light <light-node>
# cross-host needs consented tunnel; binds are 127.0.0.1
```

## E. qodesh-resident (#44)
```powershell
# Windows: start qodesh-resident; one completion; then co-run with GPU SmolLM2; watch free RAM
```

## F. Pre-existing failures (#45, closed)
```bash
python3 -m pytest tests/ -q --tb=line  # only test_ram_safety::test_overcommit_is_hard_error is expected to fail
```

## G. Old-device smoke (#48)
lowram profile + confirm no illegal-instruction on numpy/llama binary; one short completion.
