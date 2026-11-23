"""Helpers so tests stay off shared temp roots and keep pip --user deps visible.

Production code in scripts/swarm/a57_ssh_dispatch.py and bench_idle.py correctly
refuses lock or state directories under /tmp, /var/tmp, /dev/shm and
/private/tmp. pytest's default temp, and a checkout under those roots, would
otherwise put fixtures there. Tests that override HOME would also hide a
PyYAML installed with `pip install --user` from child processes.
"""
from __future__ import annotations

import os
import pwd
import site
import stat
import sys

SHARED_TEMP_ROOTS = ("/tmp", "/var/tmp", "/dev/shm", "/private/tmp")

# Captured before tests rewrite HOME.
_ORIG_USER_BASE = getattr(site, "USER_BASE", None) or ""
_ORIG_USER_SITE = getattr(site, "USER_SITE", None) or ""


def under_shared_temp(path: str) -> bool:
    """True if path is inside a shared temp root the production checks refuse."""
    try:
        real = os.path.realpath(path)
    except OSError:
        real = os.path.abspath(path)
    roots = set(SHARED_TEMP_ROOTS)
    for root in SHARED_TEMP_ROOTS:
        try:
            roots.add(os.path.realpath(root))
        except OSError:
            pass
    return any(real == r or real.startswith(r.rstrip("/") + "/") for r in roots)


def _usable_dir(path: str) -> bool:
    if not path or under_shared_temp(path):
        return False
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return False
    if st.st_uid != os.geteuid():
        return False
    if under_shared_temp(path):
        return False
    if stat.S_IMODE(st.st_mode) & 0o077:
        try:
            os.chmod(path, 0o700)
        except OSError:
            return False
    return True


def safe_temp_parent() -> str:
    """Writable directory that lock/state checks will not refuse.

    Prefer the repo's gitignored .cache when the checkout itself is not under
    a shared temp root (the existing layout). Otherwise use a user-owned cache
    under the real home from the passwd database, not $HOME, because tests
    often override HOME.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    candidates = [os.path.join(root, ".cache")]
    try:
        home = pwd.getpwuid(os.geteuid()).pw_dir
    except (KeyError, OSError):
        home = ""
    if home:
        candidates.append(os.path.join(home, ".cache", "familia-pytest"))
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg and os.path.isabs(xdg):
        candidates.append(os.path.join(xdg, "familia-pytest"))
    for parent in candidates:
        if _usable_dir(parent):
            return parent
    raise RuntimeError(
        "no safe pytest temp parent outside /tmp, /var/tmp, /dev/shm, /private/tmp"
    )


def child_python_env() -> dict:
    """Keep pip --user and the parent sys.path visible after HOME is overridden."""
    env = {}
    paths = [p for p in sys.path if p]
    if _ORIG_USER_SITE and _ORIG_USER_SITE not in paths:
        paths.append(_ORIG_USER_SITE)
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    if _ORIG_USER_BASE:
        env["PYTHONUSERBASE"] = _ORIG_USER_BASE
    return env
