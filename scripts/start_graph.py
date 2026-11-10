#!/usr/bin/env python3
"""Start the active graph topology assigned to this host, without remote operations.

Before local model servers (and the llama UI / green-roomz gateway) come up, syncs any
Harness² / Terminal-RSI accepted harness versions whose self_improve mode is on
(scripts/self_improve_attach.py; docs/harness2.md). Sync failure warns and continues.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CACHE = ROOT / ".cache"
sys.path.insert(0, str(SCRIPTS))
import validate_graph as graph_validator  # noqa: E402
import graph_types  # noqa: E402


class StartupError(RuntimeError):
    pass


def _fleet_banner(host):
    """One line when this host brings its graph topology up (joins the mesh). Best effort."""
    try:
        import fleet_greeting
        p = fleet_greeting.path()
        if fleet_greeting.load(p) is None:
            return False
        try:
            shown = os.path.relpath(p, ROOT)
        except ValueError:
            shown = p
        if shown.startswith(".."):
            shown = p
        print(f"familia-graph: welcome to the familia, {host}. Fleet greeting: {shown} "
              "(opens every agent's system prompt)", file=sys.stderr)
        return True
    except Exception:
        return False


def _os_host_matches(graph, hostname):
    """Unique graph host id for this OS hostname, or None if ambiguous/unknown."""
    if not hostname:
        return None
    short = hostname.strip().split(".", 1)[0]
    hosts = graph.get("hosts", {}) or {}
    if short in hosts:
        return short
    matches = [
        name for name, h in hosts.items()
        if isinstance(h, dict) and short in (h.get("local_names") or [])
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _pin_claims_hostname(graph, pin, hostname):
    """True if hosts.<pin> is this machine (key or local_names)."""
    if not pin or not hostname:
        return False
    short = hostname.strip().split(".", 1)[0]
    hosts = graph.get("hosts", {}) or {}
    h = hosts.get(pin)
    if not isinstance(h, dict):
        return False
    if pin == short:
        return True
    return short in (h.get("local_names") or [])


def select_host(graph, requested=None, environ=None, hostname=None):
    env = os.environ if environ is None else environ
    os_name = hostname if hostname is not None else socket.gethostname()
    try:
        from hostname_pin import resolve_candidate, read_pin
        candidate = resolve_candidate(requested=requested, environ=env, hostname=os_name)
        pinned = None if (requested or env.get("FAMILIA_HOST")) else read_pin(env)
    except ImportError:
        raw = requested or env.get("FAMILIA_HOST") or os_name
        candidate = raw.strip().split(".", 1)[0]
        pinned = None
    hosts = graph.get("hosts", {}) or {}
    # Stale pin must not steal identity: if OS hostname uniquely maps to another
    # declared host, prefer that over a pin that does not claim this machine.
    os_id = _os_host_matches(graph, os_name)
    if (
        pinned
        and os_id
        and pinned != os_id
        and not _pin_claims_hostname(graph, pinned, os_name)
        and not requested
        and not env.get("FAMILIA_HOST")
    ):
        print(
            f"familia-graph: ignoring hostname pin {pinned!r} "
            f"(OS hostname {os_name!r} is graph host {os_id!r})",
            file=sys.stderr,
        )
        candidate = os_id
    if candidate in hosts:
        return candidate
    # OS hostname may differ from the graph key (e.g. grok-bot-vm-* -> box)
    matches = [
        name for name, h in hosts.items()
        if isinstance(h, dict) and candidate in (h.get("local_names") or [])
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise StartupError(
            f"OS hostname {candidate!r} matches multiple graph hosts via local_names "
            f"({', '.join(sorted(matches))}); set --host or FAMILIA_HOST to one of them"
        )
    known = ", ".join(sorted(hosts))
    raise StartupError(
        f"local host {candidate!r} is not declared in graph.yaml; "
        f"use --host NAME or FAMILIA_HOST=NAME or "
        f"`python3 scripts/hostname_pin.py set NAME` (declared: {known}). "
        f"Or add this OS hostname under hosts.<name>.local_names after measuring. "
        f"Next step: measure this machine into the graph with "
        f"`python3 scripts/host_measure.py --name NAME --kind desktop|laptop|phone|tablet|notebook|1U|2U|3U|console|appliance|drone|watch` "
        f"(or run install/linux/install.sh, which measures for you). "
        f"Top-level curl|install.sh alone does not measure the host."
    )


def _alias_member(graph, host, alias_name, alias, node_name):
    """One alias member as {node, kind, url, remote}, or None when it cannot be routed from here
    (not active, or on another host without `remote: true` / a usable addr / a non-loopback bind)."""
    node = graph["nodes"][node_name]
    if node.get("status") != "active":
        return None
    local = node.get("host") == host
    if not local:
        if alias.get("remote") is not True:
            return None
        addr = ((graph.get("hosts") or {}).get(node.get("host")) or {}).get("addr")
        if not addr or addr == "REPLACE_ME" or node.get("bind") in ("127.0.0.1", "localhost", "::1"):
            return None
    else:
        if node.get("runtime") not in graph["runtimes"]:
            raise StartupError(f"alias {alias_name} references an unknown runtime")
        runtime = graph["runtimes"][node["runtime"]]
        if runtime.get("kind") != "llama-server":
            raise StartupError(
                f"alias {alias_name} targets node {node_name} with unsupported "
                f"runtime kind {runtime.get('kind')!r}"
            )
        if node.get("bind") not in ("127.0.0.1", "localhost", "::1"):
            raise StartupError(
                f"alias {alias_name} targets node {node_name} bound to "
                f"{node.get('bind')!r}; graph-proxy requires a loopback node bind"
            )
    model = graph["models"][node["model"]]
    if node.get("embeddings"):
        if model.get("role") != "embed":
            raise StartupError(f"alias {alias_name} marks a non-embedding model as embeddings")
        kind = "embedding"
    else:
        role = graph_validator.node_type(graph, node_name)  # node.role > model.role
        if role not in graph_validator.PROXY_ROUTABLE_ROLES:
            raise StartupError(
                f"alias {alias_name} targets node role {role!r}; graph-proxy routes "
                f"{', '.join(graph_validator.PROXY_ROUTABLE_ROLES)} as chat, plus embeddings"
            )
        kind = "chat"
    url = f"http://127.0.0.1:{node['port']}" if local else f"http://{addr}:{node['port']}"
    tools = False
    try:
        tools = bool(graph_validator.tool_policy(graph, node_name))
    except Exception:
        pass
    return {"node": node_name, "kind": kind, "url": url, "remote": not local, "tools": tools}


def _cascade_routes(graph, gateway_name, aliases, alias_members):
    """councils.<c> mode cascade -> a graph_router chain over each agent's `main` alias, in list order
    (agent 1's reply is agent 2's input). Only councils whose agents all route on this gateway."""
    out = {}
    for cname, c in sorted((graph.get("councils") or {}).items()):
        if c.get("mode") != "cascade":
            continue  # quorum: not run yet (docs/graph-recipes.md)
        steps, gws = [], set()
        for agent in c.get("agents") or []:
            main = ((graph["agents"].get(agent) or {}).get("aliases") or {}).get("main")
            alias_gw = (graph["aliases"].get(main) or {}).get("gateway")
            gws.add(alias_gw)
            if alias_gw == gateway_name and main in alias_members:
                steps.append(alias_members[main][0])
        if gateway_name not in gws:
            continue  # this council belongs to another gateway
        if len(steps) != len(c.get("agents") or []) or len(gws) > 1:
            raise StartupError(f"council {cname}: every agent's main alias must be routable on gateway "
                               f"{gateway_name} from this host")
        if cname in aliases:
            raise StartupError(f"council {cname}: name clashes with an alias")
        if any(m["kind"] != "chat" for m in steps):
            raise StartupError(f"council {cname}: cascade steps must be chat nodes")
        out[cname] = {"kind": "chat", "chain": steps}
    return out


def needs_router(aliases, gateway=None):
    """True unless `gateways.<g>.router: false` and every alias is one local node (then green-roomz
    graph-proxy). graph_router bounds a down node to a 3 s connect instead of graph-proxy's 180 s retry."""
    if any("members" in a or "chain" in a for a in aliases.values()):
        return True  # lists/remote members only graph_router can serve
    return (gateway or {}).get("router", True) is not False  # default: graph_router; router: false = graph-proxy


