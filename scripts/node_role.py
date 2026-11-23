#!/usr/bin/env python3
"""Node role / private-topology helpers.

Design law (2026-10-27, Brian): node TYPE implies capability. Placement is
hosts via the host: field. Fleet graph.yaml keys are capability names
(nanbeige-coder, cuda-sm11-decision, fleet-guardian), not hostnames.
Private per-host graphs (generated/graph-HOST.yaml) collapse those to the
type name only (coder, chat, guardian). Host-prefixed ids are legacy.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

# Matches models.role enum in graph_types (+ general as phone/chat stand-in).
NODE_ROLES = frozenset(
    {"chat", "coder", "decision", "reasoning", "embed", "vision", "diffusion", "pentest", "guardian", "general"}
)

# Hostnames / aliases that appear as prefixes in transitional fleet keys.
_DEFAULT_HOST_PREFIXES = (
    "angel", "gabriel", "miryam", "qodesh", "box", "galaxy1", "galaxy2",
    "phone7", "phone8", "godslove", "shalom", "centos10",
)


def host_prefixes(graph: dict) -> Tuple[str, ...]:
    hosts = list((graph.get("hosts") or {}).keys())
    extra = [h for h in _DEFAULT_HOST_PREFIXES if h not in hosts]
    # Longest first so phone7 beats phone
    return tuple(sorted(hosts + extra, key=len, reverse=True))


def prefer_public_role(role: str) -> str:
    """Map legacy model/node role names to public type names (seatbelts naming)."""
    if role == "pentest":
        return "guardian"  # guardian/defender node flavor; pentest remains model-catalog synonym
    return role


def infer_role(name: str, node: dict, graph: dict) -> str:
    """Return the type/role for a node (coder, chat, guardian, …)."""
    explicit = node.get("role")
    if isinstance(explicit, str) and explicit.strip():
        return prefer_public_role(explicit.strip())
    model_key = node.get("model")
    models = graph.get("models") or {}
    if isinstance(model_key, str) and model_key in models:
        mr = (models[model_key] or {}).get("role")
        if isinstance(mr, str) and mr.strip():
            # Shared weights with a different card_set (angel chat view) need
            # an explicit node.role; otherwise model.role wins.
            if name.endswith("-chat") or name == "chat":
                return "chat"
            if name.endswith("-general") or name == "general":
                return "general"
            if name.endswith("-guardian") or name.endswith("-defender") or name == "guardian":
                return "guardian"
            if name.endswith("-pentest") or name == "pentest":
                return "guardian"
            return prefer_public_role(mr.strip())
    # Strip host- prefix from transitional fleet keys
    for h in host_prefixes(graph):
        for sep in ("-", "_"):
            p = h + sep
            if name.startswith(p) and len(name) > len(p):
                rest = name[len(p) :]
                # cuda-sm11-decision → prefer decision if suffix ends with a role
                for role in sorted(NODE_ROLES, key=len, reverse=True):
                    if rest == role or rest.endswith("-" + role) or rest.endswith("_" + role):
                        return role
                if rest in NODE_ROLES:
                    return prefer_public_role(rest)
                # cpu-smol-decision / cpu-resident-coder: not pure roles — keep rest
                return rest
    if name in NODE_ROLES:
        return prefer_public_role(name)
    return prefer_public_role(name) if name == "pentest" else name


def is_host_prefixed(name: str, graph: dict) -> bool:
    for h in host_prefixes(graph):
        if name.startswith(h + "-") or name.startswith(h + "_"):
            return True
    return False


def rewrite_refs(obj: Any, rename: Dict[str, str]) -> Any:
    """Rewrite string refs that equal old node keys."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("node", "target", "from", "to") and isinstance(v, str) and v in rename:
                out[k] = rename[v]
            elif k == "aliases" and isinstance(v, dict):
                # agents.hermes.aliases: main: coder  (values are node names)
                out[k] = {
                    ak: (rename[av] if isinstance(av, str) and av in rename else av)
                    for ak, av in v.items()
                }
            elif k == "escalates_to" and isinstance(v, list):
                out[k] = [rename[x] if isinstance(x, str) and x in rename else x for x in v]
            else:
                out[k] = rewrite_refs(v, rename)
        return out
    if isinstance(obj, list):
        return [rewrite_refs(x, rename) for x in obj]
    return obj


