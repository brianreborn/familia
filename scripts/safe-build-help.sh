#!/bin/sh
# Print the safe-mode build-helper pin and how to reach it. Starts nothing.
# See docs/safe-mode-bootstrap.md and harness/safe-build/systemprompt.md.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

usage() {
  cat <<'USAGE'
Usage: sh scripts/safe-build-help.sh [-h|--help]

Print the pinned safe-mode build-helper GGUF (Laya) and how to get deps/build
help. Starts nothing.

Example:
  sh scripts/safe-build-help.sh
  familia run setup.safe-build

Docs: docs/safe-mode-bootstrap.md
USAGE
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac

cat <<'TXT'
familia safe-mode build helper
==============================

Pinned GGUF (code-bootstraps-llama.cpp decision / route):
  Laya-Q8_0.gguf
  ggml-org/Laya-GGUF @ da4b4753d62197659d8c90103cd4c43bef9afea6
  sha256: c06528c5746d3bb8baa72a27938be95abbfd0b226f8471e8a9e365ed0bb066d2
  (~449 MB Q8_0; POST /v1/systemone — routing, not chat)

Chat face for deps/build Q&A (familia graph):
  alias safe-build → node miryam-gpu-decision (SmolLM2-135M-Instruct Q4_0)
  prompt: harness/safe-build/systemprompt.md

Next steps:
  1) sh install/deps.sh --install [--profile build]   # or menu setup.deps
  2) ./start.sh --bootstrap                           # code-bootstraps router
  3) Graph gateway: use alias "safe-build" once miryam-gpu-decision is active

Docs: docs/safe-mode-bootstrap.md
Home: pinned code-bootstraps-llama.cpp (pins.txt) — not a parallel familia stack.
TXT
if [ -f "$ROOT/harness/safe-build/systemprompt.md" ]; then
  echo
  echo "---- harness/safe-build/systemprompt.md ----"
  cat "$ROOT/harness/safe-build/systemprompt.md"
fi
