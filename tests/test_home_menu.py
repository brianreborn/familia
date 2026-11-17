"""Home menu (#476): six equal items, legacy fallback, exit only on explicit quit."""
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(ROOT, "scripts", "familia_home.sh")
CATALOG = os.path.join(ROOT, "scripts", "home_catalog.py")
MENU = os.path.join(ROOT, "familia-menu.sh")
FAMILIA = os.path.join(ROOT, "familia")
TITLES = ("Models", "Harnesses", "Agents", "MCP servers", "Tool sets", "App store")
VERBS = "install, list, start, stop, status"
AREAS = ("models", "harnesses", "agents", "mcp", "tools", "apps")
LEGACY_GOALS = (
    "Talk to the protomodel",
    "Find more models",
    "List all models",
    "Configure all graphs",
    "Search my X / Twitter posts",
    "Install / first-time setup",
    "Proving grounds",
    "Legacy menu",
)
_ISOLATED = tempfile.mkdtemp(prefix="familia-home-test-")
os.chmod(_ISOLATED, 0o700)
for _sub in ("cache", "run", ".local"):
    os.makedirs(os.path.join(_ISOLATED, _sub), mode=0o700, exist_ok=True)


def base_env(**kw):
    """HOME and PATH never see the developer's ~/.local/bin/gum."""
    env = dict(os.environ)
    env.pop("FAMILIA_NO_TTY", None)
    env.pop("FAMILIA_SKIP_GUM_INSTALL", None)
    env["HOME"] = _ISOLATED
    env["XDG_CACHE_HOME"] = os.path.join(_ISOLATED, "cache")
    env["XDG_RUNTIME_DIR"] = os.path.join(_ISOLATED, "run")
    parts = [p for p in env.get("PATH", "").split(os.pathsep)
             if p and not p.endswith(os.sep + ".local" + os.sep + "bin") and not p.endswith("/.local/bin")]
    env["PATH"] = os.pathsep.join(parts) or "/usr/bin:/bin"
    env.update(kw)
    return env


def run(argv, **kw):
    env = kw.pop("env", None) or base_env()
    return subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, env=env, timeout=60, **kw
    )


def test_list_goals_are_six_equal_items_and_ascii():
    r = run(["sh", HOME, "--list-goals"])
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "\x1b" not in out
    assert all(ord(ch) < 128 for ch in out)
    lines = [ln for ln in out.splitlines() if VERBS in ln]
    assert len(lines) == 6, out
    for i, title in enumerate(TITLES):
        assert lines[i].strip().startswith("%d)" % (i + 1)), lines[i]
        assert title in lines[i]
    for goal in LEGACY_GOALS:
        assert goal in out, goal
    assert "q) Quit" in out
    # non-interactive front door is the same list and exits 0 (not an interactive quit)
    r2 = run(["sh", FAMILIA], env=base_env(FAMILIA_NO_TTY="1"))
    assert r2.returncode == 0, r2.stderr
    assert "Talk to the protomodel" in r2.stdout
    assert VERBS in r2.stdout


def test_catalog_list_and_status_are_local_ascii_and_do_not_bind():
    for area in AREAS:
        for verb in ("list", "status"):
            r = run([sys.executable, CATALOG, area, verb])
            assert r.returncode == 0, (area, verb, r.stdout, r.stderr)
            blob = r.stdout + r.stderr
            assert "\x1b" not in blob
            assert all(ord(ch) < 128 for ch in blob), (area, verb)
            assert "CLI:" in r.stdout
    models = run([sys.executable, CATALOG, "models", "list"])
    assert "stories15m-fp32" in models.stdout
    agents = run([sys.executable, CATALOG, "agents", "list"])
    assert "hermes" in agents.stdout
    start = run([sys.executable, CATALOG, "models", "start"])
    assert start.returncode == 0
    assert "Not applied" in start.stdout
    assert "instance file" in start.stdout
    mcp = run([sys.executable, CATALOG, "mcp", "start", "--apply"])
    assert mcp.returncode == 0
    assert "Refusing" in mcp.stdout
    assert "instance file" in mcp.stdout
    apps = run([sys.executable, CATALOG, "apps", "start", "--apply"])
    assert apps.returncode == 0 and "Refusing" in apps.stdout
    missing = run(
        [sys.executable, CATALOG, "models", "status"],
        env=base_env(FAMILIA_GRAPH="/no/such/graph.yaml"),
    )
    assert missing.returncode == 1
    assert "missing" in missing.stdout