def private_topology(graph: dict, host: str) -> dict:
    """Build a private host graph: only that host's nodes, keyed by type/role.

    Schema still uses a unique-key map — uniqueness holds *inside* one private
    topology (one coder per host). Same role on another host lives in that
    host's private graph. Fleet keys stay capability names (angel-coder,
    dogfood-coder) so two coders can share one fleet file.
    """
    import copy

    g = copy.deepcopy(graph)
    nodes_in = g.get("nodes") or {}
    local = {n: d for n, d in nodes_in.items() if isinstance(d, dict) and d.get("host") == host}
    if not local:
        raise ValueError(f"no nodes with host={host!r} in graph")

    rename: Dict[str, str] = {}
    new_nodes: Dict[str, dict] = {}
    for old_name, node in local.items():
        role = infer_role(old_name, node, graph)
        if role in new_nodes:
            raise ValueError(
                f"private topology host={host!r}: role {role!r} collides "
                f"({old_name!r} vs existing key); set distinct node.role fields"
            )
        node = dict(node)
        node["role"] = role
        # Spill paths stay as declared (angel-coder / angel-chat). Renaming the
        # node must not empty the slot cache the next launch restores.
        new_nodes[role] = node
        rename[old_name] = role

    local_keys = set(new_nodes)
    g["nodes"] = new_nodes
    # Drop speculative rows before rename. Fleet `coder-ngram` targets miryam's
    # node `coder`. After nanbeige-coder is renamed to `coder`, a post-rename
    # target filter would keep that row and turn Nanbeige's launch into
    # miryam's active n-gram spec. Keep only rows whose target is one of this
    # host's nodes, then rewrite those targets to the type name.
    local_old = set(local)
    g["speculative"] = {
        k: v for k, v in (g.get("speculative") or {}).items()
        if isinstance(v, dict) and v.get("target") in local_old
    }
    g = rewrite_refs(g, rename)

    # Gateways: keep only this host; if none, synthesize a loopback gateway so
    # required sections + type aliases validate (roomz stays on miryam in fleet).
    gateways = {
        k: v for k, v in (g.get("gateways") or {}).items()
        if isinstance(v, dict) and v.get("host") == host
    }
    if not gateways:
        gateways = {
            "local": {
                "kind": "green-roomz",
                "host": host,
                "port": 18080,
            }
        }
    g["gateways"] = gateways
    gw0 = next(iter(gateways))

    aliases_out = {}
    for role in local_keys:
        aliases_out[role] = {"node": role, "gateway": gw0}
    # Keep any already-local aliases that still resolve
    for k, v in (g.get("aliases") or {}).items():
        if isinstance(v, dict) and v.get("gateway") in gateways and \
                all(n in local_keys for n in __import__("graph_types").alias_nodes(v) or [None]):
            aliases_out[k] = v
    g["aliases"] = aliases_out

    # Private graphs are executable deployment files. Keep only model/runtime
    # records referenced by local nodes.
    used_models = {node.get("model") for node in new_nodes.values()}
    used_runtimes = {node.get("runtime") for node in new_nodes.values()}
    g["hosts"] = {host: g["hosts"][host]}
    g["transports"] = {
        key: value for key, value in (g.get("transports") or {}).items()
        if value.get("from") == host and value.get("to") == host
    }
    g.pop("meshes", None)
    g["models"] = {
        key: value for key, value in (g.get("models") or {}).items()
        if key in used_models
    }
    g["runtimes"] = {
        key: value for key, value in (g.get("runtimes") or {}).items()
        if key in used_runtimes
    }
    g["options"] = {
        key: {**value, "candidate_hosts": [h for h in value.get("candidate_hosts", []) if h == host]}
        for key, value in (g.get("options") or {}).items()
        if not value.get("candidate_hosts") or host in value.get("candidate_hosts", [])
    }
    g["speculative"] = {}
    g["agents"] = {}
    for section in (
        "pentests", "harnesses", "fleets", "rooms", "reaches", "councils",
        "agencies", "swarms", "stores", "kv_channels", "system_agents", "self_improve",
    ):
        g.pop(section, None)
    return g



def model_keys(graph: dict) -> List[str]:
    return sorted((graph.get("models") or {}).keys())


def resolve_model_assign(graph: dict, rhs: str, *, manifest_finder=None) -> str:
    """Resolve assign RHS to a models: key. Reject bare gguf paths for schema."""
    models = graph.get("models") or {}
    if rhs in models:
        return rhs
    # Legacy role:pick → try map onto models: by role + heuristics; else error
    if ":" in rhs and "/" not in rhs and not rhs.endswith(".gguf"):
        role, pick = rhs.split(":", 1)
        # Prefer models with matching role; pick=default → first; else name contains pick
        cands = [k for k, m in models.items() if isinstance(m, dict) and m.get("role") == role]
        if pick == "default" and cands:
            return cands[0]
        for k in cands:
            if pick in k:
                return k
        if manifest_finder is not None:
            # Still reject path writes — surface clear error
            path = manifest_finder(role, pick)
            raise ValueError(
                f"role:pick {rhs!r} resolves to path {path!r}, but nodes.model must be a "
                f"models: key. Known {role} models: {cands or 'none'}. "
                f"Register the GGUF (add_model / graph models:) then "
                f"--assign-model <node>={cands[0] if cands else '<models-key>'}."
            )
        raise ValueError(
            f"no models: key for role:pick {rhs!r}. Known models: {sorted(models)}"
        )
    if rhs.endswith(".gguf") or "/" in rhs or rhs.startswith("~"):
        raise ValueError(
            f"nodes.model must be a models: key, not a path ({rhs!r}). "
            f"Known: {sorted(models)}"
        )
    # Typo / short name: suggest close keys
    suggestions = [k for k in models if rhs in k or k.startswith(rhs)]
    hint = f" Did you mean {suggestions}?" if suggestions else ""
    raise ValueError(f"unknown models: key {rhs!r}.{hint} Known: {sorted(models)}")
