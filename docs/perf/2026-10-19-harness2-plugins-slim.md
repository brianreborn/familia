# Harness² live + plugins + slim prompts (2026-10-19 PT)

Hosts: centos10-bigram (i5-4570 4C, 23 GiB). Issues #87, #89, #92.

## Weight file

| field | value |
|---|---|
| path | `LFM2.5-1.2B-Instruct-Q4_K_M.gguf` |
| architecture | lfm2 |
| context_length | 128000 |
| rope.freq_base | 1000000.0 |
| chat_template | present (1783 chars, jinja) |
| sampling | **missing in GGUF**; run used llama.cpp library defaults (`--default sampling=library-default`) |

Launch: `llama-server -c 8192 -np 1 -t 4 --alias coder --jinja` on loopback.

## Harness² (#87)

`scripts/harness2.py install` → pinned engine `1cfe254e8d25`.
`propose --target hermes-lab --enable --max-tasks 1` against the 1.2B endpoint
(see `/tmp/p1live.log` on the box; summary filled after the run). Mode stays
`off` in repo `graph.yaml`. Self-improve gate: no tools/plugins/pentest.

## Slimming (#89)

`scripts/measure_prompt.py` on this tree:

- harness2 base: 618 chars, ~154 tokens (chars/4)
- hermes lean: 5 toolsets, 5 aux tasks (dropped 9 unused)
- hermes full: 14 aux tasks

Coordinates with #85 lean toolsets + prompt-prefix cache; does not change cache.

## Plugins (#92)

`agents.hermes-lab.plugins: [rea]` → symlink
`~/.cache/familia/hermes-hermes-lab/plugins/rea` → `~/.hermes/plugins/rea`.
Fixture package used when the catalog install was not present; replace with
`hermes plugins install rea` (needs Node) for a real MCP server. Harness²
cannot add plugins.