def test_legacy_catalog_reaches_every_home_action():
    r = run(["bash", MENU, "--list"])
    assert r.returncode == 0, r.stderr
    for area in AREAS:
        for verb in ("install", "list", "start", "stop", "status"):
            key = "home.%s.%s" % (area, verb)
            assert key in r.stdout, key
            assert "scripts/home_catalog.py %s %s" % (area, verb) in r.stdout
    for key in ("home.talk", "home.find-models", "home.search-x"):
        assert key in r.stdout
    # dry-run prints the CLI and does not apply
    dry = run(["bash", MENU, "--run", "home.models.start", "--dry-run"])
    assert dry.returncode == 0, dry.stderr
    assert dry.stdout.startswith("[dry-run]")
    assert "home_catalog.py models start" in dry.stdout
    assert "--apply" not in dry.stdout
    cli = run(["sh", FAMILIA, "home", "models", "list"])
    assert cli.returncode == 0, cli.stderr
    assert "stories15m-fp32" in cli.stdout


def test_legacy_eof_is_not_a_successful_quit():
    r = run(["bash", MENU, "--pipe"], input="")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "type q" in r.stdout.lower()
    # an explicit q is still success
    ok = run(["bash", MENU, "--pipe"], input="q\n")
    assert ok.returncode == 0, ok.stderr


_GUM_HEAD = """#!/bin/sh
case "$1" in
  --version|-v) printf '%s\\n' 'gum version 2.0.2'; exit 0 ;;
esac
if [ "$1" = choose ] && [ "$2" = --help ]; then
  printf '%s\\n' '--header' '--height'
  exit 0
fi
"""


def _gum(bin_dir, choices):
    os.makedirs(bin_dir, exist_ok=True)
    choice_file = os.path.join(bin_dir, "choices")
    with open(choice_file, "w", encoding="ascii") as fh:
        fh.write("\n".join(choices) + "\n")
    path = os.path.join(bin_dir, "gum")
    with open(path, "w", encoding="ascii") as fh:
        fh.write(
            _GUM_HEAD +
            "if [ \"$1\" = choose ]; then\n"
            "  line=$(head -n 1 '%s')\n"
            "  rest=$(tail -n +2 '%s')\n"
            "  printf '%%s\\n' \"$rest\" > '%s'\n"
            "  case \"$line\" in\n"
            "    ''|CANCEL) exit 130 ;;\n"
            "    *) printf '%%s\\n' \"$line\" ;;\n"
            "  esac\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n" % (choice_file, choice_file, choice_file)
        )
    os.chmod(path, 0o755)
    return choice_file


def _fail_gum(bin_dir):
    os.makedirs(bin_dir, exist_ok=True)
    path = os.path.join(bin_dir, "gum")
    with open(path, "w", encoding="ascii") as fh:
        fh.write(
            _GUM_HEAD +
            "if [ \"$1\" = choose ]; then\n"
            "  exit 1\n"
            "fi\n"
            "exit 0\n"
        )
    os.chmod(path, 0o755)


def _read_pty(master, proc, chunks, deadline):
    while time.time() < deadline and proc.poll() is None:
        ready, _, _ = select.select([master], [], [], 0.2)
        if not ready:
            continue
        try:
            data = os.read(master, 4096)
        except OSError:
            continue
        if not data:
            continue
        chunks.append(data)
    return b"".join(chunks)


