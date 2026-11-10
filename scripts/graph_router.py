#!/usr/bin/env python3
"""familia graph router: one OpenAI-compatible endpoint for every common graph shape.

Topologies (docs/graph-recipes.md, examples/graphs/router/):
  single      route: node
  pair        two routes, e.g. chat: chat-node, think: reasoning-node
  fallback    route: [primary, backup, ...]          first reachable node answers
  chain       route: {chain: [a, b, c]}              a's reply is b's input, ...
  router      route: {router: clf, routes: {label: target}, default: target?}
  remote      a node whose URL is another host; needs `remote: true` on the node
  tools       a node with tools: true (or a tool-enabled graph node) gets its own
              per-instance key on every forwarded request

Rules (the point of this file):
  * the route and node come only from config, never from model output except the
    router's label, which must match a configured label exactly (else default, else 502)
  * failures are refused with a JSON error naming the route/node; never a 200 from a
    node the route did not name, never a silent default; connect timeouts are short
  * every reply carries X-Familia-Route and X-Familia-Node (the node that answered)

Config is a small YAML (`routes.yaml`), optionally pointing at a graph.yaml so node
names resolve from the graph (url from bind/port and the hosts overlay addr).
"""
import argparse, http.client, json, os, re, sys, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SLASH_ONLY = {"guardian", "pentest", "defender"}
KINDS = {"chat", "embedding"}
CONNECT_S = float(os.environ.get("FAMILIA_ROUTER_CONNECT_S", "3"))
READ_S = float(os.environ.get("FAMILIA_ROUTER_TIMEOUT_S", "600"))
BODY_LIMIT = 16 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ConfigError(ValueError):
    pass


class RouteError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message); self.status = status; self.extra = extra


# ---------------------------------------------------------------- config ----

def _is_loopback(host):
    return (host or "").strip("[]") in LOOPBACK or (host or "").startswith("127.")


def _node(name, spec):
    if isinstance(spec, str):
        spec = {"url": spec}
    if not isinstance(spec, dict) or not isinstance(spec.get("url"), str):
        raise ConfigError(f"node {name}: needs a url (string or {{url: ...}})")
    u = urllib.parse.urlparse(spec["url"])
    if u.scheme != "http" or not u.hostname or not u.port:
        raise ConfigError(f"node {name}: url must be http://host:port (got {spec['url']!r})")
    if u.path not in ("", "/") or u.query or u.username:
        raise ConfigError(f"node {name}: url must contain only scheme, host and port")
    kind = spec.get("kind", "chat")
    if kind not in KINDS:
        raise ConfigError(f"node {name}: kind must be chat|embedding (got {kind!r})")
    remote = not _is_loopback(u.hostname)
    if remote and spec.get("remote") is not True:
        raise ConfigError(f"node {name}: {u.hostname} is not loopback; set remote: true to allow a remote node")
    return {"name": name, "url": f"http://{u.netloc}", "host": u.hostname, "port": u.port, "kind": kind,
            "remote": remote, "tools": bool(spec.get("tools")), "key_file": spec.get("key_file"),
            "graph_host": spec.get("graph_host")}


def nodes_from_graph(graph, here=None):
    """Routable nodes of a familia graph.yaml (hosts overlay applied by familia_yaml).
    Planned and slash-only TYPEs are recorded as refusals, not dropped silently."""
    out, refused = {}, {}
    hosts = graph.get("hosts") or {}
    models = graph.get("models") or {}
    for name, n in (graph.get("nodes") or {}).items():
        role = n.get("role") or (models.get(n.get("model")) or {}).get("role")
        if n.get("status") != "active":
            refused[name] = f"node {name} is {n.get('status') or 'not active'}; not auto-routable"; continue
        if role in SLASH_ONLY:
            refused[name] = f"node {name} is TYPE {role} (slash-only); not routable here"; continue
        h = n.get("host")
        local = here is None or h == here
        if local:
            addr = "127.0.0.1" if _is_loopback(n.get("bind")) or n.get("bind") in ("0.0.0.0", "::") else n.get("bind")
        else:
            addr = (hosts.get(h) or {}).get("addr")
            if not addr or addr == "REPLACE_ME":
                refused[name] = f"node {name} is on host {h} with no addr (set it in hosts.local.yaml)"; continue
            if _is_loopback(n.get("bind")):
                refused[name] = f"node {name} on host {h} binds loopback ({n.get('bind')}); unreachable from {here}"; continue
        tools = False
        try:
            import validate_graph as vg
            tools = bool(vg.tool_policy(graph, name))
        except Exception:
            pass
        out[name] = {"url": f"http://{addr}:{n['port']}", "kind": "embedding" if n.get("embeddings") else "chat",
                     "remote": not local, "tools": tools, "graph_host": h}
    return out, refused


