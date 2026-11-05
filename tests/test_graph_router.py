"""graph_router: every topology routes to the configured node, refuses cleanly, never hangs."""
import json, os, socket, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import graph_router as gr


class Fake:
    """Tiny OpenAI-compatible node: reply '<name>: <last user text>', or a fixed label."""
    def __init__(s, name, reply=None, status=200, hang=False, embed=False):
        s.name, s.reply, s.status, s.hang, s.embed, s.seen = name, reply, status, hang, embed, []
        me = s
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                me.seen.append((self.path, b, self.headers.get("Authorization")))
                if me.hang: time.sleep(5); return
                if me.embed: out = {"data": [{"embedding": [0.1], "index": 0}], "node": me.name}
                else:
                    u = [m["content"] for m in b["messages"] if m["role"] == "user"][-1]
                    txt = me.reply if me.reply is not None else f"{me.name}: {u}"
                    out = {"choices": [{"index": 0, "message": {"role": "assistant", "content": txt}}]}
                    if b.get("stream"):
                        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                        self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": txt}}]}).encode() + b"\n\ndata: [DONE]\n\n")
                        return
                raw = json.dumps(out if me.status == 200 else {"error": "x"}).encode()
                self.send_response(me.status); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        s.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); s.srv.daemon_threads = True
        s.url = f"http://127.0.0.1:{s.srv.server_address[1]}"
        threading.Thread(target=s.srv.serve_forever, daemon=True).start()
    def close(s): s.srv.shutdown(); s.srv.server_close()


def dead_url():
    so = socket.socket(); so.bind(("127.0.0.1", 0)); p = so.getsockname()[1]; so.close()
    return f"http://127.0.0.1:{p}"


@pytest.fixture
def fakes():
    made = []
    def mk(*a, **k):
        f = Fake(*a, **k); made.append(f); return f
    yield mk
    for f in made: f.close()


def serve(doc):
    cfg = gr.compile_config(doc)
    srv = gr.make_server(cfg, "127.0.0.1", 0); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    def post(model, text="hi", path="/v1/chat/completions", **extra):
        body = {"model": model, "messages": [{"role": "user", "content": text}], **extra}
        if path.endswith("embeddings"): body = {"model": model, "input": text}
        req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req, timeout=10); raw = r.read()
            return r.status, dict(r.headers), raw
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
    post.srv = srv
    return post


def content(raw): return json.loads(raw)["choices"][0]["message"]["content"]
def err(raw): return json.loads(raw)["error"]["message"]


# 1 single node --------------------------------------------------------------
def test_single_node_zero_boilerplate(fakes):
    a = fakes("a")
    post = serve({"nodes": {"a": a.url}})          # no routes: each node is its own route
    st, h, raw = post("a", "hello")
    assert st == 200 and content(raw) == "a: hello" and h["X-Familia-Node"] == "a"
    st, _, raw = post("nope")
    assert st == 404 and "unknown route nope" in err(raw) and "['a']" in err(raw)
    st, _, raw = post("a", path="/v1/embeddings")
    assert st == 400 and "serves chat, not embedding" in err(raw)
    assert len(a.seen) == 1


def test_single_embedding_node(fakes):
    e = fakes("e", embed=True)
    post = serve({"nodes": {"e": {"url": e.url, "kind": "embedding"}}})
    st, h, raw = post("e", path="/v1/embeddings")
    assert st == 200 and json.loads(raw)["node"] == "e"
    st, _, raw = post("e")
    assert st == 400


def test_single_node_down_is_503_not_hang():
    post = serve({"nodes": {"a": dead_url()}})
    t = time.monotonic(); st, _, raw = post("a")
    assert st == 503 and "node a" in err(raw) and "unreachable" in err(raw) and time.monotonic() - t < 3


def test_single_node_hang_times_out(fakes, monkeypatch):
    monkeypatch.setattr(gr, "READ_S", 0.5)
    h = fakes("h", hang=True)
    post = serve({"nodes": {"h": h.url}})
    t = time.monotonic(); st, _, raw = post("h")
    assert st == 504 and "timed out" in err(raw) and time.monotonic() - t < 3


# 2 chat + reasoning pair -----------------------------------------------------
def test_chat_reasoning_pair(fakes):
    c, r = fakes("chat-n"), fakes("think-n")
    post = serve({"nodes": {"chat-n": c.url, "think-n": r.url}, "routes": {"chat": "chat-n", "think": "think-n"}})
    assert content(post("chat", "x")[2]) == "chat-n: x"
    assert content(post("think", "y")[2]) == "think-n: y"
    assert len(c.seen) == 1 and len(r.seen) == 1


