"""scripts/sync_pins.py: every pinned part moves to its pin together, safely (REQUIREMENTS.md R-sync).

All repositories are temporary local git repos; no network is used."""
import os
import shutil
import stat
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNC = os.path.join(ROOT, "scripts", "sync_pins.py")
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
           FAMILIA_SYNC="1")
ENV.pop("FAMILIA_SYNC_DONE", None)

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def g(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), check=True, capture_output=True, text=True,
                          env=ENV).stdout.strip()


def commit(repo, name, text):
    (repo / name).write_text(text)
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", text)
    return g(repo, "rev-parse", "HEAD")


def upstream(tmp, name):
    r = tmp / "up" / name
    r.mkdir(parents=True)
    g(r, "init", "-q", "-b", "main")
    c1 = commit(r, "f.txt", "one")
    c2 = commit(r, "f.txt", "two")
    return r, c1, c2


def pins(root, rows):
    (root / "pins.txt").write_text("# name\trev\torigin\trole\n" +
                                   "".join("%s\t%s\t%s\tpart\n" % r for r in rows) + "node\tmodel\n")


def nested(root, up, name, at):
    d = root / name
    g(root, "clone", "-q", str(up), name)
    g(d, "-c", "advice.detachedHead=false", "checkout", "-q", at)
    return d


def sync(root, *args, env=None):
    return subprocess.run([sys.executable, SYNC, "--root", str(root)] + list(args), capture_output=True, text=True,
                          env=env or ENV)


@pytest.fixture
def fam(tmp_path):
    root = tmp_path / "familia"
    root.mkdir()
    return root


