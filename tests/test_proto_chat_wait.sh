#!/usr/bin/env bash
# proto_chat waits for the chat model by polling the router /models status
# (unloaded -> loading -> loaded) and prints a clear message on timeout.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'kill $SP 2>/dev/null; rm -rf "$T"' EXIT
PORT=$((20000 + RANDOM % 20000))
cat >"$T/srv.py" <<'PY'
import json, sys, time, http.server
mode, port = sys.argv[1], int(sys.argv[2]); t0 = [None]
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, o):
        b = json.dumps(o).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        st = "unloaded"
        if t0[0] is not None:
            st = "loaded" if (mode == "slow" and time.time() - t0[0] > 4) else "loading"
        self.send({"data": [{"id": "m1", "status": {"value": st}}]})
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/models/load") and t0[0] is None: t0[0] = time.time()
        self.send({"success": True})
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
PY
fail=0
run() { # mode wait expect-rc pattern
  python3 "$T/srv.py" "$1" $PORT & SP=$!; sleep 0.7
  out=$(echo "" | FAMILIA_NO_TTY=1 FAMILIA_PROTO_WAIT=$2 FAMILIA_PROTO_WAIT_EVERY=1 \
    timeout 60 sh "$ROOT/scripts/proto_chat.sh" --url http://127.0.0.1:$PORT --model m1 2>&1); rc=$?
  kill $SP; wait $SP 2>/dev/null
  if [ "$rc" = "$3" ] && printf '%s' "$out" | grep -q "$4"; then echo "ok: $1 rc=$rc"
  else echo "FAIL: $1 rc=$rc"; printf '%s\n' "$out"; fail=1; fi
}
run slow 30 0 "endpoint http://127.0.0.1:$PORT  model m1"
run never 3 1 "not loaded after"
exit $fail