def _pty(argv, env, feed=b"", timeout=20):
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        argv, stdin=slave, stdout=slave, stderr=slave, cwd=ROOT, env=env,
        close_fds=True, start_new_session=True,
    )
    os.close(slave)
    if feed:
        os.write(master, feed)
    chunks = []
    text = _read_pty(master, proc, chunks, time.time() + timeout)
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)
        os.close(master)
        raise AssertionError("timed out\n" + text.decode("utf-8", "replace"))
    while True:
        ready, _, _ = select.select([master], [], [], 0.1)
        if not ready:
            break
        try:
            data = os.read(master, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    os.close(master)
    rc = proc.wait(timeout=5)
    return rc, b"".join(chunks).decode("utf-8", "replace")


def test_home_stays_open_until_quit_and_survives_cancel_and_errors(tmp_path):
    bin_dir = str(tmp_path / "bin")
    choices = _gum(bin_dir, ["CANCEL", "Models", "status", "Quit"])
    env = base_env(
        PATH=bin_dir + os.pathsep + "/usr/bin:/bin",
        FAMILIA_GRAPH="/no/such/graph.yaml",
        TERM="xterm",
    )
    env.pop("NO_COLOR", None)
    rc, out = _pty(["sh", HOME], env)
    assert rc == 0, out
    assert "staying in the menu" in out
    assert "exited 1" in out
    assert "Choose Quit" in out or "Staying" in out
    leftover = open(choices, encoding="ascii").read().strip()
    assert leftover == "", leftover


def test_home_lists_a_model_then_quits(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _gum(bin_dir, ["Models", "list", "Quit"])
    env = base_env(PATH=bin_dir + os.pathsep + "/usr/bin:/bin", TERM="dumb", NO_COLOR="1")
    rc, out = _pty(["sh", HOME], env)
    assert rc == 0, out
    assert "stories15m-fp32" in out
    assert "\x1b" not in out


def test_missing_gum_falls_back_to_legacy_menu():
    env = base_env(
        PATH="/usr/bin:/bin",
        FAMILIA_SKIP_GUM_INSTALL="1",
        TERM="dumb",
        NO_COLOR="1",
    )
    rc, out = _pty(["sh", HOME], env, feed=b"q\n")
    assert rc == 0, out
    assert "falling back to the legacy menu" in out
    assert "what do you want to do?" in out
    assert "HOME:" in out
    assert out.count("six equal items") < 8


def test_failing_gum_does_not_spin_and_falls_back(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _fail_gum(bin_dir)
    env = base_env(
        PATH=bin_dir + os.pathsep + "/usr/bin:/bin",
        TERM="dumb",
        NO_COLOR="1",
        FAMILIA_SKIP_GUM_INSTALL="1",
    )
    rc, out = _pty(["sh", HOME], env, feed=b"q\n", timeout=15)
    assert rc == 0, out
    assert "falling back to the legacy menu" in out
    assert out.count("six equal items") < 8
    assert "what do you want to do?" in out


def test_failing_gum_with_no_tty_exits_2_not_zero(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _fail_gum(bin_dir)
    env = base_env(
        PATH=bin_dir + os.pathsep + "/usr/bin:/bin",
        FAMILIA_HOME_FORCE_MENU="1",
        FAMILIA_SKIP_GUM_INSTALL="1",
        TERM="dumb",
        NO_COLOR="1",
    )
    r = run(["sh", HOME], env=env, input="")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    blob = r.stdout + r.stderr
    assert "Not a quit" in blob
    assert blob.count("six equal items") < 8


def test_list_all_models_returns_to_the_menu(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _gum(bin_dir, ["List all models", "Quit"])
    env = base_env(PATH=bin_dir + os.pathsep + "/usr/bin:/bin", TERM="dumb", NO_COLOR="1")
    rc, out = _pty(["sh", HOME], env, timeout=20)
    assert rc == 0, out
    assert "stories15m-fp32" in out
    assert out.count("six equal items") >= 2


def test_configure_graphs_returns_to_the_menu(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _gum(bin_dir, ["Configure all graphs", "Quit"])
    env = base_env(PATH=bin_dir + os.pathsep + "/usr/bin:/bin", TERM="dumb", NO_COLOR="1")
    rc, out = _pty(["sh", HOME], env, timeout=30)
    assert rc == 0, out
    assert "Graphs you can configure" in out
    assert out.count("six equal items") >= 2


def test_sigint_during_action_stays_until_quit(tmp_path):
    bin_dir = str(tmp_path / "bin")
    hold = tmp_path / "hold.sh"
    hold.write_text("#!/bin/sh\n# familia-home-test-launcher\necho holding for test\nsleep 30\n")
    hold.chmod(0o755)
    _gum(bin_dir, ["Models", "start", "Quit"])
    env = base_env(
        PATH=bin_dir + os.pathsep + "/usr/bin:/bin",
        TERM="dumb",
        NO_COLOR="1",
        FAMILIA_HOME_LAUNCHER=str(hold),
        FAMILIA_SKIP_GUM_INSTALL="1",
    )
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["sh", HOME], stdin=slave, stdout=slave, stderr=slave,
        cwd=ROOT, env=env, close_fds=True, start_new_session=True,
    )
    os.close(slave)
    os.write(master, b"y\n")
    chunks = []
    sent = False
    deadline = time.time() + 20
    while time.time() < deadline and proc.poll() is None:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                continue
            if data:
                chunks.append(data)
        if not sent and b"holding for test" in b"".join(chunks):
            os.killpg(proc.pid, signal.SIGINT)
            sent = True
    text = b"".join(chunks)
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)
        os.close(master)
        raise AssertionError("timed out\n" + text.decode("utf-8", "replace"))
    while True:
        ready, _, _ = select.select([master], [], [], 0.1)
        if not ready:
            break
        try:
            data = os.read(master, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    os.close(master)
    rc = proc.wait(timeout=5)
    out = b"".join(chunks).decode("utf-8", "replace")
    assert sent, out
    assert rc == 0, out
    assert "interrupted" in out or "exited 130" in out


def test_install_prompts_for_the_missing_argument(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _gum(bin_dir, ["Models", "install", "Quit"])
    env = base_env(
        PATH=bin_dir + os.pathsep + "/usr/bin:/bin",
        TERM="dumb",
        NO_COLOR="1",
        FAMILIA_SKIP_GUM_INSTALL="1",
    )
    rc, out = _pty(["sh", HOME], env, feed=b"y\n\n", timeout=15)
    assert rc == 0, out
    assert "ORG/NAME" in out
    assert "not confirmed" in out
    assert "add-model.sh" not in out


def test_stop_follows_recorded_pid_and_agents_stop_leaves_models(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    os.chmod(run_dir, 0o700)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run_dir))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc
    hc.save_record("models", 1, 9, "not-the-real-init")
    rec = hc.load_record("models")
    rec["starttime"] = "not-pid-1"
    import json
    with open(hc._state_path("models"), "w", encoding="ascii") as fh:
        fh.write(json.dumps(rec))
    env = base_env(HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir),
                   XDG_CACHE_HOME=str(tmp_path / "cache"))
    refused = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
    assert refused.returncode == 0, refused.stdout + refused.stderr
    assert "nothing to stop" in refused.stdout
    assert "signaled pid 1" not in refused.stdout
    server = tmp_path / "llama-server"
    server.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n")
    server.chmod(0o755)
    ours = subprocess.Popen([str(server)])
    other = subprocess.Popen(["sleep", "60"])
    try:
        hc.save_record("models", ours.pid, 9931, hc._cmdline(ours.pid))
        status = run([sys.executable, CATALOG, "models", "status"], env=env)
        assert status.returncode == 0, status.stdout
        assert "recorded pid %s port 9931 alive" % ours.pid in status.stdout
        agents = run([sys.executable, CATALOG, "agents", "stop", "--apply"], env=env)
        assert agents.returncode == 0, agents.stdout
        assert "does not stop model servers" in agents.stdout
        assert ours.poll() is None
        stopped = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
        assert "signaled pid %s" % ours.pid in stopped.stdout
        ours.wait(timeout=3)
        assert other.poll() is None
    finally:
        for proc in (ours, other):
            if proc.poll() is None:
                proc.kill()


def test_exec_keeps_identity_and_stop_signals_that_pid(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    os.chmod(run_dir, 0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run_dir))
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc
    server = tmp_path / "llama-server"
    server.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n")
    server.chmod(0o755)
    starter = tmp_path / "start.sh"
    starter.write_text("#!/bin/sh\nsleep 0.2\nexec %s\n" % server)
    starter.chmod(0o755)
    proc = subprocess.Popen([str(starter)])
    try:
        time.sleep(0.05)
        early = hc._cmdline(proc.pid)
        assert "start.sh" in early
        token, _cmd = hc.process_identity(proc.pid)
        assert token
        hc.save_record("models", proc.pid, 9, early)
        time.sleep(0.6)
        later = hc._cmdline(proc.pid)
        assert "llama-server" in later
        assert hc.same_process(hc.load_record("models"))
        env = base_env(HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir))
        stopped = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
        assert "signaled pid %s" % proc.pid in stopped.stdout, stopped.stdout
        proc.wait(timeout=3)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_empty_identity_fails_closed(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    os.chmod(run_dir, 0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run_dir))
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc
    victim = subprocess.Popen(["sleep", "60"])
    try:
        hc.save_record("models", victim.pid, 9, hc._cmdline(victim.pid))
        rec = hc.load_record("models")
        rec["starttime"] = ""
        path = hc._state_path("models")
        with open(path, "w", encoding="ascii") as fh:
            import json
            fh.write(json.dumps(rec))
        assert hc.same_process(hc.load_record("models")) is False
        env = base_env(HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir))
        refused = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
        assert "nothing to stop" in refused.stdout
        assert victim.poll() is None
    finally:
        if victim.poll() is None:
            victim.kill()


def test_leading_dash_argument_is_refused():
    r = run([sys.executable, CATALOG, "models", "install", "--apply", "-x"])
    assert r.returncode == 2
    assert "starts with -" in r.stdout
    r = run([sys.executable, CATALOG, "tools", "install", "--apply", "-x"])
    assert r.returncode == 2


def test_apply_lock_fails_closed(monkeypatch, tmp_path):
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x", encoding="ascii")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(blocked))
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocked))
    monkeypatch.setenv("HOME", str(blocked))
    monkeypatch.setenv("TMPDIR", str(blocked))
    env = base_env(HOME=str(blocked), XDG_RUNTIME_DIR=str(blocked),
                   XDG_CACHE_HOME=str(blocked), TMPDIR=str(blocked))
    r = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
    assert r.returncode == 1
    assert "lock failed" in r.stdout


