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
for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
           "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX"):
    ENV.pop(_k, None)

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


def test_user_edit_survives_the_sync(tmp_path, fam):
    """familia #181 U10: a real local edit never blocks a sync and is kept."""
    a, a1, a2 = upstream(tmp_path, "a")
    commit(a, "other.txt", "upstream adds other")
    a3 = g(a, "rev-parse", "HEAD")
    b, b1, b2 = upstream(tmp_path, "b")
    da = nested(fam, a, "a", a1)
    nested(fam, b, "b", b1)
    (da / "other0.txt").write_text("x")  # untracked file is kept too
    commit(da, "mine.txt", "base")  # on a1+: a tracked file the update does not touch
    g(da, "-c", "advice.detachedHead=false", "checkout", "-q", a1)
    g(da, "checkout", "-q", "HEAD@{1}", "--", "mine.txt")
    pins(fam, [("a", a3, a), ("b", b2, b)])
    (da / "f.txt").write_text("two")  # same as upstream's change: pops cleanly
    r = sync(fam)
    assert r.returncode == 0, r.stderr
    assert g(da, "rev-parse", "HEAD") == a3 and g(fam / "b", "rev-parse", "HEAD") == b2
    assert (da / "mine.txt").read_text() == "base" and (da / "other0.txt").read_text() == "x"
    assert g(da, "stash", "list") == ""


