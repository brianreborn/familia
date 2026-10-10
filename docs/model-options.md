# Model options (not yet placed)

Models listed here are options for the graph. None is placed on a host or
served by default. Each entry records which runtime branch actually supports
it, since familia can deploy several llama.cpp branches and non-llama runtimes
side by side.

## tencent/Youtu-Parsing-Omni

- Role: vision / parsing (documents, images, charts, flowcharts, geometry, audio, video to structured JSON)
- Size: ~5B params, bf16 safetensors ~10.7 GB; revision `01f7e3e`
- Architecture: `YoutuVITAForCausalLM` (`youtu_vita`, custom code)
- License: other (`youtu-parsing`, see the model repo LICENSE)
- Context: config says 1,048,576 positions; usable context not verified
- Runtime support (checked 2026-10-09):
  - llama.cpp b11374 (pinned): no
  - llama.cpp upstream master: no (no youtu converter)
  - llama.cpp forks: none known
  - GGUF: none for Omni (`wangjazz/youtu-parsing-gguf` is the older non-omni model)
  - Works with: transformers (`trust_remote_code=True`) or vLLM plus Tencent's plugin, https://github.com/TencentCloudADP/youtu-parsing
- Placement: needs a non-llama runtime node. bf16 at ~11 GB will not fit miryam (7 GB RAM).
- Catalog: `code-bootstraps-llama.cpp` `config/models-manifest.json` key `unplaced_options`