def _target(cfg, ref, where):
    # A graph alias named like its own planned/slash-only node (embed -> embed) is not a route
    # to itself: refuse it (409) instead of resolving to the alias and reporting a cycle (#231).
    if ref in cfg["refused"] and ref not in cfg["nodes"] and cfg["raw_routes"].get(ref, ref) == ref:
        raise ConfigError(f"{where}: {cfg['refused'][ref]}")
    if ref in cfg["nodes"] or ref in cfg["raw_routes"]:
        return ref
    if ref in cfg["refused"]:
        raise ConfigError(f"{where}: {cfg['refused'][ref]}")
    raise ConfigError(f"{where}: unknown node or route {ref!r} (nodes: {sorted(cfg['nodes'])})")


def _route(cfg, name, spec):
    where = f"route {name}"
    if isinstance(spec, str):
        return {"type": "single", "nodes": [_target(cfg, spec, where)]}
    if isinstance(spec, list):
        if not spec: raise ConfigError(f"{where}: empty fallback list")
        return {"type": "fallback", "nodes": [_target(cfg, s, where) for s in spec]}
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: must be a node name, a list (fallback), or a map")
    keys = {"node", "fallback", "chain", "router"} & set(spec)
    if len(keys) != 1:
        raise ConfigError(f"{where}: exactly one of node|fallback|chain|router (got {sorted(keys) or 'none'})")
    k = keys.pop()
    if k == "node":
        return {"type": "single", "nodes": [_target(cfg, spec["node"], where)]}
    if k == "fallback":
        r = _route(cfg, name, list(spec["fallback"])); return r
    if k == "chain":
        steps = []
        for i, s in enumerate(spec["chain"] or []):
            s = {"node": s} if isinstance(s, str) else dict(s)
            s["node"] = _target(cfg, s.get("node"), f"{where} step {i + 1}")
            if "prompt" in s and "{input}" not in s["prompt"]:
                raise ConfigError(f"{where} step {i + 1}: prompt must contain {{input}}")
            steps.append(s)
        if len(steps) < 2: raise ConfigError(f"{where}: a chain needs at least 2 steps")
        return {"type": "chain", "steps": steps}
    labels = spec.get("routes") or {}
    if not isinstance(labels, dict) or not labels:
        raise ConfigError(f"{where}: router needs routes: {{label: target}}")
    bad = [l for l in labels if not re.fullmatch(r"[a-z0-9_-]+", str(l))]
    if bad: raise ConfigError(f"{where}: labels must be lowercase [a-z0-9_-] (bad: {bad})")
    return {"type": "router", "router": _target(cfg, spec["router"], where),
            "labels": {str(l): _target(cfg, t, f"{where} label {l}") for l, t in labels.items()},
            "default": _target(cfg, spec["default"], where) if spec.get("default") else None,
            "slash": spec.get("slash", True)}


