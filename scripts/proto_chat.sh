#!/bin/sh
# proto_chat.sh: interactive REPL against the familia protomodel (tiny local chat).
# Prefers an already-running OpenAI-compatible endpoint; starts bootstrap if none.
# Usage: sh scripts/proto_chat.sh [--url URL] [--model NAME] [--no-start]
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/lib/os.mk"   # mk_nproc
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
PRINT_PROMPT=0
PROTO_CTX=""
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

--print-system-prompt prints the system prompt (fleet greeting included) and
exits. It does not start a server. --ctx N picks the full or compact prompt
for that context size (the chat path uses the selected node's ctx).
FAMILIA_PROTOGRAPH_PROMPT overrides the prompt file. The file must be a
regular file inside skills/protograph/prompts (no symlink, no path outside
that directory). A rejected file uses the short fallback.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL=${2-}; shift ;;
    --model) MODEL=${2-}; shift ;;
    --no-start) NO_START=1 ;;
    --print-system-prompt) PRINT_PROMPT=1 ;;
    --ctx) PROTO_CTX=${2-}; shift ;;
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
prefer = ["general-text", "general-text-speculator", "chat", "safe-build", "vulkan-igpu-decision"]
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
      cores=$(mk_nproc 4)
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

# Versioned protograph system prompt (#327). protograph.py opens it with
# O_NOFOLLOW and fstat, confined to skills/protograph/prompts, and picks the
# full or compact file so the greeting, a user turn, and 512 output tokens
# still fit the node's ctx. The chosen file is static (KV prefix reuse).
# A rejected file warns and uses the short pre-#327 prompt.
_proto_load_system_prompt() {
  _pp_rc=0
  if [ -n "${1:-}" ]; then
    _pp_body=$("$PY" "$FAMILIA_SCRIPTS/protograph.py" --print-prompt --ctx "$1") || _pp_rc=$?
  elif [ -n "${2:-}" ]; then
    _pp_body=$("$PY" "$FAMILIA_SCRIPTS/protograph.py" --print-prompt --model "$2") || _pp_rc=$?
  else
    _pp_body=$("$PY" "$FAMILIA_SCRIPTS/protograph.py" --print-prompt) || _pp_rc=$?
  fi
  if [ "$_pp_rc" -ne 0 ]; then
    die "system prompt does not fit this model" "$_pp_rc"
  fi
  SYSTEM_PROMPT="$_pp_body"
  unset _pp_body _pp_rc
  return 0
}

# Fleet greeting once, after the variant is chosen. The trailing x keeps the
# last newline. A missing greeting file only warns (scripts/fleet_greeting.py).
_proto_apply_greeting() {
  if _greeted=$(printf '%s' "$SYSTEM_PROMPT" | "$PY" "$FAMILIA_SCRIPTS/fleet_greeting.py" prepend && printf x); then
    SYSTEM_PROMPT=${_greeted%x}
  fi
  unset _greeted
}

if [ "$PRINT_PROMPT" = 1 ]; then
  _proto_load_system_prompt "${PROTO_CTX:-}" ""
  _proto_apply_greeting
  printf '%s\n' "$SYSTEM_PROMPT"
  exit 0
fi

# Private scratch for child stderr (honors TMPDIR, incl. Termux $PREFIX/tmp).
_tbase=${TMPDIR:-${PREFIX:+$PREFIX/tmp}}
PROTO_TMP=$(umask 077; mktemp -d "${_tbase:-/tmp}/familia-proto.XXXXXX") || die "mktemp failed" 1
PROTO_EXEC_PID=""
# Stop a running familia exec (its python parent SIGTERMs, which killpg's the
# session) before deleting the scratch dir. TERM, a grace wait, then KILL.
_proto_stop_exec() {
  _pid=${PROTO_EXEC_PID:-}
  if [ -n "$_pid" ] && kill -0 "$_pid" 2>/dev/null; then
    kill -TERM "$_pid" 2>/dev/null || true
    sleep 1
    kill -KILL "$_pid" 2>/dev/null || true
    wait "$_pid" 2>/dev/null || true
  fi
  PROTO_EXEC_PID=""
}
trap '_proto_stop_exec; rm -rf -- "$PROTO_TMP"' EXIT HUP INT TERM
PROTO_ERR=$PROTO_TMP/err
export FAMILIA_PROTO_CTX_FILE=$PROTO_TMP/ctx

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
if [ -n "$PROTO_CTX" ]; then
  _proto_load_system_prompt "$PROTO_CTX" ""
else
  _proto_load_system_prompt "" "$MODEL"
fi
_proto_apply_greeting
if [ -n "$PROTO_CTX" ]; then
  PROTO_CTX_EFFECTIVE=$PROTO_CTX
elif [ -s "$PROTO_TMP/ctx" ]; then
  PROTO_CTX_EFFECTIVE=$(cat "$PROTO_TMP/ctx")
else
  PROTO_CTX_EFFECTIVE=8192
fi
_proto_osc working --id home/proto --msg "Talk to the protomodel ($MODEL)" --title "proto_chat"
say "type a message (empty /q /quit /exit to quit)"
printf '\n'