def router_routes(aliases):
    """graph_router config (version 1) for a gateway's aliases."""
    nodes, routes = {}, {}
    def key(m):  # router: route and node names are disjoint
        return m["node"] + "-node" if m["node"] in aliases else m["node"]
    for alias, a in sorted(aliases.items()):
        if "chain" in a:
            for m in a["chain"]:
                nodes[key(m)] = {"url": m["url"], "kind": m["kind"], "remote": m["remote"], "tools": m.get("tools", False)}
            routes[alias] = {"chain": [key(m) for m in a["chain"]]}
            continue
        ms = a.get("members") or [{"node": alias + "--node", "url": a["url"], "kind": a["kind"], "remote": False, "tools": a.get("tools", False)}]
        names = []
        for m in ms:
            nodes[key(m)] = {"url": m["url"], "kind": m["kind"], "remote": m["remote"], "tools": m.get("tools", False)}
            names.append(key(m))
        routes[alias] = names[0] if len(names) == 1 else names
    return {"version": 1, "nodes": nodes, "routes": routes}


def local_topology(graph, host):
    import node_state  # DUP-03 owner
    nodes = node_state.local_active(graph, host)
    remote_nodes = node_state.remote_active(graph, host)
    gateways = []
    omitted_aliases = []
    remote_gateways = sorted(
        (name, gateway.get("host"))
        for name, gateway in graph.get("gateways", {}).items()
        if gateway.get("host") != host
    )
    for gateway_name, gateway in sorted(graph.get("gateways", {}).items()):
        if gateway.get("host") != host:
            continue
        if gateway.get("kind") != "green-roomz":
            raise StartupError(f"gateway {gateway_name} has unsupported kind {gateway.get('kind')!r}")
        aliases = {}
        alias_members = {}
        for alias_name, alias in sorted(graph.get("aliases", {}).items()):
            if alias.get("gateway") != gateway_name:
                continue
            members = []
            for node_name in graph_types.alias_nodes(alias):
                m = _alias_member(graph, host, alias_name, alias, node_name)
                if m is None:
                    node = graph["nodes"][node_name]
                    omitted_aliases.append((alias_name, node_name, node.get("host")))
                else:
                    members.append(m)
            if not members:
                continue
            alias_members[alias_name] = members
            kinds = {m["kind"] for m in members}
            if len(kinds) > 1:
                raise StartupError(f"alias {alias_name} mixes chat and embedding nodes")
            if len(members) == 1 and not members[0]["remote"]:
                aliases[alias_name] = {"kind": members[0]["kind"], "url": members[0]["url"]}
                if members[0].get("tools"):
                    aliases[alias_name]["tools"] = True  # graph_router must send the node's per-port key
            else:
                # fallback list and/or remote member: served by scripts/graph_router.py, not graph-proxy
                aliases[alias_name] = {"kind": kinds.pop(), "members": members}
        aliases.update(_cascade_routes(graph, gateway_name, aliases, alias_members))
        if aliases:
            gateways.append((gateway_name, gateway, aliases))
    return nodes, remote_nodes, gateways, omitted_aliases, remote_gateways


