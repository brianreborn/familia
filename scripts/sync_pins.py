#!/usr/bin/env python3
"""sync_pins.py: bring every pinned part in pins.txt to its pinned revision, all together.

Every familia script that updates or runs pinned parts (code-bootstraps-llama.cpp, green-roomz,
green-agentz, ...) calls this first, so a nested checkout can never lag behind pins.txt.
Adding or fetching a model does not call it.

Usage:
  scripts/sync_pins.py [--dry-run] [--auto] [--quiet] [--license-gate enforce|warn|off]
  scripts/sync_pins.py --update [--branch BRANCH] [--dry-run]
  scripts/sync_pins.py --branch BRANCH        switch/track origin/BRANCH, then sync
  scripts/sync_pins.py --check             exit 0 if every part is at its pin, 1 if not; changes nothing
  scripts/sync_pins.py --install-hooks     sync after every `git pull` of familia itself
Options:
  --dry-run, -n    show what would move, be cloned or fetched; change nothing, use no network
  --auto           used by scripts: silent when everything is in sync; skipped when
                   FAMILIA_SYNC_DONE is this checkout (an outer script already synced)
  --quiet, -q      print only problems
  --license-gate   after a part was cloned or moved: enforce (default) runs scripts/licenses.py
                   gate when the licenses changed; warn only says so; off skips it
  --branch BRANCH  fetch and switch to origin/BRANCH (tracking it) before syncing its pins.txt
  --root DIR       familia checkout to sync (default: the one this script is in)
Example:
  scripts/sync_pins.py --dry-run
How it works: a part whose HEAD already is its pin costs one small file read (no git, no
network). Otherwise every part is checked first; nothing moves if any part has uncommitted
changes or commits that are on no branch, or if a missing pin cannot be fetched. Then all
parts are checked out to their pins, each HEAD is verified, and a failure puts back the
ones already moved. Nothing is ever force-pushed, reset or cleaned.
Engine pins (llama-server__*) are synced when they are checked out already or asked for by
an ENGINE_* setting. FAMILIA_SYNC=0 skips syncing (a note is printed).
Exit codes: 0 in sync; 1 could not sync (nothing changed); 2 usage; 3 refused (local
changes); 4 synced, but the licenses changed and are not accepted yet.
Stdlib only. Docs: MANUAL.md (Keeping the pinned parts in sync).
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEX = re.compile(r"[0-9a-f]{7,40}")
HOOK_MARK = "# familia: sync pinned parts (scripts/sync_pins.py --install-hooks)"
GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")


def say(msg, out=sys.stderr):
    print("familia sync: " + msg, file=out)


def git(path, *args, check=False):
    r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, env=GIT_ENV)
    if check and r.returncode:
        raise RuntimeError("git %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r


def short(s):
    return s[:7] if s and HEX.fullmatch(s) else (s or "-")


def read_pins(root):
    pins = []
    path = os.path.join(root, "pins.txt")
    if not os.path.isfile(path):
        return pins
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cols = line.split("\t")
            if cols[0] in ("node", "transport") or len(cols) < 3:
                continue
            name, rev, url = cols[0].strip(), cols[1].strip(), cols[2].strip()
            if name and rev and url:
                pins.append({"name": name, "rev": rev, "url": url,
                             "engine": name.startswith("llama-server__") or name == "runtime"})
    return pins


def requested_engines(root):
    """Engine names asked for by ENGINE_* in the environment or the launcher settings."""
    vals = {v for k, v in os.environ.items() if k.startswith("ENGINE_")}
    env = os.path.join(root, "code-bootstraps-llama.cpp", ".cache", "panel.env")
    try:
        with open(env, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*(?:export\s+)?ENGINE_\w+=(.*)", line)
                if m:
                    vals.add(m.group(1).strip().strip("'\""))
    except OSError:
        pass
    return vals


def git_dir(path):
    d = os.path.join(path, ".git")
    if os.path.isfile(d):  # worktree or submodule: "gitdir: ..."
        try:
            with open(d, encoding="utf-8") as fh:
                m = re.match(r"gitdir:\s*(.+)", fh.read().strip())
            if m:
                g = m.group(1)
                return g if os.path.isabs(g) else os.path.normpath(os.path.join(path, g))
        except OSError:
            return None
    return d if os.path.isdir(d) else None


def fast_head(path):
    """HEAD without running git when it is a detached commit (the normal state of a pin)."""
    g = git_dir(path)
    if not g:
        return None
    try:
        with open(os.path.join(g, "HEAD"), encoding="utf-8") as fh:
            h = fh.read().strip()
    except OSError:
        return None
    return h if re.fullmatch(r"[0-9a-f]{40}", h) else None


def head(path):
    return fast_head(path) or (git(path, "rev-parse", "-q", "--verify", "HEAD").stdout.strip() or None)


def resolve(path, rev):
    """The full commit for rev if this checkout already has it, else None."""
    cands = [rev + "^{commit}"] if HEX.fullmatch(rev) else \
        ["refs/remotes/origin/%s^{commit}" % rev, "refs/tags/%s^{commit}" % rev, rev + "^{commit}"]
    for c in cands:
        r = git(path, "rev-parse", "-q", "--verify", c)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def plan(root, pins, engines):
    out = []
    for p in pins:
        c = dict(p, path=os.path.join(root, p["name"]), have=None, want=None, state=None, note="")
        out.append(c)
        exists = os.path.lexists(c["path"])
        if c["engine"] and not exists and p["name"].replace("llama-server__", "", 1) not in engines:
            c["state"], c["note"] = "skip", "engine pin not in use (asked for by an ENGINE_* setting)"
            continue
        if not exists:
            sib = os.path.join(root, "..", p["name"])
            if git_dir(sib):
                c["state"], c["sibling"] = "link", os.path.normpath(sib)
                c["path"] = c["sibling"]
            else:
                c["state"] = "clone"
                continue
        if not git_dir(c["path"]):
            c["state"], c["note"] = "refuse", "%s exists but is not a git checkout; move it aside" % c["path"]
            continue
        c["have"] = head(c["path"])
        if HEX.fullmatch(p["rev"]) and c["have"] and c["have"].startswith(p["rev"]):
            c["want"] = c["have"]
            c["state"] = c["state"] or "ok"
            continue
        c["want"] = resolve(c["path"], p["rev"])
        if c["want"] and c["want"] == c["have"]:
            c["state"] = c["state"] or "ok"
            continue
        c["state"] = "move" if c["want"] else "fetch"
        dirty = git(c["path"], "status", "--porcelain", "--untracked-files=no").stdout.strip()
        if dirty:
            n = len(dirty.splitlines())
            c["state"], c["note"] = "refuse", ("%d uncommitted change%s in %s; commit or stash them "
                                               "(git -C %s stash), then sync again"
                                               % (n, "" if n == 1 else "s", c["path"], c["path"]))
            continue
        if c["have"] and git(c["path"], "symbolic-ref", "-q", "HEAD").returncode:
            on_ref = git(c["path"], "for-each-ref", "--count=1", "--contains", c["have"], "--format=x",
                         "refs/heads", "refs/remotes", "refs/tags").stdout.strip()
            if not on_ref:
                c["state"], c["note"] = "refuse", ("HEAD %s of %s is on no branch; save it first "
                                                   "(git -C %s branch keep-%s)" % (short(c["have"]), c["path"],
                                                                                   c["path"], short(c["have"])))
    return out


def describe(c):
    n, have, pin = c["name"], short(c["have"]), short(c["rev"])
    s = c["state"]
    if s == "ok":
        return "%-30s %s  in sync" % (n, have)
    if s == "skip":
        return "%-30s -        not synced: %s" % (n, c["note"])
    if s == "clone":
        return "%-30s missing -> %s  clone %s" % (n, pin, c["url"])
    if s == "link":
        return "%-30s use sibling %s (%s -> %s)" % (n, c["sibling"], have, pin)
    if s == "move":
        return "%-30s %s -> %s  checkout (commit is here; no network)" % (n, have, pin)
    if s == "fetch":
        return "%-30s %s -> %s  fetch the pin from %s, then checkout" % (n, have, pin, c["url"])
    return "%-30s %s  REFUSED: %s" % (n, have, c["note"])


def fetch(path, url, rev):
    for args in (["fetch", "-q", "--no-tags", url, rev], ["fetch", "-q", url, "+refs/heads/*:refs/remotes/origin/*"]):
        if git(path, *args).returncode == 0:
            want = resolve(path, rev)
            if not want and not HEX.fullmatch(rev):
                fh = git(path, "rev-parse", "-q", "--verify", "FETCH_HEAD^{commit}").stdout.strip()
                want = fh or None
            if want:
                return want
    return None


class Lock:
    def __init__(self, root):
        d = os.path.join(root, ".cache")
        os.makedirs(d, exist_ok=True)
        self.fh = open(os.path.join(d, "sync.lock"), "a+")

    def __enter__(self):
        try:
            import fcntl
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except ImportError:  # Windows
            import msvcrt
            self.fh.seek(0)
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, *a):
        self.fh.close()


def apply(root, comps, quiet):
    todo = [c for c in comps if c["state"] in ("clone", "link", "move", "fetch")]
    # Phase 1: get every missing commit; nothing is checked out yet.
    temps = []
    try:
        for c in todo:
            if c["state"] == "clone":
                tmp = c["path"] + ".sync-tmp"
                if os.path.lexists(tmp):
                    shutil.rmtree(tmp)
                say("cloning %s from %s" % (c["name"], c["url"]))
                if git(root, "clone", "-q", "--no-checkout", c["url"], tmp).returncode:
                    raise RuntimeError("could not clone %s from %s" % (c["name"], c["url"]))
                temps.append(tmp)
                c["work"] = tmp
                c["want"] = resolve(tmp, c["rev"]) or fetch(tmp, c["url"], c["rev"])
            else:
                c["work"] = c["path"]
                if not c["want"]:
                    if not quiet:
                        say("fetching pin %s@%s" % (c["name"], short(c["rev"])))
                    c["want"] = fetch(c["path"], c["url"], c["rev"])
            if not c["want"]:
                raise RuntimeError("pin %s@%s is not in %s (network down, or the commit is gone)"
                                   % (c["name"], c["rev"], c["url"]))
    except RuntimeError as e:
        for t in temps:
            shutil.rmtree(t, ignore_errors=True)
        say("FAILED: %s. Nothing was changed." % e)
        return 1
    # Phase 2: check out every pin; put back the ones already moved if any fails.
    done = []
    try:
        for c in todo:
            r = git(c["work"], "-c", "advice.detachedHead=false", "checkout", "-q", c["want"])
            now = head(c["work"])
            if r.returncode or now != c["want"]:
                raise RuntimeError("checkout of %s@%s failed: %s" % (c["name"], short(c["want"]),
                                                                    (r.stderr or "HEAD did not move").strip()))
            done.append(c)
        for c in todo:
            if c["state"] == "clone":
                os.rename(c["work"], c["path"])
            elif c["state"] == "link":
                os.symlink(c["sibling"], os.path.join(root, c["name"]))
    except (RuntimeError, OSError) as e:
        for c in done:
            if c["state"] in ("move", "fetch", "link") and c["have"]:
                git(c["work"], "-c", "advice.detachedHead=false", "checkout", "-q", c["have"])
        for t in temps:
            shutil.rmtree(t, ignore_errors=True)
        say("FAILED: %s. Parts already moved were put back." % e)
        return 1
    for c in todo:
        verb = {"clone": "cloned", "link": "linked sibling", "move": "moved", "fetch": "fetched and moved"}[c["state"]]
        say("%s %s %s -> %s" % (verb, c["name"], short(c["have"]), short(c["want"])))
    return 0


def license_gate(root, mode):
    lic = os.path.join(root, "scripts", "licenses.py")
    if mode == "off" or not os.path.isfile(lic):
        return 0
    if subprocess.run([sys.executable, lic, "check", "--quiet"], cwd=root).returncode == 0:
        return 0
    if mode == "warn":
        say("note: the licenses of your selection changed or are not accepted yet; "
            "review them before running anything: python3 scripts/licenses.py review")
        return 0
    say("a part brought in new or changed licenses; reviewing them (docs/licenses.md)")
    if subprocess.run([sys.executable, lic, "gate"], cwd=root).returncode:
        say("the parts are synced, but their licenses are not accepted; nothing should run until you "
            "review them: python3 scripts/licenses.py review")
        return 4
    return 0


def install_hooks(root):
    g = git_dir(root)
    if not g:
        say("%s is not a git checkout; no hooks installed" % root)
        return 1
    hooks = os.path.join(g, "hooks")
    os.makedirs(hooks, exist_ok=True)
    body = ("#!/bin/sh\n%s\n# After git pull / merge / rebase of familia: pins.txt may have changed.\n"
            "root=$(git rev-parse --show-toplevel) || exit 0\n"
            "[ \"${FAMILIA_SYNC:-1}\" = 0 ] && exit 0\n"
            "[ -f \"$root/scripts/sync_pins.py\" ] || exit 0\n"
            "PY=${PYTHON:-python3}; command -v \"$PY\" >/dev/null 2>&1 || PY=python\n"
            "\"$PY\" \"$root/scripts/sync_pins.py\" --root \"$root\" --quiet --license-gate warn || "
            "echo 'familia: the pinned parts are NOT in sync; see above, then run: ./familia sync' >&2\n"
            "exit 0\n" % HOOK_MARK)
    rc = 0
    for name in ("post-merge", "post-rewrite", "post-checkout"):
        p = os.path.join(hooks, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="replace") as fh:
                if HOOK_MARK not in fh.read():
                    say("left your own %s hook alone; add this line to it: python3 scripts/sync_pins.py --quiet" % p)
                    rc = 0
                    continue
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        os.chmod(p, 0o755)
    return rc


def do_update(root, rest, dry, branch=None):
    """Update familia itself (fast-forward only), then sync with the selected branch's pins.txt."""
    if branch and git(root, "check-ref-format", "--branch", branch).returncode:
        say("invalid branch name %r" % branch)
        return 2
    if dry:
        if branch:
            print("familia update: dry run; would fetch origin/%s, switch this checkout to track it, "
                  "fast-forward only, then sync the pins" % branch)
        else:
            print("familia update: dry run; would run: git -C %s pull --ff-only, then sync the pins" % root)
        print("familia update: the pins as they are now (pins.txt can change with the pull):")
        return main(rest)
    before = git(root, "rev-parse", "HEAD").stdout.strip()
    if branch:
        r = subprocess.run(["git", "-C", root, "fetch", "origin",
                            "+refs/heads/%s:refs/remotes/origin/%s" % (branch, branch)], env=GIT_ENV)
        if r.returncode:
            say("could not fetch origin/%s; nothing was synced. See: git -C %s status" % (branch, root))
            return 1
        exists = git(root, "show-ref", "--verify", "--quiet", "refs/heads/" + branch).returncode == 0
        if exists:
            r = subprocess.run(["git", "-C", root, "switch", branch], env=GIT_ENV)
        else:
            r = subprocess.run(["git", "-C", root, "switch", "--track", "-c", branch,
                                "origin/" + branch], env=GIT_ENV)
        if r.returncode:
            say("could not switch to %s (check for local changes or branch conflicts); nothing was synced. "
                "See: git -C %s status" % (branch, root))
            return 1
        r = subprocess.run(["git", "-C", root, "branch", "--set-upstream-to=origin/" + branch, branch],
                           env=GIT_ENV)
        if r.returncode:
            say("could not set %s to track origin/%s; nothing was synced" % (branch, branch))
            return 1
        r = subprocess.run(["git", "-C", root, "merge", "--ff-only", "origin/" + branch], env=GIT_ENV)
    else:
        r = subprocess.run(["git", "-C", root, "pull", "--ff-only"], env=GIT_ENV)
    if r.returncode:
        say("git update failed (local commits or changes may prevent a fast-forward); nothing was synced. "
            "See: git -C %s status" % root)
        return 1
    after = git(root, "rev-parse", "HEAD").stdout.strip()
    if before != after:
        say("familia %s -> %s" % (short(before), short(after)))
    # Run the sync from the updated checkout: sync_pins.py itself may have changed.
    env = dict(os.environ)
    env.pop("FAMILIA_SYNC_DONE", None)
    return subprocess.run([sys.executable, os.path.join(root, "scripts", "sync_pins.py"), "--root", root] + rest,
                          env=env).returncode


