#!/usr/bin/env bash
# add-model.sh: register a model in code-bootstraps-llama.cpp/config/models-manifest.json
# and models-preset.ini. Thin wrapper; the logic is scripts/add_model.py (stdlib only).
#   add-model.sh DIR                 Hugging Face snapshot dir (card, config, GGUFs, aux models)
#   add-model.sh FILE.gguf           a lone GGUF (role inferred)
#   add-model.sh ROLE FILE.gguf      legacy form
#   add-model.sh --help              every flag (--role/--type, --aux KIND=PATH, --dry-run, --fetch ...)
# Model database requirement: REQUIREMENTS.md "Model database" (#51).
set -euo pipefail
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || { echo "add-model.sh: $PY not found" >&2; exit 1; }
exec "$PY" "$HERE/add_model.py" "$@"
