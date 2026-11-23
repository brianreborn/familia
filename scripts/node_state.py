"""Single owner for node status predicates and auto-route eligibility (DUP-03).

TYPE carries capability; `status` carries routability. A planned node is excluded from
automatic routing/placement (reachable only by slash/alias). See docs/config/routing-spec.md
(CFG-SPEC-PLAN) and docs/config/graph/nodes.md (CFG-GRAPH-NODES-102).
"""


def is_active(node):
    return (node or {}).get("status") == "active"


def is_planned(node):
    return (node or {}).get("status") == "planned"


def active_items(graph):
    """(name, node) for every active node (any host)."""
    return [(n, nd) for n, nd in (graph.get("nodes") or {}).items() if is_active(nd)]


def local_active(graph, host):
    """Sorted names of active nodes placed on `host` (auto-routable here)."""
    return sorted(n for n, nd in active_items(graph) if nd.get("host") == host)


def remote_active(graph, host):
    """Sorted (name, host) of active nodes placed on other hosts."""
    return sorted((n, nd.get("host")) for n, nd in active_items(graph) if nd.get("host") != host)


def placeable_items(graph):
    """(name, node) for nodes subject to placement/measurement (non-planned)."""
    return [(n, nd) for n, nd in (graph.get("nodes") or {}).items() if not is_planned(nd)]
