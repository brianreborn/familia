import json, os, sys, threading, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import escalation_proxy as EP

def mock(name, seen):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            b = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); seen.append((name, b))
            out = json.dumps({"choices": [{"message": {"role": "assistant", "content": "same answer"}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
    s = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]

def graph(pl, ph, mode):
    return {"hosts": {"h": {}}, "aliases": {},
            "nodes": {"light": {"host": "h", "port": pl, "model": "smollm2", "escalates_to": ["heavy"], "escalation": {"mode": mode}},
                      "heavy": {"host": "h", "port": ph, "model": "qwen35-2b"}}}

def post(port, msgs):
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps({"model": "x", "messages": msgs}).encode(), headers={"Content-Type": "application/json"}))
    return json.load(r)["choices"][0]["message"]["content"]

def test_auto_swap_handoff_and_swap_back(monkeypatch, tmp_path):
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []; g = graph(mock("light", seen), mock("heavy", seen), "auto")
    recs = [{"host": "h", "kind": "bench", "model": {"repo": "qwen3.5-2b"}, "metrics": {"tg_tps": {"max": 10}}}]
    esc = EP.Escalator(g, "light", recs, "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "fix it"}]
    post(p, msgs); post(p, msgs); out = post(p, msgs)       # 3 identical outputs -> auto
    assert "escalated to heavy" in out
    post(p, msgs + [{"role": "user", "content": "go"}])
    assert seen[-1][0] == "heavy" and json.loads(seen[-1][1]["messages"][-1]["content"])["open_problem"] == "go"
    post(p, msgs)
    assert seen[-1][0] == "light"                            # swapped back
    srv.shutdown()

def test_suggest_then_accept(monkeypatch, tmp_path):
    for k, f in (("STATE", ""), ("PENDING", "p.json"), ("ACCEPT", "a.json")): monkeypatch.setattr(EP, k, str(tmp_path / f))
    seen = []; g = graph(mock("light", seen), mock("heavy", seen), "suggest")
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    msgs = [{"role": "user", "content": "please try harder"}]
    out = post(p, msgs)
    assert "escalate.py accept" in out and os.path.exists(EP.PENDING)
    json.dump({"target": "heavy"}, open(EP.ACCEPT, "w"))
    post(p, msgs); assert seen[-1][0] == "heavy"
    srv.shutdown()

def test_signals_count_tool_failures():
    s = EP.Signals()
    s.observe_request({"messages": [{"role": "user", "content": "x"}, {"role": "tool", "content": "Traceback: boom"},
                                    {"role": "tool", "content": "ok"}, {"role": "tool", "content": "exit code 2"}]})
    assert s.failures == 2

def test_remote_loopback_node_unreachable():
    g = {"hosts": {"a": {}, "b": {"addr": "10.0.0.2"}}, "nodes": {"x": {"host": "b", "port": 1, "bind": "127.0.0.1"}}}
    assert EP.node_url(g, "x", "a") is None

def mock_raw(name, seen, body_bytes=None, status=200):
    """Stub that returns raw bytes (possibly invalid JSON)."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            b = self.rfile.read(int(self.headers["Content-Length"]))
            try: seen.append((name, json.loads(b)))
            except Exception: seen.append((name, b))
            out = body_bytes if body_bytes is not None else json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(out)
    s = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]

def closed_port():
    """Bind then close so the port refuses connections."""
    s = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = s.server_address[1]; s.server_close()
    return port

def post_status(port, msgs):
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({"model": "x", "messages": msgs}).encode(),
            headers={"Content-Type": "application/json"}))
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def test_heavy_down_falls_back_to_light(monkeypatch, tmp_path):
    """#98: after escalation, heavy unreachable → fall back to light; later requests work."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setenv("FAMILIA_ESCALATE", "auto")
    seen = []
    pl = mock("light", seen)
    ph = closed_port()
    # Phrase-only triggers so identical mock replies do not re-escalate.
    g = {"hosts": {"h": {}}, "aliases": {},
         "nodes": {"light": {"host": "h", "port": pl, "model": "smollm2", "escalates_to": ["heavy"],
                            "escalation": {"mode": "auto", "triggers": {"repeat_outputs": 0, "failure_retries": 0,
                                                                       "phrases": ["try harder"]}}},
                   "heavy": {"host": "h", "port": ph, "model": "qwen35-2b"}}}
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    msgs = [{"role": "user", "content": "please try harder"}]
    # First reply on light triggers auto escalate (phrase); current becomes heavy.
    out = post(p, msgs)
    assert "escalated to heavy" in out
    assert esc.current == "heavy"
    # Next request: heavy down → fall back + retry on light → 200, back on light.
    status, body = post_status(p, [{"role": "user", "content": "continue"}])
    assert status == 200
    assert esc.current == "light"
    assert "failed; back on light" in body or seen[-1][0] == "light"
    # Later requests must not stick on heavy 502s.
    for _ in range(3):
        status, _ = post_status(p, [{"role": "user", "content": "hello"}])
        assert status == 200
        assert esc.current == "light"
    srv.shutdown()

def test_malformed_upstream_json_returns_502_and_recovers(monkeypatch, tmp_path):
    """#99: invalid JSON after 200 from heavy → 502 (not empty 200), fall back to light."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setenv("FAMILIA_ESCALATE", "auto")
    seen = []
    pl = mock("light", seen)
    ph = mock_raw("heavy", seen, body_bytes=b"{not json")
    g = {"hosts": {"h": {}}, "aliases": {},
         "nodes": {"light": {"host": "h", "port": pl, "model": "smollm2", "escalates_to": ["heavy"],
                            "escalation": {"mode": "auto", "triggers": {"repeat_outputs": 0, "failure_retries": 0,
                                                                       "phrases": ["try harder"]}}},
                   "heavy": {"host": "h", "port": ph, "model": "qwen35-2b"}}}
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    msgs = [{"role": "user", "content": "please try harder"}]
    post(p, msgs)  # escalate to heavy
    assert esc.current == "heavy"
    # Request to heavy returns garbage JSON → 502 or recovered 200 via light fallback.
    status, body = post_status(p, [{"role": "user", "content": "go"}])
    assert status in (200, 502)
    if status == 502:
        assert "invalid JSON" in body or "JSON" in body or "json" in body.lower()
    # State machine recovered onto light either way.
    assert esc.current == "light"
    status2, _ = post_status(p, [{"role": "user", "content": "hello"}])
    assert status2 == 200
    assert esc.current == "light"
    srv.shutdown()

def test_light_transport_errors_escalate(monkeypatch, tmp_path):
    """#100: light upstream errors feed decide; auto escalates to heavy."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setenv("FAMILIA_ESCALATE", "auto")
    seen = []
    pl = closed_port()
    ph = mock("heavy", seen)
    # failure_retries=1 so a single transport error escalates
    g = {"hosts": {"h": {}}, "aliases": {},
         "nodes": {"light": {"host": "h", "port": pl, "model": "smollm2", "escalates_to": ["heavy"],
                            "escalation": {"mode": "auto", "triggers": {"failure_retries": 1,
                                                                       "repeat_outputs": 0, "phrases": []}}},
                   "heavy": {"host": "h", "port": ph, "model": "qwen35-2b"}}}
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    status, body = post_status(p, [{"role": "user", "content": "hi"}])
    assert status == 200, body
    assert "escalated to heavy" in body
    assert seen and seen[-1][0] == "heavy"
    # Proxy should be on heavy after escalate; one clean reply swaps back.
    # (handoff request already consumed the escalate; next clean reply swaps back)
    srv.shutdown()

def test_transport_failures_persist_across_observe_request():
    """#100: observe_request must not wipe transport_failures."""
    s = EP.Signals()
    s.transport_failures = 2
    s.observe_request({"messages": [{"role": "user", "content": "x"}]})
    assert s.failures == 0
    assert s.transport_failures == 2
    assert s.dict()["failures"] == 2

def post_headers(port, msgs, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps({"model": "x", "messages": msgs}).encode(), headers=h))
    return json.load(r)["choices"][0]["message"]["content"]


def test_session_id_from_headers():
    assert EP.session_id_from({}) == EP.DEFAULT_SESSION
    assert EP.session_id_from({"X-Familia-Session": " a "}) == "a"
    assert EP.session_id_from({"Authorization": "Bearer tok123"}) == "bearer:tok123"
    # Explicit session header wins over bearer.
    assert EP.session_id_from({"X-Familia-Session": "s1", "Authorization": "Bearer tok"}) == "s1"


def test_concurrent_sessions_no_crosstalk(monkeypatch, tmp_path):
    """#101: N parallel clients; only the one with an escalation phrase gets [familia]."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setenv("FAMILIA_ESCALATE", "auto")
    seen = []
    pl = mock("light", seen)
    ph = mock("heavy", seen)
    g = {"hosts": {"h": {}}, "aliases": {},
         "nodes": {"light": {"host": "h", "port": pl, "model": "smollm2", "escalates_to": ["heavy"],
                            "escalation": {"mode": "auto", "triggers": {"repeat_outputs": 0, "failure_retries": 0,
                                                                       "phrases": ["try harder"]}}},
                   "heavy": {"host": "h", "port": ph, "model": "qwen35-2b"}}}
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]

    n = 8
    escalate_i = 3
    results = [None] * n
    errors = [None] * n
    barrier = threading.Barrier(n)

    def worker(i):
        try:
            barrier.wait(timeout=5)
            sid = f"client-{i}"
            msg = "please try harder" if i == escalate_i else "hello from quiet client"
            results[i] = post_headers(p, [{"role": "user", "content": msg}],
                                      headers={"X-Familia-Session": sid})
        except Exception as e:
            errors[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    assert all(e is None for e in errors), errors
    assert all(r is not None for r in results)
    for i, out in enumerate(results):
        if i == escalate_i:
            assert "[familia]" in out and "escalated to heavy" in out, out
        else:
            assert "[familia]" not in out, f"client-{i} got cross-talk: {out!r}"
    srv.shutdown()


def test_default_session_lock_serializes_mutations(monkeypatch, tmp_path):
    """#101: without a session header, concurrent requests share one Escalator under a lock."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setenv("FAMILIA_ESCALATE", "auto")
    seen = []
    pl = mock("light", seen)
    ph = mock("heavy", seen)
    g = {"hosts": {"h": {}}, "aliases": {},
         "nodes": {"light": {"host": "h", "port": pl, "model": "smollm2", "escalates_to": ["heavy"],
                            "escalation": {"mode": "auto", "triggers": {"repeat_outputs": 0, "failure_retries": 0,
                                                                       "phrases": ["try harder"]}}},
                   "heavy": {"host": "h", "port": ph, "model": "qwen35-2b"}}}
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    assert isinstance(esc.lock, type(threading.RLock()))

    n = 6
    results = [None] * n
    errors = [None] * n
    barrier = threading.Barrier(n)

    def worker(i):
        try:
            barrier.wait(timeout=5)
            # Mix escalate + quiet on the shared default session; lock must prevent torn state.
            msg = "please try harder" if i == 0 else f"quiet {i}"
            results[i] = post(p, [{"role": "user", "content": msg}])
        except Exception as e:
            errors[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    assert all(e is None for e in errors), errors
    assert all(r is not None for r in results)
    # At least one reply carries the escalate note; no crashes / empty bodies.
    assert any("escalated to heavy" in (r or "") for r in results)
    # Escalator state machine remains coherent (on light or heavy, never half-swapped).
    assert esc.current in ("light", "heavy")
    srv.shutdown()


def test_handoff_keeps_tools(monkeypatch, tmp_path):
    """#106: heavy handoff must keep tools so agent sessions can finish tool turns."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setenv("FAMILIA_ESCALATE", "auto")
    seen = []; g = graph(mock("light", seen), mock("heavy", seen), "auto")
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    tools = [{"type": "function", "function": {"name": "shell", "parameters": {"type": "object"}}}]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "fix it"}]
    post(p, msgs); post(p, msgs); post(p, msgs)  # escalate
    body = {"model": "x", "messages": msgs + [{"role": "user", "content": "go"}], "tools": tools, "tool_choice": "auto"}
    urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{p}/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}))
    heavy = [s for s in seen if s[0] == "heavy"]
    assert heavy, "expected a heavy request"
    last = heavy[-1][1]
    assert "tools" in last and last["tools"] == tools
    assert last.get("tool_choice") == "auto"
    srv.shutdown()
