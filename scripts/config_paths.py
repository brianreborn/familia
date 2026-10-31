"""Single owner for repo-root and graph-path resolution (DUP-02, DUP-10).

Before this module every script recomputed ROOT = dirname(dirname(abspath(__file__)))
and resolved the graph path inconsistently: some honoured $FAMILIA_GRAPH, some did not
(guardian_ready, model_db). Consumers now call here so FAMILIA_GRAPH is honoured uniformly.
Implements CFG-FILE-007; see docs/config/duplication-audit.md DUP-02/DUP-10.
"""
import os

# Repo root = parent of scripts/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH_ENV = "FAMILIA_GRAPH"
DEFAULT_GRAPH_NAME = "graph.yaml"


def default_graph():
    """Repo-relative default graph path (no env)."""
    return os.path.join(ROOT, DEFAULT_GRAPH_NAME)


def graph_path(explicit=None, environ=None):
    """Resolve the graph path with one precedence everywhere:
    explicit argument/flag > $FAMILIA_GRAPH > <repo>/graph.yaml."""
    if explicit:
        return explicit
    env = environ if environ is not None else os.environ
    return env.get(GRAPH_ENV) or default_graph()
