"""Menu search (/word, ?word, n, N, --search) on POSIX, and the same feature in the Windows menu."""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MENU = os.path.join(ROOT, "familia-menu.sh")
PS1 = os.path.join(ROOT, "scripts", "windows", "familia-menu.ps1")


def env(**kw):
    e = dict(os.environ, FAMILIA_NO_TTY="1")
    e.pop("FAMILIA_ACCEPT_LICENSES", None)
    e.pop("FAMILIA_COLOR", None)
    e.update(kw)
    return e


def menu(*args, inp=None, **kw):
    return subprocess.run(["bash", MENU, *args], cwd=ROOT, capture_output=True, text=True, env=env(**kw),
                          input=inp, stdin=None if inp is not None else subprocess.DEVNULL, timeout=180)


def groups_of(out):
    return set(re.findall(r"^[> ] ?\s*\d+\) (.+?) > ", out, re.M))


def test_search_matches_across_groups_case_insensitive():
    # no menu item mentions dry-run any more (#228); HERMES (upper) still proves case-insensitivity
    r = menu("--search", "HERMES")
    assert r.returncode == 0, r.stderr
    assert len(groups_of(r.stdout)) >= 3, r.stdout
    assert "runs: " in r.stdout and "key: " in r.stdout
    assert "--search HERMES --run N" in r.stdout
    # group names and keys are searched too
    assert "hosts.monitor" in menu("--search", "Hosts").stdout
    assert "adv.db-list" in menu("--search", "adv.db").stdout


def test_search_no_match():
    r = menu("--search", "zzqqxx")
    assert r.returncode == 1
    assert "No item matches 'zzqqxx'" in r.stdout


def test_search_needs_a_word():
    r = menu("--search")
    assert r.returncode == 2 and "--search needs a word" in r.stderr