def _private_run(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    os.chmod(run_dir, 0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run_dir))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return run_dir


def test_stale_pidfile_is_not_adopted(tmp_path, monkeypatch):
    run_dir = _private_run(tmp_path, monkeypatch)
    victim = subprocess.Popen(["sleep", "60"])
    state = run_dir / "familia"
    state.mkdir()
    os.chmod(state, 0o700)
    pidfile = state / "home-models.pid"
    pidfile.write_text("%s\n" % victim.pid)
    old = time.time() - 30
    os.utime(pidfile, (old, old))
    launcher = tmp_path / "reuse.sh"
    launcher.write_text("#!/bin/sh\n# familia-home-test-launcher\necho reusing it\nexit 0\n")
    launcher.chmod(0o755)
    env = base_env(
        HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        FAMILIA_HOME_LAUNCHER=str(launcher),
    )
    try:
        started = run([sys.executable, CATALOG, "models", "start", "--apply"], env=env)
        assert started.returncode == 0, started.stdout + started.stderr
        assert "did not write a pid file" in started.stdout
        assert victim.poll() is None
        stopped = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
        assert "signaled" not in stopped.stdout
        assert victim.poll() is None
    finally:
        if victim.poll() is None:
            victim.kill()


def test_non_server_pid_from_this_launch_is_not_signaled(tmp_path, monkeypatch):
    run_dir = _private_run(tmp_path, monkeypatch)
    victim = subprocess.Popen(["sleep", "60"])
    launcher = tmp_path / "write-sleep.sh"
    launcher.write_text(
        "#!/bin/sh\n# familia-home-test-launcher\nprintf '%%s\\n' %s > \"$FAMILIA_PIDFILE\"\nexit 0\n"
        % victim.pid
    )
    launcher.chmod(0o755)
    env = base_env(
        HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        FAMILIA_HOME_LAUNCHER=str(launcher),
    )
    try:
        started = run([sys.executable, CATALOG, "models", "start", "--apply"], env=env)
        assert started.returncode == 0, started.stdout + started.stderr
        assert "not a server" in started.stdout
        assert victim.poll() is None
        stopped = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
        assert "signaled pid %s" % victim.pid not in stopped.stdout
        assert victim.poll() is None
    finally:
        if victim.poll() is None:
            victim.kill()


