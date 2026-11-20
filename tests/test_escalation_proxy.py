import io, json, os, socket, sys, threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import escalation_proxy as EP
import validate_graph as VG

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _instance_key(monkeypatch):
    """The proxy fails closed without an instance key (familia_auth); give tests one."""
    monkeypatch.setenv("FAMILIA_API_KEY", "test-instance-key")


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
    assert isinstance(esc.lock, EP.FairLock)  # re-entrant FIFO lock (R5 #248)

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


def _tool_graph(pl, pc, route="coder", coder_role="coder"):
    # Off-loopback light is not direct and must not rely on discovery; tool_route is the
    # TOOLS-009 opt-in that still forwards (chat + bind 0.0.0.0, no server_tools).
    return {"hosts": {"h": {}}, "aliases": {"coder-a": {"node": "coder"}},
            "models": {"m": {"role": "chat"}, "c": {"role": coder_role, "tool_calls": True}},
            "nodes": {"light": {"host": "h", "port": pl, "model": "m", "bind": "0.0.0.0", "tool_route": route},
                      "coder": {"host": "h", "port": pc, "model": "c", "bind": "127.0.0.1"}}}

def _post_body(port, body):
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}))
    return json.load(r)

TOOLS = [{"type": "function", "function": {"name": "ls", "parameters": {"type": "object"}}}]

def test_tool_request_forwarded_to_tool_route(monkeypatch, tmp_path):
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []; g = _tool_graph(mock("light", seen), mock("coder", seen))
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={})); p = srv.server_address[1]
    msgs = [{"role": "user", "content": "list files"}]
    _post_body(p, {"model": "x", "messages": msgs, "tools": TOOLS})
    assert seen[-1][0] == "coder" and seen[-1][1]["model"] == "coder-a" and seen[-1][1]["tools"] == TOOLS
    _post_body(p, {"model": "x", "messages": msgs})          # no tools -> stays on light
    assert seen[-1][0] == "light"
    srv.shutdown()

def test_tool_route_to_fail_closed_target_not_forwarded(monkeypatch, tmp_path):
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []; g = _tool_graph(mock("light", seen), mock("coder", seen), coder_role="guardian")
    assert EP.tool_target(g, "light") is None
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={})); p = srv.server_address[1]
    _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "x"}], "tools": TOOLS})
    assert seen[-1][0] == "light"
    srv.shutdown()

def test_tool_target_ignores_unrouted_and_bad_graph():
    assert EP.tool_target({"nodes": {"a": {}}}, "a") is None
    assert EP.tool_target({"nodes": {"a": {"tool_route": "missing"}}}, "a") is None


# Boundary nits on #251: legacy tool fields, unreachable/invalid target stays put, forward log.

@_pytest.mark.parametrize("extra", [{"functions": [{"name": "ls", "parameters": {"type": "object"}}]},
                                    {"tool_choice": "auto"}, {"tool_choice": {"type": "function", "function": {"name": "ls"}}},
                                    {"function_call": "auto"}])
def test_legacy_tool_fields_are_tool_bearing(monkeypatch, tmp_path, extra):
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    assert EP.tool_bearing(extra)
    seen = []; g = _tool_graph(mock("light", seen), mock("coder", seen))
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={})); p = srv.server_address[1]
    _post_body(p, dict({"model": "x", "messages": [{"role": "user", "content": "x"}]}, **extra))
    assert seen[-1][0] == "coder"
    srv.shutdown()

def test_tool_choice_none_is_not_tool_bearing():
    assert not EP.tool_bearing({"messages": []})
    assert not EP.tool_bearing({"tool_choice": "none"})
    assert not EP.tool_bearing({"function_call": "none", "tools": []})

def test_invalid_tool_route_stays_put_with_no_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []; g = _tool_graph(mock("light", seen), mock("coder", seen), route="nope")
    assert EP.tool_target(g, "light") is None
    assert VG.tool_policy(g, "light") == [] and VG.tools_argv(g, "light") == []
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={})); p = srv.server_address[1]
    _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "x"}], "tools": TOOLS})
    assert seen[-1][0] == "light" and seen[-1][1]["model"] == "light"
    srv.shutdown()

def test_unreachable_tool_route_fails_closed_without_tools_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []; g = _tool_graph(mock("light", seen), 1)
    g["hosts"]["r"] = {"addr": "10.0.0.9"}; g["nodes"]["coder"]["host"] = "r"   # remote + loopback bind
    g["models"]["m"]["tool_calls"] = False   # routed-only light (not itself tool-capable)
    assert EP.tool_target(g, "light") == "coder" and EP.node_url(g, "coder", "h") is None
    assert VG.tools_argv(g, "light") == []    # light never launches with --tools; tools run only on coder
    esc = EP.Escalator(g, "light", [], "h", consent={})
    url, body = esc.rewrite({"model": "x", "messages": [{"role": "user", "content": "x"}], "tools": TOOLS})
    assert url is None
    assert esc.tool_note == "[familia] tool_route coder unreachable; refusing tool request (502)"

