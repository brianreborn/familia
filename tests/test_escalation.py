import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import escalation as E
from graph_types import validate_types
import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")

def g():
    n = lambda host: {"host": host, "model": "qwen35-2b-q4km"}
    gr = {"nodes": {"light": {"host": "qodesh", "model": "smollm2-135m-q4", "escalates_to": ["far", "near"],
                              "escalation": {"mode": "auto"}},
                    "far": n("miryam"), "near": n("qodesh")}}
    return gr

RECS = [{"host": "miryam", "kind": "bench", "model": {"repo": "Qwen/Qwen3.5-2B"}, "metrics": {"tg_tps": {"min": 8.4, "max": 17.4}}},
        {"host": "qodesh", "kind": "bench", "model": {"repo": "Qwen/Qwen3.5-2B"}, "metrics": {"tg_tps": {"min": 0.91, "max": 0.91}}}]

def test_no_signal_no_escalation():
    assert E.decide(g(), "light", {}, RECS, {})["decision"] == "none"

def test_triggers():
    t = E.DEFAULT_TRIGGERS
    assert E.stuck_reasons({"outputs": ["same answer here"] * 3}, t)
    assert not E.stuck_reasons({"outputs": ["a b c", "d e f", "g h i"]}, t)
    assert E.stuck_reasons({"failures": 3}, t) and not E.stuck_reasons({"failures": 2}, t)
    assert E.stuck_reasons({"user_messages": ["please TRY HARDER"]}, t)
    assert E.stuck_reasons({"tags": ["multi-file"]}, t)
    assert E.stuck_reasons({"elapsed_s": 601}, t) and not E.stuck_reasons({"elapsed_s": 10}, t)

def test_phrase_word_boundary_and_negation():
    t = E.DEFAULT_TRIGGERS
    # Positive: still trigger
    assert E.stuck_reasons({"user_messages": ["please escalate"]}, t)
    assert E.stuck_reasons({"user_messages": ["try harder"]}, t)
    assert E.stuck_reasons({"user_messages": ["please TRY HARDER"]}, t)
    # Negated: must not fire from phrases alone
    assert not E.stuck_reasons({"user_messages": ["do not escalate, just answer"]}, t)
    assert not E.stuck_reasons({"user_messages": ["don't escalate"]}, t)
    assert not E.stuck_reasons({"user_messages": ["dont escalate"]}, t)
    assert not E.stuck_reasons({"user_messages": ["never escalate"]}, t)
    assert not E.stuck_reasons({"user_messages": ["do not try harder"]}, t)
    # Substring that is not a whole-word phrase must not fire
    assert not E.stuck_reasons({"user_messages": ["deescalate the situation"]}, t)

def test_decide_ignores_negated_escalate_phrase():
    # Phrases alone with negation → none; positive phrase → suggest (cross-host)
    assert E.decide(g(), "light", {"user_messages": ["do not escalate, just answer"]}, RECS, {})["decision"] == "none"
    d = E.decide(g(), "light", {"user_messages": ["please escalate"]}, RECS, {})
    assert d["decision"] == "suggest" and "escalate" in d["reasons"][0]

def test_eta_ranking_prefers_fastest():
    r = E.rank(g(), "light", RECS)
    assert [x["node"] for x in r] == ["far", "near"] and r[0]["crosses_host"] and not r[1]["crosses_host"]
    assert r[0]["eta_s"] < r[1]["eta_s"]
    assert [x["node"] for x in E.rank(g(), "light", RECS, reachable={"qodesh"})] == ["near"]

def test_cross_host_needs_consent_then_auto(tmp_path):
    sig = {"failures": 5}
    d = E.decide(g(), "light", sig, RECS, {})
    assert d["decision"] == "suggest" and d["target"] == "far" and d["needs_consent"]
    p = str(tmp_path / "c.json")
    E.record_consent("light", "far", p)
    d = E.decide(g(), "light", sig, RECS, E.load_consent(p))
    assert d["decision"] == "auto" and not d["needs_consent"]

def test_same_host_auto_and_suggest_mode():
    d = E.decide(g(), "light", {"failures": 5}, RECS, {}, reachable={"qodesh"})
    assert d["decision"] == "auto" and d["target"] == "near"
    gr = g(); gr["nodes"]["light"]["escalation"]["mode"] = "suggest"
    assert E.decide(gr, "light", {"failures": 5}, RECS, {}, reachable={"qodesh"})["decision"] == "suggest"
    gr["nodes"]["light"]["escalation"]["mode"] = "off"
    assert E.decide(gr, "light", {"failures": 5}, RECS, {})["decision"] == "none"

def test_validation_cycles_and_unknown():
    gr = g(); gr["nodes"]["far"]["escalates_to"] = ["light"]
    errs = []; E.check_node_escalation(gr, "light", gr["nodes"]["light"], errs)
    assert any("cycle" in e for e in errs)
    gr = g(); gr["nodes"]["light"]["escalates_to"] = ["nope"]
    errs = []; E.check_node_escalation(gr, "light", gr["nodes"]["light"], errs)
    assert any("unknown node" in e for e in errs)
    gr = g(); gr["nodes"]["light"]["escalation"] = {"mode": "bogus"}
    errs = []; E.check_node_escalation(gr, "light", gr["nodes"]["light"], errs)
    assert errs

def test_handoff_is_compact():
    turns = [{"role": "user", "content": "x" * 5000}] * 20
    h = E.handoff(turns, "fix the build", last_n=4)
    assert len(h["turns"]) == 4 and h["omitted_turns"] == 16 and len(h["turns"][0]["content"]) < 700

def test_real_graph_valid_and_qodesh_prefers_miryam():
    gr = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    assert not [e for e in validate_types(gr) if "escalat" in e]
    t = [x["node"] for x in E.targets(gr, "qodesh-smol-cpu")]
    assert t[:2] == ["coder", "qodesh-resident"]
    d = E.decide(gr, "qodesh-smol-cpu", {"failures": 9}, RECS, {})
    assert d["decision"] == "suggest" and d["target"] == "coder"
