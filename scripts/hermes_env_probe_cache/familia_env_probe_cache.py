"""Per-host cache for hermes-agent tools.env_probe "Python toolchain:" line (#96).

Upstream env_probe caches only for the process lifetime; pip detection is flaky across
launches, which invalidates familia's prompt-cache prefix mid-system-prompt. This module
stores the first successful probe result under
``$XDG_CACHE_HOME/familia/hermes-env-probe/<hostname>`` (default
``~/.cache/familia/hermes-env-probe/<hostname>``) and reuses it on later process starts.

Force a fresh probe with ``FAMILIA_HERMES_ENV_PROBE_REFRESH=1`` (also ``yes`` / ``true``).
Installed via sitecustomize when familia prepends this directory to PYTHONPATH
(see hermes_harness.hermes_child_env).
"""
from __future__ import annotations

import importlib.abc
import importlib.util
import os
import socket
import sys
import tempfile
from typing import Callable, Optional

REFRESH_ENV = "FAMILIA_HERMES_ENV_PROBE_REFRESH"
CACHE_SUBDIR = ("familia", "hermes-env-probe")
_ATTR = "_familia_host_cache_wrapped"


def refresh_requested(environ: Optional[dict] = None) -> bool:
    env = os.environ if environ is None else environ
    return (env.get(REFRESH_ENV) or "").strip().lower() in ("1", "yes", "true", "on")


def cache_root(environ: Optional[dict] = None) -> str:
    env = os.environ if environ is None else environ
    xdg = (env.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return os.path.join(xdg, *CACHE_SUBDIR)
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".cache", *CACHE_SUBDIR)


def hostname_key(hostname: Optional[str] = None) -> str:
    """Safe single path segment from the host name."""
    name = hostname if hostname is not None else socket.gethostname()
    name = (name or "unknown").strip() or "unknown"
    # Keep it a single path component; drop path separators and NULs.
    out = []
    for ch in name:
        if ch in ("/", "\\", "\0"):
            out.append("_")
        else:
            out.append(ch)
    return "".join(out) or "unknown"


def cache_path(hostname: Optional[str] = None, environ: Optional[dict] = None) -> str:
    return os.path.join(cache_root(environ), hostname_key(hostname))


def read_cache(path: str) -> Optional[str]:
    """Return cached line (possibly "") or None if missing/unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def write_cache(path: str, line: str) -> None:
    """Atomic replace; best-effort (never raise into hermes prompt build)."""
    try:
        os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env-probe-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(line)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass


def cached_build(
    build: Callable[[], str],
    *,
    hostname: Optional[str] = None,
    environ: Optional[dict] = None,
    path: Optional[str] = None,
) -> str:
    """Return host-cached probe line, building+storing on miss or refresh."""
    env = os.environ if environ is None else environ
    p = path if path is not None else cache_path(hostname=hostname, environ=env)
    if not refresh_requested(env):
        hit = read_cache(p)
        if hit is not None:
            return hit
    line = build()
    if line is None:
        line = ""
    write_cache(p, line)
    return line


def wrap_env_probe_module(mod) -> bool:
    """Wrap ``mod._build_probe_line`` with the host cache. Idempotent. -> True if wrapped now."""
    if getattr(mod, _ATTR, False):
        return False
    orig = getattr(mod, "_build_probe_line", None)
    if not callable(orig):
        return False

    def _build_probe_line():
        return cached_build(orig)

    mod._build_probe_line = _build_probe_line
    setattr(mod, _ATTR, True)
    return True


def wrap_if_loaded() -> bool:
    mod = sys.modules.get("tools.env_probe")
    if mod is None:
        return False
    return wrap_env_probe_module(mod)


class _WrapLoader(importlib.abc.Loader):
    def __init__(self, real_spec):
        self._real_spec = real_spec

    def create_module(self, spec):
        # Prefer the real loader's create_module when present.
        real = self._real_spec
        if real.loader is not None and hasattr(real.loader, "create_module"):
            return real.loader.create_module(real)
        return None

    def exec_module(self, module):
        real = self._real_spec
        if real.loader is None:
            raise ImportError("tools.env_probe: no loader")
        real.loader.exec_module(module)
        wrap_env_probe_module(module)


class _EnvProbeFinder:
    """Meta path finder: load tools.env_probe normally, then wrap _build_probe_line."""

    def find_spec(self, fullname, path, target=None):
        if fullname != "tools.env_probe":
            return None
        # Avoid recursion while resolving the real module.
        try:
            sys.meta_path.remove(self)
        except ValueError:
            return None
        try:
            real = importlib.util.find_spec(fullname)
        finally:
            sys.meta_path.insert(0, self)
        if real is None or real.loader is None:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            _WrapLoader(real),
            origin=getattr(real, "origin", None),
            is_package=False,
        )


_FINDER: Optional[_EnvProbeFinder] = None


def install_import_hook() -> None:
    """Install the meta_path finder once (sitecustomize entrypoint)."""
    global _FINDER
    wrap_if_loaded()
    if _FINDER is not None and _FINDER in sys.meta_path:
        return
    _FINDER = _EnvProbeFinder()
    sys.meta_path.insert(0, _FINDER)
