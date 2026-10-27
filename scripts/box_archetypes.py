#!/usr/bin/env python3
"""Box / platform archetypes = physical (or dedicated) form factors — never virtualization.

Canonical host ``kind`` values live here so schema, host_measure, generate_graph,
and docs share one enum. Each kind carries a default **graph shape**: the starter
topology (roles, reserve hint, transports, offload bias) the platform implies
before per-host / per-user overrides.

1U = small server, 2U = medium, 3U = large. ``vm`` is obsolete (fail-loud).
``unknown`` is transitional only (unmeasured hosts).
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

# Physical form factors + dedicated device classes. Not hypervisors / "vm".
HOST_KINDS = frozenset({
    "desktop",
    "phone",
    "tablet",
    "notebook",
    "laptop",
    "1U",
    "2U",
    "3U",
    "console",
    "appliance",
    "drone",
    "watch",
    "unknown",
})

# Kinds an operator may pass to host_measure (unknown stays transitional / explicit-only).
MEASURABLE_HOST_KINDS = frozenset(k for k in HOST_KINDS if k != "unknown")

OBSOLETE_HOST_KINDS = {
    "vm": (
        "obsolete: box archetypes are physical/dedicated form factors "
        "(desktop|phone|tablet|notebook|laptop|1U|2U|3U|console|appliance|drone|watch); "
        "1U=small / 2U=medium / 3U=large server — not virtualization"
    ),
}

# Default graph shape per kind. Roles are public node types (see node_role.NODE_ROLES).
# status_bias: which roles start planned vs preferred-active when first placed.
# Overrides: host notes, generate_graph --set, host-overrides.yaml, explicit nodes in graph.yaml.
DEFAULT_SHAPES: Dict[str, Dict[str, Any]] = {
    "phone": {
        "roles": ["decision", "general", "chat"],
        "reserve_ram_mib": 5120,
        "transports": ["ssh"],
        "offload_prefer": "vulkan",
        "ctx_bias": "short",
        "parallel_bias": 1,
        "notes": (
            "On-device assistant: tiny decision + compact chat/general. "
            "Tight RAM floor; Vulkan when verified. Jump-host SSH typical (angel→galaxy*)."
        ),
    },
    "tablet": {
        "roles": ["decision", "chat", "general"],
        "reserve_ram_mib": 4096,
        "transports": ["ssh", "local"],
        "offload_prefer": "vulkan",
        "ctx_bias": "medium",
        "parallel_bias": 1,
        "notes": "Phone-class stack with slightly larger ctx budget; still one heavy job at a time.",
    },
    "watch": {
        "roles": ["decision"],
        "reserve_ram_mib": 768,
        "transports": ["ssh"],
        "offload_prefer": "none",
        "ctx_bias": "tiny",
        "parallel_bias": 1,
        "notes": "Wearable edge: single tiny decision model; no coder/embed by default.",
    },
    "laptop": {
        "roles": ["coder", "chat", "embed"],
        "reserve_ram_mib": 3072,
        "transports": ["local", "ssh"],
        "offload_prefer": "auto",
        "ctx_bias": "medium",
        "parallel_bias": 1,
        "notes": "Dev laptop (e.g. miryam): coder+chat+embed; never pack RAM (docs/ram-safety.md).",
    },
    "notebook": {
        "roles": ["coder", "chat", "embed"],
        "reserve_ram_mib": 3072,
        "transports": ["local", "ssh"],
        "offload_prefer": "auto",
        "ctx_bias": "medium",
        "parallel_bias": 1,
        "notes": "Thin/portable PC — same starter shape as laptop; tune reserve after measure.",
    },
    "desktop": {
        "roles": ["coder", "chat", "embed", "guardian"],
        "reserve_ram_mib": 4096,
        "transports": ["local", "ssh"],
        "offload_prefer": "auto",
        "ctx_bias": "medium",
        "parallel_bias": 2,
        "notes": (
            "Tower/desktop (angel, qodesh, centos-class): full assistant stack; "
            "guardian seatbelts on (launch-test, empty tools allow) until widened."
        ),
    },
    "1U": {
        "roles": ["coder", "chat", "embed", "guardian"],
        "reserve_ram_mib": 6144,
        "transports": ["ssh", "local"],
        "offload_prefer": "auto",
        "ctx_bias": "long",
        "parallel_bias": 2,
        "notes": "Small rack server: same roles as desktop with higher reserve and SSH-first mesh.",
    },
    "2U": {
        "roles": ["coder", "chat", "embed", "reasoning", "guardian"],
        "reserve_ram_mib": 8192,
        "transports": ["ssh", "local", "nfs"],
        "offload_prefer": "auto",
        "ctx_bias": "long",
        "parallel_bias": 4,
        "notes": "Medium server: add reasoning; more parallel slots; shared storage optional.",
    },
    "3U": {
        "roles": ["coder", "chat", "embed", "reasoning", "vision", "guardian"],
        "reserve_ram_mib": 12288,
        "transports": ["ssh", "local", "nfs", "zfs"],
        "offload_prefer": "auto",
        "ctx_bias": "long",
        "parallel_bias": 8,
        "notes": "Large server: broad role set; fleet hub / agency host candidate.",
    },
    "console": {
        "roles": ["chat", "decision", "vision"],
        "reserve_ram_mib": 4096,
        "transports": ["local"],
        "offload_prefer": "auto",
        "ctx_bias": "medium",
        "parallel_bias": 1,
        "notes": "Living-room / game console class: chat+decision+vision; coder not default.",
    },
    "appliance": {
        "roles": ["decision", "guardian"],
        "reserve_ram_mib": 2048,
        "transports": ["local"],
        "offload_prefer": "none",
        "ctx_bias": "short",
        "parallel_bias": 1,
        "notes": (
            "Dedicated appliance (NAS, filter, lab gadget): minimal decision + guardian "
            "seatbelts; default-deny beyond owned fleet — protect home appliances from accidental scans."
        ),
    },
    "drone": {
        "roles": ["decision"],
        "reserve_ram_mib": 1024,
        "transports": ["ssh"],
        "offload_prefer": "none",
        "ctx_bias": "tiny",
        "parallel_bias": 1,
        "notes": "Air/edge vehicle: tiny on-board decision only; telemetry via SSH/mesh, no heavy stack.",
    },
    "unknown": {
        "roles": [],
        "reserve_ram_mib": 3072,
        "transports": [],
        "offload_prefer": "none",
        "ctx_bias": "short",
        "parallel_bias": 1,
        "notes": "Transitional only — identify form factor and re-measure with an explicit --kind.",
    },
}


def shape_for(kind: Optional[str]) -> Dict[str, Any]:
    """Return a copy of the default shape for ``kind`` (unknown shape if missing)."""
    import copy
    key = kind if kind in DEFAULT_SHAPES else "unknown"
    return copy.deepcopy(DEFAULT_SHAPES[key])


def obsolete_kind_message(kind: str) -> Optional[str]:
    return OBSOLETE_HOST_KINDS.get(kind)


def validate_kind(kind: str) -> Tuple[bool, Optional[str]]:
    """Return (ok, error_message)."""
    if kind in OBSOLETE_HOST_KINDS:
        return False, OBSOLETE_HOST_KINDS[kind]
    if kind not in HOST_KINDS:
        return False, f"not one of {sorted(HOST_KINDS)}"
    return True, None


def shape_header_lines(kind: str, host: str) -> List[str]:
    """Comment lines for generated/graph-HOST.yaml describing the platform shape."""
    s = shape_for(kind)
    roles = ", ".join(s.get("roles") or []) or "(none — identify kind)"
    return [
        f"# platform kind: {kind}",
        f"# default shape roles: {roles}",
        f"# reserve_ram_mib hint: {s.get('reserve_ram_mib')}",
        f"# transports: {', '.join(s.get('transports') or []) or 'n/a'}",
        f"# offload_prefer: {s.get('offload_prefer')}  ctx_bias: {s.get('ctx_bias')}  "
        f"parallel_bias: {s.get('parallel_bias')}",
        f"# shape notes: {s.get('notes')}",
        f"# overrides: graph.yaml nodes for host={host}, config/host-overrides.yaml, generate_graph --set",
    ]


def merge_shape_roles(existing_roles: Mapping[str, Any], kind: str) -> List[str]:
    """Ordered role list: shape order first, then any extra roles already present."""
    shape_roles = list(shape_for(kind).get("roles") or [])
    extras = [r for r in existing_roles if r not in shape_roles]
    return shape_roles + extras