# One chat completion. FAMILIA_PROTO_ASSIST_FILE + FAMILIA_PROTO_TOOL_FILE, when
# both are set, append the previous reply and the command output (the feedback turn).
proto_complete() {
  "$PY" - "$URL" "$MODEL" "$SYSTEM_PROMPT" "$1" <<'PY' 2>"$PROTO_ERR" || true
import os, sys
sys.path.insert(0, os.environ["FAMILIA_SCRIPTS"]); import familia_auth
import json, urllib.request
url, model, system, user = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
messages = [
    {"role": "system", "content": system},
    {"role": "user", "content": user},
]
assist = os.environ.get("FAMILIA_PROTO_ASSIST_FILE") or ""
tool = os.environ.get("FAMILIA_PROTO_TOOL_FILE") or ""
user_file = os.environ.get("FAMILIA_PROTO_USER_FILE") or ""
if assist and tool and user_file:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": open(user_file, encoding="utf-8", errors="replace").read()},
        {"role": "assistant", "content": open(assist, encoding="utf-8", errors="replace").read()},
        {"role": "user", "content": open(tool, encoding="utf-8", errors="replace").read()},
    ]
elif assist and tool:
    messages.append({"role": "assistant", "content": open(assist, encoding="utf-8", errors="replace").read()})
    messages.append({"role": "user", "content": open(tool, encoding="utf-8", errors="replace").read()})
body = {
    "model": model,
    "messages": messages,
    "temperature": 0.7,
    "max_tokens": int(os.environ.get("FAMILIA_PROTO_MAX_TOKENS", "512")),
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
content = (msg.get("content") or "").strip()
reasoning = (msg.get("reasoning_content") or "").strip()
if not content and reasoning:
    content = f"[reasoning: {reasoning}]"
print(content or "(empty reply)", end="")
PY
}

# Execute RUN directives in $1. $2 is the user turn already in the context.
# Result text is left in PROTO_TMP/exec.out. follow_max (reply budget that
# still fits ctx) is left in PROTO_TMP/follow_max. Runs in the current shell
# so PROTO_EXEC_PID is visible to the signal trap.
proto_exec_reply() {
  printf '%s\n' "$1" > "$PROTO_TMP/reply"
  printf '%s' "$2" > "$PROTO_TMP/user"
  printf '%s' "$SYSTEM_PROMPT" > "$PROTO_TMP/system"
  : > "$PROTO_TMP/exec.out"
  "$PY" "$FAMILIA_SCRIPTS/protograph.py" --exec-reply "$PROTO_TMP/reply" \
    --ctx "$PROTO_CTX_EFFECTIVE" \
    --budget-system "$PROTO_TMP/system" --budget-user "$PROTO_TMP/user" \
    --follow-max-file "$PROTO_TMP/follow_max" > "$PROTO_TMP/exec.out" &
  PROTO_EXEC_PID=$!
  wait "$PROTO_EXEC_PID" || true
  PROTO_EXEC_PID=""
}

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
  unset FAMILIA_PROTO_ASSIST_FILE FAMILIA_PROTO_TOOL_FILE
  reply=$(proto_complete "$line")
  if [ -z "$reply" ]; then
    if [ -s "$PROTO_ERR" ]; then
      printf 'proto> %s\n' "$(cat "$PROTO_ERR")"
    else
      printf 'proto> (no reply)\n'
    fi
  else
    printf 'proto> %s\n\n' "$reply"
    printf '%s' "$line" > "$PROTO_TMP/turn"
    proto_exec_reply "$reply" "$line"
    exec_out=$(cat "$PROTO_TMP/exec.out" 2>/dev/null || true)
    if [ -n "$exec_out" ]; then
      printf 'run> %s\n\n' "$exec_out"
      _follow_max=$(cat "$PROTO_TMP/follow_max" 2>/dev/null || echo 0)
      if [ "$_follow_max" -eq 0 ]; then
        printf 'run> follow-up skipped: reply does not fit ctx %s\n\n' "$PROTO_CTX_EFFECTIVE"
      else
        printf '%s\n' "$reply" > "$PROTO_TMP/assist"
        printf '%s\n' "$exec_out" > "$PROTO_TMP/tool"
        FAMILIA_PROTO_ASSIST_FILE=$PROTO_TMP/assist
        FAMILIA_PROTO_TOOL_FILE=$PROTO_TMP/tool
        FAMILIA_PROTO_USER_FILE=$PROTO_TMP/turn
        FAMILIA_PROTO_MAX_TOKENS=$_follow_max
        export FAMILIA_PROTO_ASSIST_FILE FAMILIA_PROTO_TOOL_FILE FAMILIA_PROTO_USER_FILE FAMILIA_PROTO_MAX_TOKENS
        follow=$(proto_complete "$line")
        unset FAMILIA_PROTO_ASSIST_FILE FAMILIA_PROTO_TOOL_FILE FAMILIA_PROTO_USER_FILE FAMILIA_PROTO_MAX_TOKENS
        # The follow-up is shown and not executed. Tool output is fenced data,
        # so a RUN line it contains cannot start another command.
        if [ -n "$follow" ]; then
          printf 'proto> %s\n\n' "$follow"
        fi
      fi
    fi
  fi
done
