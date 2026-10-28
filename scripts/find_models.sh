#!/bin/sh
# find_models.sh: guided "Find more models" flow for the gum home.
# Asks what the user wants, suggests HF repos, then runs a real fetch (confirm OK).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
YES=0
GUM=$(command -v gum || true)

say() { printf 'find-models: %s\n' "$*"; }
die() { printf 'find-models: error: %s\n' "$1" >&2; exit "${2:-1}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    -h|--help)
      printf 'Usage: sh scripts/find_models.sh [--yes]\n'; exit 0 ;;
    *) die "unknown arg $1" 2 ;;
  esac
  shift
done

can_prompt() { [ -t 0 ] && [ "${FAMILIA_NO_TTY:-}" != 1 ]; }

choose() {
  # choose HEADER opt1 opt2 ... → prints choice
  header=$1; shift
  if [ -n "$GUM" ] && can_prompt; then
    gum choose --header "$header" "$@"
  elif can_prompt; then
    printf '%s\n' "$header" >&2
    i=1
    for o in "$@"; do printf '  %d) %s\n' "$i" "$o" >&2; i=$((i+1)); done
    printf 'Choice [1]: ' >&2
    read -r n || return 1
    [ -z "$n" ] && n=1
    i=1
    for o in "$@"; do
      [ "$i" = "$n" ] && { printf '%s\n' "$o"; return 0; }
      i=$((i+1))
    done
    return 1
  else
    printf '%s\n' "$1"
  fi
}

confirm() {
  [ "$YES" = 1 ] && return 0
  if [ -n "$GUM" ] && can_prompt; then
    gum confirm "$1"
  elif can_prompt; then
    printf '%s [y/N] ' "$1" >&2
    read -r a || return 1
    case "$a" in y|Y|yes|YES) return 0 ;; esac
    return 1
  else
    return 1
  fi
}

# Ensure protomodel tip is available (best-effort; never a gate).
if command -v curl >/dev/null 2>&1; then
  if ! curl -sf --connect-timeout 1 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 \
     && { rc=0; python3 "$ROOT/scripts/familia_auth.py" probe >/dev/null || rc=$?; [ "$rc" != 4 ] || say "the :9931 server rejects our API key (see above); not starting another one"; [ "$rc" = 3 ]; }; then
    say "protomodel not up yet — starting chat helper in background (optional)…"
    sh "$ROOT/scripts/proto_chat.sh" --no-start >/dev/null 2>&1 || true
    # Don't block on start; fetch works without the chat server.
  fi
fi

GOAL=$(choose "What do you want the next model for?" \
  "Coding / agents" \
  "Everyday chat" \
  "Phone / tiny (≤1B)" \
  "Vision / images" \
  "Cancel") || GOAL="Cancel"

case "$GOAL" in
  Cancel|"") say "Cancelled."; exit 0 ;;
  "Coding / agents")
    REPO="Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
    QUANT="Q4_K_M"
    HINT="Strong local coder; ~4–5 GB Q4_K_M."
    ;;
  "Everyday chat")
    REPO="Qwen/Qwen2.5-3B-Instruct-GGUF"
    QUANT="Q4_K_M"
    HINT="Balanced chat; fits most laptops."
    ;;
  "Phone / tiny (≤1B)")
    REPO="HuggingFaceTB/SmolLM2-360M-Instruct-GGUF"
    QUANT="Q4_K_M"
    HINT="Phone / Termux friendly."
    ;;
  "Vision / images")
    REPO="ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"
    QUANT="Q4_K_M"
    HINT="Multimodal VL; needs a vision-capable runtime."
    ;;
esac

say "$HINT"
say "Suggested HF repo: $REPO  quant: $QUANT"
say "(You can edit the repo/quant when prompted next.)"

if [ -n "$GUM" ] && can_prompt; then
  REPO=$(gum input --header "Hugging Face repo ORG/NAME[@REV]" --value "$REPO")
  QUANT=$(gum input --header "Quant" --value "$QUANT")
elif can_prompt; then
  printf 'HF repo [%s]: ' "$REPO" >&2
  read -r r || true
  [ -n "${r:-}" ] && REPO=$r
  printf 'Quant [%s]: ' "$QUANT" >&2
  read -r q || true
  [ -n "${q:-}" ] && QUANT=$q
fi

[ -n "$REPO" ] || die "need a repo" 2

say "Will run a REAL fetch (downloads weights; license prompt applies):"
say "  scripts/add-model.sh --fetch $REPO --quant $QUANT"
if confirm "Fetch $REPO ($QUANT) for real?"; then
  scripts/add-model.sh --fetch "$REPO" --quant "$QUANT"
else
  say "Skipped fetch. Talk to the protomodel for other suggestions, or rerun Find more models."
fi
