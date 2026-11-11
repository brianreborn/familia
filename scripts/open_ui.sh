#!/bin/sh
# open_ui.sh: discover running llama-server web UIs or graph gateways and open them in the browser
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# Scan ports: coder (9941), phone-coder (18112), decision (18110), router gateway (9931), green-roomz (8080)
CANDIDATES="9941 18112 18110 9931 8080"
FOUND=""

for port in $CANDIDATES; do
  if curl -s -m 1 "http://127.0.0.1:$port/props" >/dev/null 2>&1; then
    FOUND="http://127.0.0.1:$port/"
    printf 'familia-ui: active llama-ui found at %s\n' "$FOUND"
    break
  elif curl -s -m 1 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    FOUND="http://127.0.0.1:$port/"
    printf 'familia-ui: active gateway found at %s\n' "$FOUND"
    break
  fi
done

if [ -z "$FOUND" ]; then
  printf 'familia-ui: no running UI/server detected. Start one via ./familia or ./start.sh\n' >&2
  exit 1
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$FOUND" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
  open "$FOUND" >/dev/null 2>&1 &
else
  printf 'familia-ui: open %s in your browser\n' "$FOUND"
fi
