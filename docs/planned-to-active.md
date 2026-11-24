# Planned → active (P0, 2026-11-22)

Brian, 2026-11-22: "planned is now actively required, it's priority 0." Every node in
`graph.yaml` that was `status: planned` on main `292859e` is now `status: active`. Where a node
cannot actually run yet, it stays active (required) and its missing artifact is listed below:
nothing is faked (no invented sha, no registry `weights: present` without a fetch).

The guardian / pentest / defender seats were flipped in a separate commit; Brian confirmed
them on 2026-11-22.

## Node table

| node | host | model (GGUF) | runtime | aliases | was asserted planned by | missing before it really runs |
|---|---|---|---|---|---|---|
| cpu-smol-decision | qodesh | SmolLM2-135M-Instruct.Q4_0 | llama-b11540-win-cpu | — | test_graph_types (smollm2 catalog) | qodesh online; model sha256 is `unmeasured`; Windows runtime is legacy b11540 (b12359 Windows archive untested, see known-issues) |
| vulkan-igpu-decision | miryam | SmolLM2-135M-Instruct-Q4_0 | llama-b11541-linux-vulkan | safe-build (direct-only) | test_graph_types (phone7 vulkan) | nothing new; legacy b11541 Vulkan prebuilt kept (move to b12359 Vulkan after a measured run) |
| vulkan-handset-decision | phone7 | SmolLM2-135M-Instruct-Q4_0 | termux-llama-cpp-0.6.0 | — | test_graph_types | phone7 online with Termux pkg; no flag table for the Termux pkg build |
| vulkan-handset-general | phone8 | Qwen2.5-0.5B-Instruct-Q4_K_M | termux-llama-cpp-0.6.0 | — | (none) | phone8 online with Termux pkg; no flag table for the Termux pkg build |
| embed | miryam | embeddinggemma-2-Q8_0 | **llama-b12359** (was llama-b11944) | embed | test_start_graph (#38 deferral) | b12359 runtime installed on miryam (`install/linux/install.sh`); GGUF on miryam; RAM beside the coder unmeasured (#38) |
| fleet-guardian | miryam | Dolphin3.0-Llama3.1-8B-abliterated.Q2_K | **llama-b12359** (was llama-b11944) | guardian, pentest, defender (never routed) | test_activate_guardian_weights, test_graph_types, test_node_role_private | GGUF not fetched: registry `weights: absent (damp)`; `validate_graph` refuses the node until fetched + sha measured |
| freebsd-guardian | angel | Dolphin3.0-Llama3.1-8B-abliterated.Q2_K | llama-b11669-freebsd (build b12359) | — (private key `guardian`) | test_activate_guardian_weights, test_node_role_private | same GGUF missing on angel |

`pentests.fleet` and `pentests.freebsd-guardian` are active too. Their seatbelts are unchanged:
`tools.allow: []`, `launch_test_only: true`, `requires_operator_confirm: true`.

Excluded: `nanbeige-chat` (Nanbeige4.3-33B on angel) stays planned and is not part of this change; 33B models are too slow for the available memory.

## Fail-closed rules kept

To park or re-enable these seats locally without editing `graph.yaml`, use
[security levels](security-levels.md): `familia security off | guardian | pentest | full`.


- `familia start` never launches a guardian / pentest / defender node, even when active. They start
  only through the operator path: `FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start`.
- Their gateway aliases (`guardian`, `pentest`, `defender`) are listed as omitted, never routed.
- No node has them in `escalates_to` or `tool_route`; the validator still rejects that.
- Decision-role nodes (e.g. `safe-build` → `vulkan-igpu-decision`) are active but direct-only: reach them
  on their own port; the gateway lists the alias as omitted instead of refusing to start.

## Runtime baseline

The repo's real llama.cpp pin is **b12359** (llama.cpp v1.0.0): the Linux installer prebuilt, the FreeBSD
source build, README and pins. `b12609` appears only as an example in LESSONS-LEARNED; no installer,
pin or runtime entry carries it. This change adds `runtimes.llama-b12359` (upstream commit `b1b770d`)
with its flag table `registry/llama-builds/b12359.json`, and moves embed and fleet-guardian onto it.
The active `coder` stays on `llama-b11944` (its pins are tested separately). Renaming
`llama-b11669-freebsd` (already build b12359) is left for a follow-up to avoid colliding with open PRs.

## Not nodes (left as is)

`speculative.coder-draft` (only one active speculative per target; `coder-ngram` is active),
`speculative.nanbeige-ngram`, and `kv_channels.coder-self` (experimental placeholder; its build
and slot ctx differ) are still planned. They are not graph nodes.
