#!/bin/sh
# proto_chat.sh: interactive REPL against the familia protomodel (tiny local chat).
# Prefers an already-running OpenAI-compatible endpoint; starts bootstrap if none.
# Usage: sh scripts/proto_chat.sh [--url URL] [--model NAME] [--no-start]
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}

# OSC 7501 status (#123); soft-fail if absent.
_proto_osc_ready=0
_proto_osc() {
  if [ "$_proto_osc_ready" != 1 ] && [ -f "$ROOT/scripts/osc7501.sh" ]; then
    # shellcheck disable=SC1091
    . "$ROOT/scripts/osc7501.sh"
    _proto_osc_ready=1
  fi
  command -v osc7501_emit >/dev/null 2>&1 || return 0
  osc7501_emit "$@" --app familia 2>/dev/null || true
}

URL="${FAMILIA_PROTO_URL:-}"
MODEL="${FAMILIA_PROTO_MODEL:-}"
NO_START=0
BOOT_PID=""

usage() {
  cat <<'USAGE'
Usage: sh scripts/proto_chat.sh [--url URL] [--model NAME] [--no-start]

Talk to the familia protomodel (tiny local chat). Detects a local server
(green-roomz :8080, bootstrap :9931, or FAMILIA_PROTO_URL). Starts
./start.sh --bootstrap when nothing is listening (unless --no-start).

Quit with an empty line, /q, /quit, or exit.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL=${2-}; shift ;;
    --model) MODEL=${2-}; shift ;;
    --no-start) NO_START=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'proto-chat: unknown arg %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say() { printf 'proto-chat: %s\n' "$*"; }
die() { _proto_osc error --id home/proto --msg "$1"; printf 'proto-chat: error: %s\n' "$1" >&2; exit "${2:-1}"; }

