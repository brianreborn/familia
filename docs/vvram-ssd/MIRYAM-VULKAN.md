# miryam Vulkan unstick (2026-10-26 PT probe)

MachineId `509c2b46-f11b-42c4-9f89-b2f43b827730` (connected).

## Present
- `/dev/dri/card1` + `renderD128`
- Intel ICD: `/usr/share/vulkan/icd.d/intel_icd.json` → `libvulkan_intel.so` (API 1.4.335)
- Also haswell-era `intel_hasvk_icd.json`
- RAM ~7.1 GiB, ~1.4 GiB available at probe (busy desktop)

## Missing (blocks `miryam-gpu-decision` -ngl 99 hang)
- **No `SmolLM2-135M*.gguf`** under `~/.local/share/gguf/models/` or `code-bootstraps-llama.cpp/models/` (only hf-meta + registry JSON). Decision symlink is `Laya-Q8_0.gguf`, not SmolLM.
- **No vulkan `llama-server` tree** under `code-bootstraps-llama.cpp/bin/` (empty/absent). Only found `/home/green/llama-server__nace-ai__edlm/build/bin/llama-server` (edlm fork — not the graph vulkan runtime).

## Next (when fetching)
1. Restore `llama-b11374-linux-x64-vulkan` or `llama-b11539-linux-x64-vulkan` per graph `runtimes`.
2. Fetch SmolLM2-135M Q4_0/Q4_K_M into path for `models.smollm2-135m-q4-miryam`.
3. Short smoke: `-ngl 99` vs CPU (expect Vulkan slower on HD 620 historically — still hang for coverage).
4. `vulkaninfo` may need packages; ICD file readable without sudo. If `vulkan-tools` needs sudo — blocker noted, do not stall angel/nvso work.