def test_unreachable_tool_route_returns_502_and_runs_no_tools(monkeypatch, tmp_path):
    """#251 fail-closed: unreachable tool_route target -> 502; current node never sees the tools."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []; g = _tool_graph(mock("light", seen), 1)
    g["hosts"]["r"] = {"addr": "10.0.0.9"}; g["nodes"]["coder"]["host"] = "r"   # remote + loopback bind
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={})); p = srv.server_address[1]
    with _pytest.raises(urllib.error.HTTPError) as ei:
        _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "x"}], "tools": TOOLS})
    assert ei.value.code == 502 and seen == []
    _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "x"}]})   # no tools: still served
    assert seen[-1][0] == "light"
    srv.shutdown()

def test_tool_route_target_down_mid_request_not_retried_on_current(monkeypatch, tmp_path):
    """#251: forwarded tool request whose target refuses -> 502, no redial with tools elsewhere."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); dead = s.getsockname()[1]; s.close()
    seen = []; g = _tool_graph(mock("light", seen), dead)
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={})); p = srv.server_address[1]
    with _pytest.raises(urllib.error.HTTPError) as ei:
        _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "x"}], "tools": TOOLS})
    assert ei.value.code == 502 and seen == []
    srv.shutdown()

def test_tool_target_logs_validate_graph_error(monkeypatch, capsys):
    """#251: validate_graph exceptions are logged, and the safe default (no forward) holds."""
    import validate_graph as VG_
    def boom(g, n): raise ValueError("bad graph")
    monkeypatch.setattr(VG_, "tool_route", boom)
    assert EP.tool_target({"nodes": {"a": {"tool_route": "b"}}}, "a") is None
    err = capsys.readouterr().err
    assert "validate_graph error" in err and "ValueError: bad graph" in err

def test_tool_forward_logged_source_to_target(monkeypatch, tmp_path):
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []; g = _tool_graph(mock("light", seen), mock("coder", seen))
    esc = EP.Escalator(g, "light", [], "h", consent={}); buf = io.StringIO()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), EP.make_handler(EP.EscalatorPool(lambda: esc, seed=("default", esc)), log=buf))
    threading.Thread(target=srv.serve_forever, daemon=True).start(); p = srv.server_address[1]
    secret = "list files SECRET-BODY"
    _post_body(p, {"model": "x", "messages": [{"role": "user", "content": secret}], "tools": TOOLS})
    _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "plain"}]})
    out = buf.getvalue()
    assert out.splitlines() == ["[familia] tool forward: light -> coder"]   # one line, no body/keys
    assert "SECRET" not in out
    srv.shutdown()


def test_tool_route_malformed_json_fails_closed_no_retry(monkeypatch, tmp_path):
    """#251 F1: tool_route target returns malformed JSON -> 502; never redial with tools on light."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    seen = []
    pl = mock("light", seen)
    pc = mock_raw("coder", seen, body_bytes=b"{not json")
    g = _tool_graph(pl, pc)
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={})); p = srv.server_address[1]
    with _pytest.raises(urllib.error.HTTPError) as ei:
        _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "x"}], "tools": TOOLS})
    assert ei.value.code == 502
    body = ei.value.read().decode()
    assert "tool_route" in body and "invalid JSON" in body
    # coder saw the tools request; light must not get a redial with tools.
    assert [s[0] for s in seen] == ["coder"]
    assert "tools" in seen[0][1]
    srv.shutdown()


def test_tool_route_malformed_json_while_escalated_not_retried_on_light(monkeypatch, tmp_path):
    """#251 F1: escalated session + tool forward + bad JSON must not resend tools to light."""
    monkeypatch.setattr(EP, "STATE", str(tmp_path)); monkeypatch.setattr(EP, "PENDING", str(tmp_path / "p.json"))
    monkeypatch.setenv("FAMILIA_ESCALATE", "auto")
    seen = []
    pl = mock("light", seen)
    ph = mock("heavy", seen)
    pc = mock_raw("coder", seen, body_bytes=b"{not json")
    g = {"hosts": {"h": {}}, "aliases": {"coder-a": {"node": "coder"}},
         "models": {"m": {"role": "chat"}, "c": {"role": "coder", "tool_calls": True},
                    "q": {"role": "chat"}},
         "nodes": {"light": {"host": "h", "port": pl, "model": "m", "bind": "0.0.0.0",
                            "escalates_to": ["heavy"],
                            "escalation": {"mode": "auto", "triggers": {"repeat_outputs": 0,
                                                                       "failure_retries": 0,
                                                                       "phrases": ["try harder"]}}},
                   "heavy": {"host": "h", "port": ph, "model": "q", "bind": "0.0.0.0",
                             "tool_route": "coder"},
                   "coder": {"host": "h", "port": pc, "model": "c", "bind": "127.0.0.1"}}}
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    post(p, [{"role": "user", "content": "please try harder"}])  # escalate to heavy
    assert esc.current == "heavy"
    with _pytest.raises(urllib.error.HTTPError) as ei:
        _post_body(p, {"model": "x", "messages": [{"role": "user", "content": "run tool"}], "tools": TOOLS})
    assert ei.value.code == 502
    # Before the fix, after_reply fell back to light and _retry_once resent tools there.
    light_tool = [s for s in seen if s[0] == "light" and isinstance(s[1], dict) and "tools" in s[1]]
    assert light_tool == [], f"light must not see tools; seen={seen}"
    assert any(s[0] == "coder" for s in seen)
    # Stay fail-closed: do not silently swap back via the malformed path.
    assert esc.current == "heavy"
    srv.shutdown()
