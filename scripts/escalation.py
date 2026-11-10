#!/usr/bin/env python3
"""Semi-automatic heavyweight-model escalation (docs/escalation.md).

The light node handles everything by default. When session signals show it is
stuck, decide() returns one of:
  {"decision": "none"}
  {"decision": "suggest", "target": T, "eta_s": ..., ...}   ask the user first
  {"decision": "auto", "target": T, ...}                     only inside consented scope
Rules: the system may suggest an edge but never opens one unasked. A target on
another host (crosses_host) needs recorded consent before it can be auto; until
then it is only ever suggested. Consent lives in .cache/familia/escalation-consent.json.
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSENT = os.path.join(ROOT, ".cache", "familia", "escalation-consent.json")
MODES = {"off", "suggest", "auto"}
TRIGGER_KEYS = {"repeat_outputs", "similarity", "failure_retries", "phrases", "tags", "time_budget_s"}
DEFAULT_TRIGGERS = {
    "repeat_outputs": 3,          # >= N (near-)identical consecutive outputs
    "similarity": 0.9,            # token-set Jaccard counted as "near-identical"
    "failure_retries": 3,         # >= N failed tool calls / tests
    "phrases": ["try harder", "escalate", "use the big model", "heavier model"],
    "tags": ["hard", "multi-file"],
    "time_budget_s": 600,         # elapsed on one problem
}
DEFAULT_REPLY_TOKENS = 256

def escalation_cfg(node):
    e = dict(node.get("escalation") or {})
    trig = dict(DEFAULT_TRIGGERS); trig.update(e.get("triggers") or {})
    return {"mode": e.get("mode", "suggest"), "triggers": trig}

# ---- graph checks (called from graph_types.check_node) --------------------
def check_node_escalation(g, name, n, errs):
    nodes = g.get("nodes") or {}
    tg = n.get("escalates_to")
    if tg is not None:
        if not isinstance(tg, list): errs.append(f"nodes.{name}.escalates_to: expected list of node ids"); tg = []
        for t in tg:
            if t == name: errs.append(f"nodes.{name}.escalates_to: node escalates to itself")
            elif t not in nodes: errs.append(f"nodes.{name}.escalates_to: unknown node {t!r}")
        if len(set(tg)) != len(tg): errs.append(f"nodes.{name}.escalates_to: duplicate targets")
    e = n.get("escalation")
    if e is not None:
        if not isinstance(e, dict): errs.append(f"nodes.{name}.escalation: expected mapping"); return
        for k in e:
            if k not in ("mode", "triggers"): errs.append(f"nodes.{name}.escalation: unknown field {k!r}")
        if e.get("mode", "suggest") not in MODES: errs.append(f"nodes.{name}.escalation.mode: must be one of {sorted(MODES)}")
        for k in (e.get("triggers") or {}):
            if k not in TRIGGER_KEYS: errs.append(f"nodes.{name}.escalation.triggers: unknown trigger {k!r}")
        if e.get("mode") in ("suggest", "auto") and not tg:
            errs.append(f"nodes.{name}.escalation: mode {e['mode']} but no escalates_to targets")
    # cycle check (DFS from this node)
    stack, seen = [(name, [name])], set()
    while stack:
        cur, path = stack.pop()
        for t in (nodes.get(cur) or {}).get("escalates_to") or []:
            if t == name and len(path) > 1:
                errs.append(f"nodes.{name}.escalates_to: cycle {' -> '.join(path + [t])}"); return
            if t in nodes and t not in seen and t != cur:
                seen.add(t); stack.append((t, path + [t]))

def targets(g, name):
    """Ordered escalation targets with crosses_host flags."""
    n = g["nodes"][name]
    return [{"node": t, "host": g["nodes"][t]["host"], "crosses_host": g["nodes"][t]["host"] != n["host"]}
            for t in n.get("escalates_to") or [] if t in g["nodes"]]

# ---- stuck detection ------------------------------------------------------
def _sim(a, b):
    ta, tb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    if not ta and not tb: return 1.0
    return len(ta & tb) / len(ta | tb)


# Negation immediately before a phrase match (short window). Word-boundary
# phrase hits only; "do not escalate" must not fire on phrase "escalate".
_NEG_BEFORE = re.compile(r"(?i)\b(?:do\s+not|don'?t|dont|never|no)\s*$")

def _nospace(ch):
    """Scripts written without spaces between words (Han, kana, Hangul, Thai...): no \\b there."""
    import unicodedata as _u
    n = _u.name(ch, "")
    return n.startswith(("CJK ", "HIRAGANA", "KATAKANA", "HANGUL", "THAI", "LAO", "KHMER", "MYANMAR", "TIBETAN"))

def _phrase_hit(message, phrases):
    """First phrase that matches on word boundaries and is not negated.
    Text and phrases are NFC-normalised (NFD input from macOS/IMEs must still match), and
    no-space scripts (CJK) match without word boundaries (routing-l10n)."""
    import unicodedata as _u
    message = _u.normalize("NFC", message)
    for p in phrases:
        words = re.findall(r"\w+", _u.normalize("NFC", p).lower())
        if not words:
            continue
        lb = "" if _nospace(words[0][0]) else r"\b"
        rb = "" if _nospace(words[-1][-1]) else r"\b"
        pat = re.compile(lb + r"\s*".join(re.escape(w) for w in words) + rb if all(_nospace(w[0]) for w in words)
                         else lb + r"\s+".join(re.escape(w) for w in words) + rb, re.IGNORECASE)
        for m in pat.finditer(message):
            window = message[max(0, m.start() - 24):m.start()]
            if _NEG_BEFORE.search(window):
                continue
            return p
    return None

def stuck_reasons(sig, trig):
    """sig keys (all optional): outputs [str], failures int, user_messages [str],
    tags [str], elapsed_s num. Returns list of human-readable reasons."""
    why = []
    outs = sig.get("outputs") or []
    n = trig["repeat_outputs"]
    if n and len(outs) >= n:
        last = outs[-n:]
        if all(_sim(last[0], o) >= trig["similarity"] for o in last[1:]):
            why.append(f"last {n} outputs (near-)identical")
    if trig["failure_retries"] and (sig.get("failures") or 0) >= trig["failure_retries"]:
        why.append(f"{sig['failures']} failed tool calls/tests (>= {trig['failure_retries']})")
    for m in sig.get("user_messages") or []:
        hit = _phrase_hit(m, trig["phrases"])
        if hit: why.append(f"user asked: {hit!r}"); break
    tags = set(sig.get("tags") or []) & set(trig["tags"])
    if tags: why.append(f"task tagged {sorted(tags)}")
    if trig["time_budget_s"] and (sig.get("elapsed_s") or 0) > trig["time_budget_s"]:
        why.append(f"elapsed {sig['elapsed_s']}s > budget {trig['time_budget_s']}s")
    return why

# ---- ETA from registry ----------------------------------------------------
def _norm(s): return re.sub(r"[^a-z0-9]", "", s.lower())

def node_tps(g, name, recs):
    """Best measured tg t/s for this node's model on its host (registry), else None."""
    n = g["nodes"][name]
    stem = _norm(re.split(r"-q\d|-f\d|-fp", n["model"])[0])
    best = None
    for r in recs:
        if r.get("host") != n["host"] or r.get("kind") not in (None, "bench", "concurrency", "measure"): continue
        if stem not in _norm(json.dumps(r.get("model"))): continue
        hi = ((r.get("metrics") or {}).get("tg_tps") or {}).get("max")
        if isinstance(hi, (int, float)) and (best is None or hi > best): best = hi
    return best

