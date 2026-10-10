# Optional model scale-down

`scripts/scale_down.py` makes a smaller copy of a model that `graph.yaml` already
declares. It is **off unless configured**: a node is touched only if it has
`scale_down: {enabled: true, ...}`. It only wraps existing published tooling and
never invents or trains a compression method.

## Origin: Samsung LittleBit

The "13B model in under 1 GB" news (reposted Oct 8, 2026) is **LittleBit**, from
Samsung Research:

- Paper: arXiv [2506.13771](https://arxiv.org/abs/2506.13771), NeurIPS 2025
  ([proceedings PDF](https://proceedings.neurips.cc/paper_files/paper/2025/file/a917c1d57088897beba47f96b4fd7f3c-Paper-Conference.pdf)).
  It reaches 0.1 bits per weight (Llama2-13B under 0.9 GB) by factorizing weights
  into low-rank latent factors, binarizing those factors, and learning
  row, column, and latent scales.
- Code: [SamsungLabs/LittleBit](https://github.com/SamsungLabs/LittleBit), which also
  contains LittleBit-2 (ICML 2026, `--use_itq`).

The method needs quantization-aware training on a GPU, starting from Hugging Face
checkpoints. Its output is a factorized PyTorch layer, not a GGUF that llama.cpp can
load. So `backend: littlebit` exists as a placeholder and **refuses to run (TBD)**
until a CPU-loadable export exists.

## Backends (in order of preference)

| backend | what it does | needs |
|---|---|---|
| `published` | downloads an already-compressed GGUF (e.g. an existing IQ1_S/IQ2_XXS quant) from HF | `repo`, `file`, `sha256` (recommended), optional `revision` |
| `llama-quantize` | runs llama.cpp `llama-quantize`, optionally after `llama-imatrix` | `type`, `quantize_bin`; for IQ1_*/IQ2_*: `imatrix` or `calibration` + `imatrix_bin` |
| `littlebit` | TBD, refuses to run | none |

## Example

```yaml
nodes:
  coder:
    # ... the normal node fields ...
    scale_down:
      enabled: true
      backend: published
      repo: unsloth/Qwen3.5-2B-GGUF        # example; pin a real repo, file, and sha256
      file: Qwen3.5-2B-UD-IQ2_XXS.gguf
      sha256: <64 hex>
      output: ~/.local/share/gguf/models/coder/Qwen3.5-2B-IQ2_XXS.gguf
      suffix: iq2          # derived node is coder-iq2, aliases coder-iq2
      port: 9942
```

```
scripts/scale_down.py --graph graph.yaml [--node coder] [--dry-run] [--force] [--replace] [--out-graph graph.scaled.yaml]
scripts/validate_graph.py --graph graph.scaled.yaml
```

## Guarantees

- The original GGUF is never written. An `output` that equals the source is refused,
  and an existing output is refused unless you pass `--force`.
- The output arch must equal the node's `arch`, and the output must be smaller than
  the source.
- `<output>.scale-down.json` records the backend, the params (including calibration
  and imatrix sha256), the source sha256 and size, and the output sha256 and size.
- A derived node `<name>-<suffix>` with `derived_from: {node, sha256, manifest}` is
  written to `graph.scaled.yaml`. `graph.yaml` itself is never modified.
  `validate_graph.py` checks the derived node like any other node (RAM, ctx, runtime
  arch). It also fails if the file no longer matches the manifest, if the arch
  differs from the source node, or if the output isn't smaller than the source.
- With `--replace`, the scaled graph keeps only the derived node, not the original.

## Tests

`python3 -m unittest tests.test_scale_down -v` with `FAMILIA_TEST_GGUF`
(ggml-org/models `tinyllamas/stories15M.gguf`) and `FAMILIA_LLAMA_BIN` (a llama.cpp
release directory). `FAMILIA_TEST_PUB_SHA256` enables the network test for
`published`.
