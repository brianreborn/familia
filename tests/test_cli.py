"""familia(1): every menu item is a subcommand, runs the identical command, and the man page is current."""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import familia_cli  # noqa: E402

FAMILIA = os.path.join(ROOT, "familia")
MENU = os.path.join(ROOT, "familia-menu.sh")


def env(**kw):
    e = dict(os.environ, FAMILIA_NO_TTY="1")
    for k in ("FAMILIA_ACCEPT_LICENSES", "FAMILIA_COLOR"):
        e.pop(k, None)
    e.update(kw)
    return e


def fam(*args, **kw):
    return subprocess.run(["sh", FAMILIA, *args], cwd=ROOT, capture_output=True, text=True, env=env(**kw),
                          stdin=subprocess.DEVNULL, timeout=120)


def nvals(cmd):
    return len(familia_cli.PH.findall(cmd))


ITEMS = [i for i in familia_cli.items() if i["cmd"]]
_, PREFER = familia_cli.table(False)
_, PREFER_WIN = familia_cli.table(True)


def test_every_item_has_a_subcommand():
    missing = [i["key"] for i in ITEMS if i["key"] not in PREFER]
    assert not missing, missing
    missing = [i["key"] for i in familia_cli.items() if i["win"] and i["key"] not in PREFER_WIN]
    assert not missing, missing


def test_name_table_points_at_real_items():
    keys = {i["key"] for i in familia_cli.items()}
    for f in familia_cli.rows(familia_cli.NAMES):
        assert f[1] == "raw" or f[1] in keys, f"scripts/cli-commands.txt: '{f[0]}' points at unknown item {f[1]}"
        assert f[0].split()[0] not in familia_cli.BUILTINS, f[0]


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["key"])
def test_subcommand_runs_the_identical_command(it):
    vals = ["v%d" % k for k in range(nvals(it["cmd"]))]
    words = list(PREFER[it["key"]])
    a = fam("--dry-run", *words, *vals)
    b = subprocess.run(["bash", MENU, "--run", it["key"], *vals, "--dry-run"], cwd=ROOT, capture_output=True,
                       text=True, env=env(), stdin=subprocess.DEVNULL, timeout=120)
    assert (a.returncode, a.stdout) == (b.returncode, b.stdout), (words, a.stderr, b.stderr)
    # the key and GROUP NAME forms reach the same item
    assert fam("--dry-run", it["key"], *vals).stdout == b.stdout
    pre, _, short = it["key"].partition(".")
    if pre not in familia_cli.BUILTINS:
        assert fam("--dry-run", pre, short, *vals).stdout == b.stdout


def test_values_as_flags_defaults_and_passthrough():
    r = fam("--dry-run", "harness2", "set", "--mode", "propose", "--agent", "hermes", "-v")
    assert r.stdout.splitlines()[-1] == "[dry-run] python3 scripts/harness2.py set --agent hermes --mode propose -v"
    r = fam("--dry-run", "harness2", "set", "hermes", "off")
    assert "set --agent hermes --mode off" in r.stdout
    assert "--agent hermes" in fam("--dry-run", "skills", "menu").stdout  # [hermes] default
    assert "--quant Q4_K_M" in fam("--dry-run", "model", "fetch", "org/name").stdout
    r = fam("--dry-run", "serve")
    assert r.returncode == 2 and "item needs NODE" in r.stderr and "familia serve VALUE" in r.stderr
    assert "[dry-run] sh familia-monitor --once phone7" in fam("--dry-run", "monitor", "--once", "phone7").stdout
    assert "scripts/hermes.sh --model coder" in fam("--dry-run", "hermes", "--model", "coder").stdout
    assert "scripts/hermes.sh --graph-mode" in fam("--dry-run", "hermes", "--graph-mode").stdout
    assert "[dry-run] sh install/linux/install.sh --dry-run" in fam("--dry-run", "install", "--dry-run").stdout


def test_pass_through_commands():
    assert fam("--dry-run", "skills", "enable", "green-probe").stdout.strip() == \
        "[dry-run] python3 scripts/skills.py enable green-probe"
    assert fam("--dry-run", "licenses", "check").stdout.strip() == "[dry-run] python3 scripts/licenses.py check"
    r = fam("skills", "list")
    assert r.returncode == 0 and "green-zkillz" in r.stdout


