#!/usr/bin/env python3
"""Node role / private-topology helpers.

Design law (2026-10-27, Brian): node TYPE implies capability. Placement is
hosts via the host: field — not host-prefixed node ids (angel-coder, …).
Fleet graph.yaml still carries transitional host-prefixed keys (unique map);
private per-host graphs (generated/graph-HOST.yaml) use type names only.
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
                # qodesh-gpu-decision → prefer decision if suffix ends with a role
                for role in sorted(NODE_ROLES, key=len, reverse=True):
                    if rest == role or rest.endswith("-" + role) or rest.endswith("_" + role):
                        return role
                if rest in NODE_ROLES:
                    return prefer_public_role(rest)
                # qodesh-smol-cpu / qodesh-resident: not pure roles — keep rest
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
    host's private graph, not as angel-coder / box-coder fake names.
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
        # Spill paths may still say angel-coder; keep as declared for live compat.
        new_nodes[role] = node
        rename[old_name] = role

    local_keys = set(new_nodes)
    g["nodes"] = new_nodes
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
        if isinstance(v, dict) and v.get("node") in local_keys and v.get("gateway") in gateways:
            aliases_out[k] = v
    g["aliases"] = aliases_out

    # Agents: keep those already on this host; else clone fleet hermes onto host
    # so required agents: section is non-empty and hermes can target type aliases.
    agents_in = g.get("agents") or {}
    agents = {
        k: v for k, v in agents_in.items()
        if isinstance(v, dict) and v.get("host") == host
    }
    if not agents and "hermes" in agents_in and isinstance(agents_in["hermes"], dict):
        h = copy.deepcopy(agents_in["hermes"])
        h["host"] = host
        # Point at type aliases that exist locally
        pref = "coder" if "coder" in aliases_out else next(iter(aliases_out), None)
        if pref:
            h["aliases"] = {"main": pref, "auxiliary": pref}
        agents = {"hermes": h}
    for an, av in list(agents.items()):
        amap = av.get("aliases") or {}
        if isinstance(amap, dict):
            av["aliases"] = {ak: al for ak, al in amap.items() if al in aliases_out}
            if not av["aliases"] and aliases_out:
                pref = "coder" if "coder" in aliases_out else next(iter(aliases_out))
                av["aliases"] = {"main": pref, "auxiliary": pref}
    g["agents"] = agents

    spec = g.get("speculative") or {}
    g["speculative"] = {
        k: v for k, v in spec.items()
        if isinstance(v, dict) and v.get("target") in local_keys
    }
    g["pentests"] = {
        k: v for k, v in (g.get("pentests") or {}).items()
        if isinstance(v, dict) and v.get("node") in local_keys
    }
    # Pentests / harnesses may reference agents hosted elsewhere in the fleet
    # (e.g. pentest-ops on miryam). Keep those agent descriptors so private
    # graphs still validate (ref=agents). Remap aliases onto local type names.
    needed = set()
    for block in (g.get("pentests") or {}).values():
        if isinstance(block, dict) and isinstance(block.get("agent"), str):
            needed.add(block["agent"])
    for block in (g.get("harnesses") or {}).values():
        if isinstance(block, dict) and isinstance(block.get("agent"), str):
            needed.add(block["agent"])
    for aname in sorted(needed):
        if aname in agents:
            continue
        src = agents_in.get(aname)
        if not isinstance(src, dict):
            # Drop dangling refs rather than leave an unsatisfiable graph
            for sec in ("pentests", "harnesses"):
                for k, v in list((g.get(sec) or {}).items()):
                    if isinstance(v, dict) and v.get("agent") == aname:
                        if sec == "pentests":
                            del g["pentests"][k]
                        else:
                            v = dict(v)
                            v.pop("agent", None)
                            g["harnesses"][k] = v
            continue
        cloned = copy.deepcopy(src)
        cloned["host"] = host
        amap = cloned.get("aliases") or {}
        if isinstance(amap, dict) and aliases_out:
            remapped = {}
            for ak, al in amap.items():
                if al in aliases_out:
                    remapped[ak] = al
                elif prefer_public_role(str(al)) in aliases_out:
                    remapped[ak] = prefer_public_role(str(al))
                elif "guardian" in aliases_out and ak in ("main", "auxiliary"):
                    remapped[ak] = "guardian"
                elif "coder" in aliases_out and ak in ("main", "auxiliary"):
                    remapped[ak] = "coder"
            if not remapped:
                pref = "guardian" if "guardian" in aliases_out else (
                    "coder" if "coder" in aliases_out else next(iter(aliases_out))
                )
                remapped = {"main": pref, "auxiliary": pref}
            cloned["aliases"] = remapped
        agents[aname] = cloned
    g["agents"] = agents
    g["kv_channels"] = {
        k: v for k, v in (g.get("kv_channels") or {}).items()
        if isinstance(v, dict) and v.get("from") in local_keys and v.get("to") in local_keys
    }
    # Harnesses: keep only those whose node is local; drop or rewrite agent ref
    harnesses_out = {}
    for k, v in (g.get("harnesses") or {}).items():
        if not isinstance(v, dict) or v.get("node") not in local_keys:
            continue
        v = dict(v)
        if v.get("agent") and v.get("agent") not in agents:
            v.pop("agent", None)
        harnesses_out[k] = v
    g["harnesses"] = harnesses_out

    # Drop cross-host agency/fleet/room refs that would fail validation
    for sec in ("fleets", "rooms", "reaches", "councils", "agencies", "swarms", "stores"):
        block = g.get(sec) or {}
        if not isinstance(block, dict):
            continue
        kept = {}
        for k, v in block.items():
            if not isinstance(v, dict):
                continue
            if sec == "agencies":
                assigns = v.get("assignments") or {}
                if isinstance(assigns, dict):
                    v = dict(v)
                    v["assignments"] = {
                        ak: av for ak, av in assigns.items()
                        if not isinstance(av, str) or av in agents
                    }
                    # drop agency if assignments empty and had any before
                    if assigns and not v["assignments"]:
                        continue
            ags = v.get("agents")
            if isinstance(ags, list):
                v = dict(v)
                v["agents"] = [a for a in ags if a in agents]
                if not v["agents"]:
                    continue
            kept[k] = v
        g[sec] = kept
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
