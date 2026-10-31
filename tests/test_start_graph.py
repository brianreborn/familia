import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import start_graph  # noqa: E402
import validate_graph  # noqa: E402

GRAPH = validate_graph.load(os.path.join(ROOT, "graph.yaml"))


def graph():
    return copy.deepcopy(GRAPH)


def test_host_selection_requires_an_exact_declared_graph_host(tmp_path):
    g = graph()
    env = {"XDG_STATE_HOME": str(tmp_path)}  # isolate from this machine's hostname pin
    assert start_graph.select_host(g, environ=dict(env), hostname="miryam.example") == "miryam"
    assert start_graph.select_host(g, requested="angel", environ={**env, "FAMILIA_HOST": "miryam"}) == "angel"
    with pytest.raises(start_graph.StartupError, match="not declared"):
        start_graph.select_host(g, environ=dict(env), hostname="codespace")
    # OS hostname can differ from the graph key via hosts.*.local_names
    assert start_graph.select_host(g, environ=dict(env), hostname="grok-bot-vm-414232872") == "box"


def test_local_topology_starts_only_local_active_nodes_and_routes():
    nodes, remote, gateways, omitted, remote_gateways = start_graph.local_topology(graph(), "miryam")
    assert nodes == ["coder", "embed"]
    assert {name for name, _ in remote} >= {"qodesh-gpu-decision", "qodesh-resident"}
    assert len(gateways) == 1
    name, gateway, aliases = gateways[0]
    assert name == "roomz"
    assert gateway["port"] == 9931
    assert aliases == {
        "coder": {"kind": "chat", "url": "http://127.0.0.1:9941", "tools": True},
        "general": {"kind": "chat", "url": "http://127.0.0.1:9941", "tools": True},
        "embed": {"kind": "embedding", "url": "http://127.0.0.1:9951"},
    }
    # planned/unbuilt roles on miryam are listed, not started (graph.yaml)
    assert {role for role, _node, host in omitted} == {"defender", "guardian", "pentest", "safe-build"}
    assert all(host == "miryam" for _r, _n, host in omitted)
    assert remote_gateways == []


def test_freebsd_host_runs_its_nodes_without_starting_a_gateway():
    # angel-coder is active on angel since the Nanbeige prize; the gateway stays on miryam
    nodes, remote, gateways, omitted, remote_gateways = start_graph.local_topology(graph(), "angel")
    assert nodes == ["angel-coder"]
    assert remote
    assert gateways == []
    assert omitted == []
    assert remote_gateways == [("roomz", "miryam")]


def test_local_active_node_with_unimplemented_runtime_fails_closed():
    g = graph()
    g["nodes"]["qodesh-gpu-decision"]["host"] = "miryam"
    with pytest.raises(start_graph.StartupError, match="unsupported runtime kind"):
        start_graph.validate_local_nodes(g, "miryam", ["qodesh-gpu-decision"], check_files=False)


def test_graph_proxy_manifest_preserves_graph_routes_without_remote_aliases():
    g = graph()
    _, _, gateways, _, _ = start_graph.local_topology(g, "miryam")
    name, gateway, aliases = gateways[0]
    manifest = start_graph.graph_proxy_manifest("miryam", gateway, aliases)
    assert manifest == {
        "schema_version": 1,
        "graph_host": "miryam",
        "gateway": {"host": "127.0.0.1", "port": 9931},
        "aliases": {n: {k: v for k, v in a.items() if k != "tools"} for n, a in aliases.items()},
    }


def _two_host():
    return validate_graph.load(os.path.join(ROOT, "examples", "graphs", "two-host.yaml"))


def test_single_node_aliases_keep_graph_proxy_shape():
    _n, _r, gws, omitted, _rg = start_graph.local_topology(_two_host(), "h1")
    (_name, _gw, aliases), = gws
    assert aliases == {"chat": {"kind": "chat", "url": "http://127.0.0.1:9001", "tools": True}}
    assert ("far", "far", "h2") in omitted


