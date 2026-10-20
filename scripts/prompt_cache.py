#!/usr/bin/env python3
"""prompt_cache.py: prefill an agent's fixed prompt prefix once per host and reload it from disk (#85).

hermes-agent sends the same tool schemas and system prompt at the start of every session. On a
slow CPU node that prefix costs minutes (12.5k tokens = ~11 min on miryam's coder). llama-server
can save a slot's KV / recurrent state to a file (--slot-save-path) and restore it in ~0.1 s, and
a request whose tokens start with the restored ones then only prefills the rest.

  warm(base, prefix_text)   restore <slots>/<sha>.bin if it exists, else prefill + save it.

The prefix is the byte-stable part: rendered with the node's own chat template (/apply-template)
up to where the agent's volatile text (date, model line) starts, minus one token so a merge at
the cut cannot change it. Its sha256 names the file, so any change to tools, system prompt or
template simply makes a new file. Stdlib only; no agent imports (independent of hermes and
Harness²). Docs: docs/perf/2026-10-19-hermes-prompt.md."""
import hashlib, json, sys, time, urllib.request


def _post(base, path, body, timeout):
    r = urllib.request.Request(base.rstrip("/") + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.load(resp)


SPLIT = "\u2063FAMILIA_SPLIT\u2063"


def stable_prefix(base, system, tools, volatile="", timeout=120, unstable=()):
    """Rendered prompt text before the first user turn, cut where `volatile` starts or at the
    first line starting with any `unstable` marker (text the agent re-probes per session)."""
    p = _post(base, "/apply-template", {"messages": [{"role": "system", "content": system},
                                                     {"role": "user", "content": SPLIT}], "tools": tools}, timeout)["prompt"]
    p = p[:p.index(SPLIT)]
    cuts = [p.index(volatile)] if volatile and volatile in p else []
    cuts += [i + 1 for i in (p.find("\n" + m) for m in unstable) if i >= 0]  # keep the newline
    return p[:min(cuts)] if cuts else p


def prefix_tokens(base, text, timeout=120):
    toks = _post(base, "/tokenize", {"content": text, "add_special": False}, timeout)["tokens"]
    return toks[:-1] if len(toks) > 1 else toks


def name_for(tokens, tag=""):
    h = hashlib.sha256((tag + "|" + ",".join(map(str, tokens))).encode()).hexdigest()[:20]
    return f"prefix-{h}.bin"


def warm(base, tokens, tag="", slot=0, timeout=7200, log=lambda m: print(m, file=sys.stderr)):
    """-> ("restored"|"warmed"|"skipped", seconds). Never raises: a cache is an optimisation."""
    fn, t0 = name_for(tokens, tag), time.time()
    try:
        r = _post(base, f"/slots/{slot}?action=restore", {"filename": fn}, 600)
        if r.get("n_restored"):
            log(f"prompt cache: restored {r['n_restored']} prefix tokens from {fn} in {time.time() - t0:.1f}s")
            return "restored", time.time() - t0
    except Exception:
        pass  # no file yet (llama-server answers 400), or slot saving is off
    try:
        log(f"prompt cache: prefilling the fixed prefix once ({len(tokens)} tokens); later starts restore it from disk")
        _post(base, "/completion", {"prompt": tokens, "n_predict": 0, "cache_prompt": True, "id_slot": slot}, timeout)
        _post(base, f"/slots/{slot}?action=save", {"filename": fn}, 600)
        log(f"prompt cache: saved {fn} after {time.time() - t0:.0f}s")
        return "warmed", time.time() - t0
    except Exception as e:
        log(f"prompt cache: skipped ({e})")
        return "skipped", time.time() - t0