# 3 router fan-out -------------------------------------------------------------
def router_doc(clf, code, math, default=None):
    d = {"nodes": {"clf": clf.url, "code": code.url, "math": math.url},
         "routes": {"ask": {"router": "clf", "routes": {"code": "code", "math": "math"}}}}
    if default: d["routes"]["ask"]["default"] = default
    return d


def test_router_fans_out_by_label(fakes):
    clf, code, math = fakes("clf", reply="Math."), fakes("code"), fakes("math")
    post = serve(router_doc(clf, code, math))
    st, h, raw = post("ask", "2+2?")
    assert st == 200 and content(raw) == "math: 2+2?" and h["X-Familia-Node"] == "math" and h["X-Familia-Route-Label"] == "math"
    assert not code.seen and "code, math" in clf.seen[0][1]["messages"][0]["content"]


def test_router_slash_override_skips_classifier(fakes):
    clf, code, math = fakes("clf", reply="math"), fakes("code"), fakes("math")
    post = serve(router_doc(clf, code, math))
    st, h, raw = post("ask", "/code write fizzbuzz")
    assert content(raw) == "code: write fizzbuzz" and not clf.seen


def test_router_unknown_label_refused_without_default(fakes):
    clf, code, math = fakes("clf", reply="poetry"), fakes("code"), fakes("math")
    post = serve(router_doc(clf, code, math))
    st, _, raw = post("ask", "a poem")
    assert st == 502 and "no known label" in err(raw) and "poetry" in err(raw)
    assert not code.seen and not math.seen


def test_router_unknown_label_uses_explicit_default(fakes):
    clf, code, math = fakes("clf", reply="poetry"), fakes("code"), fakes("math")
    post = serve(router_doc(clf, code, math, default="code"))
    st, h, raw = post("ask", "a poem")
    assert st == 200 and h["X-Familia-Route-Label"] == "<default>" and h["X-Familia-Node"] == "code"


def test_router_specialist_down_is_503(fakes):
    clf, code = fakes("clf", reply="math"), fakes("code")
    d = router_doc(clf, code, code); d["nodes"]["math"] = dead_url()
    post = serve(d)
    st, _, raw = post("ask", "1+1")
    assert st == 503 and "math" in err(raw) and not code.seen


# 4 chain -------------------------------------------------------------------------
def test_chain_a_b_c(fakes):
    a, b, c = fakes("a"), fakes("b"), fakes("c")
    post = serve({"nodes": {"a": a.url, "b": b.url, "c": c.url},
                  "routes": {"pipe": {"chain": ["a", {"node": "b", "prompt": "refine: {input}"}, "c"]}}})
    st, h, raw = post("pipe", "q")
    assert st == 200 and content(raw) == "c: b: refine: a: q" and h["X-Familia-Chain"] == "a>b>c" and h["X-Familia-Node"] == "c"


def test_chain_middle_step_down(fakes):
    a, c = fakes("a"), fakes("c")
    post = serve({"nodes": {"a": a.url, "b": dead_url(), "c": c.url}, "routes": {"pipe": {"chain": ["a", "b", "c"]}}})
    st, _, raw = post("pipe", "q")
    assert st == 503 and "step 2/3 (b)" in err(raw) and not c.seen


def test_chain_streams_only_the_final_step(fakes):
    a, b, c = fakes("a"), fakes("b"), fakes("c")
    post = serve({"nodes": {"a": a.url, "b": b.url, "c": c.url}, "routes": {"pipe": {"chain": ["a", "b", "c"]}}})
    st, h, raw = post("pipe", "q", stream=True)
    assert st == 200 and h["Content-Type"].startswith("text/event-stream")
    assert raw.startswith(b"data: ") and b"c: b: a: q" in raw and raw.rstrip().endswith(b"[DONE]")
    assert h["X-Familia-Node"] == "c" and h["X-Familia-Chain"] == "a>b>c"
    assert a.seen[0][1]["stream"] is False and b.seen[0][1]["stream"] is False and c.seen[0][1]["stream"] is True