def test_fallback_list_alias_launches_graph_router(tmp_path, monkeypatch):
    g = _two_host()
    g["nodes"]["chat2"] = dict(g["nodes"]["chat"], port=9003)
    g["aliases"]["chat"]["node"] = ["chat", "chat2"]
    assert validate_graph.validate(g, check_files=False)[0] == []
    _n, _r, gws, _o, _rg = start_graph.local_topology(g, "h1")
    (name, gw, aliases), = gws
    assert [m["url"] for m in aliases["chat"]["members"]] == ["http://127.0.0.1:9001", "http://127.0.0.1:9003"]
    assert start_graph.needs_router(aliases)
    cfg = start_graph.router_routes(aliases)
    assert cfg["routes"] == {"chat": ["chat-node", "chat2"]}
    monkeypatch.setattr(start_graph, "CACHE", tmp_path)
    argv = start_graph.gateway_command("h1", name, gw, aliases, "/gr")
    assert argv[1].endswith("graph_router.py") and argv[-2:] == ["--port", "8080"]
    import json, graph_router
    compiled = graph_router.compile_config(json.loads(open(argv[2]).read()))
    assert compiled["routes"]["chat"]


def test_remote_member_needs_explicit_opt_in_and_reachable_bind():
    g = _two_host()
    g["aliases"]["far"]["remote"] = True                    # node bound to loopback: still omitted
    assert "far" not in start_graph.local_topology(g, "h1")[2][0][2]
    g["nodes"]["far"]["bind"] = "0.0.0.0"; g["hosts"]["h2"]["addr"] = "10.0.0.2"
    aliases = start_graph.local_topology(g, "h1")[2][0][2]
    assert aliases["far"]["members"][0]["url"] == "http://10.0.0.2:9002" and start_graph.needs_router(aliases)
    del g["aliases"]["far"]["remote"]                       # no consent: omitted again
    assert "far" not in start_graph.local_topology(g, "h1")[2][0][2]


def test_default_gateway_is_graph_router(tmp_path, monkeypatch):
    g = _two_host()
    (name, gw, aliases), = start_graph.local_topology(g, "h1")[2]
    assert start_graph.needs_router(aliases, gw)
    monkeypatch.setattr(start_graph, "CACHE", tmp_path)
    argv = start_graph.gateway_command("h1", name, gw, aliases, "/gr")
    assert argv[1].endswith("graph_router.py") and argv[-2:] == ["--port", "8080"]
    assert "--no-auth" not in argv  # caller auth on by default (per-port instance key)


def test_router_false_opts_out_to_graph_proxy(tmp_path, monkeypatch):
    g = _two_host(); g["gateways"]["gw"]["router"] = False
    assert validate_graph.validate(g, check_files=False)[0] == []
    (name, gw, aliases), = start_graph.local_topology(g, "h1")[2]
    assert not start_graph.needs_router(aliases, gw)
    monkeypatch.setattr(start_graph, "CACHE", tmp_path)
    assert start_graph.gateway_command("h1", name, gw, aliases, "/gr")[:3] == ["node", "/gr", "graph-proxy"]
    g["gateways"]["gw"]["router"] = "yes"
    assert validate_graph.validate(g, check_files=False)[0]


def test_router_false_still_routes_lists_via_graph_router():
    g = _two_host(); g["gateways"]["gw"]["router"] = False
    g["nodes"]["chat2"] = dict(g["nodes"]["chat"], port=9003); g["aliases"]["chat"]["node"] = ["chat", "chat2"]
    (_n, gw, aliases), = start_graph.local_topology(g, "h1")[2]
    assert start_graph.needs_router(aliases, gw)


def test_dry_run_reports_gateway_process(tmp_path):
    import subprocess, yaml
    for flag, via in ((None, "via graph_router (caller auth"), (False, "via graph-proxy")):
        g = _two_host()
        if flag is not None:
            g["gateways"]["gw"]["router"] = flag
        p = tmp_path / "g.yaml"; p.write_text(yaml.safe_dump(g))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "start_graph.py"), "--graph", str(p),
                            "--host", "h1", "--dry-run", "--fleet"], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, r.stderr
        assert via in r.stdout, r.stdout


