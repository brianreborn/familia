"""--tools child lifetime (platform routing-lifetime): the llama-server that serve.sh starts
must not outlive start_graph on SIGTERM or SIGINT/Ctrl-C, and its port must be reusable after.
Uses the real scripts/serve.sh against a stub runtime in tmp_path; ports are ephemeral (0).
Only PIDs spawned by these tests are ever signalled."""
import os, shutil, signal, socket, subprocess, sys, textwrap, time
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import start_graph  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups/signals")

FAKE_SERVER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, socket, sys, time
    a = sys.argv; out = a[a.index("--pidfile") + 1]
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(("127.0.0.1", 0)); s.listen()
    assert "--tools" in a          # a --tools launch, as llama-server would get it
    tmp = out + ".tmp"; open(tmp, "w").write(f"{os.getpid()} {s.getsockname()[1]}"); os.replace(tmp, out)
    while True: time.sleep(0.2)
    ''')


@pytest.fixture
def tree(tmp_path):
    """Minimal checkout: real serve.sh + lib/msg.mk; stub validate_graph/licenses; stub runtime."""
    t = tmp_path / "repo"; (t / "scripts").mkdir(parents=True); (t / "lib").mkdir()
    shutil.copy(os.path.join(ROOT, "scripts", "serve.sh"), t / "scripts" / "serve.sh")
    shutil.copy(os.path.join(ROOT, "lib", "msg.mk"), t / "lib" / "msg.mk")
    for _n in ("bind_auth_guard.py", "familia_auth.py"):
        shutil.copy(os.path.join(ROOT, "scripts", _n), t / "scripts" / _n)
    kf = tmp_path / "api-keys"; kf.write_text("k" * 32); kf.chmod(0o600)
    srv = tmp_path / "bin" / "llama-server"; srv.parent.mkdir(); srv.write_text(FAKE_SERVER); srv.chmod(0o755)
    model = tmp_path / "m.gguf"; model.write_bytes(b"GGUF")
    pidfile = tmp_path / "server.pid"
    (t / "scripts" / "validate_graph.py").write_text(
        f"print({str(srv)!r} + ' -m ' + {str(model)!r} + ' -ngl 0 --tools all --pidfile ' + {str(pidfile)!r} + ' --api-key-file ' + {str(kf)!r})\n")
    (t / "scripts" / "licenses.py").write_text("raise SystemExit(0)\n")
    env = dict(os.environ, FAMILIA_MEMCAP="0", FAMILIA_GUARD="0", FAMILIA_LOG_DIR=str(tmp_path / "logs"))
    env.pop("FAMILIA_HOST", None)
    return t, pidfile, env


def _wait_pidfile(p, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if p.exists(): pid, port = p.read_text().split(); return int(pid), int(port)
        time.sleep(0.05)
    raise AssertionError("stub server never started")


def _alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as f: return f.read().split(") ")[1][0] != "Z"
    except FileNotFoundError: return False
    except OSError:
        try: os.kill(pid, 0); return True
        except ProcessLookupError: return False


def _gone(pid, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _alive(pid): return True
        time.sleep(0.05)
    return False


def _spawn(argv, **kw):
    """start_graph.run launches serve.sh/gateway with start_new_session=True (own group)."""
    f = getattr(start_graph, "spawn_child", None)
    return f(argv, **kw) if f else subprocess.Popen(argv, start_new_session=True, **kw)


def test_stop_children_reaps_serve_sh_runtime_and_frees_port(tree):
    t, pidfile, env = tree
    child = _spawn(["sh", str(t / "scripts" / "serve.sh"), "coder"], cwd=str(t), env=env)
    pid = None
    try:
        pid, port = _wait_pidfile(pidfile)
        assert not start_graph.port_available("127.0.0.1", port)
        start_graph._stop_children([(child, "node coder")])
        assert _gone(pid), f"runtime pid {pid} orphaned after serve.sh was stopped"
        assert start_graph.port_available("127.0.0.1", port)
    finally:
        if child.poll() is None: child.kill(); child.wait()
        if pid and _alive(pid): os.kill(pid, signal.SIGKILL)


DRIVER = textwrap.dedent('''\
    import os, signal, subprocess, sys, time
    sys.path.insert(0, sys.argv[1]); import start_graph
    spawn = getattr(start_graph, "spawn_child", None) or (
        lambda a, **kw: subprocess.Popen(a, start_new_session=True, **kw))
    def interrupt(signum, frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)        # same handler start_graph.run installs
    children = [(spawn(["sh", sys.argv[2], "coder"], cwd=sys.argv[3]), "node coder")]
    print("up", flush=True)
    try:
        while True: time.sleep(0.1)
    except KeyboardInterrupt:
        start_graph._stop_children(children); sys.exit(130)
    ''')


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_parent_signal_leaves_no_orphan_and_port_reusable(tree, tmp_path, sig):
    t, pidfile, env = tree
    drv = tmp_path / "driver.py"; drv.write_text(DRIVER)
    p = subprocess.Popen([sys.executable, str(drv), os.path.join(ROOT, "scripts"),
                          str(t / "scripts" / "serve.sh"), str(t)], env=env, stdout=subprocess.PIPE,
                         start_new_session=True)   # own group: a Ctrl-C to it never hits pytest
    pid = None
    try:
        assert p.stdout.readline().strip() == b"up"
        pid, port = _wait_pidfile(pidfile)
        if sig == signal.SIGINT:
            os.killpg(p.pid, signal.SIGINT)     # terminal Ctrl-C: whole foreground group
        else:
            p.send_signal(sig)                 # service manager stop: parent only
        assert p.wait(timeout=15) == 130
        assert _gone(pid), f"runtime pid {pid} survived {sig.name} to start_graph"
        s = socket.socket(); s.bind(("127.0.0.1", port)); s.close()   # port reusable
    finally:
        if p.poll() is None: p.kill(); p.wait()
        if pid and _alive(pid): os.kill(pid, signal.SIGKILL)


def test_port_available_uses_requested_port_only():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.listen()
    try: assert not start_graph.port_available("127.0.0.1", port)
    finally: s.close()
    assert start_graph.port_available("127.0.0.1", port)


def test_stop_children_probes_group_once_not_in_a_loop(monkeypatch, tmp_path):
    """A reaped pgid can be reused; _stop_children must probe it once, never poll it.

    Also covers the orphan case: the group leader (sh) exits on SIGTERM while a
    grandchild in the same group ignores SIGTERM and would keep a port bound.
    After the leader is reaped, the single post-reap probe + SIGKILL must reap it.
    """
    if os.name != "posix":
        pytest.skip("POSIX process groups/signals")
    probes = []
    real = os.killpg
    def spy(pg, sig):
        if sig == 0: probes.append(pg)
        return real(pg, sig)
    monkeypatch.setattr(start_graph.os, "killpg", spy)
    pidfile = tmp_path / "grandchild.pid"
    grandchild = tmp_path / "ignore_sigterm.py"
    grandchild.write_text(
        "import os, pathlib, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "while True:\n"
        "    time.sleep(0.2)\n"
    )
    # sh is the start_new_session group leader; it starts the ignore-SIGTERM
    # grandchild and exits when the group is signalled, leaving the grandchild.
    child = _spawn(["sh", "-c", f"{sys.executable} {grandchild} {pidfile} & wait"])
    gc_pid = None
    try:
        end = time.monotonic() + 10
        while time.monotonic() < end:
            if pidfile.exists() and pidfile.read_text().strip():
                gc_pid = int(pidfile.read_text().strip())
                break
            time.sleep(0.05)
        assert gc_pid is not None, "SIGTERM-ignoring grandchild never started"
        assert os.getpgid(gc_pid) == child.pid
        start_graph._stop_children([(child, "k")])
        assert _gone(gc_pid), f"SIGTERM-ignoring grandchild {gc_pid} survived post-reap sweep"
        assert probes.count(child.pid) == 1, probes  # exactly one probe, never a loop
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                if child.poll() is None:
                    child.kill()
            child.wait()
        if gc_pid and _alive(gc_pid):
            try:
                os.kill(gc_pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
