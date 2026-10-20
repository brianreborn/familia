> **invalidated: memcg cap bug, rerun pending** (#95). Results gathered under per-launch cgroup caps of 1 GiB / peak+15% with swap 0; rerun via scripts/rerun_all.sh.

# hermes fixed prompt on small nodes (#85), 2026-10-19

miryam coder: Qwen3.5-2B Q4_K_M, exact `validate_graph.py --args coder` (`-t 3 -lm none -c 65536 -ctk/-ctv q8_0 -fa on`), nice 19 / ionice idle, RSS watchdog 3500 MiB, `GGML_VK_VISIBLE_DEVICES=` as serve.sh sets it.
- GGUF metadata was validated before each run (`bench_guard`): qwen35, ctx 262144, rope freq_base 1e7, gpt2 tokenizer, 7816-char template.
- The header has no `general.sampling.*`. The serve.sh card sampling was used, and test requests ran at temperature 0, top_k 1, seed 1.
- The desktop was busy throughout (load avg 4-7), so these are 1 rep each and the numbers are coarse.

## Where the tokens go (Qwen3.5 tokenizer, rendered with the node's chat template)

| part | tokens |
|---|---|
| 27 tool schemas (cli toolsets, both `--graph` and `--model` modes) | 11,103 |
| top 4: session_search 1382, delegate_task 1333, terminal 1258, browser_* (10 tools) 1444 | |
| system prompt, stable part (identity, guidance, environment probe) | 1,414 |
| system prompt, volatile part (date, model line) | 19 |
| skills index, memory, user profile, AGENTS.md | 0 |
| **total before the first user message** | **12,553** |

The two modes differ by 4 tokens (the model line).
- The Qwen template puts `<tools>` before the system text.
- The only per-session text is the date/model line at the end, plus one bug: hermes' "Python toolchain:" environment-probe line inside the stable part changed between two launches minutes apart (pip detection). It ends up mid-prompt, after the tools.

## Changes

- **Lean profile:** `agents.<a>.prompt_profile` (auto|lean|full). auto picks lean on phones and on hosts with less than 8 GiB.
  - Lean keeps the toolsets terminal, file, todo, clarify and skills (11 tools). It only narrows the user's own list and never adds a toolset. disabled_toolsets is untouched.
  - The long guidance stays reachable on demand through `skills_list` / `skill_view`.
  - On miryam this cuts the prompt to 7,162 tokens (8.4k chars of system text plus 21.5 KB of tools).
- **Persistent prompt cache:** a node can set `slot_save: true`, which passes `--slot-save-path ~/.cache/familia/slots/<node>`. After the server comes up, hermes.sh calls `scripts/prompt_cache.py`, which:
  - asks hermes offline (inside its snap environment) for the system prompt and tools;
  - renders them with the node's own template and keeps the byte-stable part, cut before the volatile text and before the probe line, minus one token;
  - restores `prefix-<sha>.bin` (62-68 MB) if it exists, or else prefills once and saves it.
  - Any failure only costs speed.
  - The module imports neither hermes nor Harness².
- **Cache reuse within a server (#16) works:** turns 2-3 hit 6,374-12,617 cached tokens, with prompt_n 32-72.

## TTFT on miryam

| run | turn 1 | turn 2 | turn 3 |
|---|---|---|---|
| full prompt, cold server (12,564 tokens) | **1,068 s** | 7.9 s | 6.6 s |
| lean, cold, no cache file (6,378 tokens) | 335 s | 3.4 s | 5.9 s |
| lean, after restart, prefix restored from disk (6,359 restored, prompt_n 19) | **1.5 s** | 4.2 s | 3.6 s |
| real `hermes.sh -- -z ...` (graph mode, lean), first-ever launch: prefix prefill + save 650 s, then first request prefilled 559 tokens (40 s) | ~13 min wall | | |
| real hermes.sh after a restart: restore 6,815 tokens in 1.4 s, first request prefilled 373 tokens (22.6 s) | **~24 s to first reply** | | |

The cache file is written once per host and prompt content. The first ever launch on a host still pays the lean prefill (about 6-11 min on miryam), once.

**Tool calls.** hermes ran the terminal tool through familia (graph mode, lean profile) and returned the command's output in all three launches: `familia-tool-ok-first`, `-restart`, `-first`. Pentest roles were not used or exercised.

**Harness².** It sends its composed harness text with no tool schemas. It is unaffected by the lean profile (the profile is in hermes_harness only).

Raw logs: familia-private `logs/2026-10-19-hermes-prompt/`.