def compile_config(doc, base_dir=".", graph=None, here=None):
    """routes.yaml dict -> {nodes, routes}. Raises ConfigError with one clear message."""
    if not isinstance(doc, dict) or doc.get("version", 1) != 1:
        raise ConfigError("routes config needs version: 1")
    cfg = {"nodes": {}, "refused": {}, "raw_routes": dict(doc.get("routes") or {}), "refused_routes": {}}
    imported = set()
    if graph is None and doc.get("graph"):
        import familia_yaml
        graph = familia_yaml.load(os.path.join(base_dir, doc["graph"]))
    here = doc.get("host", here)
    specs = {}
    if graph is not None:
        specs, cfg["refused"] = nodes_from_graph(graph, here)
        for alias, a in (graph.get("aliases") or {}).items():   # graph aliases are routes for free
            if isinstance(a, dict) and isinstance(a.get("node"), str):
                if alias not in cfg["raw_routes"]:
                    cfg["raw_routes"][alias] = a["node"]; imported.add(alias)
    for n, s in (doc.get("nodes") or {}).items():
        specs[n] = s if n not in specs or not isinstance(s, dict) else {**specs[n], **s}
    for n, s in specs.items():
        if not NAME_RE.match(str(n)): raise ConfigError(f"invalid node name {n!r}")
        cfg["nodes"][n] = _node(n, s)
    if not cfg["raw_routes"]:   # zero-boilerplate default: every node is its own route
        cfg["raw_routes"] = {n: n for n in cfg["nodes"]}
    routes = {}
    for r, s in cfg["raw_routes"].items():
        if not NAME_RE.match(str(r)): raise ConfigError(f"invalid route name {r!r}")
        if r in cfg["nodes"] and s != r:
            raise ConfigError(f"route {r}: name is also a node; rename the route (a route may share a name only with the node it targets)")
        try:
            routes[r] = _route(cfg, r, s)
        except ConfigError as e:
            if r not in imported: raise
            cfg["refused_routes"][r] = str(e)   # graph alias to a planned/slash-only node: 409, not dropped
    cfg["routes"] = routes
    _check_cycles(cfg)
    for r, rt in routes.items():   # kinds must agree; chains/routers are chat only
        kinds = {cfg["nodes"][n]["kind"] for n in _leaf_nodes(cfg, r)}
        if len(kinds) > 1: raise ConfigError(f"route {r}: mixes chat and embedding nodes")
        if rt["type"] in ("chain", "router") and kinds != {"chat"}:
            raise ConfigError(f"route {r}: {rt['type']} routes need chat nodes")
        rt["kind"] = kinds.pop()
    del cfg["raw_routes"]
    return cfg


def _refs(rt):
    if rt["type"] in ("single", "fallback"): return list(rt["nodes"])
    if rt["type"] == "chain": return [s["node"] for s in rt["steps"]]
    return [rt["router"], *rt["labels"].values()] + ([rt["default"]] if rt["default"] else [])


def _leaf_nodes(cfg, ref, seen=()):
    if ref in cfg["nodes"] and ref not in cfg["routes"]: return [ref]
    rt = cfg["routes"][ref]
    if rt["type"] == "router":
        refs = [*rt["labels"].values()] + ([rt["default"]] if rt["default"] else [])
    else:
        refs = _refs(rt)
    out = []
    for x in refs:
        out += [x] if x in cfg["nodes"] and (x not in cfg["routes"] or x == ref) else _leaf_nodes(cfg, x, seen + (ref,))
    return out


def _check_cycles(cfg):
    def walk(r, stack):
        if r in stack: raise ConfigError("route cycle: " + " -> ".join(stack + [r]))
        if r not in cfg["routes"]: return
        for x in _refs(cfg["routes"][r]):
            if x == r and x in cfg["nodes"]: continue   # route named like its node
            walk(x, stack + [r])
    for r in cfg["routes"]: walk(r, [])


def load(path, here=None):
    import yaml
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return compile_config(doc, os.path.dirname(os.path.abspath(path)), here=here)


# --------------------------------------------------------------- runtime ----

class Down(Exception):
    """Node unreachable or not ready: the only failure a fallback may skip."""


def _key_headers(node):
    if not node["tools"] and not node.get("key_file"):
        return {}
    import familia_auth
    path = node.get("key_file")
    if path:
        k = familia_auth._read(os.path.expanduser(path))
    elif not node["remote"]:
        k = familia_auth._read(familia_auth.instance_key_file(port=node["port"]))
    else:
        k = ""
    if not k:
        raise RouteError(503, f"node {node['name']} is tool-enabled but has no readable API key "
                              f"(key_file or ~/.config/familia/instances/{node['port']}/api-keys)", node=node["name"])
    return {"Authorization": "Bearer " + k}


def call_node(node, path, body, stream_to=None):
    """POST body to node. Returns (status, headers, bytes) or streams to stream_to(status, headers, iter)."""
    data = json.dumps(dict(body, model=body.get("model") and node["name"])).encode()
    headers = {"Content-Type": "application/json", **_key_headers(node)}
    conn = http.client.HTTPConnection(node["host"], node["port"], timeout=CONNECT_S)
    try:
        conn.connect()
    except (OSError, http.client.HTTPException) as e:
        conn.close(); raise Down(f"node {node['name']} ({node['url']}) unreachable: {e.__class__.__name__}: {e}")
    conn.sock.settimeout(READ_S)
    try:
        conn.request("POST", path, body=data, headers=headers)
        r = conn.getresponse()
    except TimeoutError:
        conn.close(); raise RouteError(504, f"node {node['name']} timed out after {READ_S:.0f}s", node=node["name"])
    except (OSError, http.client.HTTPException) as e:
        conn.close(); raise Down(f"node {node['name']} dropped the connection: {e.__class__.__name__}")
    if r.status in (502, 503):    # llama-server 503 = loading/unavailable: let fallback try the next
        msg = r.read()[:300].decode("utf-8", "replace"); conn.close()
        raise Down(f"node {node['name']} answered {r.status}: {msg}")
    if stream_to is not None and r.status == 200:
        def it():
            try:
                while True:
                    b = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                    if not b: return
                    yield b
            finally:
                conn.close()
        return stream_to(r.status, dict(r.getheaders()), it())
    raw = r.read(); conn.close()
    return r.status, dict(r.getheaders()), raw


