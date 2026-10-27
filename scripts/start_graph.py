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


class StartupError(RuntimeError):
    pass


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


def local_topology(graph, host):
    nodes = sorted(
        name for name, node in graph.get("nodes", {}).items()
        if node.get("status") == "active" and node.get("host") == host
    )
    remote_nodes = sorted(
        (name, node.get("host"))
        for name, node in graph.get("nodes", {}).items()
        if node.get("status") == "active" and node.get("host") != host
    )
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
        for alias_name, alias in sorted(graph.get("aliases", {}).items()):
            if alias.get("gateway") != gateway_name:
                continue
            node_name = alias["node"]
            node = graph["nodes"][node_name]
            if node.get("status") != "active" or node.get("host") != host:
                omitted_aliases.append((alias_name, node_name, node.get("host")))
                continue
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
                if model.get("role") not in ("chat", "coder"):
                    raise StartupError(
                        f"alias {alias_name} targets model role {model.get('role')!r}; "
                        "graph-proxy only routes chat and embeddings"
                    )
                kind = "chat"
            aliases[alias_name] = {
                "kind": kind,
                "url": f"http://127.0.0.1:{node['port']}",
            }
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
        if not port_available(node["bind"], node["port"]):
            raise StartupError(
                f"node {name} port {node['port']} is already occupied; "
                "nothing was started and familia will not stop an unrelated process"
            )
        plans.append((name, argv))
    return plans


def graph_proxy_manifest(host, gateway, aliases):
    return {
        "schema_version": 1,
        "graph_host": host,
        "gateway": {"host": "127.0.0.1", "port": gateway["port"]},
        "aliases": aliases,
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


def _run_gate_and_sync(root, yes):
    env = dict(os.environ)
    if yes:
        env["FAMILIA_ACCEPT_LICENSES"] = "yes"
    gate = subprocess.run(
        [sys.executable, str(root / "scripts" / "licenses.py"), "gate", "--graph", str(root / "graph.yaml")],
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
        [sys.executable, str(root / "scripts" / "licenses.py"), "gate", "--graph", str(root / "graph.yaml")],
        cwd=root,
        env=env,
    )
    if gate.returncode:
        raise StartupError("license review was not accepted after synchronization; no graph services were started")
    env["FAMILIA_ACCEPT_LICENSES"] = "yes"
    env["FAMILIA_SYNC_DONE"] = str(root)
    return env


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


def _stop_children(children):
    for child, _ in reversed(children):
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 10
    for child, label in reversed(children):
        if child.poll() is None:
            try:
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                print(f"familia-graph: {label} did not stop after SIGTERM; sending SIGKILL", file=sys.stderr)
                child.kill()
                child.wait()


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
        priv = (ROOT / "generated" / f"graph-{host}.yaml").resolve()
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
        nodes, remote_nodes, gateways, omitted_aliases, remote_gateways = local_topology(graph, host)
        errors, _ = graph_validator.validate(graph, check_files=False)
        if errors:
            raise StartupError("graph validation failed:\n  " + "\n  ".join(errors))
        if options.dry_run:
            plans = validate_local_nodes(graph, host, nodes, check_files=False)
            _report_remote_topology(remote_nodes, remote_gateways, omitted_aliases)
            print(f"familia-graph: host {host}; active local nodes: {', '.join(n for n, _ in plans) or 'none'}")
            for gateway_name, gateway, aliases in gateways:
                print(f"familia-graph: gateway {gateway_name} on 127.0.0.1:{gateway['port']}; aliases: {', '.join(aliases)}")
            if not nodes and not gateways:
                print("familia-graph: no active local nodes or routable local gateway; nothing would start")
            return 0

        if not nodes and not gateways:
            print(f"familia-graph: no active local topology on {host}; nothing started")
            return 0

        _report_remote_topology(remote_nodes, remote_gateways, omitted_aliases)

        launch_env = _run_gate_and_sync(ROOT, options.yes)
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
        if gateways and not shutil.which("node"):
            raise StartupError("Node.js is required to start Green-Roomz graph-proxy")
        green_roomz = ROOT / "green-roomz" / "bin" / "green-roomz.mjs"
        if gateways and not green_roomz.is_file():
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
                )
                label = f"node {name}"
                children.append((child, label))
                print(f"familia-graph: starting {label}", file=sys.stderr)
                _wait_ready(child, f"http://127.0.0.1:{graph['nodes'][name]['port']}/health",
                            label, float(os.environ.get("FAMILIA_START_TIMEOUT", "0")))
                print(f"familia-graph: {label} ready")

            for gateway_name, gateway, aliases in gateways:
                manifest_path = _write_proxy_manifest(host, gateway_name, gateway, aliases)
                child = subprocess.Popen(
                    ["node", str(green_roomz), "graph-proxy", "--manifest", str(manifest_path)],
                    cwd=ROOT,
                    env=launch_env,
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