def test_drift_is_corrected_together(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    b, b1, b2 = upstream(tmp_path, "b")
    nested(fam, a, "a", a1)
    nested(fam, b, "b", b1)
    pins(fam, [("a", a2, a), ("b", b2, b)])
    r = sync(fam)
    assert r.returncode == 0, r.stderr
    assert g(fam / "a", "rev-parse", "HEAD") == a2 and g(fam / "b", "rev-parse", "HEAD") == b2
    assert "moved a" in r.stderr and "moved b" in r.stderr


def test_in_sync_is_a_noop_without_git_or_network(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    nested(fam, a, "a", a2)
    pins(fam, [("a", a2, "https://unreachable.invalid/a.git")])
    fake = tmp_path / "bin"
    fake.mkdir()
    marker = tmp_path / "git-was-called"
    (fake / "git").write_text("#!/bin/sh\ntouch %s\nexit 1\n" % marker)
    (fake / "git").chmod(0o755)
    env = dict(ENV, PATH=str(fake) + os.pathsep + ENV["PATH"])
    r = sync(fam, "--auto", env=env)
    assert r.returncode == 0 and r.stderr == "" and r.stdout == ""
    assert not marker.exists(), "an in-sync part must not run git (and so never touches the network)"


def test_dirty_nested_checkout_refuses_and_moves_nothing(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    b, b1, b2 = upstream(tmp_path, "b")
    da = nested(fam, a, "a", a1)
    nested(fam, b, "b", b1)
    (da / "f.txt").write_text("my local edit")
    pins(fam, [("a", a2, a), ("b", b2, b)])
    r = sync(fam)
    assert r.returncode == 3
    assert "REFUSED a" in r.stderr and "stash" in r.stderr
    assert (da / "f.txt").read_text() == "my local edit"
    assert g(da, "rev-parse", "HEAD") == a1
    assert g(fam / "b", "rev-parse", "HEAD") == b1, "all or nothing: b must not move when a is refused"
    assert sync(fam, "--dry-run").returncode == 3




def test_empty_placeholder_dir_is_replaced_not_refused(tmp_path, fam):
    """A leftover empty gitlink dir (plain git clone of a 160000 entry) must clone."""
    a, a1, a2 = upstream(tmp_path, "a")
    (fam / "a").mkdir()  # empty placeholder, like an unpopulated submodule
    pins(fam, [("a", a2, a)])
    dry = sync(fam, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "replace empty dir" in dry.stdout or "clone" in dry.stdout
    r = sync(fam)
    assert r.returncode == 0, r.stderr
    assert g(fam / "a", "rev-parse", "HEAD") == a2
    assert (fam / "a" / "f.txt").exists()


def test_nonempty_nongit_dir_still_refused(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    d = fam / "a"
    d.mkdir()
    (d / "keepme.txt").write_text("local stuff")
    pins(fam, [("a", a2, a)])
    r = sync(fam)
    assert r.returncode == 3
    assert "REFUSED a" in r.stderr
    assert (d / "keepme.txt").read_text() == "local stuff"
    assert not (d / ".git").exists()

def test_commit_on_no_branch_refuses(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    da = nested(fam, a, "a", a1)
    lone = commit(da, "g.txt", "local work on a detached HEAD")
    pins(fam, [("a", a2, a)])
    r = sync(fam)
    assert r.returncode == 3 and "on no branch" in r.stderr
    assert g(da, "rev-parse", "HEAD") == lone


def test_missing_commit_is_fetched(tmp_path, fam):
    a, a1, _ = upstream(tmp_path, "a")
    da = nested(fam, a, "a", a1)
    a3 = commit(a, "f.txt", "three")  # only upstream has it
    pins(fam, [("a", a3, a)])
    assert "fetch the pin" in sync(fam, "--dry-run").stdout
    assert g(da, "rev-parse", "HEAD") == a1, "dry run changes nothing"
    r = sync(fam)
    assert r.returncode == 0, r.stderr
    assert g(da, "rev-parse", "HEAD") == a3


def test_missing_part_is_cloned_and_unfetchable_pin_changes_nothing(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    b, b1, b2 = upstream(tmp_path, "b")
    nested(fam, b, "b", b1)
    pins(fam, [("a", a2, a), ("b", "0" * 40, b)])
    r = sync(fam)
    assert r.returncode == 1 and "Nothing was changed" in r.stderr
    assert not (fam / "a").exists() and not list(fam.glob("*.sync-tmp"))
    pins(fam, [("a", a2, a), ("b", b2, b)])
    r = sync(fam)
    assert r.returncode == 0, r.stderr
    assert g(fam / "a", "rev-parse", "HEAD") == a2 and g(fam / "b", "rev-parse", "HEAD") == b2


def test_engine_pin_only_when_asked_for(tmp_path, fam):
    e, e1, e2 = upstream(tmp_path, "e")
    pins(fam, [("llama-server__x__y", e2, e)])
    assert sync(fam).returncode == 0 and not (fam / "llama-server__x__y").exists()
    r = sync(fam, env=dict(ENV, ENGINE_CHAT="x__y"))
    assert r.returncode == 0, r.stderr
    assert g(fam / "llama-server__x__y", "rev-parse", "HEAD") == e2


def test_git_pull_of_familia_syncs_through_the_hook_and_update(tmp_path):
    a, a1, a2 = upstream(tmp_path, "a")
    up = tmp_path / "up" / "familia"
    (up / "scripts").mkdir(parents=True)
    shutil.copy(SYNC, up / "scripts" / "sync_pins.py")
    g(up.parent, "init", "-q", "-b", "main", "familia")
    pins(up, [("a", a1, a)])
    g(up, "add", ".")
    g(up, "commit", "-q", "-m", "pins a1")
    g(tmp_path, "clone", "-q", "--branch", "main", str(up), "mine")
    mine = tmp_path / "mine"
    assert sync(mine).returncode == 0 and g(mine / "a", "rev-parse", "HEAD") == a1
    assert sync(mine, "--install-hooks").returncode == 0
    pins(up, [("a", a2, a)])
    g(up, "commit", "-q", "-am", "pins a2")
    subprocess.run(["git", "-C", str(mine), "pull", "-q", "--ff-only"], check=True, env=ENV, capture_output=True)
    assert g(mine / "a", "rev-parse", "HEAD") == a2, "post-merge hook syncs after git pull"
    a3 = commit(a, "f.txt", "three")
    pins(up, [("a", a3, a)])
    g(up, "commit", "-q", "-am", "pins a3")
    hook = mine / ".git" / "hooks" / "post-merge"
    hook.unlink()
    r = sync(mine, "--update")
    assert r.returncode == 0, r.stderr
    assert g(mine / "a", "rev-parse", "HEAD") == a3, "familia update = pull, then sync"


def test_branch_option_fast_forwards_familia_then_syncs_its_pins(tmp_path):
    a, a1, a2 = upstream(tmp_path, "a")
    up = tmp_path / "up" / "familia"
    (up / "scripts").mkdir(parents=True)
    shutil.copy(SYNC, up / "scripts" / "sync_pins.py")
    g(up.parent, "init", "-q", "-b", "main", "familia")
    pins(up, [("a", a1, a)])
    g(up, "add", ".")
    g(up, "commit", "-q", "-m", "main pins")
    g(up, "checkout", "-q", "-b", "feature")
    pins(up, [("a", a2, a)])
    g(up, "commit", "-q", "-am", "feature pins")
    g(tmp_path, "clone", "-q", "--branch", "main", str(up), "mine")
    mine = tmp_path / "mine"

    dry = sync(mine, "--branch", "feature", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "switch this checkout to track it" in dry.stdout
    assert g(mine, "branch", "--show-current") == "main"

    r = sync(mine, "--branch", "feature")
    assert r.returncode == 0, r.stderr
    assert g(mine, "branch", "--show-current") == "feature"
    assert g(mine, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/feature"
    assert g(mine, "rev-parse", "HEAD") == g(up, "rev-parse", "HEAD")
    assert g(mine / "a", "rev-parse", "HEAD") == a2
    r = sync(mine, "--update")
    assert r.returncode == 0, r.stderr
    assert g(mine, "branch", "--show-current") == "feature"


def test_branch_option_rejects_invalid_names(tmp_path, fam):
    g(fam, "init", "-q")
    r = sync(fam, "--branch", "-bad")
    assert r.returncode == 2
    assert "invalid branch name" in r.stderr


def test_foreign_hook_is_left_alone(tmp_path, fam):
    g(fam, "init", "-q")
    h = fam / ".git" / "hooks" / "post-merge"
    h.parent.mkdir(parents=True, exist_ok=True)
    h.write_text("#!/bin/sh\necho mine\n")
    r = sync(fam, "--install-hooks")
    assert r.returncode == 0 and "left your own" in r.stderr
    assert h.read_text() == "#!/bin/sh\necho mine\n"
    assert "sync_pins.py" in (fam / ".git" / "hooks" / "post-rewrite").read_text()


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


CALLERS = ["scripts/configure.sh", "scripts/run-tests.sh", "start.sh", "scripts/serve.sh", "with-fleet.sh",
           "scripts/panel.py", "install/linux/install.sh", "install/termux/install.sh",
           "install/windows/install.ps1", "scripts/windows/start.bat", "scripts/cli-commands.txt"]


@pytest.mark.parametrize("rel", CALLERS)
def test_every_updating_or_running_script_syncs(rel):
    assert "sync_pins.py" in read(rel), rel + " must call scripts/sync_pins.py (REQUIREMENTS.md R-sync)"


def test_menu_has_sync_and_update():
    items = read("scripts/menu-items.txt")
    for key in ("setup.sync|", "setup.update|", "setup.sync-goal|"):
        assert key in items


@pytest.mark.parametrize("rel", ["scripts/add-model.sh", "scripts/add_model.py", "scripts/hf_fetch.py",
                                 "scripts/model_db.py"])
def test_adding_or_fetching_a_model_does_not_sync(rel):
    assert "sync_pins" not in read(rel)


def test_run_tests_syncs_before_pytest(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    nested(fam, a, "a", a1)
    pins(fam, [("a", a2, a)])
    (fam / "scripts").mkdir()
    for f in ("run-tests.sh", "sync_pins.py"):
        shutil.copy(os.path.join(ROOT, "scripts", f), fam / "scripts" / f)
    (fam / ".cache").mkdir()
    pylib = os.path.join(ROOT, ".cache", "pylib")
    if not os.path.isdir(pylib):
        pytest.skip("pytest is not in .cache/pylib")
    os.symlink(pylib, fam / ".cache" / "pylib")
    (fam / "tests").mkdir()
    (fam / "tests" / "test_x.py").write_text(
        "import subprocess\n"
        "def test_synced():\n"
        "    h = subprocess.run(['git', '-C', %r, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()\n"
        "    assert h == %r\n" % (str(fam / "a"), a2))
    r = subprocess.run(["sh", str(fam / "scripts" / "run-tests.sh")], capture_output=True, text=True,
                       env=dict(ENV, PYTHON=sys.executable))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "moved a" in r.stderr