def _cascade_graph():
    g = _two_host()
    g["nodes"]["critic"] = dict(g["nodes"]["chat"], port=9003)
    g["aliases"]["critic"] = {"node": "critic", "gateway": "gw"}
    g["agents"]["crit"] = dict(g["agents"]["ag"], aliases={"main": "critic", "auxiliary": "critic"})
    g["councils"] = {"review": {"experimental": True, "mode": "cascade", "agents": ["ag", "crit"]}}
    return g


def test_cascade_council_becomes_a_chain_route():
    """Regression: councils mode cascade validated but start_graph never compiled it into a route."""
    g = _cascade_graph()
    assert validate_graph.validate(g, check_files=False)[0] == []
    (_n, gw, aliases), = start_graph.local_topology(g, "h1")[2]
    assert "review" in aliases, "cascade council has no route on its gateway"
    assert [m["url"] for m in aliases["review"]["chain"]] == ["http://127.0.0.1:9001", "http://127.0.0.1:9003"]
    cfg = start_graph.router_routes(aliases)
    import graph_router
    route = graph_router.compile_config(cfg)["routes"]["review"]
    assert route["type"] == "chain" and [s["node"] for s in route["steps"]] == ["chat-node", "critic-node"]


def test_cascade_council_runs_agents_in_order(tmp_path, monkeypatch):
    """End to end through graph_router: ag's node answers first, its reply feeds crit's node."""
    import json, threading, urllib.request, graph_router
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    def stub(name):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                d = json.dumps({"choices": [{"message": {"role": "assistant",
                               "content": f"{name}({b['messages'][-1]['content']})"}}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
        s = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start(); return s
    a, b = stub("A"), stub("B")
    g = _cascade_graph(); g["nodes"]["chat"]["port"] = a.server_address[1]; g["nodes"]["critic"]["port"] = b.server_address[1]
    import familia_auth
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # tool nodes get their own per-port key
    for p in (a.server_address[1], b.server_address[1]):
        familia_auth.load_or_create_key_file(familia_auth.instance_key_file(port=p))
    (_n, _gw, aliases), = start_graph.local_topology(g, "h1")[2]
    srv = graph_router.make_server(graph_router.compile_config(start_graph.router_routes(aliases)), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions",
                                 json.dumps({"model": "review", "messages": [{"role": "user", "content": "x"}]}).encode(),
                                 {"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=10).read())
    except urllib.error.HTTPError as e:
        raise AssertionError(e.read().decode())
    assert r["choices"][0]["message"]["content"] == "B(A(x))"
    srv.shutdown(); a.shutdown(); b.shutdown()


def test_cascade_council_refuses_agent_off_gateway():
    g = _cascade_graph(); g["agents"]["crit"]["aliases"] = {"main": "far", "auxiliary": "far"}
    with pytest.raises(start_graph.StartupError, match="council review"):
        start_graph.local_topology(g, "h1")


def test_dry_run_prints_full_command_per_node(tmp_path):
    import subprocess, yaml
    p = tmp_path / "g.yaml"; p.write_text(yaml.safe_dump(_two_host()))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "start_graph.py"), "--graph", str(p),
                        "--host", "h1", "--dry-run", "--fleet"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    line = next(l for l in r.stdout.splitlines() if l.startswith("familia-graph: node chat: "))
    argv = line.split(": ", 2)[2].split()
    assert argv[0] == "llama-server" and argv[1] == "-m" and "--port" in argv and "-t" in argv


def test_launch_preflight_checks_the_real_binary(monkeypatch):
    """--launch used to take argv[0] ('-m') as the binary: preflight must look at llama-server itself."""
    g = _two_host()
    monkeypatch.setattr(start_graph.graph_validator, "validate", lambda *a, **k: ([], []))
    monkeypatch.setattr(start_graph.shutil, "which", lambda name: None)
    with pytest.raises(start_graph.StartupError, match=r"runtime for node chat is missing or not executable: .*llama-server$"):
        start_graph.validate_local_nodes(g, "h1", ["chat"], check_files=True)


def test_start_graph_passes_its_graph_to_serve_and_gate(tmp_path, monkeypatch):
    """Regression: --graph X validated X, but serve.sh and the license gate read the fleet graph.yaml."""
    import subprocess as sp
    calls = []
    monkeypatch.setattr(start_graph.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw["env"])) or sp.CompletedProcess(argv, 0))
    g = tmp_path / "mine.yaml"
    from pathlib import Path
    env = start_graph._run_gate_and_sync(Path(ROOT), True, g)
    assert env["FAMILIA_GRAPH"] == str(g)
    gates = [a for a, _ in calls if "gate" in a]
    assert len(gates) == 2 and all(a[a.index("--graph") + 1] == str(g) for a in gates)


def test_serve_sh_validates_familia_graph(tmp_path):
    import subprocess, yaml
    g = _two_host(); g["models"]["mchat"]["gguf"] = str(tmp_path / "only-in-this-graph.gguf")
    p = tmp_path / "g.yaml"; p.write_text(yaml.safe_dump(g))
    r = subprocess.run(["sh", os.path.join(ROOT, "scripts", "serve.sh"), "chat"], capture_output=True, text=True,
                       env=dict(os.environ, FAMILIA_GRAPH=str(p), FAMILIA_HOST="h1"), timeout=60)
    assert r.returncode != 0 and "only-in-this-graph.gguf" in r.stdout + r.stderr


def test_single_alias_to_tool_node_carries_its_key(tmp_path, monkeypatch):
    """Regression (live 9931 run): single-node aliases dropped tools, so graph_router sent no key -> 401."""
    import json, threading, urllib.request, graph_router, familia_auth
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"])); seen.append(self.headers.get("Authorization"))
            raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    s = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    g = _two_host(); g["nodes"]["chat"]["port"] = s.server_address[1]
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    key = familia_auth.load_or_create_key_file(familia_auth.instance_key_file(port=s.server_address[1]))
    (_n, gw, aliases), = start_graph.local_topology(g, "h1")[2]
    alias = next(a for a, v in aliases.items() if v.get("url", "").endswith(f":{s.server_address[1]}"))
    assert "tools" not in json.dumps(start_graph.graph_proxy_manifest("h1", gw, aliases))
    srv = graph_router.make_server(graph_router.compile_config(start_graph.router_routes(aliases)), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions",
                                 data=json.dumps({"model": alias, "messages": [{"role": "user", "content": "x"}]}).encode(),
                                 headers={"Content-Type": "application/json"})
    assert urllib.request.urlopen(req, timeout=10).status == 200
    assert seen and seen[0] and seen[0].startswith("Bearer ")


def test_stop_children_stops_the_server_under_serve_sh(tmp_path):
    """Regression (live 9931 run): SIGTERM reached serve.sh only; its llama-server kept the port."""
    import subprocess, time
    pidf = tmp_path / "grandchild.pid"
    child = subprocess.Popen(["sh", "-c", f"sleep 300 & echo $! > {pidf}; wait"], start_new_session=True)
    for _ in range(100):
        if pidf.exists() and pidf.read_text().strip(): break
        time.sleep(0.05)
    gc = int(pidf.read_text())
    start_graph._stop_children([(child, "node x")])
    for _ in range(100):
        try:
            os.kill(gc, 0)
            with open(f"/proc/{gc}/stat") as f:
                if f.read().split()[2] == "Z": break
        except (ProcessLookupError, FileNotFoundError):
            break
        time.sleep(0.05)
    else:
        os.kill(gc, 9)
        pytest.fail("grandchild (the llama-server stand-in) survived _stop_children")