def test_chain_stream_earlier_step_down_is_json_error(fakes):
    b = fakes("b")
    post = serve({"nodes": {"a": dead_url(), "b": b.url}, "routes": {"pipe": {"chain": ["a", "b"]}}})
    st, _, raw = post("pipe", "q", stream=True)
    assert st == 503 and "step 1/2 (a)" in err(raw) and not b.seen


def test_router_streams_the_chosen_target(fakes):
    clf, code = fakes("clf", reply="code"), fakes("code")
    post = serve({"nodes": {"clf": clf.url, "code": code.url},
                  "routes": {"ask": {"router": "clf", "routes": {"code": "code"}}}})
    st, h, raw = post("ask", "fix it", stream=True)
    assert st == 200 and raw.startswith(b"data: ") and b"code: fix it" in raw
    assert h["X-Familia-Node"] == "code" and h["X-Familia-Route-Label"] == "code"
    assert clf.seen[0][1]["stream"] is False and code.seen[0][1]["stream"] is True


def test_chain_step_http_error_not_200(fakes):
    a, b = fakes("a", status=400), fakes("b")
    post = serve({"nodes": {"a": a.url, "b": b.url}, "routes": {"pipe": {"chain": ["a", "b"]}}})
    st, _, raw = post("pipe", "q")
    assert st == 502 and "step 1" in err(raw) and not b.seen


# 5 tool nodes ----------------------------------------------------------------------
def test_tool_node_gets_its_own_key(fakes, tmp_path):
    t, plain = fakes("t"), fakes("p")
    kf = tmp_path / "api-keys"; kf.write_text("# k\nsecret-t\n")
    post = serve({"nodes": {"t": {"url": t.url, "tools": True, "key_file": str(kf)}, "p": plain.url}})
    assert post("t")[0] == 200 and t.seen[0][2] == "Bearer secret-t"
    assert post("p")[0] == 200 and plain.seen[0][2] is None     # no key leaks to a non-tool node


