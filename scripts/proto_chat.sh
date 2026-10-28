#!/bin/sh
# proto_chat.sh: interactive REPL against the familia protomodel (tiny local chat).
# Prefers an already-running OpenAI-compatible endpoint; starts bootstrap if none.
# Usage: sh scripts/proto_chat.sh [--url URL] [--model NAME] [--no-start]
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
export FAMILIA_SCRIPTS="$ROOT/scripts"

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

Waits for the server with readiness polling (/v1/models, then the router's
/models status of the chat model), printing progress. FAMILIA_PROTO_WAIT=SECONDS
sets the ceiling (default 1800, 3600 on Android/Termux or <=2 cores; 0 = no limit).
FAMILIA_PROTO_REPLY_TIMEOUT (default 900) bounds one reply.

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
import os, sys, urllib.request
sys.path.insert(0, os.environ["FAMILIA_SCRIPTS"]); import familia_auth
url = sys.argv[1].rstrip("/") + "/v1/models"
try:
    with familia_auth.open_url(url, timeout=1.5) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

pick_model() {
  # pick_model URL [hint] — print a model id
  u=$1; hint=${2:-}
  "$PY" - "$u" "$hint" <<'PY'
import json, os, sys, urllib.request
sys.path.insert(0, os.environ["FAMILIA_SCRIPTS"]); import familia_auth
url = sys.argv[1].rstrip("/") + "/v1/models"
hint = (sys.argv[2] or "").strip()
prefer = ["general-text", "general-text-speculator", "chat", "safe-build", "miryam-gpu-decision"]
try:
    with familia_auth.open_url(url, timeout=3) as r:
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
  # a code-bootstraps server says where it is (start.sh may have moved off 9931)
  ready=""
  for b in "$ROOT/code-bootstraps-llama.cpp" "$ROOT/../code-bootstraps-llama.cpp" "${FAMILIA_BOOTSTRAP_ROOT:-}"; do
    [ -n "$b" ] && [ -f "$b/.cache/serve.ready" ] && { ready=$(cut -d' ' -f1 "$b/.cache/serve.ready"); break; }
  done
  for cand in ${ready:+"http://127.0.0.1:$ready"} \
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
  printf 'proto-chat: logs: %s\n' "$ROOT/.cache/proto-bootstrap.log" >&2
  ( cd "$ROOT" && nohup sh ./start.sh --bootstrap >"$ROOT/.cache/proto-bootstrap.log" 2>&1 & echo $! >"$ROOT/.cache/proto-bootstrap.pid" ) || true
    BOOT_PID=$(cat "$ROOT/.cache/proto-bootstrap.pid" 2>/dev/null || true)
    return 0
  fi
  if [ -n "$BACKEND" ]; then
    say "starting code-bootstraps at $BACKEND …"
    mkdir -p "$ROOT/.cache"
    printf 'proto-chat: logs: %s\n' "$ROOT/.cache/proto-bootstrap.log" >&2
    ( cd "$(dirname "$BACKEND")" && nohup sh "$(basename "$BACKEND")" >"$ROOT/.cache/proto-bootstrap.log" 2>&1 & echo $! >"$ROOT/.cache/proto-bootstrap.pid" ) || true
    BOOT_PID=$(cat "$ROOT/.cache/proto-bootstrap.pid" 2>/dev/null || true)
  else
    die "no chat server on :8080/:9931 and no start.sh / code-bootstraps to launch. Run: ./start.sh --bootstrap  OR  bring up green-roomz on :8080" 1
  fi
}

# Readiness ceiling (seconds). A first start can build llama.cpp, hash and load models:
# minutes on a laptop, much longer on a phone or a throttled CPU. FAMILIA_PROTO_WAIT
# overrides (0 = wait as long as the server process lives).
wait_ceiling() {
  case "${FAMILIA_PROTO_WAIT:-auto}" in
    auto)
      cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 4)
      case "${PREFIX:-}" in *com.termux*) echo 3600; return ;; esac
      if [ -n "${ANDROID_ROOT:-}" ] || [ "${cores:-4}" -le 2 ]; then echo 3600; else echo 1800; fi ;;
    *[!0-9]*|"") die "FAMILIA_PROTO_WAIT must be seconds (0 = no limit)" 2 ;;
    *) echo "$FAMILIA_PROTO_WAIT" ;;
  esac
}
WAIT_EVERY=${FAMILIA_PROTO_WAIT_EVERY:-15}   # progress line interval (seconds)
boot_alive() { [ -z "$BOOT_PID" ] || kill -0 "$BOOT_PID" 2>/dev/null; }
log_hint() {
  f="$ROOT/.cache/proto-bootstrap.log"
  [ -s "$f" ] && tail -n 1 "$f" | cut -c1-160
}

