"""qodesh and shalom were retired from the fleet on 2026-11-23 PT (PR #734).

start_graph.py loads generated/graph-HOST.yaml before graph.yaml, so both the fleet
graph and every generated graph must be free of them as structured data: no host
entry, no list member (meshes, runtimes, allow/candidate lists), no gpu_host, no
node placed on them. Free-text notes may still mention them as history.
"""
import glob, os
import pytest, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETIRED = {"qodesh", "shalom"}
GRAPHS = [os.path.join(ROOT, "graph.yaml")] + sorted(glob.glob(os.path.join(ROOT, "generated", "*.yaml")))


def _refs(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{path}.{k}"
            if k in RETIRED:
                yield p
            if k in ("host", "gpu_host", "hub", "tracker", "from", "to") and v in RETIRED:
                yield p
            yield from _refs(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str) and v in RETIRED:
                yield f"{path}[{i}]"
            else:
                yield from _refs(v, f"{path}[{i}]")


@pytest.mark.parametrize("path", GRAPHS, ids=lambda p: os.path.relpath(p, ROOT))
def test_graph_has_no_retired_hosts(path):
    with open(path, encoding="utf-8") as f:
        g = yaml.safe_load(f) or {}
    assert not set(g.get("hosts") or {}) & RETIRED
    assert list(_refs(g)) == []


def test_registry_hosts_has_no_retired_hosts():
    with open(os.path.join(ROOT, "registry", "hosts.yaml"), encoding="utf-8") as f:
        assert not set(yaml.safe_load(f) or {}) & RETIRED