def test_tool_node_without_key_refused(fakes, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    t = fakes("t")
    post = serve({"nodes": {"t": {"url": t.url, "tools": True}}})
    st, _, raw = post("t")
    assert st == 503 and "no readable API key" in err(raw) and not t.seen


def test_tool_node_uses_instance_key_file(fakes, tmp_path, monkeypatch):
    """Local tool node: the per-port instance key written by H4 tool_key_file (#264)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    t = fakes("t"); port = int(t.url.rsplit(":", 1)[1])
    import familia_auth
    key = familia_auth.load_or_create_key_file(familia_auth.instance_key_file(port=port))
    post = serve({"nodes": {"t": {"url": t.url, "tools": True}}})
    assert post("t")[0] == 200 and t.seen[0][2] == "Bearer " + key


# 6 remote node ------------------------------------------------------------------------
def test_remote_node_needs_explicit_opt_in():
    with pytest.raises(gr.ConfigError, match="set remote: true"):
        gr.compile_config({"nodes": {"r": "http://192.0.2.10:8081"}})
    cfg = gr.compile_config({"nodes": {"r": {"url": "http://192.0.2.10:8081", "remote": True}}})
    assert cfg["nodes"]["r"]["remote"] and cfg["routes"]["r"]["nodes"] == ["r"]


def test_remote_node_down_is_fast_503(monkeypatch):
    monkeypatch.setattr(gr, "CONNECT_S", 0.5)
    post = serve({"nodes": {"r": {"url": "http://192.0.2.10:8081", "remote": True}}})   # TEST-NET-1: unroutable
    t = time.monotonic(); st, _, raw = post("r")
    assert st == 503 and "node r" in err(raw) and time.monotonic() - t < 3


def _graph():
    return {"hosts": {"here": {"addr": "REPLACE_ME"}, "far": {"addr": "192.0.2.7"}, "nowhere": {"addr": "REPLACE_ME"}},
            "models": {"m": {"role": "chat"}, "g": {"role": "guardian"}, "e": {"role": "embed"}},
            "nodes": {"local": {"host": "here", "bind": "127.0.0.1", "port": 8081, "status": "active", "model": "m"},
                      "farnode": {"host": "far", "bind": "0.0.0.0", "port": 8082, "status": "active", "model": "m"},
                      "farlo": {"host": "far", "bind": "127.0.0.1", "port": 8083, "status": "active", "model": "m"},
                      "lost": {"host": "nowhere", "bind": "0.0.0.0", "port": 8084, "status": "active", "model": "m"},
                      "plan": {"host": "here", "bind": "127.0.0.1", "port": 8085, "status": "planned", "model": "m"},
                      "guard": {"host": "here", "bind": "127.0.0.1", "port": 8086, "status": "active", "model": "g"},
                      "emb": {"host": "here", "bind": "127.0.0.1", "port": 8087, "status": "active", "model": "e", "embeddings": True}},
            "aliases": {"chat": {"node": "local", "gateway": "gw"}}}


def test_graph_backed_nodes_and_aliases():
    g = _graph()
    nodes, refused = gr.nodes_from_graph(g, "here")
    assert nodes["local"]["url"] == "http://127.0.0.1:8081"
    assert nodes["farnode"]["url"] == "http://192.0.2.7:8082" and nodes["farnode"]["remote"]
    assert nodes["emb"]["kind"] == "embedding"
    assert "loopback" in refused["farlo"] and "no addr" in refused["lost"]
    assert "planned" in refused["plan"] and "slash-only" in refused["guard"]
    nodes["farnode"]["remote"] = True
    cfg = gr.compile_config({"routes": {"far": "farnode"}}, graph=g, here="here")
    assert cfg["routes"]["chat"]["nodes"] == ["local"]      # graph alias becomes a route for free
    with pytest.raises(gr.ConfigError, match="planned"):
        gr.compile_config({"routes": {"p": "plan"}}, graph=g, here="here")
    with pytest.raises(gr.ConfigError, match="slash-only"):
        gr.compile_config({"routes": {"p": "guard"}}, graph=g, here="here")


# 7 fallback ---------------------------------------------------------------------------
def test_fallback_primary_down(fakes):
    b = fakes("b")
    post = serve({"nodes": {"a": dead_url(), "b": b.url}, "routes": {"ask": ["a", "b"]}})
    st, h, raw = post("ask", "x")
    assert st == 200 and content(raw) == "b: x" and h["X-Familia-Node"] == "b"


def test_fallback_primary_loading_503(fakes):
    a, b = fakes("a", status=503), fakes("b")
    post = serve({"nodes": {"a": a.url, "b": b.url}, "routes": {"ask": {"fallback": ["a", "b"]}}})
    st, h, raw = post("ask")
    assert st == 200 and h["X-Familia-Node"] == "b" and len(a.seen) == 1


def test_fallback_client_error_not_masked(fakes):
    a, b = fakes("a", status=400), fakes("b")
    post = serve({"nodes": {"a": a.url, "b": b.url}, "routes": {"ask": ["a", "b"]}})
    st, h, _ = post("ask")
    assert st == 400 and h["X-Familia-Node"] == "a" and not b.seen   # a 4xx is the right node's answer


def test_fallback_all_down_lists_each(fakes):
    post = serve({"nodes": {"a": dead_url(), "b": dead_url()}, "routes": {"ask": ["a", "b"]}})
    t = time.monotonic(); st, _, raw = post("ask")
    e = json.loads(raw)["error"]
    assert st == 503 and "no node reachable" in e["message"] and len(e["tried"]) == 2 and time.monotonic() - t < 3


def test_fallback_stream(fakes):
    b = fakes("b")
    post = serve({"nodes": {"a": dead_url(), "b": b.url}, "routes": {"ask": ["a", "b"]}})
    st, h, raw = post("ask", "s", stream=True)
    assert st == 200 and b"b: s" in raw and h["X-Familia-Node"] == "b"


def test_fallback_of_route(fakes):
    """A router target may be a fallback route (specialist with a backup)."""
    clf, b = fakes("clf", reply="code"), fakes("b")
    post = serve({"nodes": {"clf": clf.url, "a": dead_url(), "b": b.url},
                  "routes": {"code": ["a", "b"], "ask": {"router": "clf", "routes": {"code": "code"}}}})
    st, h, raw = post("ask", "x")
    assert st == 200 and h["X-Familia-Node"] == "b"


# config errors ------------------------------------------------------------------------
@pytest.mark.parametrize("doc,msg", [
    ({"nodes": {"a": "http://127.0.0.1:1"}, "routes": {"x": "zz"}}, "unknown node or route 'zz'"),
    ({"nodes": {"a": "http://127.0.0.1:1"}, "routes": {"x": {"chain": ["a"]}}}, "at least 2 steps"),
    ({"nodes": {"a": "http://127.0.0.1:1"}, "routes": {"x": {"node": "a", "chain": ["a", "a"]}}}, "exactly one of"),
    ({"nodes": {"a": "http://127.0.0.1:1"}, "routes": {"x": "y", "y": "x"}}, "route cycle"),
    ({"nodes": {"a": "http://127.0.0.1:1", "b": "http://127.0.0.1:2"}, "routes": {"a": "b"}}, "also a node"),
    ({"nodes": {"a": "ftp://127.0.0.1:1"}}, "http://host:port"),
    ({"nodes": {"a": "http://127.0.0.1:1", "e": {"url": "http://127.0.0.1:2", "kind": "embedding"}},
      "routes": {"x": ["a", "e"]}}, "mixes chat and embedding"),
    ({"nodes": {"a": "http://127.0.0.1:1"}, "routes": {"x": {"router": "a", "routes": {"Big": "a"}}}}, "lowercase"),
    ({"version": 2}, "version: 1"),
])
def test_config_errors(doc, msg):
    with pytest.raises(gr.ConfigError, match=msg.replace("(", r"\(").replace("[", r"\[")):
        gr.compile_config(doc)


def test_examples_compile():
    d = os.path.join(os.path.dirname(__file__), "..", "examples", "graphs", "router")
    files = sorted(f for f in os.listdir(d) if f.endswith(".yaml"))
    assert len(files) >= 6
    for f in files:
        gr.load(os.path.join(d, f))


def test_graph_alias_to_planned_node_is_409_not_dropped():
    g = _graph(); g["aliases"]["later"] = {"node": "plan", "gateway": "gw"}
    cfg = gr.compile_config({}, graph=g, here="here")
    assert "later" not in cfg["routes"] and "planned" in cfg["refused_routes"]["later"]
    srv = gr.make_server(cfg, "127.0.0.1", 0); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions",
                                 json.dumps({"model": "later", "messages": []}).encode())
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 409 and "planned" in json.loads(e.value.read())["error"]["message"]


# caller auth (H4 pattern) ----------------------------------------------------------
def _authed_server(fakes, key="caller-key-1"):
    a = fakes("a")
    srv = gr.make_server(gr.compile_config({"nodes": {"a": a.url}}), "127.0.0.1", 0, api_key=key)
    srv.daemon_threads = True; threading.Thread(target=srv.serve_forever, daemon=True).start()
    return a, f"http://127.0.0.1:{srv.server_address[1]}"


def _call(base, path="/v1/chat/completions", headers=None, body=True):
    data = json.dumps({"model": "a", "messages": [{"role": "user", "content": "hi"}]}).encode() if body else None
    req = urllib.request.Request(base + path, data, {"Content-Type": "application/json", **(headers or {})})
    try:
        r = urllib.request.urlopen(req, timeout=5); return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_router_caller_auth_required(fakes):
    a, base = _authed_server(fakes)
    assert _call(base)[0] == 401
    assert _call(base, headers={"Authorization": "Bearer wrong"})[0] == 401
    assert _call(base, "/v1/models", body=False)[0] == 401
    assert not a.seen                                         # nothing reached the node
    assert _call(base, "/health", body=False)[0] == 200       # health stays public
    st, raw = _call(base, headers={"Authorization": "Bearer caller-key-1"})
    assert st == 200 and content(raw) == "a: hi"
    assert _call(base, headers={"X-Api-Key": "caller-key-1"})[0] == 200
    assert a.seen[0][2] is None                               # caller key is never forwarded to a node


def test_router_main_creates_instance_key_once(tmp_path, monkeypatch):
    """CLI default: per-port instance key, created 0600 on first start, never rotated; fail closed."""
    import stat, familia_auth
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path)); monkeypatch.delenv("API_KEY_FILE", raising=False)
    cfgf = tmp_path / "r.yaml"; cfgf.write_text("version: 1\nnodes: {a: 'http://127.0.0.1:1'}\n")
    started = []
    monkeypatch.setattr(gr, "make_server", lambda cfg, h, p, api_key=None: started.append(api_key) or
                        type("S", (), {"serve_forever": lambda s: None})())
    assert gr.main([str(cfgf), "--port", "19999"]) == 0
    path = familia_auth.instance_key_file(port=19999)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and started[0] == familia_auth._read(path)
    assert gr.main([str(cfgf), "--port", "19999"]) == 0 and started[1] == started[0]
    assert gr.main([str(cfgf), "--port", "19999", "--no-auth"]) == 0 and started[2] is None
    assert gr.main([str(cfgf), "--api-key-file", "/proc/familia-no-such/k"]) == 2   # fail closed