def test_server_pid_written_by_this_launch_can_be_stopped(tmp_path, monkeypatch):
    run_dir = _private_run(tmp_path, monkeypatch)
    server = tmp_path / "llama-server"
    server.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n")
    server.chmod(0o755)
    proc = subprocess.Popen([str(server)])
    launcher = tmp_path / "write-server.sh"
    launcher.write_text(
        "#!/bin/sh\n# familia-home-test-launcher\nprintf '%%s\\n' %s > \"$FAMILIA_PIDFILE\"\nexit 0\n"
        % proc.pid
    )
    launcher.chmod(0o755)
    env = base_env(
        HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        FAMILIA_HOME_LAUNCHER=str(launcher),
    )
    try:
        started = run([sys.executable, CATALOG, "models", "start", "--apply"], env=env)
        assert "recorded pid %s" % proc.pid in started.stdout, started.stdout
        stopped = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
        assert "signaled pid %s" % proc.pid in stopped.stdout, stopped.stdout
        proc.wait(timeout=3)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_listener_on_the_recorded_port_is_signaled(tmp_path, monkeypatch):
    run_dir = _private_run(tmp_path, monkeypatch)
    portf = tmp_path / "port"
    code = (
        "import socket,sys,time\n"
        "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "s.bind(('127.0.0.1', 0)); s.listen(1)\n"
        "open(sys.argv[1],'w').write(str(s.getsockname()[1]))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(portf)])
    try:
        for _ in range(50):
            if portf.exists():
                break
            time.sleep(0.05)
        port = int(portf.read_text())
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import home_catalog as hc
        hc.save_record("models", proc.pid, port, hc._cmdline(proc.pid))
        env = base_env(HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir),
                       XDG_CACHE_HOME=str(tmp_path / "cache"))
        stopped = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
        assert "signaled pid %s" % proc.pid in stopped.stdout, stopped.stdout
        proc.wait(timeout=3)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_windows_stop_uses_taskkill_tree(monkeypatch, tmp_path):
    run_dir = _private_run(tmp_path, monkeypatch)
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc
    calls = []

    def fake_run(argv, **_kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(hc, "_windows", lambda: True)
    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    assert hc._end_process(4242) is True
    assert calls and calls[0][:4] == ["taskkill", "/T", "/PID", "4242"]
    text = open(CATALOG, encoding="utf-8").read()
    assert "llama-server.exe" in text
    assert run_dir.is_dir()


def test_apply_error_is_not_called_a_lock_failure(monkeypatch, tmp_path):
    _private_run(tmp_path, monkeypatch)
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc

    def boom(_apply, _extra):
        raise OSError("real failure")

    monkeypatch.setitem(hc.ACTIONS["tools"], "stop", boom)
    try:
        hc.main(["tools", "stop", "--apply"])
    except OSError as exc:
        assert "real failure" in str(exc)
    else:
        raise AssertionError("the action error was swallowed")


def test_home_test_hold_is_not_a_production_switch():
    text = open(CATALOG, encoding="utf-8").read()
    shell = open(HOME, encoding="utf-8").read()
    assert "FAMILIA_HOME_TEST_HOLD" not in text
    assert "FAMILIA_HOME_TEST_HOLD" not in shell
    assert "# familia-home-test-launcher" in text


def test_save_record_stores_the_platform_identity_token(monkeypatch, tmp_path):
    _private_run(tmp_path, monkeypatch)
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc
    monkeypatch.setattr(hc, "_starttime", lambda pid: "")
    monkeypatch.setattr(hc, "process_identity", lambda pid: ("ps-lstart-token", "llama-server"))
    doc = hc.save_record("models", 50, 9, "")
    assert doc is not None
    assert doc["starttime"] == "ps-lstart-token"
    assert hc.load_record("models")["starttime"] == "ps-lstart-token"
    monkeypatch.setattr(hc, "process_identity", lambda pid: (None, None))
    assert hc.save_record("agents", 51, 9, "llama-server") is None
    assert hc.load_record("agents") is None
    assert hc.load_record("models")["starttime"] == "ps-lstart-token"


def test_adopt_does_not_claim_a_record_it_could_not_store(monkeypatch, tmp_path, capsys):
    _private_run(tmp_path, monkeypatch)
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc
    server = tmp_path / "llama-server"
    server.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
    server.chmod(0o755)
    proc = subprocess.Popen([str(server)])
    monkeypatch.setattr(hc, "save_record", lambda *a, **k: None)
    try:
        assert hc._adopt("models", proc.pid, 9) is None
        out = capsys.readouterr().out
        assert "recorded pid" not in out
        assert "could not be stored" in out
    finally:
        if proc.poll() is None:
            proc.kill()


def test_windows_license_gate_runs_on_the_tty_before_detach(monkeypatch, tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import home_catalog as hc
    monkeypatch.setattr(hc, "_windows", lambda: True)
    popen = []

    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "", "")

    def fake_popen(argv, **kw):
        popen.append(kw.get("stdin"))
        class P:
            pid = 77
        return P()

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    monkeypatch.setattr(hc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(hc, "_windows_server_pid", lambda _parent: 0)
    monkeypatch.setattr(hc, "_adopt", lambda *a, **k: {"pid": 77})
    assert hc.models_start(True, []) == 0
    assert popen == [subprocess.DEVNULL]
    body = open(CATALOG, encoding="utf-8").read().split("def models_start", 1)[1].split("def models_stop", 1)[0]
    assert "HERMES_ACCEPT_LICENSES" not in body
    assert body.find("licenses.py") < body.find("DETACHED_PROCESS")

    def refuse(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(hc.subprocess, "run", refuse)
    popen.clear()
    assert hc.models_start(True, []) == 1
    assert popen == []


def test_bootstrap_reuse_writes_the_listener_pid(tmp_path):
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    holder = tmp_path / "hold.py"
    holder.write_text(
        "import socket,sys,time\n"
        "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen(1)\n"
        "time.sleep(30)\n"
    )
    sock.close()
    proc = subprocess.Popen([sys.executable, str(holder), str(port)])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_py = sys.executable.replace("'", "'\\''")
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        "  *familia_auth.py*) exit 0 ;;\n"
        "esac\n"
        "exec '%s' \"$@\"\n" % real_py
    )
    stub.chmod(0o755)
    pidfile = tmp_path / "home-models.pid"
    env = base_env(
        PATH=str(bin_dir) + os.pathsep + "/usr/bin:/bin",
        HOME=str(tmp_path),
        PORT=str(port),
        FAMILIA_PIDFILE=str(pidfile),
        FAMILIA_ACCEPT_LICENSES="yes",
        FAMILIA_LICENSE_ACCEPT_FILE=str(tmp_path / "accept.json"),
        FAMILIA_SYNC="0",
    )
    try:
        bound = False
        for _ in range(50):
            if proc.poll() is not None:
                break
            try:
                probe = socket.socket()
                probe.settimeout(0.2)
                probe.connect(("127.0.0.1", port))
                probe.close()
                bound = True
                break
            except OSError:
                time.sleep(0.05)
        assert bound, "listener did not bind"
        started = run(["sh", os.path.join(ROOT, "start.sh"), "--bootstrap"], env=env)
        blob = started.stdout + started.stderr
        assert started.returncode == 0, blob
        assert "reusing it" in blob
        assert pidfile.read_text().strip() == str(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_cockpit_q_returns_to_the_menu(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _gum(bin_dir, ["Open llama-ui web cockpit", "Quit"])
    env = base_env(PATH=bin_dir + os.pathsep + "/usr/bin:/bin", TERM="dumb", NO_COLOR="1")
    rc, out = _pty(["sh", HOME], env, feed=b"q\n", timeout=25)
    assert rc == 0, out
    assert out.count("six equal items") >= 2


def test_termux_pkg_is_after_the_prompt():
    text = open(os.path.join(ROOT, "scripts", "install-gum.sh"), encoding="utf-8").read()
    ask = text.find("Install it now? [y/N]")
    pkg = text.find("pkg install -y gum")
    assert ask != -1 and pkg != -1 and ask < pkg
    assert "export PATH=" not in open(os.path.join(ROOT, "scripts", "familia_home.sh"), encoding="utf-8").read().split("gum()", 1)[0]


def test_unpinned_gum_version_is_refused(tmp_path):
    env = base_env(HOME=str(tmp_path), PATH="/usr/bin:/bin", FAMILIA_GUM_VERSION="9.9.9")
    script = os.path.join(ROOT, "scripts", "install-gum.sh")
    text = open(script, encoding="utf-8").read()
    assert "d842e06d93dbed90af48cb8dd10698db6f22e331fc40346bb37bbc753109edc2" in text
    assert "--proto '=https'" in text
    assert "mv -f" in text
    r = run(["sh", script, "--yes"], env=env)
    assert r.returncode != 0
    assert "pinned" in (r.stdout + r.stderr).lower()