def main(argv):
    root = os.path.dirname(HERE)
    dry = auto = quiet = hooks = check = update = False
    branch = None
    gate = "enforce"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        elif a in ("--dry-run", "-n"):
            dry = True
        elif a == "--auto":
            auto = True
        elif a in ("--quiet", "-q"):
            quiet = True
        elif a == "--install-hooks":
            hooks = True
        elif a == "--check":
            check = True
        elif a == "--update":
            update = True
        elif a == "--branch" and i + 1 < len(argv):
            i += 1
            branch = argv[i]
        elif a in ("--license-gate", "--root") and i + 1 < len(argv):
            i += 1
            if a == "--root":
                root = os.path.abspath(argv[i])
            else:
                gate = argv[i]
        elif a.startswith("--license-gate="):
            gate = a.split("=", 1)[1]
        elif a.startswith("--root="):
            root = os.path.abspath(a.split("=", 1)[1])
        else:
            say("unknown option '%s'. Try: scripts/sync_pins.py --help" % a)
            return 2
        i += 1
    if gate not in ("enforce", "warn", "off"):
        say("--license-gate takes enforce, warn or off")
        return 2
    if hooks:
        return install_hooks(root)
    if update or branch is not None:
        rest = []
        i = 0
        while i < len(argv):
            if argv[i] == "--branch":
                i += 2
                continue
            if argv[i] != "--update":
                rest.append(argv[i])
            i += 1
        return do_update(root, rest, dry, branch)
    if os.environ.get("FAMILIA_SYNC", "1") == "0":
        say("skipped (FAMILIA_SYNC=0); the pinned parts may be behind pins.txt")
        return 0
    if auto and os.path.normcase(os.environ.get("FAMILIA_SYNC_DONE", "")) == os.path.normcase(root):
        return 0
    try:
        return run(root, argv, pins=read_pins(root), dry=dry, auto=auto, quiet=quiet, check=check, gate=gate)
    except FileNotFoundError:
        say("git is needed to sync the pinned parts (Debian/Ubuntu: sudo apt install git; Termux: pkg install git; "
            "Windows: https://git-scm.com). Nothing was changed.")
        return 1