def test_conflicting_user_edit_is_kept_in_stash(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    da = nested(fam, a, "a", a1)
    (da / "f.txt").write_text("my local edit")
    pins(fam, [("a", a2, a)])
    r = sync(fam)
    assert r.returncode == 0, r.stderr
    assert g(da, "rev-parse", "HEAD") == a2
    assert (da / "f.txt").read_text() == "two"
    assert "stash pop stash@{0}" in r.stderr and "familia-sync" in g(da, "stash", "list")
    g(da, "checkout", "-q", "-B", "restore")
    g(da, "-c", "advice.detachedHead=false", "checkout", "-q", a1)
    g(da, "stash", "pop")
    assert (da / "f.txt").read_text() == "my local edit", "the user's edit is never lost"


def test_no_stash_refuses_and_moves_nothing(tmp_path, fam):
    a, a1, a2 = upstream(tmp_path, "a")
    b, b1, b2 = upstream(tmp_path, "b")
    da = nested(fam, a, "a", a1)
    nested(fam, b, "b", b1)
    (da / "f.txt").write_text("my local edit")
    pins(fam, [("a", a2, a), ("b", b2, b)])
    r = sync(fam, "--no-stash")
    assert r.returncode == 3
    assert "REFUSED a" in r.stderr and "stash" in r.stderr
    assert (da / "f.txt").read_text() == "my local edit"
    assert g(da, "rev-parse", "HEAD") == a1
    assert g(fam / "b", "rev-parse", "HEAD") == b1
    assert sync(fam, "--force").returncode == 0


def test_our_patched_submodule_is_clean(tmp_path, fam):
    """Our own llama.cpp patch commits in a submodule never count as a local change."""
    lib, l1, l2 = upstream(tmp_path, "lib")
    a, a1, a2 = upstream(tmp_path, "a")
    g(a, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "sub")
    g(a, "commit", "-q", "-m", "sub")
    a3 = g(a, "rev-parse", "HEAD")
    commit(a, "g.txt", "later")
    a4 = g(a, "rev-parse", "HEAD")
    da = fam / "a"
    g(fam, "clone", "-q", str(a), "a")
    g(da, "-c", "advice.detachedHead=false", "checkout", "-q", a3)
    g(da, "-c", "protocol.file.allow=always", "submodule", "update", "-q", "--init")
    commit(da / "sub", "f.txt", "familia patch")  # like apply-patches.sh: a local commit in the submodule
    (da / "sub" / "build.ini").write_text("generated")
    pins(fam, [("a", a4, a)])
    r = sync(fam)
    assert r.returncode == 0, r.stderr
    assert "stash" not in r.stderr
    assert g(da, "rev-parse", "HEAD") == a4


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



def test_linked_worktree_hook_skips_sync_by_default(tmp_path):
    """git worktree add must not clone every pin (#108); message says how to sync."""
    a, a1, a2 = upstream(tmp_path, "a")
    up = tmp_path / "up" / "familia"
    (up / "scripts").mkdir(parents=True)
    shutil.copy(SYNC, up / "scripts" / "sync_pins.py")
    g(up.parent, "init", "-q", "-b", "main", "familia")
    pins(up, [("a", a2, a)])
    g(up, "add", ".")
    g(up, "commit", "-q", "-m", "pins")
    g(tmp_path, "clone", "-q", "--branch", "main", str(up), "mine")
    mine = tmp_path / "mine"
    assert sync(mine, "--install-hooks").returncode == 0
    # No pins checked out yet in the primary either for this test — we care that
    # creating a linked worktree does not clone them into the new tree.
    wt = tmp_path / "wt"
    env = dict(ENV)
    env.pop("FAMILIA_SYNC", None)  # default: linked worktrees skip
    r = subprocess.run(["git", "-C", str(mine), "worktree", "add", str(wt), "HEAD"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    combined = (r.stdout or "") + (r.stderr or "")
    assert "linked worktree" in combined and "FAMILIA_SYNC=1" in combined and "./familia sync" in combined
    assert not (wt / "a").exists(), "linked worktree must not clone pins by default"
    assert (wt / ".git").is_file()


def test_linked_worktree_syncs_with_FAMILIA_SYNC_1(tmp_path):
    a, a1, a2 = upstream(tmp_path, "a")
    up = tmp_path / "up" / "familia"
    (up / "scripts").mkdir(parents=True)
    shutil.copy(SYNC, up / "scripts" / "sync_pins.py")
    g(up.parent, "init", "-q", "-b", "main", "familia")
    pins(up, [("a", a2, a)])
    g(up, "add", ".")
    g(up, "commit", "-q", "-m", "pins")
    g(tmp_path, "clone", "-q", "--branch", "main", str(up), "mine")
    mine = tmp_path / "mine"
    assert sync(mine, "--install-hooks").returncode == 0
    wt = tmp_path / "wt"
    r = subprocess.run(["git", "-C", str(mine), "worktree", "add", str(wt), "HEAD"],
                       capture_output=True, text=True, env=dict(ENV, FAMILIA_SYNC="1"))
    assert r.returncode == 0, r.stderr
    assert g(wt / "a", "rev-parse", "HEAD") == a2


def test_linked_worktree_explicit_sync_still_runs(tmp_path):
    a, a1, a2 = upstream(tmp_path, "a")
    up = tmp_path / "up" / "familia"
    (up / "scripts").mkdir(parents=True)
    shutil.copy(SYNC, up / "scripts" / "sync_pins.py")
    g(up.parent, "init", "-q", "-b", "main", "familia")
    pins(up, [("a", a2, a)])
    g(up, "add", ".")
    g(up, "commit", "-q", "-m", "pins")
    g(tmp_path, "clone", "-q", "--branch", "main", str(up), "mine")
    mine = tmp_path / "mine"
    assert sync(mine, "--install-hooks").returncode == 0
    wt = tmp_path / "wt"
    env = dict(ENV)
    env.pop("FAMILIA_SYNC", None)
    assert subprocess.run(["git", "-C", str(mine), "worktree", "add", str(wt), "HEAD"],
                          capture_output=True, text=True, env=env).returncode == 0
    assert not (wt / "a").exists()
    # Explicit sync (no --auto) must still bring pins in, even without FAMILIA_SYNC=1.
    r = sync(wt, env=env)
    assert r.returncode == 0, r.stderr
    assert g(wt / "a", "rev-parse", "HEAD") == a2


def test_linked_worktree_auto_skips_without_opt_in(tmp_path):
    a, a1, a2 = upstream(tmp_path, "a")
    up = tmp_path / "up" / "familia"
    (up / "scripts").mkdir(parents=True)
    shutil.copy(SYNC, up / "scripts" / "sync_pins.py")
    g(up.parent, "init", "-q", "-b", "main", "familia")
    pins(up, [("a", a2, a)])
    g(up, "add", ".")
    g(up, "commit", "-q", "-m", "pins")
    g(tmp_path, "clone", "-q", "--branch", "main", str(up), "mine")
    mine = tmp_path / "mine"
    assert sync(mine, "--install-hooks").returncode == 0
    wt = tmp_path / "wt"
    env = dict(ENV)
    env.pop("FAMILIA_SYNC", None)
    assert subprocess.run(["git", "-C", str(mine), "worktree", "add", str(wt), "HEAD"],
                          capture_output=True, text=True, env=env).returncode == 0
    r = sync(wt, "--auto", env=env)
    assert r.returncode == 0
    assert "linked worktree" in r.stderr and "FAMILIA_SYNC=1" in r.stderr
    assert not (wt / "a").exists()

def test_hook_env_git_dir_does_not_move_familia_head(tmp_path, fam):
    """#111: leaked GIT_DIR/GIT_WORK_TREE must not make pin checkouts hit familia."""
    a, a1, a2 = upstream(tmp_path, "a")
    g(fam, "init", "-q", "-b", "main")
    (fam / "KEEP.txt").write_text("familia-only\n")
    g(fam, "add", "KEEP.txt")
    g(fam, "commit", "-q", "-m", "familia base")
    fam_head = g(fam, "rev-parse", "HEAD")
    nested(fam, a, "a", a1)
    pins(fam, [("a", a2, a)])
    # Simulate post-checkout hook env pointing at the familia worktree.
    leak = dict(ENV,
                GIT_DIR=str(fam / ".git"),
                GIT_WORK_TREE=str(fam))
    r = sync(fam, env=leak)
    assert r.returncode == 0, r.stderr
    assert g(fam, "rev-parse", "HEAD") == fam_head, "familia HEAD must stay put under leaked GIT_DIR"
    assert (fam / "KEEP.txt").read_text() == "familia-only\n"
    assert g(fam / "a", "rev-parse", "HEAD") == a2, "pin must still move to its pin"


def test_install_hooks_skips_file_checkout_and_linked_worktree(tmp_path, fam):
    """Hook body guards: file checkout ($3=0) and linked worktrees must no-op."""
    g(fam, "init", "-q", "-b", "main")
    assert sync(fam, "--install-hooks").returncode == 0
    body = (fam / ".git" / "hooks" / "post-checkout").read_text()
    assert 'unset GIT_DIR' in body
    assert '[ "$3" = "1" ] || exit 0' in body
    assert '[ -f "$root/.git" ]' in body
    # File-checkout simulation: hook exits before sync (no pin scripts needed).
    r = subprocess.run(["sh", str(fam / ".git" / "hooks" / "post-checkout"),
                        "a" * 40, "b" * 40, "0"],
                       cwd=str(fam), capture_output=True, text=True, env=ENV)
    assert r.returncode == 0
    assert "sync" not in r.stderr.lower() or "NOT in sync" not in r.stderr


def test_linked_worktree_hook_skips_auto_sync(tmp_path):
    """#111/#108: post-checkout in a linked worktree must not run sync_pins."""
    a, a1, a2 = upstream(tmp_path, "a")
    main = tmp_path / "main"
    main.mkdir()
    (main / "scripts").mkdir()
    shutil.copy(SYNC, main / "scripts" / "sync_pins.py")
    g(main, "init", "-q", "-b", "main")
    pins(main, [("a", a1, a)])
    (main / "README").write_text("x\n")
    g(main, "add", ".")
    g(main, "commit", "-q", "-m", "base")
    assert sync(main, "--install-hooks").returncode == 0
    nested(main, a, "a", a1)
    wt = tmp_path / "wt"
    g(main, "worktree", "add", "-q", str(wt), "HEAD")
    assert (wt / ".git").is_file()
    hook = main / ".git" / "hooks" / "post-checkout"
    assert hook.is_file()
    env = dict(ENV,
               GIT_DIR=g(wt, "rev-parse", "--git-dir"),
               GIT_WORK_TREE=str(wt))
    before = g(main, "rev-parse", "HEAD")
    # Branch-checkout flag ($3=1) still must skip because $root/.git is a file.
    r = subprocess.run(["sh", str(hook), before, before, "1"],
                       cwd=str(wt), capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert g(main, "rev-parse", "HEAD") == before
    assert g(main / "a", "rev-parse", "HEAD") == a1
    # Manual sync with leaked hook env must still move only the pin, not familia HEAD.
    pins(main, [("a", a2, a)])
    r = sync(main, env=dict(ENV, GIT_DIR=str(main / ".git"), GIT_WORK_TREE=str(main)))
    assert r.returncode == 0, r.stderr
    assert g(main, "rev-parse", "HEAD") == before
    assert g(main / "a", "rev-parse", "HEAD") == a2


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
           "install/linux/install.sh", "install/termux/install.sh",
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
