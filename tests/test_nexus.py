"""scripts/nexus/nexus.py unit tests (no live ssh)."""
import importlib.util
import os
import shlex
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "familia_nexus", os.path.join(ROOT, "scripts", "nexus", "nexus.py")
)
nx = importlib.util.module_from_spec(SPEC)
sys.modules["familia_nexus"] = nx
SPEC.loader.exec_module(nx)


def _n():
    return object.__new__(nx.Nexus)


def test_tilde_path_quotes_remainder_and_keeps_home_expandable():
    """#346: ~ paths become "$HOME" + shlex.quote(rest); spaces and ; are quoted."""
    n = _n()
    assert n.r("~/artifacts/x") == '"$HOME"' + shlex.quote("/artifacts/x")
    got = n.r("~/my dir;rm -rf /")
    assert got == '"$HOME"' + shlex.quote("/my dir;rm -rf /")
    assert "my dir" in got and ";" in got
    # remainder is quoted as one word: a remote shell will not split on space or run `rm`
    assert got.startswith('"$HOME"')
    assert shlex.split("echo " + got) == ["echo", "$HOME/my dir;rm -rf /"]
    # non-~ paths stay fully quoted
    assert n.r("/var/lib/familia/root") == shlex.quote("/var/lib/familia/root")
    assert n.r("/var/lib/familia/my dir") == shlex.quote("/var/lib/familia/my dir")
