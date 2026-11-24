"""catalog.py: every graph model and every graph file is listed."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "catalog.py")


def _run(*args):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_help():
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    out = (r.stdout + r.stderr).lower()
    assert "usage" in out or "example" in out


def test_models_lists_fleet_and_database():
    r = _run("models")
    assert r.returncode == 0, r.stderr
    assert "qwen35-2b-q4km" in r.stdout
    assert "removed-large-model" not in r.stdout
    assert "Model database" in r.stdout
    # Hostname is placement (host:), not the model key.
    assert "smollm2-135m-q4-miryam" not in r.stdout
    assert "smollm2-135m-q4-linux" in r.stdout


def test_graphs_lists_fleet_private_and_examples():
    r = _run("graphs")
    assert r.returncode == 0, r.stderr
    assert "[fleet] graph.yaml" in r.stdout
    assert "modify_graph.py --list" in r.stdout
    assert "[private-host] generated/graph-angel.yaml" in r.stdout or "generated/graph-angel.yaml" in r.stdout
    assert "examples/graphs/single-node.yaml" in r.stdout
    assert "configure GRAPH" in r.stdout


def test_configure_fleet_is_read_only_and_shows_nodes():
    r = _run("configure", "graph.yaml")
    assert r.returncode == 0, r.stderr
    assert "angel-coder" in r.stdout
    assert "fleet-guardian" in r.stdout
    assert "Nothing was written." in r.stdout
    assert "removed-large-coder" not in r.stdout
