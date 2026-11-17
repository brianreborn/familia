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
    assert "API key" in start.stdout
    mcp = run([sys.executable, CATALOG, "mcp", "start", "--apply"])
    assert mcp.returncode == 0
    assert "Refusing" in mcp.stdout
    assert "API key" in mcp.stdout
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


def test_sigint_during_action_stays_until_quit(tmp_path):
    bin_dir = str(tmp_path / "bin")
    _gum(bin_dir, ["Models", "start", "Quit"])
    env = base_env(
        PATH=bin_dir + os.pathsep + "/usr/bin:/bin",
        TERM="dumb",
        NO_COLOR="1",
        FAMILIA_HOME_TEST_HOLD="1",
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
    env = base_env(HOME=str(tmp_path), XDG_RUNTIME_DIR=str(run_dir),
                   XDG_CACHE_HOME=str(tmp_path / "cache"))
    refused = run([sys.executable, CATALOG, "models", "stop", "--apply"], env=env)
    assert refused.returncode == 0, refused.stdout + refused.stderr
    assert "nothing to stop" in refused.stdout
    assert "signaled pid 1" not in refused.stdout
    ours = subprocess.Popen(["sleep", "60"])
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