def _content(raw, who):
    try:
        return json.loads(raw)["choices"][0]["message"]["content"] or ""
    except Exception:
        raise RouteError(502, f"{who} returned a reply without choices[0].message.content")


def _last_user(body):
    for m in reversed(body.get("messages") or []):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return ""


class Router:
    def __init__(self, cfg):
        self.cfg = cfg

    def node(self, n):
        return self.cfg["nodes"][n]

    def run(self, ref, path, body, trail, stream_to=None):
        """Resolve ref (route or node) and serve. Returns (status, headers, raw, node_name)."""
        if ref in self.cfg["routes"] and not (self.cfg["routes"][ref]["type"] == "single"
                                              and self.cfg["routes"][ref]["nodes"] == [ref] and ref in self.cfg["nodes"]):
            return self.route(ref, path, body, trail, stream_to)
        n = self.node(ref)
        if stream_to is not None:
            outer = stream_to
            stream_to = lambda st, h, it: outer(st, dict(h, **{"X-Familia-Node": ref}), it)
        res = call_node(n, path, body, stream_to)
        return (*res, ref) if isinstance(res, tuple) else (None, None, None, ref)

    def route(self, name, path, body, trail, stream_to=None):
        rt = self.cfg["routes"][name]
        trail.append(name)
        if rt["type"] in ("single", "fallback"):
            tried = []
            for ref in rt["nodes"]:
                try:
                    return self.run(ref, path, body, trail, stream_to)
                except Down as e:
                    tried.append(str(e))
            raise RouteError(503, (f"route {name}: no node reachable" if len(tried) > 1 else f"route {name}: {tried[0]}"),
                             route=name, tried=tried)
        def tag(extra):  # add route headers to a streamed reply
            return None if stream_to is None else (lambda st, h, it: stream_to(st, dict(h, **extra), it))
        if rt["type"] == "chain":
            # stream=true: steps 1..n-1 run non-streamed (their text feeds the next step); only the final
            # step streams to the client
            text, served, last = None, [], len(rt["steps"]) - 1
            for i, s in enumerate(rt["steps"]):
                b = body if i == 0 else dict(body, messages=[{"role": "user", "content": s.get("prompt", "{input}").replace("{input}", text)}])
                if i == 0 and s.get("prompt"):
                    b = dict(body, messages=[{"role": "user", "content": s["prompt"].replace("{input}", _last_user(body))}])
                final_stream = i == last and stream_to is not None and body.get("stream")
                if not final_stream:
                    b = dict(b, stream=False) if body.get("stream") else b
                try:
                    if final_stream:
                        chain_hdr = {"X-Familia-Chain": ">".join(served + [s["node"]])}
                        st, h, raw, who = self.run(s["node"], path, b, trail, tag(chain_hdr))
                        if st is None:
                            return None, None, None, who
                    else:
                        st, h, raw, who = self.run(s["node"], path, b, trail)
                except Down as e:
                    raise RouteError(503, f"route {name}: step {i + 1}/{len(rt['steps'])} ({s['node']}) failed: {e}", route=name, step=i + 1)
                if st != 200:
                    raise RouteError(502, f"route {name}: step {i + 1} ({s['node']}) answered HTTP {st}", route=name, step=i + 1)
                text = _content(raw, f"route {name} step {i + 1} ({s['node']})"); served.append(who)
            return st, dict(h, **{"X-Familia-Chain": ">".join(served)}), raw, served[-1]
        # router
        label, msg = None, _last_user(body)
        m = re.match(r"^/([a-z0-9_-]+)\s+", msg) if rt["slash"] else None
        if m and m.group(1) in rt["labels"]:
            label = m.group(1)
            body = dict(body, messages=[*(body.get("messages") or [])[:-1], {"role": "user", "content": msg[m.end():]}])
        else:
            labels = sorted(rt["labels"])
            q = {"messages": [{"role": "system", "content": "Classify the user's request. Reply with exactly one word from: "
                               + ", ".join(labels) + ". No other text."}, {"role": "user", "content": msg}],
                 "temperature": 0, "max_tokens": 8, "stream": False}
            try:
                st, _, raw, _ = self.run(rt["router"], "/v1/chat/completions", q, trail)
            except Down as e:
                if not rt["default"]: raise RouteError(503, f"route {name}: router node failed: {e}", route=name)
                st, raw = None, None
            if st == 200:
                word = re.sub(r"[^a-z0-9_-]", "", (_content(raw, f"route {name} router").strip().split() or [""])[0].lower())
                label = word if word in rt["labels"] else None
            if label is None and not rt["default"]:
                got = _content(raw, "router")[:60] if st == 200 else f"HTTP {st}"
                raise RouteError(502, f"route {name}: router returned no known label ({got!r}); labels: {sorted(rt['labels'])}", route=name)
        target = rt["labels"][label] if label else rt["default"]
        lab = {"X-Familia-Route-Label": label or "<default>"}
        st, h, raw, who = self.run(target, path, body, trail, tag(lab) if body.get("stream") else None)
        if st is None:
            return None, None, None, who
        return st, dict(h, **{"X-Familia-Route-Label": label or "<default>"}), raw, who


