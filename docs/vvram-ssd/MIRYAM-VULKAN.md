# miryam Vulkan unstick (2026-10-26 PT)

MachineId `509c2b46-f11b-42c4-9f89-b2f43b827730`.

## Present
- `/dev/dri/card1` + `renderD128`
- Intel ICD: `/usr/share/vulkan/icd.d/intel_icd.json`
- **SmolLM2-135M-Instruct-Q4_0.gguf** at `~/models/` (sha `bcc3af2849ad6095af57e9b5cd43775256efdc66e306acb529172f92d0c04b03`, fetched 2026-10-26 ~21:00 PT)
- RAM ~7.1 GiB; often ~1.3–1.5 GiB available + swap in use — keep loads light

## Missing (blocks `miryam-gpu-decision` -ngl 99)
- **No vulkan `llama-server`** at `~/repositories/llama-vulkan-b11541/llama-b11541/llama-server` (graph `runtimes.llama-b11541-linux-vulkan`).
- edlm fork `~/llama-server__nace-ai__edlm/build/bin/llama-server` is not the graph vulkan runtime.

## Next
1. Restore `llama-b11541` ubuntu-vulkan-x64 under the repositories path above.
2. CPU smoke first; Vulkan `-ngl 99` only when MemAvailable ≳ 3 GiB.
3. `vulkaninfo` may need `vulkan-tools` (apt mirror flaky on box; on miryam install when convenient).
