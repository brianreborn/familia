"""Spec conformance for SPEC config (docs/config/pentest-policy.md, routing-spec.md).
Pure data checks against docs/config/spec/*.yaml; runs nothing, probes nothing.
The reference validator lives here until graph_types implements it (strict xfail below)."""
import copy, sys
from pathlib import Path
import pytest, yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = yaml.safe_load((ROOT / "docs/config/spec/pentest-policy.schema.yaml").read_text())
MODES = SPEC["modes"]
LAB = {"kind": "isolated", "members": ["lab-target-1"], "cidrs": ["192.0.2.0/24"], "egress": "none",
       "verify": {"no_default_route": True, "no_lan_route": True, "dns_lab_only": True, "max_age_s": 3600}}

def check_policy(p, labs, escalation_targets=(), node="miryam-pentest"):
    """Reference validator for CFG-PENT-POL/LAB/AUD rules. Returns error list."""
    e, pol = [], p.get("policy") or {}
    mode = pol.get("mode", "planned")
    if mode not in MODES: e.append("mode")
    rank = MODES.index(mode) if mode in MODES else 0
    if pol.get("autonomy") == "autonomous" and mode != "autonomous-lab": e.append("autonomy")   # POL-003
    if rank > MODES.index("planned") and not p.get("requires_operator_confirm"): e.append("confirm")  # POL-005
    if mode in ("tools-confirm", "autonomous-lab"):
        if pol.get("audit") != "on": e.append("audit")                                  # AUD-002
        if not (p.get("scope") or {}).get("allow"): e.append("scope")
    if mode == "autonomous-lab":                                                          # LAB-001/002
        lab = labs.get(pol.get("lab"))
        if not lab: e.append("lab")
        elif lab.get("kind") != "isolated" or lab.get("egress") != "none" or not all(
                (lab.get("verify") or {}).get(k) is True for k in ("no_default_route", "no_lan_route", "dns_lab_only")):
            e.append("lab-verify")
        elif not set((p.get("scope") or {}).get("allow") or []) <= set(lab["members"]): e.append("scope-lab")
    if node in escalation_targets: e.append("escalation-target")                          # POL-004
    return e

def pent(mode, **kw):
    p = {"node": "miryam-pentest", "requires_operator_confirm": True, "scope": {"allow": ["lab-target-1"]},
         "policy": {"enabled": mode not in ("off", "planned"), "mode": mode, "tools": "none" if mode in ("off", "planned", "slash-confirm") else "all",
                    "autonomy": "autonomous" if mode == "autonomous-lab" else "confirm-each-action", "audit": "on"}}
    if mode == "autonomous-lab": p["policy"]["lab"] = "range1"
    p["policy"].update(kw); return p

@pytest.mark.parametrize("mode", MODES)
def test_every_mode_expressible(mode):  # design covers all modes, incl. autonomous exploitation
    assert check_policy(pent(mode), {"range1": LAB}) == []

def test_ladder_is_complete_and_ordered():
    assert MODES == ["off", "planned", "slash-confirm", "tools-confirm", "autonomous-lab"]

@pytest.mark.parametrize("mutate,err", [
    (lambda p, l: p["policy"].pop("lab"), "lab"),
    (lambda p, l: l["range1"].update(egress="lan"), "lab-verify"),
    (lambda p, l: l["range1"]["verify"].update(no_lan_route=False), "lab-verify"),
    (lambda p, l: p["policy"].update(audit="off"), "audit"),
    (lambda p, l: p.update(requires_operator_confirm=False), "confirm"),
    (lambda p, l: p["scope"].update(allow=["not-in-lab"]), "scope-lab"),
])
def test_autonomous_gated_by_verified_lab(mutate, err):
    p, labs = pent("autonomous-lab"), {"range1": copy.deepcopy(LAB)}
    mutate(p, labs); assert err in check_policy(p, labs)

def test_autonomy_only_in_lab_mode():
    assert "autonomy" in check_policy(pent("tools-confirm", autonomy="autonomous"), {})

def test_never_escalation_target():
    assert "escalation-target" in check_policy(pent("slash-confirm"), {}, escalation_targets={"miryam-pentest"})

def test_examples_use_documentation_ranges_only():
    import ipaddress, re
    for f in (ROOT / "docs/config").rglob("*"):
        if f.is_file():
            for m in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d+)?\b", f.read_text()):
                net = ipaddress.ip_network(m, strict=False)
                assert any(net.subnet_of(ipaddress.ip_network(d)) for d in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")), (f, m)

@pytest.mark.xfail(strict=True, reason="SPEC CFG-PENT-POL-*: graph_types does not accept pentests.policy/labs yet")
def test_graph_types_accepts_policy():
    import graph_types as GT
    assert "policy" in GT.TYPES["pentests"].fields and "labs" in GT.TYPES