probe() {
  # probe URL — 0 if /v1/models answers
  u=$1
  "$PY" - "$u" <<'PY' 2>/dev/null
import sys, urllib.request
url = sys.argv[1].rstrip("/") + "/v1/models"
try:
    with urllib.request.urlopen(url, timeout=1.5) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

pick_model() {
  # pick_model URL [hint] — print a model id
  u=$1; hint=${2:-}
  "$PY" - "$u" "$hint" <<'PY'
import json, sys, urllib.request
url = sys.argv[1].rstrip("/") + "/v1/models"
hint = (sys.argv[2] or "").strip()
prefer = ["general-text", "general-text-speculator", "chat", "safe-build", "miryam-gpu-decision"]
try:
    with urllib.request.urlopen(url, timeout=3) as r:
        data = json.load(r)
except Exception as e:
    print("", end="")
    sys.exit(0)
ids = [m.get("id") or m.get("name") or "" for m in (data.get("data") or [])]
ids = [i for i in ids if i]
if hint and hint in ids:
    print(hint); sys.exit(0)
for p in prefer:
    for i in ids:
        if p in i:
            print(i); sys.exit(0)
print(ids[0] if ids else "")
PY
}

find_endpoint() {
  if [ -n "$URL" ]; then
    if probe "$URL"; then
      printf '%s\n' "$URL"
      return 0
    fi
    return 1
  fi
  for cand in \
      "http://127.0.0.1:8080" \
      "http://127.0.0.1:9931" \
      "http://127.0.0.1:8187"; do
    if probe "$cand"; then
      printf '%s\n' "$cand"
      return 0
    fi
  done
  return 1
}

start_bootstrap() {
  [ "$NO_START" = 1 ] && die "no local chat server and --no-start set" 1
  BACKEND=""
  if [ -f "$ROOT/code-bootstraps-llama.cpp/start.sh" ]; then
    BACKEND="$ROOT/code-bootstraps-llama.cpp/start.sh"
  elif [ -f "$ROOT/../code-bootstraps-llama.cpp/start.sh" ]; then
    BACKEND="$ROOT/../code-bootstraps-llama.cpp/start.sh"
  elif [ -f "$ROOT/start.sh" ]; then
    say "starting bootstrap via ./start.sh --bootstrap (detached)…"
    # Overlap: free-download first-try models while bootstrap reactor comes up.
  if [ -f "$ROOT/scripts/prefetch-first-models.sh" ]; then
    printf 'proto-chat: PREFETCHING ORDNANCE (models) in background…\n' >&2
    sh "$ROOT/scripts/prefetch-first-models.sh" --background >/dev/null 2>&1 || true
  fi
  ( cd "$ROOT" && nohup sh ./start.sh --bootstrap >"$ROOT/.cache/proto-bootstrap.log" 2>&1 & echo $! >"$ROOT/.cache/proto-bootstrap.pid" ) || true
    BOOT_PID=$(cat "$ROOT/.cache/proto-bootstrap.pid" 2>/dev/null || true)
    return 0
  fi
  if [ -n "$BACKEND" ]; then
    say "starting code-bootstraps at $BACKEND …"
    mkdir -p "$ROOT/.cache"
    ( cd "$(dirname "$BACKEND")" && nohup sh "$(basename "$BACKEND")" >"$ROOT/.cache/proto-bootstrap.log" 2>&1 & echo $! >"$ROOT/.cache/proto-bootstrap.pid" ) || true
    BOOT_PID=$(cat "$ROOT/.cache/proto-bootstrap.pid" 2>/dev/null || true)
  else
    die "no chat server on :8080/:9931 and no start.sh / code-bootstraps to launch. Run: ./start.sh --bootstrap  OR  bring up green-roomz on :8080" 1
  fi
}

wait_ready() {
  i=0
  while [ "$i" -lt 60 ]; do
    if ep=$(find_endpoint); then
      URL=$ep
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  return 1
}

SYSTEM_PROMPT='You are the familia protomodel — a tiny local helper that runs on this machine.
Help with local install and build (deps, licenses, configure, PATH).
Help the user explore which larger models to fetch next (coding, chat, phone, vision).
Help search the user'\''s X/Twitter posts when Agent-Reach / twitter-cli is available.
Keep answers short and actionable. Prefer one next command. Never claim cloud access you do not have.'

if ! URL=$(find_endpoint); then
  say "no local OpenAI-compatible server detected"
  start_bootstrap
  say "waiting for server…"
_proto_osc working --id home/proto --msg "waiting for local chat server" --progress 10
  wait_ready || die "server did not become ready (see .cache/proto-bootstrap.log)" 1
fi

[ -n "$MODEL" ] || MODEL=$(pick_model "$URL" "${FAMILIA_PROTO_MODEL:-}")
[ -n "$MODEL" ] || MODEL=general-text

say "endpoint $URL  model $MODEL"
_proto_osc working --id home/proto --msg "Talk to the protomodel ($MODEL)" --title "proto_chat"
say "type a message (empty /q /quit /exit to quit)"
printf '\n'

while true; do
  if [ -t 0 ] && [ "${FAMILIA_NO_TTY:-}" != 1 ]; then
    printf 'you> '
  fi
  if ! IFS= read -r line; then
    break
  fi
  case "$line" in
    ""|/q|/quit|/exit|exit|quit) say "bye"; _proto_osc done --id home/proto --msg "proto chat ended"; break ;;
  esac
  reply=$("$PY" - "$URL" "$MODEL" "$SYSTEM_PROMPT" "$line" <<'PY' 2>/tmp/proto-chat.err || true
import json, sys, urllib.request, urllib.error
url, model, system, user = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
body = {
    "model": model,
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ],
    "temperature": 0.7,
    "max_tokens": 512,
    "stream": False,
}
req = urllib.request.Request(
    url.rstrip("/") + "/v1/chat/completions",
    data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
except Exception as e:
    print(f"(error talking to {url}: {e})", file=sys.stderr)
    sys.exit(1)
choices = data.get("choices") or []
if not choices:
    print("(empty reply)", end="")
    sys.exit(0)
msg = choices[0].get("message") or {}
print((msg.get("content") or "").strip() or "(empty reply)", end="")
PY
)
  if [ -z "$reply" ]; then
    if [ -s /tmp/proto-chat.err ]; then
      printf 'proto> %s\n' "$(cat /tmp/proto-chat.err)"
    else
      printf 'proto> (no reply)\n'
    fi
  else
    printf 'proto> %s\n\n' "$reply"
  fi
done