def run(root, argv, pins, dry, auto, quiet, check, gate):
    comps = plan(root, pins, requested_engines(root))
    changes = [c for c in comps if c["state"] not in ("ok", "skip")]
    if check:
        for c in changes if not quiet else ():
            say(describe(c))
        return 1 if changes else 0
    if dry:
        print("familia sync: dry run; nothing changes (pins.txt in %s)" % root)
        for c in comps:
            print("  " + describe(c))
        n = {s: sum(1 for c in comps if c["state"] == s) for s in ("ok", "move", "fetch", "clone", "link", "refuse")}
        if n["refuse"]:
            print("familia sync: would REFUSE (nothing would move): %d part(s) need you first" % n["refuse"])
            return 3
        print("familia sync: would move %d, fetch %d, clone %d, link %d; %d already in sync."
              % (n["move"], n["fetch"], n["clone"], n["link"], n["ok"]))
        return 0
    if not changes:
        if not (auto or quiet):
            say("all %d pinned parts are at their pins" % sum(1 for c in comps if c["state"] == "ok"))
        return 0
    refused = [c for c in changes if c["state"] == "refuse"]
    if refused:
        for c in refused:
            say("REFUSED %s: %s" % (c["name"], c["note"]))
        say("nothing was moved (the parts are kept in step together). Then run: ./familia sync")
        return 3
    with Lock(root):
        comps = plan(root, pins, requested_engines(root))  # again, under the lock
        if any(c["state"] == "refuse" for c in comps):
            return main(argv)
        rc = apply(root, comps, quiet)
    if rc:
        return rc
    if any(c["state"] not in ("ok", "skip") for c in comps):
        return license_gate(root, gate)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
