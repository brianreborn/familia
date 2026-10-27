# harness/

`base/` is the generic starting harness for Harness² targets whose own prompt files do not exist
yet (docs/harness2.md). Layout follows Harness²'s component tree; familia applies only
`systemprompt.md`, `guardrails.md`, `LongTermMEMORY.md` and `skills/<name>/SKILL.md`.
`tool_descriptions/tool_guidance.md` is shown to the editor but frozen.

`safe-build/` is the tiny **build helper** prompt (deps + cmake/ninja/pkg help across
Linux/Termux/FreeBSD/Windows). It is not a Harness² target and is not loaded by
hermes (hermes needs 64K). Use it with the graph alias `safe-build` /
`docs/safe-mode-bootstrap.md`. The weights identity in the pinned
code-bootstraps component is **Laya-Q8_0.gguf** (decision/route); the chat face
is SmolLM2-135M via `miryam-gpu-decision`.