def port_available(host, port):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def validate_local_nodes(graph, host, nodes, *, check_files):
    if check_files:
        errors, _ = graph_validator.validate(graph, check_files=True, host=host)
        if errors:
            raise StartupError("graph preflight failed:\n  " + "\n  ".join(errors))
    plans = []
    for name in nodes:
        node = graph["nodes"][name]
        runtime = graph["runtimes"][node["runtime"]]
        if runtime.get("kind") != "llama-server":
            raise StartupError(
                f"active local node {name} uses unsupported runtime kind "
                f"{runtime.get('kind')!r}; no nodes were started"
            )
        try:
            argv = graph_validator.server_args(graph, name)
        except SystemExit as error:
            raise StartupError(str(error)) from error
        if check_files:
            if "/" not in argv[0] and shutil.which(argv[0]):
                binary = Path(shutil.which(argv[0]))  # runtime without bin: llama-server on PATH
            else:
                binary = Path(argv[0]).expanduser()
            if not binary.is_absolute():
                binary = ROOT / binary
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise StartupError(f"runtime for node {name} is missing or not executable: {binary}")
            model_arg = next((argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "-m"), None)
            model_path = Path(model_arg).expanduser() if model_arg else None
            if model_path and not model_path.is_absolute():
                model_path = ROOT / model_path
            if model_path and not model_path.is_file():
                raise StartupError(
                    f"model for node {name} is missing: {model_arg}. "
                    f"Next step: place the GGUF at that path, or fetch with "
                    f"`python3 scripts/add_model.py --fetch ORG/NAME --file FILE.gguf --accept-licenses` "
                    f"then symlink/copy into the graph model path."
                )
            if os.environ.get("FAMILIA_GUARD", "1") != "0":
                guard = SCRIPTS / "bench_guard.py"
                checked = subprocess.run(
                    [sys.executable, str(guard), "check", "--", *argv[1:]],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                if checked.returncode:
                    details = (checked.stdout + checked.stderr).strip()
                    raise StartupError(f"launch guard refused node {name}:\n{details}")
        plans.append((name, argv))
    return plans


def graph_proxy_manifest(host, gateway, aliases):
    return {
        "schema_version": 1,
        "graph_host": host,
        "gateway": {"host": "127.0.0.1", "port": gateway["port"]},
        "aliases": {n: {k: v for k, v in a.items() if k != "tools"} for n, a in aliases.items()},
    }


def _report_remote_topology(remote_nodes, remote_gateways, omitted_aliases):
    for name, remote_host in remote_nodes:
        print(f"familia-graph: remote node {name} on {remote_host}; not starting or connecting without consent")
    for gateway_name, remote_host in remote_gateways:
        print(f"familia-graph: remote gateway {gateway_name} on {remote_host}; not starting or connecting")
    for alias, node_name, remote_host in omitted_aliases:
        print(f"familia-graph: route {alias} -> {node_name} omitted ({remote_host}); no remote connection")


def _check_port_available(host, port, label):
    if not port_available(host, port):
        raise StartupError(f"{label} port {port} is already occupied; nothing was started")


def _run_gate_and_sync(root, yes, graph_path=None):
    env = dict(os.environ)
    graph_file = str(graph_path or root / "graph.yaml")
    env["FAMILIA_GRAPH"] = graph_file  # serve.sh and the gate read the same graph as start_graph
    if yes:
        env["FAMILIA_ACCEPT_LICENSES"] = "yes"
    gate = subprocess.run(
        [sys.executable, str(root / "scripts" / "licenses.py"), "gate", "--graph", graph_file],
        cwd=root,
        env=env,
    )
    if gate.returncode:
        raise StartupError("license review was not accepted; no graph services were started")
    sync = subprocess.run(
        [sys.executable, str(root / "scripts" / "sync_pins.py"), "--auto"],
        cwd=root,
        env=env,
    )
    if sync.returncode:
        raise StartupError(f"pinned projects could not be synchronized (exit {sync.returncode}); nothing started")
    gate = subprocess.run(
        [sys.executable, str(root / "scripts" / "licenses.py"), "gate", "--graph", graph_file],
        cwd=root,
        env=env,
    )
    if gate.returncode:
        raise StartupError("license review was not accepted after synchronization; no graph services were started")
    env["FAMILIA_ACCEPT_LICENSES"] = "yes"
    env["FAMILIA_SYNC_DONE"] = str(root)
    return env


def gateway_command(host, gateway_name, gateway, aliases, green_roomz):
    """argv for one local gateway: green-roomz graph-proxy for plain one-node aliases, else
    scripts/graph_router.py (fallback lists, remote members) on the same port."""
    if needs_router(aliases, gateway):
        CACHE.mkdir(parents=True, exist_ok=True)
        path = CACHE / f"graph-router-{host}-{gateway_name}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(router_routes(aliases), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return [sys.executable, str(SCRIPTS / "graph_router.py"), str(path), "--port", str(gateway["port"])]
    manifest_path = _write_proxy_manifest(host, gateway_name, gateway, aliases)
    return ["node", str(green_roomz), "graph-proxy", "--manifest", str(manifest_path)]


def _write_proxy_manifest(host, gateway_name, gateway, aliases):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"graph-proxy-{host}-{gateway_name}.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(graph_proxy_manifest(host, gateway, aliases), indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
    return path


def _wait_ready(child, url, label, timeout):
    # timeout <= 0: wait until healthy or the child exits (no wall-clock fail).
    # Large GGUF mmap loads under heavy nightly I/O can exceed any fixed budget.
    deadline = None if timeout <= 0 else (time.monotonic() + timeout)
    last_note = 0.0
    started = time.monotonic()
    while deadline is None or time.monotonic() < deadline:
        if child.poll() is not None:
            raise StartupError(f"{label} exited during startup with status {child.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return
        except (OSError, urllib.error.URLError):
            pass
        now = time.monotonic()
        if now - last_note >= 60:
            print(
                f"familia-graph: still waiting for {label} ({now - started:.0f}s; "
                f"FAMILIA_START_TIMEOUT={'unlimited' if deadline is None else f'{timeout:g}s'})",
                file=sys.stderr,
            )
            last_note = now
        time.sleep(0.5)
    raise StartupError(f"{label} did not become ready within {timeout:g} seconds")


def spawn_child(argv, **kw):
    """Start a service in its own process group (POSIX) so stopping it also stops what it
    started: serve.sh does not exec llama-server on the default path (CPU retry), so a plain
    terminate() of sh orphaned the runtime and kept its port bound (routing-lifetime)."""
    if os.name == "posix":
        kw.setdefault("start_new_session", True)
    return subprocess.Popen(argv, **kw)


def _signal_group(child, sig):
    """serve.sh runs llama-server as a child (not exec) so it can retry on the CPU; signal the
    whole process group, or SIGTERM to the shell leaves llama-server holding the port."""
    try:
        if os.getpgid(child.pid) == child.pid:
            os.killpg(child.pid, sig); return
    except (ProcessLookupError, PermissionError):
        pass
    child.send_signal(sig)


def _stop_children(children):
    for child, _ in reversed(children):
        if child.poll() is None:
            _signal_group(child, signal.SIGTERM)
    deadline = time.monotonic() + 10
    for child, label in reversed(children):
        if child.poll() is None:
            try:
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                print(f"familia-graph: {label} did not stop after SIGTERM; sending SIGKILL", file=sys.stderr)
                _signal_group(child, signal.SIGKILL)
                child.wait()
        # The group may outlive its leader (sh died, runtime still up). Probe it ONCE right
        # after the reap and kill it; never poll, since a reaped pgid can be reused by an
        # unrelated group later.
        if os.name == "posix":
            try:
                os.killpg(child.pid, 0)
            except (ProcessLookupError, PermissionError):
                continue
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def run(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=ROOT / "graph.yaml")
    parser.add_argument("--host", help="declared graph host; defaults to an exact local hostname match")
    parser.add_argument("--dry-run", action="store_true", help="validate and show the local plan without starting services")
    parser.add_argument("--yes", action="store_true", help="accept the graph's reviewed licenses")
    parser.add_argument(
        "--fleet",
        action="store_true",
        help="force fleet graph.yaml (skip generated/graph-HOST.yaml private topology)",
    )
    options = parser.parse_args(args)
    graph_path = options.graph.expanduser().resolve()
    os.chdir(ROOT)
    try:
        graph = graph_validator.load(str(graph_path))
        graph["_path"] = str(graph_path)
        host = select_host(graph, options.host)
        fleet_default = (ROOT / "graph.yaml").resolve()
        import config_paths
        priv = (Path(config_paths.generated_dir()) / f"graph-{host}.yaml").resolve()
        if (
            not options.fleet
            and graph_path == fleet_default
            and priv.is_file()
            and priv != graph_path
        ):
            print(
                f"familia-graph: using private topology {priv} (type-named nodes); "
                f"pass --fleet for fleet graph.yaml",
                file=sys.stderr,
            )
            graph_path = priv
            graph = graph_validator.load(str(graph_path))
            graph["_path"] = str(graph_path)
        # Validate first: local_topology indexes nodes by alias target, so an invalid graph
        # (unknown alias node, list alias) would otherwise crash with a raw KeyError/TypeError.
        errors, _ = graph_validator.validate(graph, check_files=False)
        if errors:
            raise StartupError("graph validation failed:\n  " + "\n  ".join(errors))
        nodes, remote_nodes, gateways, omitted_aliases, remote_gateways = local_topology(graph, host)
        if options.dry_run:
            plans = validate_local_nodes(graph, host, nodes, check_files=False)
            _report_remote_topology(remote_nodes, remote_gateways, omitted_aliases)
            print(f"familia-graph: host {host}; active local nodes: {', '.join(n for n, _ in plans) or 'none'}")
            for name, argv in plans:
                print(f"familia-graph: node {name}: {shlex.join(argv)}")
            for gateway_name, gateway, aliases in gateways:
                via = (f"graph_router (caller auth: {__import__('familia_auth').instance_key_file(port=gateway['port'])}; /health public)"
                       if needs_router(aliases, gateway) else "graph-proxy (router: false; down node retried up to 180 s)")
                print(f"familia-graph: gateway {gateway_name} on 127.0.0.1:{gateway['port']} via {via}; aliases: {', '.join(aliases)}")
            if not nodes and not gateways:
                print("familia-graph: no active local nodes or routable local gateway; nothing would start")
                print(f"familia-graph: next: give host {host} a node in graph.yaml (or set FAMILIA_HOST), then re-run", file=sys.stderr)
                return 3
            return 0

        if not nodes and not gateways:
            print(f"familia-graph: no active local topology on {host}; nothing started")
            return 0

        _report_remote_topology(remote_nodes, remote_gateways, omitted_aliases)
        _fleet_banner(host)

        launch_env = _run_gate_and_sync(ROOT, options.yes, graph_path)
        # Harness² / Terminal-RSI: put accepted versions in place for any agent whose
        # self_improve mode is on, before model servers / llama UI come up (docs/harness2.md).
        try:
            import self_improve_attach as SIA
            SIA.attach(graph, str(graph_path), log_prefix="familia-graph: self-improve")
        except SystemExit as e:
            # Pentest refuse only; other sync issues warn+continue inside attach.
            raise StartupError(str(e)) from e
        plans = validate_local_nodes(graph, host, nodes, check_files=True)
        for name, _ in plans:
            node = graph["nodes"][name]
            if not port_available(node["bind"], node["port"]):
                raise StartupError(f"node {name} port {node['port']} is already occupied; nothing was started")
        for gateway_name, gateway, _ in gateways:
            _check_port_available("127.0.0.1", gateway["port"], f"gateway {gateway_name}")
        proxied = [g for g in gateways if not needs_router(g[2], g[1])]
        if proxied and not shutil.which("node"):
            raise StartupError("Node.js is required to start Green-Roomz graph-proxy")
        green_roomz = ROOT / "green-roomz" / "bin" / "green-roomz.mjs"
        if proxied and not green_roomz.is_file():
            raise StartupError("pinned Green-Roomz checkout is missing; synchronize pins before starting")

        children = []
        def interrupt(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupt)
        try:
            for name, _ in plans:
                child = subprocess.Popen(
                    ["sh", str(SCRIPTS / "serve.sh"), name],
                    cwd=ROOT,
                    env=dict(launch_env, FAMILIA_HOST=host),
                    start_new_session=True,  # own process group: stopping it also stops llama-server
                )
                label = f"node {name}"
                children.append((child, label))
                print(f"familia-graph: starting {label}", file=sys.stderr)
                _wait_ready(child, f"http://127.0.0.1:{graph['nodes'][name]['port']}/health",
                            label, float(os.environ.get("FAMILIA_START_TIMEOUT", "0")))
                print(f"familia-graph: {label} ready")

            for gateway_name, gateway, aliases in gateways:
                child = subprocess.Popen(
                    gateway_command(host, gateway_name, gateway, aliases, green_roomz),
                    cwd=ROOT,
                    env=launch_env,
                    start_new_session=True,
                )
                label = f"gateway {gateway_name}"
                children.append((child, label))
                print(f"familia-graph: starting {label}", file=sys.stderr)
                _wait_ready(child, f"http://127.0.0.1:{gateway['port']}/health",
                            label, float(os.environ.get("FAMILIA_START_TIMEOUT", "60")))
                print(f"familia-graph: {label} ready on 127.0.0.1:{gateway['port']} "
                      f"({', '.join(aliases)})")

            while True:
                for child, label in children:
                    status = child.poll()
                    if status is not None:
                        raise StartupError(f"{label} exited with status {status}; stopping this graph's services")
                time.sleep(1)
        except KeyboardInterrupt:
            print("familia-graph: stopping graph services", file=sys.stderr)
            _stop_children(children)
            return 130
        except BaseException:
            _stop_children(children)
            raise
    except (OSError, ValueError, StartupError) as error:
        print(f"familia-graph: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
