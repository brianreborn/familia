"""Test-only helper: re-add the retired qodesh/shalom graph entries to a copy of a graph.

qodesh and shalom were removed from the fleet (graph.yaml) on 2026-11-23 PT. Several schema
tests used them as the only Windows host, sm11-legacy runtime and unknown-kind host. Those
tests merge this fixture into a deep copy so the schema checks stay covered; the live graph
itself carries no retired hosts.
"""
import copy, os
import yaml

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "retired_hosts", "qodesh_shalom.yaml")


def with_retired(graph):
    g = copy.deepcopy(graph)
    with open(FIXTURE, encoding="utf-8") as f:
        fx = yaml.safe_load(f)
    for section, entries in fx.items():
        dest = g.get(section) or {}
        for k, v in entries.items():
            dest.setdefault(k, copy.deepcopy(v))
        g[section] = dest
    if "lbref" in (g.get("runtimes") or {}):
        hosts = g["runtimes"]["lbref"].setdefault("hosts", [])
        if "qodesh" not in hosts:
            hosts.append("qodesh")
    mesh = (g.get("meshes") or {}).get("lan-nexus")
    if mesh is not None and "qodesh" not in mesh.setdefault("members", []):
        mesh["members"].append("qodesh")
    return g