wait_ready() {
  ceiling=$(wait_ceiling) || exit 2
  start=$(date +%s); next=$WAIT_EVERY
  while :; do
    if ep=$(find_endpoint); then
      URL=$ep
      say "server answers /v1/models after $(( $(date +%s) - start ))s"
      return 0
    fi
    el=$(( $(date +%s) - start ))
    if ! boot_alive; then
      die "the server process (pid $BOOT_PID) exited after ${el}s before answering; last log line: $(log_hint) (full log: .cache/proto-bootstrap.log)" 1
    fi
    if [ "$ceiling" -gt 0 ] && [ "$el" -ge "$ceiling" ]; then
      die "server not ready after ${el}s (FAMILIA_PROTO_WAIT=$ceiling). It may still be building or loading models: see .cache/proto-bootstrap.log, then rerun with FAMILIA_PROTO_WAIT=0 (no limit) or a larger value" 1
    fi
    if [ "$el" -ge "$next" ]; then
      lim="no limit"; [ "$ceiling" -gt 0 ] && lim="limit ${ceiling}s"
      say "still waiting for the server (${el}s, $lim)${BOOT_PID:+; last: $(log_hint)}"
      _proto_osc working --id home/proto --msg "waiting for local chat server (${el}s)" --progress 10
      next=$((next + WAIT_EVERY))
    fi
    sleep 2
  done
}

# The router answers /v1/models before the chat model is loaded; the first message would
# then wait for the load inside one request (and time out on a slow host). Load it first
# and poll the router's /models status. Servers without /models (one model) are ready.
wait_model() {
  ceiling=$(wait_ceiling) || exit 2
  "$PY" - "$URL" "$MODEL" "$ceiling" "$WAIT_EVERY" <<'PY'
import json, os, sys, time, urllib.request
sys.path.insert(0, os.environ["FAMILIA_SCRIPTS"]); import familia_auth
url, model, ceiling, every = sys.argv[1].rstrip("/"), sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
def status():
    with familia_auth.open_url(url + "/models", timeout=5) as r:
        data = json.load(r)
    for m in data.get("data") or []:
        if m.get("id") == model or model in (m.get("aliases") or []):
            st = m.get("status") or {}
            return st.get("value") if isinstance(st, dict) else st
    return None
try:
    st = status()
except Exception:
    sys.exit(0)            # not a router: one model, served once /v1/models answers
if st in (None, "loaded"):
    sys.exit(0)
if st == "unloaded":
    req = urllib.request.Request(url + "/models/load", data=json.dumps({"model": model}).encode(),
                                 headers=familia_auth.auth_headers({"Content-Type": "application/json"}, key=familia_auth.key_for_url(url)), method="POST")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"proto-chat: could not ask the router to load {model}: {e}", file=sys.stderr)
t0 = time.time(); nxt = every
while True:
    try:
        st = status()
    except Exception:
        st = "unreachable"
    el = int(time.time() - t0)
    if st == "loaded":
        print(f"proto-chat: model {model} loaded after {el}s", file=sys.stderr); sys.exit(0)
    if st == "failed":
        print(f"proto-chat: error: the router failed to load {model} (see the server log)", file=sys.stderr); sys.exit(1)
    if ceiling > 0 and el >= ceiling:
        print(f"proto-chat: error: {model} not loaded after {el}s (FAMILIA_PROTO_WAIT={ceiling}); "
              "it may still be loading: rerun with FAMILIA_PROTO_WAIT=0 or a larger value", file=sys.stderr); sys.exit(1)
    if el >= nxt:
        lim = f"limit {ceiling}s" if ceiling > 0 else "no limit"
        print(f"proto-chat: loading {model} ({st}, {el}s, {lim})", file=sys.stderr); nxt += every
    time.sleep(2)
PY
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

_proto_osc working --id home/proto --msg "loading $MODEL" --progress 50
wait_model || die "model $MODEL did not load" 1
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
import json, os, sys, urllib.request, urllib.error
sys.path.insert(0, os.environ["FAMILIA_SCRIPTS"]); import familia_auth
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
    headers=familia_auth.auth_headers({"Content-Type": "application/json"}, key=familia_auth.key_for_url(url)),
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=int(os.environ.get("FAMILIA_PROTO_REPLY_TIMEOUT", "900"))) as r:
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
