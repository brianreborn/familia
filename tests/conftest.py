"""Keep the swarm-pull suite off the live forge.

Any unmocked subprocess, gh invocation, or network call in
test_swarm_pull_*.py raises. A test that needs a command or a socket
mocks that call. The rest of the suite is unchanged.
"""
import socket
import subprocess
import urllib.request

import pytest


class LiveForgeBlocked(AssertionError):
    """A swarm-pull test tried to leave the process."""


def _swarm_pull_module(request):
    name = getattr(request.module, "__name__", "") or ""
    return name.startswith("test_swarm_pull")


def _blocked_subprocess(*args, **kwargs):
    argv = args[0] if args else kwargs.get("args")
    raise LiveForgeBlocked("unmocked subprocess call: %r" % (argv,))


def _blocked_connect(*args, **kwargs):
    raise LiveForgeBlocked("unmocked socket connect: %r %r" % (args[1:], kwargs))


def _blocked_urlopen(*args, **kwargs):
    raise LiveForgeBlocked("unmocked urlopen: %r" % (args[:1],))


@pytest.fixture(autouse=True)
def block_live_forge(request, monkeypatch):
    if not _swarm_pull_module(request):
        return
    monkeypatch.setattr(subprocess, "run", _blocked_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _blocked_subprocess)
    monkeypatch.setattr(socket, "create_connection", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked_urlopen)
