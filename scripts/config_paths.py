"""Single owner for repo-root and graph-path resolution (DUP-02, DUP-10).

Before this module every script recomputed ROOT = dirname(dirname(abspath(__file__)))
and resolved the graph path inconsistently: some honoured $FAMILIA_GRAPH, some did not
(guardian_ready, model_db). Consumers now call here so FAMILIA_GRAPH is honoured uniformly.
Implements CFG-FILE-007; see docs/config/duplication-audit.md DUP-02/DUP-10.

$FAMILIA_GRAPH is expanduser+abspath-normalised; an empty value counts as unset (with a
warning). The hosts overlay lookup follows the resolved graph's directory, so $FAMILIA_GRAPH
also moves the overlay for guardian_ready/model_db (documented in docs/config/files.md).
"""
import os
import sys

# Repo root = parent of scripts/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH_ENV = "FAMILIA_GRAPH"
DEFAULT_GRAPH_NAME = "graph.yaml"
_warned_empty = False


def default_graph():
    """Repo-relative default graph path (no env)."""
    return os.path.join(ROOT, DEFAULT_GRAPH_NAME)


def _norm(p):
    return os.path.abspath(os.path.expanduser(p))


def graph_path(explicit=None, environ=None):
    """Resolve the graph path with one precedence everywhere:
    explicit argument/flag > $FAMILIA_GRAPH > <repo>/graph.yaml.
    The chosen value is expanduser+abspath-normalised. An empty $FAMILIA_GRAPH is treated
    as unset (and warned once), so `~` works under systemd Environment= / start.cmd."""
    global _warned_empty
    if explicit:
        return _norm(explicit)
    env = environ if environ is not None else os.environ
    val = env.get(GRAPH_ENV)
    if val is not None and val.strip() == "" and not _warned_empty:
        _warned_empty = True
        print(f"warning: {GRAPH_ENV} is set but empty; ignoring and using {default_graph()}", file=sys.stderr)
    if val and val.strip():
        return _norm(val)
    return default_graph()


GENERATED_ENV = "FAMILIA_GENERATED_DIR"
MODEL_DB_ENV = "FAMILIA_MODEL_DB_DIR"


def _env_dir(name, default, environ=None):
    env = environ if environ is not None else os.environ
    val = env.get(name)
    return os.path.realpath(os.path.expanduser(val)) if val else default


def generated_dir(environ=None):
    """Per-host generated graph dir: $FAMILIA_GENERATED_DIR (expanduser+resolve; empty = unset)
    or <repo>/generated (CFG-FILE-007b)."""
    return _env_dir(GENERATED_ENV, os.path.join(ROOT, "generated"), environ)


def model_db_dir(environ=None):
    """Model database dir: $FAMILIA_MODEL_DB_DIR (expanduser+resolve; empty = unset)
    or <repo>/registry/models (CFG-FILE-001a)."""
    return _env_dir(MODEL_DB_ENV, os.path.join(ROOT, "registry", "models"), environ)