def rank(g, name, recs, reachable=None, reply_tokens=DEFAULT_REPLY_TOKENS):
    """Targets fastest-first; unreachable hosts dropped; unmeasured last in declared order."""
    out = []
    for i, t in enumerate(targets(g, name)):
        if reachable is not None and t["host"] not in reachable: continue
        tps = node_tps(g, t["node"], recs)
        t.update(tg_tps=tps, eta_s=round(reply_tokens / tps, 1) if tps else None, _i=i)
        out.append(t)
    out.sort(key=lambda t: (t["tg_tps"] is None, -(t["tg_tps"] or 0), t["_i"]))
    for t in out: t.pop("_i")
    return out

# ---- consent --------------------------------------------------------------
def load_consent(path=CONSENT):
    try: return json.load(open(path))
    except Exception: return {}

def has_consent(c, src, dst):
    return dst in (c.get(src) or {}) or dst in (c.get("*") or {})

def record_consent(src, dst, path=CONSENT, now=None):
    c = load_consent(path)
    c.setdefault(src, {})[dst] = {"granted_at": now or time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(c, open(path, "w"), indent=2, sort_keys=True)
    return c

# ---- decision -------------------------------------------------------------
def decide(g, name, sig, recs, consent=None, reachable=None):
    n = g["nodes"][name]; cfg = escalation_cfg(n)
    if cfg["mode"] == "off" or not n.get("escalates_to"):
        return {"decision": "none", "node": name, "reasons": [], "why_none": "escalation off or no targets"}
    why = stuck_reasons(sig, cfg["triggers"])
    if not why: return {"decision": "none", "node": name, "reasons": []}
    ranked = rank(g, name, recs, reachable, sig.get("reply_tokens") or DEFAULT_REPLY_TOKENS)
    if not ranked: return {"decision": "none", "node": name, "reasons": why, "why_none": "no reachable target"}
    consent = load_consent() if consent is None else consent
    best = ranked[0]
    needs = best["crosses_host"] and not has_consent(consent, name, best["node"])
    kind = "auto" if cfg["mode"] == "auto" and not needs else "suggest"
    eta = f"~{best['eta_s']:.0f}s for {sig.get('reply_tokens') or DEFAULT_REPLY_TOKENS} tokens at {best['tg_tps']} t/s" if best["eta_s"] else "speed unmeasured"
    return {"decision": kind, "node": name, "target": best["node"], "host": best["host"],
            "crosses_host": best["crosses_host"], "needs_consent": needs, "eta_s": best["eta_s"],
            "tg_tps": best["tg_tps"], "reasons": why, "alternatives": ranked[1:],
            "prompt": f"This looks stuck ({'; '.join(why)}). Switch to {best['node']} on {best['host']}? ({eta})"
                      + (" This sends the conversation summary to another host." if best["crosses_host"] else ""),
            "swap_back_to": name}

def handoff(turns, problem, last_n=6, max_chars=600):
    """Compact payload for the heavy node: open problem + last N turns, each clipped."""
    keep = turns[-last_n:]
    clip = lambda s: s if len(s) <= max_chars else s[:max_chars] + " [...]"
    return {"open_problem": problem, "omitted_turns": len(turns) - len(keep),
            "turns": [{"role": t.get("role", "user"), "content": clip(t.get("content", ""))} for t in keep],
            "instruction": "Solve the open problem. Be concise; control returns to the light model afterwards."}