def test_same_license_gate_as_the_menu(tmp_path):
    f = str(tmp_path / "a.json")
    a = fam("start", FAMILIA_LICENSE_ACCEPT_FILE=f)
    b = subprocess.run(["bash", MENU, "--run", "hosts.start"], cwd=ROOT, capture_output=True, text=True,
                       env=env(FAMILIA_LICENSE_ACCEPT_FILE=f), stdin=subprocess.DEVNULL)
    assert a.returncode == b.returncode != 0
    assert "licenses" in a.stderr.lower()
    assert "would first run: python3 scripts/licenses.py gate" in fam("--dry-run", "start").stdout


def test_help():
    r = fam("help")
    assert r.returncode == 0
    for it in ITEMS:
        assert " ".join(PREFER[it["key"]]) in r.stdout, it["key"]
    assert "serve <NODE>" in r.stdout and "*" in r.stdout
    assert fam("--help").stdout == r.stdout
    r = fam("help", "serve")
    assert "familia serve <NODE>" in r.stdout and "runs: sh scripts/serve.sh <NODE>" in r.stdout
    r = fam("model", "params", "--help")
    assert r.returncode == 0 and "--explain <NODE>" in r.stdout and "validate_graph.py --help" in r.stdout
    assert fam("help", "nope-nope").returncode == 2


def test_unknown_and_builtins():
    r = fam("bogus")
    assert r.returncode == 2 and "familia help" in r.stderr
    assert fam("--bogus").returncode == 2
    assert "skills.menu" in fam("list").stdout
    assert fam("search", "hermes").returncode == 0
    assert "[dry-run]" in fam("--dry-run", "run", "models.check").stdout
    assert fam("menu").returncode == 2  # no terminal
    r = fam("completion", "bash")
    assert r.returncode == 0 and "complete -o default -F _familia" in r.stdout
    words = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "familia_cli.py"), "words"],
                           capture_output=True, text=True).stdout.split()
    assert {"serve", "model", "help", "search"} <= set(words)
    words = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "familia_cli.py"), "words", "model"],
                           capture_output=True, text=True).stdout.split()
    assert {"add", "fetch", "params", "db"} <= set(words)


def test_man_page_is_current():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "familia_cli.py"), "man", "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    page = open(os.path.join(ROOT, "man", "familia.1"), encoding="utf-8").read()
    for sec in ("NAME", "SYNOPSIS", "DESCRIPTION", "COMMANDS", "OPTIONS", "ENVIRONMENT", "FILES", "EXIT STATUS",
                "EXAMPLES", "SEE ALSO"):
        assert f".SH {sec}" in page, sec
    for v in ("FAMILIA_COLOR", "NO_COLOR", "HF_TOKEN"):
        assert v.replace("_", "_") in page
    assert "never printed" in page


@pytest.mark.skipif(not shutil.which("man"), reason="man is not installed")
def test_help_man():
    r = fam("help", "--man", MANPAGER="cat", PAGER="cat")
    assert r.returncode == 0 and "SYNOPSIS" in r.stdout


@pytest.mark.skipif(not shutil.which("groff"), reason="groff is not installed")
def test_man_page_renders_without_warnings():
    r = subprocess.run(["groff", "-man", "-ww", "-z", os.path.join(ROOT, "man", "familia.1")], capture_output=True,
                       text=True)
    assert r.returncode == 0 and not r.stderr.strip(), r.stderr


def test_windows_front_door_reads_the_same_tables():
    ps = open(os.path.join(ROOT, "scripts", "windows", "familia-menu.ps1"), encoding="utf-8").read()
    assert "familia_cli.py resolve --windows" in ps
    cmd = open(os.path.join(ROOT, "familia.cmd"), encoding="utf-8").read()
    assert "FAMILIA_CLI_ARGS" in cmd


@pytest.mark.skipif(not shutil.which("pwsh"), reason="pwsh is not installed")
def test_windows_subcommands_with_pwsh():
    ps = os.path.join(ROOT, "scripts", "windows", "familia-menu.ps1")

    def run(args):
        return subprocess.run(["pwsh", "-NoProfile", "-File", ps, "-Cli"], cwd=ROOT, capture_output=True, text=True,
                              env=env(FAMILIA_CLI_ARGS=args), stdin=subprocess.DEVNULL, timeout=120).stdout
    out = run("--dry-run harness2 set --mode propose --agent hermes -v")
    assert 'set --agent "hermes" --mode "propose" -v' in out
    assert "familia.cmd model params <NODE>" in run("help model params")