def make_server(cfg, host="127.0.0.1", port=9940, api_key=None):
    """api_key: required on every endpoint except /health (H4 pattern); None = no caller auth (tests)."""
    if not _is_loopback(host):
        raise ConfigError("graph router binds loopback only")
    R = Router(cfg)

    def _hdr(v):
        """Header-safe text: drop CR, LF and other C0/DEL control chars."""
        return "".join(c for c in str(v) if c >= " " and c != "\x7f")

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass

        def send_header(self, keyword, value):
            # familia#303 / CodeQL py/http-response-splitting: header values can carry
            # request- or upstream-derived text (route name, node, labels); never let
            # CR/LF or other control chars through into the response head.
            super().send_header(_hdr(keyword), _hdr(value))

        def _json(self, st, obj, extra=None):
            b = json.dumps(obj).encode()
            self.send_response(st)
            for k, v in {"Content-Type": "application/json", "Content-Length": str(len(b)), **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers(); self.wfile.write(b)

        def _err(self, st, msg, **extra):
            self._json(st, {"error": {"message": msg, "type": "familia_route_error", **extra}})

        def _authed(self):
            if api_key is None:
                return True
            import familia_auth
            a = self.headers.get("Authorization") or ""
            given = a[7:].strip() if a.lower().startswith("bearer ") else (self.headers.get("X-Api-Key") or "").strip()
            if familia_auth.keys_match(given, api_key):
                return True
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= BODY_LIMIT: self.rfile.read(n)
            self._err(401, "missing or invalid API key for this graph router (Authorization: Bearer <key>)")
            return False

        def do_GET(self):
            p = urllib.parse.urlparse(self.path).path
            if p in ("/health", "/v1/health"):
                return self._json(200, {"status": "ok", "routes": len(cfg["routes"])})
            if not self._authed(): return
            if p == "/v1/models":
                return self._json(200, {"object": "list", "data": [
                    {"id": r, "object": "model", "owned_by": "familia", "familia": {"type": rt["type"], "kind": rt["kind"]}}
                    for r, rt in sorted(cfg["routes"].items())]})
            self._err(404, f"unknown path {p}")

        def do_POST(self):
            p = urllib.parse.urlparse(self.path).path
            if not self._authed(): return
            kind = {"/v1/chat/completions": "chat", "/v1/embeddings": "embedding"}.get(p)
            if not kind:
                return self._err(404, f"unknown path {p}")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > BODY_LIMIT: return self._err(413, "request body exceeds 16 MiB")
                body = json.loads(self.rfile.read(n) or b"null")
                if not isinstance(body, dict): raise ValueError
            except ValueError:
                return self._err(400, "request body must be a JSON object")
            name = str(body.get("model") or "").strip()
            if name in cfg["refused_routes"]:
                return self._err(409, cfg["refused_routes"][name], route=name)
            if name not in cfg["routes"]:
                return self._err(404, f"unknown route {name or '<missing>'}; routes: {sorted(cfg['routes'])}")
            if cfg["routes"][name]["kind"] != kind:
                return self._err(400, f"route {name} serves {cfg['routes'][name]['kind']}, not {kind}")
            trail = []
            started = []

            def stream_to(st, h, it):
                self.send_response(st)
                self.send_header("Content-Type", h.get("Content-Type", "text/event-stream"))
                self.send_header("X-Familia-Route", name)
                self.send_header("X-Familia-Node", h.get("X-Familia-Node") or (started[0] if started else "?"))
                for k, v in h.items():
                    if k.startswith("X-Familia") and k not in ("X-Familia-Route", "X-Familia-Node"):
                        self.send_header(k, v)
                self.send_header("Connection", "close"); self.end_headers()
                for b in it:
                    self.wfile.write(b); self.wfile.flush()
                self.close_connection = True
                return None

            try:
                rt = cfg["routes"][name]
                if body.get("stream") and rt["type"] in ("single", "fallback"):
                    # resolve node name for the header before streaming starts
                    def tagged(st, h, it, _s=stream_to):
                        return _s(st, h, it)
                    for ref in rt["nodes"]:
                        started[:] = [ref]
                        try:
                            res = R.run(ref, p, body, trail, stream_to=tagged)
                            if res[0] is not None:
                                st, h, raw, who = res
                                return self._json(st, json.loads(raw or b"{}"), {"X-Familia-Route": name, "X-Familia-Node": who})
                            return
                        except Down as e:
                            trail.append(str(e))
                    raise RouteError(503, f"route {name}: no node reachable", route=name, tried=[t for t in trail if " " in t])
                st, h, raw, who = R.route(name, p, body, trail, stream_to if body.get("stream") else None)
                if st is None:
                    return  # streamed (chain final step / router target)
                extra = {k: v for k, v in h.items() if k.startswith("X-Familia")}
                self.send_response(st)
                for k, v in {"Content-Type": h.get("Content-Type", "application/json"), "Content-Length": str(len(raw)),
                             "X-Familia-Route": name, "X-Familia-Node": who, **extra}.items():
                    self.send_header(k, v)
                self.end_headers(); self.wfile.write(raw)
            except RouteError as e:
                self._err(e.status, str(e), **e.extra)
            except Down as e:
                self._err(503, f"route {name}: {e}", route=name)

    return ThreadingHTTPServer((host, port), H)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", help="routes.yaml")
    ap.add_argument("--port", type=int, default=int(os.environ.get("FAMILIA_ROUTER_PORT", "9940")))
    ap.add_argument("--host-id", help="graph host this router runs on (for graph-backed configs)")
    ap.add_argument("--api-key-file", help="caller key file (default: the per-port instance key "
                    "~/.config/familia/instances/<port>/api-keys, created 0600 once, never rotated)")
    ap.add_argument("--no-auth", action="store_true", help="serve without caller auth (loopback dev only)")
    ap.add_argument("--check", action="store_true", help="validate and print the compiled routes, then exit")
    a = ap.parse_args(argv)
    try:
        cfg = load(a.config, here=a.host_id)
    except ConfigError as e:
        print(f"graph-router: config error: {e}", file=sys.stderr); return 2
    for r, why in sorted(cfg["refused_routes"].items()):
        print(f"graph-router: route {r} refused (409): {why}", file=sys.stderr)
    for r, rt in sorted(cfg["routes"].items()):
        print(f"graph-router: route {r} [{rt['type']}/{rt['kind']}] -> {', '.join(_refs(rt))}", file=sys.stderr)
    if a.check: return 0
    key = None
    if not a.no_auth:
        import familia_auth
        path = a.api_key_file or os.environ.get("API_KEY_FILE") or familia_auth.instance_key_file(port=a.port)
        try:
            key = familia_auth.load_or_create_key_file(os.path.expanduser(path))
        except (OSError, familia_auth.MissingKey) as e:
            print(f"graph-router: ERROR: cannot read or create API key file {path} ({e.__class__.__name__}); not starting",
                  file=sys.stderr); return 2
        print(f"graph-router: caller auth on ({path}, {familia_auth.fingerprint(key)})", file=sys.stderr)
    srv = make_server(cfg, "127.0.0.1", a.port, api_key=key)
    print(f"graph-router: listening on 127.0.0.1:{a.port}", file=sys.stderr)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
