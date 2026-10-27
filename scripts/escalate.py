#!/usr/bin/env python3
"""CLI for docs/escalation.md.
  escalate.py decide --node X --signals FILE.json [--graph graph.yaml] [--reachable h1,h2]
  escalate.py consent --node X --target Y        record first-time cross-host consent
  escalate.py accept                             accept the pending suggestion from the hermes proxy
  escalate.py handoff --signals FILE.json        print compact handoff payload
signals JSON: {outputs, failures, user_messages, tags, elapsed_s, reply_tokens, turns, problem}
"""
import argparse, json, os, sys
import yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import escalation as E, registry

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Escalation helpers (docs/escalation.md).",
        epilog="Example: escalate.py decide --node coder --signals signals.json",
    ); p.add_argument("cmd", choices=["decide", "consent", "handoff", "accept"])
    p.add_argument("--node"); p.add_argument("--target"); p.add_argument("--signals")
    p.add_argument("--graph", default=os.path.join(E.ROOT, "graph.yaml")); p.add_argument("--reachable")
    p.add_argument("--consent-file", default=E.CONSENT)
    o = p.parse_args(argv)
    sig = json.load(sys.stdin if o.signals == "-" else open(o.signals)) if o.signals else {}
    if o.cmd == "accept":  # accept the proxy's pending suggestion (docs/escalation.md)
        import escalation_proxy as EP
        try: d = json.load(open(EP.PENDING))
        except Exception: print("escalate: no pending suggestion", file=sys.stderr); return 1
        json.dump({"target": d["target"]}, open(EP.ACCEPT, "w")); print(f"escalate: accepted {d['node']} -> {d['target']}; applies on the next request"); return 0
    if o.cmd == "handoff":
        print(json.dumps(E.handoff(sig.get("turns") or [], sig.get("problem", "")), indent=2)); return 0
    g = yaml.safe_load(open(o.graph))
    if o.node not in g["nodes"]: print(f"escalate: unknown node {o.node!r}", file=sys.stderr); return 2
    if o.cmd == "consent":
        if o.target not in (g["nodes"][o.node].get("escalates_to") or []):
            print(f"escalate: {o.target!r} is not in {o.node}.escalates_to", file=sys.stderr); return 2
        E.record_consent(o.node, o.target, o.consent_file); print(f"escalate: consent recorded {o.node} -> {o.target}"); return 0
    reach = set(o.reachable.split(",")) if o.reachable else None
    d = E.decide(g, o.node, sig, registry.load(), E.load_consent(o.consent_file), reach)
    print(json.dumps(d, indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
