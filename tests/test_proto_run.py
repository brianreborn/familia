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


def test_run_timeout(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    stub = _stub(
        tmp_path,
        "#!/usr/bin/env python3\nimport os, time\n"
        "open(os.environ['MARKER'], 'w').write('started')\n"
        "time.sleep(30)\n",
    )
    monkeypatch.setenv("MARKER", str(marker))
    audit = tmp_path / "audit.log"
    result = protograph.execute_familia("./familia graph check", bin_path=str(stub), timeout=1, audit=str(audit))
    assert result["status"] == "timeout"
    assert marker.read_text() == "started"
    assert audit.read_text().strip().endswith("\ttimeout")


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
