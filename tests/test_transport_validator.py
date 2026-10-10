#!/usr/bin/env python3
"""Validator checks for hosts:/transports: (no model files needed)."""
import copy, os, sys, yaml
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from transport_graph import validate_transports
g = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "graph.yaml")))
assert validate_transports(g) == [], validate_transports(g)
print("ok  shipped graph.yaml meshes validate")
cases = {
  "bind 0.0.0.0":      (lambda x: x["meshes"]["lan-bt"].__setitem__("bind", "0.0.0.0"), "must be a loopback or private LAN"),
  "public bind":       (lambda x: x["meshes"]["lan-bt"].__setitem__("bind", "8.8.8.8"), "must be a loopback or private LAN"),
  "bind != tracker":  (lambda x: x["meshes"]["lan-bt"].__setitem__("bind", "192.168.1.99"), "!= tracker host addr"),
  "not private":       (lambda x: x["meshes"]["lan-bt"].__setitem__("private", False), "private must be true"),
  "hostkey no":        (lambda x: x["meshes"]["lan-nexus"].__setitem__("host_key_policy", "no"), "never no"),
  "password on host":  (lambda x: x["hosts"]["phone7"].__setitem__("password", "x"), "'password' is not allowed"),
  "undeclared member": (lambda x: x["meshes"]["lan-nexus"]["members"].append("phone9"), "not a declared host"),
  "unknown type":      (lambda x: x["meshes"]["lan-bt"].__setitem__("type", "carrier-pigeon"), "not one of"),
  "missing host port": (lambda x: x["hosts"]["phone8"].pop("port"), "missing required 'port'"),
}
for name, (mut, want) in cases.items():
    h = copy.deepcopy(g); mut(h); errs = validate_transports(h)
    assert any(want in e for e in errs), (name, errs); print(f"ok  rejects {name}: {errs[0]}")
print("transport validator: all cases pass")
