#!/usr/bin/env python3
"""Phone system agents (Bixby, Gemini) as optional, off-by-default graph entries (#80).

usage: system_agents.py status [--graph FILE] [--json]
       system_agents.py licenses [--graph FILE] [--json]
       system_agents.py check [--graph FILE]
       system_agents.py -h | --help

status    list the system_agents entries in graph.yaml and what each one would send off the device
licenses  the license/terms rows for scripts/licenses.py (Shizuku, provider terms)
check     schema + safety checks only (the same ones validate_graph.py runs)

Nothing here touches a phone. The phone side is scripts/termux/system_agent.py, which runs
in Termux through Shizuku's rish (no root). Research and sources:
docs/research/phone-system-agents.md; usage: docs/system-agents.md.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PROVIDERS = {
    # provider -> backend -> facts (all from docs/research/phone-system-agents.md)
    "gemini": {
        "app": {"cloud": True, "package": "com.google.android.apps.bard",
                "leaves_device": "your prompt and Gemini's reply, under your Google account",
                "terms": "proprietary service terms: Google Terms of Service, Gemini Apps Privacy Notice, "
                         "Generative AI Prohibited Use Policy (13+)",
                "link": "https://support.google.com/gemini/answer/16625148"},
        "nano": {"cloud": False, "package": "com.google.android.aicore",
                 "leaves_device": "no prompt data (ML Kit metrics only)",
                 "terms": "proprietary: Google APIs Terms of Service + ML Kit GenAI API Additional Terms "
                          "(18+, no weight extraction, no bypassing safety filters)",
                 "link": "https://developers.google.com/ml-kit/genai-terms"},
    },
    "bixby": {
        "app": {"cloud": True, "package": None,  # found at runtime; Samsung documents no package/intent API
                "leaves_device": "your request to Samsung; web questions also to Perplexity (new Bixby)",
                "terms": "proprietary service terms: Samsung account terms and Samsung privacy notice "
                         "(new Bixby web answers via Perplexity; exact text not reviewed)",
                "link": "https://www.samsungmobilepress.com/articles/bixby-one-ui-8-5-conversational-device-agent"},
    },
}
SHIZUKU = ("Apache-2.0", "https://github.com/RikkaApps/Shizuku",
           "Shizuku and its rish shell (no root). Apache-2.0; section 6 bars reusing the Shizuku name, icon "
           "and app id. Get it from GitHub releases or the IzzyOnDroid F-Droid repo "
           "(https://shizuku.rikka.app/download/). Must be started again after every reboot unless rooted.")


def entries(g):
    sa = (g or {}).get("system_agents") or {}
    return sa if isinstance(sa, dict) else {}


def enabled(g):
    return {n: e for n, e in entries(g).items() if isinstance(e, dict) and e.get("status") in ("planned", "active")}


def check_entry(g, name, e, errs):
    """Per-entry checks for graph_types (TYPES['system_agents'])."""
    w = f"system_agents.{name}"
    prov, be = e.get("provider"), e.get("backend")
    facts = (PROVIDERS.get(prov) or {}).get(be)
    if prov in PROVIDERS and be is not None and facts is None:
        errs.append(f"{w}: provider {prov} has no {be!r} backend (bixby: app only; gemini: app or nano)")
    if facts is not None and e.get("cloud") is not facts["cloud"]:
        errs.append(f"{w}: cloud must be {str(facts['cloud']).lower()} for {prov}/{be} "
                    f"(what leaves the device: {facts['leaves_device']})")
    h = ((g.get("hosts") or {}).get(e.get("host")) or {})
    if h and h.get("kind") != "phone":
        errs.append(f"{w}: host {e.get('host')!r} is kind {h.get('kind')!r}; system agents run on a phone")
    for a in e.get("agents") or []:
        for pn, p in (g.get("pentests") or {}).items():
            if isinstance(p, dict) and p.get("agent") == a:
                errs.append(f"{w}: agent {a!r} is used by pentests.{pn}; pentest roles never get system agents")


def check_graph(g):
    """Cross-section rule: a pentest may not name a system agent among its tools."""
    errs, names = [], set(entries(g))
    for pn, p in (g.get("pentests") or {}).items():
        tools = (p or {}).get("tools") if isinstance(p, dict) else None
        flat = json.dumps(tools) if tools is not None else ""
        for n in sorted(names):
            if f'"{n}"' in flat:
                errs.append(f"pentests.{pn}.tools: names system agent {n!r}; pentest roles never get system agents")
        if "system-agent" in flat or "system_agent" in flat:
            errs.append(f"pentests.{pn}.tools: system agents are never pentest tools")
    return errs


def license_rows(g):
    """(kind, id, used_for, license, link, notes) for each enabled entry, plus Shizuku once."""
    rows, en = [], enabled(g)
    if not en:
        return rows
    lic, link, notes = SHIZUKU
    rows.append(("component", "Shizuku + rish (RikkaApps)", "no-root bridge for system agents: " + ", ".join(sorted(en)),
                 lic, link, notes))
    seen = set()
    for n, e in sorted(en.items()):
        f = (PROVIDERS.get(e.get("provider")) or {}).get(e.get("backend"))
        if not f or (e["provider"], e["backend"]) in seen:
            continue
        seen.add((e["provider"], e["backend"]))
        where = "cloud" if f["cloud"] else "on-device"
        rows.append(("service", f"{e['provider']} ({e['backend']}, {where})", f"system agent {n} on {e.get('host')}",
                     f["terms"], f["link"], "Leaves the device: " + f["leaves_device"]
                     + (". familia asks before every cloud call." if f["cloud"] else ".")))
    return rows


def describe(g):
    out = []
    for n, e in sorted(entries(g).items()):
        f = (PROVIDERS.get(e.get("provider")) or {}).get(e.get("backend")) or {}
        out.append({"name": n, "provider": e.get("provider"), "backend": e.get("backend"), "host": e.get("host"),
                    "status": e.get("status"), "cloud": f.get("cloud"), "leaves_device": f.get("leaves_device"),
                    "agents": e.get("agents") or [], "live_tested": False})
    return out


def _load(path):
    sys.path.insert(0, HERE)
    import familia_yaml
    try:
        return familia_yaml.load(path) or {}
    except OSError:
        return {}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip()); return 0 if argv else 2
    cmd, rest, graph, as_json = argv[0], argv[1:], os.path.join(ROOT, "graph.yaml"), False
    it = iter(rest)
    for x in it:
        if x == "--graph":
            graph = next(it, None)
            if not graph: print("system_agents.py: --graph needs a value", file=sys.stderr); return 2
        elif x == "--json": as_json = True
        elif x in ("-h", "--help"): print(__doc__.strip()); return 0
        else: print(f"system_agents.py: unknown argument {x!r}", file=sys.stderr); return 2
    if cmd not in ("status", "licenses", "check"):
        print(f"system_agents.py: unknown command {cmd!r} (status, licenses, check)", file=sys.stderr); return 2
    g = _load(graph)
    if cmd == "check":
        sys.path.insert(0, HERE)
        from graph_types import validate_types
        errs = [x for x in validate_types(g) if x.startswith(("system_agents", "pentests"))]
        for x in errs: print(f"system_agents: ERROR: {x}", file=sys.stderr)
        if not errs: print(f"system_agents: OK ({len(entries(g))} entr{'y' if len(entries(g)) == 1 else 'ies'})")
        return 1 if errs else 0
    if cmd == "licenses":
        rows = license_rows(g)
        if as_json: print(json.dumps([dict(zip(("kind", "id", "used_for", "license", "link", "notes"), r)) for r in rows], indent=1))
        else:
            for r in rows: print(f"{r[1]}: {r[3]}\n  {r[4]}\n  {r[5]}")
            if not rows: print("No system agents switched on (system_agents: in graph.yaml); nothing to agree to.")
        return 0
    d = describe(g)
    if as_json: print(json.dumps(d, indent=1)); return 0
    if not d:
        print("No system agents in graph.yaml (they are off by default). See docs/system-agents.md."); return 0
    for x in d:
        print(f"{x['name']}: {x['provider']}/{x['backend']} on {x['host']}, status {x['status']}, "
              f"{'CLOUD' if x['cloud'] else 'on-device'}; leaves the device: {x['leaves_device']}; live test pending")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