def test_search_run_n_goes_through_the_same_gate(tmp_path):
    r = menu("--search", "start the model server on this", "--run", "1", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "would first run: python3 scripts/licenses.py gate" in r.stdout
    assert "[dry-run] sh start.sh" in r.stdout
    # for real, without accepted licenses and no terminal: refused exactly like --run hosts.start
    r = menu("--search", "start the model server on this", "--run", "1",
             FAMILIA_LICENSE_ACCEPT_FILE=str(tmp_path / "a.json"))
    assert r.returncode != 0 and "licenses" in r.stderr.lower()
    r2 = menu("--run", "hosts.start", FAMILIA_LICENSE_ACCEPT_FILE=str(tmp_path / "a.json"))
    assert r2.returncode == r.returncode


def test_search_run_n_prompts_args_and_bounds():
    r = menu("--search", "explain", "--run", "1", "coder", "--dry-run")
    assert r.returncode == 0 and "--explain coder" in r.stdout, r.stdout + r.stderr
    r = menu("--search", "explain", "--run", "1", "--dry-run")
    assert r.returncode == 2 and "item needs NODE" in r.stderr
    r = menu("--search", "explain", "--run", "9")
    assert r.returncode == 2 and "match(es)" in r.stderr


def test_interactive_search_n_and_N_cycle():
    r = menu("--pipe", "--dry-run", inp="/start the\nn\nn\nN\nb\nq\n")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "Search: 'start the' (2 match(es)" in out
    steps = re.findall(r"match (\d) of 2 for 'start the'", out)
    assert steps == ["2", "1", "2"], steps  # n, n (wraps), N


def test_backward_search_and_repeat():
    r = menu("--pipe", "--dry-run", inp="?skills\nb\n/\nb\nq\n")
    out = r.stdout
    blocks = out.split("Search: 'skills'")
    assert len(blocks) == 3, out  # ?skills, then / alone repeats it
    first = blocks[1].split("Choose")[0]
    marked = [l for l in first.splitlines() if l.startswith(">")]
    assert len(marked) == 1 and "adv.skills-paths" not in marked[0]
    assert re.search(r"^>\s*\d+\) Advanced: agents", first, re.M), first  # backward: starts at the last match
    second = blocks[2].split("Choose")[0]
    assert re.search(r"^>\s*1\) Skills", second, re.M)  # / searches forward from the first


def test_search_from_a_group_and_no_previous():
    r = menu("--pipe", "--dry-run", inp="n\n2\n/zzqqxx\n/licen\nb\nb\nq\n")
    out = r.stdout
    assert "No previous search" in out
    assert "No item matches 'zzqqxx'" in out
    assert "Search: 'licen'" in out


def test_selected_result_runs_like_a_regular_item():
    r = menu("--pipe", "--dry-run", inp="/explain\n1\ncoder\nq\n")
    assert "[dry-run] python3 scripts/validate_graph.py --graph graph.yaml --explain coder" in r.stdout, r.stdout
    r = menu("--pipe", "--dry-run", inp="/start the model\n1\nq\n")
    assert "would first run: python3 scripts/licenses.py gate" in r.stdout


def test_footer_shows_search():
    r = menu("--pipe", inp="2\nb\nq\n")
    assert r.stdout.count("/word search every group") >= 2
    assert "/search or q" in r.stderr and "/search or b" in r.stderr  # prompts go to stderr
    assert "--search TEXT" in menu("--help").stdout


def test_highlight_only_when_supported():
    plain = menu("--search", "hermes").stdout
    assert "\x1b[" not in plain
    color = menu("--search", "hermes", FAMILIA_COLOR="always").stdout
    assert "\x1b[7mhermes\x1b[0m" in color


def test_familia_entry_point_search():
    r = subprocess.run(["sh", os.path.join(ROOT, "familia"), "search", "licen"], capture_output=True, text=True,
                       cwd=ROOT, env=env())
    assert r.returncode == 0 and "setup.licenses" in r.stdout
    r = subprocess.run(["sh", os.path.join(ROOT, "familia"), "--search", "skills list", "--run", "1"],
                       capture_output=True, text=True, cwd=ROOT, env=env())
    assert r.returncode == 0 and "green-probe" in r.stdout


def test_windows_menu_has_the_same_search():
    s = open(PS1, encoding="utf-8").read()
    for needle in ("[string]$Search", "function SearchUi", "function FindMatches", "-ceq 'N'",
                   "/word search every group", "-Search TEXT" if "-Search TEXT" in s else "-Search"):
        assert needle in s, needle
    assert "$pageSize = 7" in s and "</> page" in s
    assert "&&" not in s


PWSH = shutil.which("pwsh")


@pytest.mark.skipif(not PWSH, reason="PowerShell (pwsh) is not installed")
def test_windows_long_group_is_paged():
    r = subprocess.run([PWSH, "-NoProfile", "-File", PS1, "-Pipe", "-DryRun"], cwd=ROOT, capture_output=True,
                       text=True, env=env(), input="1\n>\n<\nb\nq\n", timeout=180)
    assert r.returncode == 0, r.stderr
    assert "Page 1 of 3 (items 1-7 of 15)" in r.stdout
    assert "Page 2 of 3 (items 8-14 of 15)" in r.stdout


@pytest.mark.skipif(not PWSH, reason="PowerShell (pwsh) is not installed")
def test_windows_search_runs(tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python").symlink_to(shutil.which("python3"))
    e = env(PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
    run = lambda *a, inp=None: subprocess.run([PWSH, "-NoProfile", "-File", PS1, *a], cwd=ROOT, capture_output=True,
                                              text=True, env=e, input=inp, timeout=180)
    r = run("-Search", "start the model server on this", "-Run", "1", "-DryRun")
    assert "would first run: python scripts\\licenses.py gate" in r.stdout
    r = run("-Pipe", "-DryRun", inp="/model data\nn\nN\nb\nq\n")
    assert re.findall(r"match (\d) of \d+ for 'model data'", r.stdout) == ["2", "1"]
