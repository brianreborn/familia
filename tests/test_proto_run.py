"""Host execution of RUN: ./familia directives (#753, Brian's correction on #327)."""
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import protograph  # noqa: E402

PROTO = ROOT / "scripts" / "proto_chat.sh"


def _stub(tmp_path, body):
    path = tmp_path / "familia-stub"
    path.write_text(body, encoding="ascii")
    path.chmod(0o755)
    return path


def test_allowlisted_command_runs_and_is_audited(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    stub = _stub(tmp_path, "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$MARKER\"\nprintf 'stub-ok %s\\n' \"$*\"\n")
    monkeypatch.setenv("MARKER", str(marker))
    monkeypatch.setenv(protograph.BIN_ENV, str(stub))
    audit = tmp_path / "audit.log"
    out = protograph.execute_reply("RUN: ./familia graph check\n", audit=str(audit))
    assert "graph check" in marker.read_text()
    assert "status: ran" in out and "exit: 0" in out and "stub-ok graph check" in out
    time_s, command, code = audit.read_text().strip().split("\t")
    assert time_s.endswith("Z") and command == "./familia graph check" and code == "0"


def test_non_menu_command_and_metacharacters_are_not_run(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    stub = _stub(tmp_path, "#!/bin/sh\nprintf ran > \"$MARKER\"\n")
    monkeypatch.setenv("MARKER", str(marker))
    monkeypatch.setenv(protograph.BIN_ENV, str(stub))
    audit = tmp_path / "audit.log"
    refused = protograph.execute_reply("RUN: ./familia bench\n", audit=str(audit))
    assert not marker.exists()
    assert "status: refused" in refused and "menu-items.txt" in refused
    meta = protograph.execute_reply("RUN: ./familia graph check; echo pwned\n", audit=str(audit))
    assert not marker.exists()
    assert "metacharacter" in meta
    fenced = protograph.execute_reply("```run\n./familia graph check | tee /tmp/x\n```\n", audit=str(audit))
    assert not marker.exists()
    assert "metacharacter" in fenced
    assert audit.read_text().count("\trefused") == 3


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pid, seconds=2.0):
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def test_run_timeout_kills_grandchild_before_next_run(tmp_path, monkeypatch):
    gpid = tmp_path / "gpid"
    marker = tmp_path / "marker"
    stub = _stub(tmp_path, """#!/bin/sh
if [ "$1" = "graph" ]; then
  "$PY" -c 'import os, signal, time
signal.signal(signal.SIGHUP, signal.SIG_IGN)
open(os.environ["GPID"], "w").write(str(os.getpid()))
time.sleep(60)' &
  sleep 60
else
  pid=$(cat "$GPID")
  if kill -0 "$pid" 2>/dev/null; then
    printf overlap > "$MARKER"
  else
    printf clear > "$MARKER"
  fi
fi
""")
    monkeypatch.setenv("GPID", str(gpid))
    monkeypatch.setenv("MARKER", str(marker))
    monkeypatch.setenv("PY", sys.executable)
    monkeypatch.setenv(protograph.BIN_ENV, str(stub))
    audit = tmp_path / "audit.log"
    out = protograph.execute_reply(
        "RUN: ./familia graph check\nRUN: ./familia serve coder\n",
        timeout=1, audit=str(audit))
    assert "status: timeout" in out
    assert gpid.is_file()
    assert _wait_dead(int(gpid.read_text().strip()))
    assert marker.read_text() == "clear"
    assert "\ttimeout" in audit.read_text()


def test_sigterm_kills_the_process_group(tmp_path):
    import signal
    import time
    gpid = tmp_path / "gpid"
    stub = _stub(tmp_path, """#!/bin/sh
"$PY" -c 'import os, signal, time
signal.signal(signal.SIGHUP, signal.SIG_IGN)
open(os.environ["GPID"], "w").write(str(os.getpid()))
time.sleep(60)' &
sleep 60
""")
    audit = tmp_path / "audit.log"
    code = (
        "import os, sys\n"
        "sys.path.insert(0, os.environ['SCRIPTS'])\n"
        "import protograph\n"
        "protograph.execute_familia('./familia graph check', "
        "bin_path=os.environ['STUB'], timeout=30, audit=os.environ['AUDIT'])\n"
    )
    env = dict(os.environ)
    env.update(GPID=str(gpid), PY=sys.executable, STUB=str(stub),
               AUDIT=str(audit), SCRIPTS=str(ROOT / "scripts"))
    proc = subprocess.Popen([sys.executable, "-c", code], env=env)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not gpid.is_file():
        time.sleep(0.05)
    assert gpid.is_file()
    os.kill(proc.pid, signal.SIGTERM)
    proc.wait(timeout=5)
    assert _wait_dead(int(gpid.read_text().strip()))
    assert _wait_dead(proc.pid)


def test_output_is_capped_and_process_stops(tmp_path):
    stub = _stub(tmp_path, "#!/usr/bin/env python3\nimport sys, time\n"
                 "sys.stdout.write('Y' * 200000)\nsys.stdout.flush()\ntime.sleep(30)\n")
    audit = tmp_path / "audit.log"
    result = protograph.execute_familia(
        "./familia graph check", bin_path=str(stub), timeout=10,
        max_output_bytes=80, audit=str(audit))
    assert result["status"] == "truncated"
    assert len(result["output"].encode("utf-8")) <= 80
    assert "truncated" in result["output"]


def test_feedback_budget_fits_ctx_2048_at_the_max(tmp_path):
    import fleet_greeting
    greeting = fleet_greeting.load()
    body, variant, fallback, _warn = protograph.select_system_prompt(2048, greeting=greeting)
    assert variant == "compact" and fallback is False
    system = fleet_greeting.prepend(body, greeting=greeting)
    user = "u" * (protograph.USER_TURN_TOKENS * 4)
    # The uncapped follow-up (another 512) does not fit.
    assert (protograph.estimate_tokens(system) + protograph.USER_TURN_TOKENS
            + protograph.MAX_OUTPUT_TOKENS + protograph.MAX_OUTPUT_TOKENS) > 2048
    reply = "RUN: ./familia graph check\n" + ("a" * (protograph.MAX_OUTPUT_TOKENS * 4))
    follow, tool_bytes = protograph.feedback_room(2048, system, user, reply)
    assert 1 <= follow < protograph.MAX_OUTPUT_TOKENS
    tool_tokens = (tool_bytes + 3) // 4
    total = (protograph.estimate_tokens(system) + protograph.estimate_tokens(user)
             + protograph.estimate_tokens(reply) + tool_tokens + follow)
    assert total <= 2048
    stub = _stub(tmp_path, "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('Y'*200000)\n")
    text, got_follow = protograph.execute_reply_budgeted(
        reply, ctx=2048, system_text=system, user_text=user,
        bin_path=str(stub), timeout=10, audit=str(tmp_path / "audit.log"))
    assert got_follow == follow
    assert len(text.encode("utf-8")) <= tool_bytes
    assert "truncated" in text


def test_proto_chat_runs_directive_and_feeds_output_back(tmp_path):
    marker = tmp_path / "marker"
    stub = _stub(tmp_path, "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$MARKER\"\nprintf 'stub-ok %s\\n' \"$*\"\n")
    calls = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body):
            raw = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._send('{"data":[{"id":"m1"}]}')

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            calls["n"] += 1
            content = "RUN: ./familia graph check" if calls["n"] == 1 else "saw-output"
            self._send('{"choices":[{"message":{"content":"%s"}}]}' % content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, PYTHON=sys.executable, FAMILIA_NO_TTY="1", FAMILIA_PROTO_WAIT="5")
    env[protograph.BIN_ENV] = str(stub)
    env[protograph.AUDIT_ENV] = str(tmp_path / "audit.log")
    env["MARKER"] = str(marker)
    env["FAMILIA_FLEET_GREETING"] = str(tmp_path / "no-greeting.md")
    env.pop("FAMILIA_PROTOGRAPH_PROMPT", None)
    try:
        result = subprocess.run(
            ["sh", str(PROTO), "--no-start", "--url", "http://127.0.0.1:%s" % port, "--model", "m1"],
            input="hello\n\n", capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert "graph check" in marker.read_text()
    assert "stub-ok graph check" in result.stdout
    assert "saw-output" in result.stdout
    assert (tmp_path / "audit.log").read_text().strip().endswith("\t0")
    assert calls["n"] >= 2
