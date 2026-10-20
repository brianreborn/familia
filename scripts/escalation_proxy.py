#!/usr/bin/env python3
"""Localhost OpenAI-compatible proxy that implements escalation for hermes (docs/escalation.md).

hermes -> proxy (127.0.0.1) -> current upstream node. The proxy records session
signals from the traffic (assistant outputs, failed tool results, user phrases,
elapsed time), calls escalation.decide() after each reply, and:
  suggest -> prints the prompt to stderr, appends it to the reply hermes sees,
             writes .cache/familia/escalation-pending.json; accept with
             `scripts/escalate.py accept` (or FAMILIA_ESCALATE=auto).
  auto    -> swaps immediately.
On swap the next request goes to the target node with a compact handoff instead
of the full history; after one clean reply it swaps back (swap_back=True).
"""
import json, os, re, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import escalation as E

STATE = os.path.join(E.ROOT, ".cache", "familia")
PENDING = os.path.join(STATE, "escalation-pending.json")
ACCEPT = os.path.join(STATE, "escalation-accept.json")
FAIL_RE = re.compile(r"(error|traceback|failed|exception|exit code [1-9]|FAILED)", re.I)

def node_url(g, name, local_host):
    """Base URL for a node. Remote nodes need a non-loopback bind (else None: needs a tunnel)."""
    n = g["nodes"][name]
    if n["host"] == local_host: return f"http://127.0.0.1:{n['port']}/v1"
    addr = (g["hosts"].get(n["host"]) or {}).get("addr")
    if n.get("bind", "127.0.0.1").startswith("127.") or not addr: return None
    return f"http://{addr}:{n['port']}/v1"

def alias_for(g, name):
    return next((a for a, x in (g.get("aliases") or {}).items() if x["node"] == name), name)

class Signals:
    def __init__(self): self.reset()
    def reset(self):
        self.outputs, self.failures, self.user_messages, self.t0 = [], 0, [], time.time()
    def observe_request(self, body):
        msgs = body.get("messages") or []
        users = [m for m in msgs if m.get("role") == "user"]
        if users: self.user_messages = [_text(users[-1])]
        # count failed tool results since the last user turn
        last_u = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)
        self.failures = sum(1 for m in msgs[last_u + 1:] if m.get("role") == "tool" and FAIL_RE.search(_text(m)))
    def observe_reply(self, text):
        if text: self.outputs.append(text); self.outputs = self.outputs[-10:]
    def dict(self):
        return {"outputs": self.outputs, "failures": self.failures, "user_messages": self.user_messages,
                "elapsed_s": round(time.time() - self.t0)}

def _text(m):
    c = m.get("content")
    if isinstance(c, list): return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""

class Escalator:
    """State machine: light node <-> target. Pure logic; HTTP lives in Proxy."""
    def __init__(self, g, light, recs, local_host, ensure=None, consent=None, swap_back=True, reachable=None):
        self.g, self.light, self.recs, self.local_host = g, light, recs, local_host
        self.ensure = ensure or (lambda name: True)
        self.consent, self.swap_back, self.reachable = consent, swap_back, reachable
        self.current, self.pending, self.handoff_next, self.sig = light, None, False, Signals()
        self.auto_env = os.environ.get("FAMILIA_ESCALATE") == "auto"

    def upstream(self):
        return node_url(self.g, self.current, self.local_host), alias_for(self.g, self.current)

    def after_reply(self, ok):
        """Returns a user-visible note or None."""
        if self.current != self.light:
            if ok and self.swap_back:
                self.current = self.light; self.sig.reset(); return f"[familia] escalation done; back on {self.light}"
            return None
        d = E.decide(self.g, self.light, self.sig.dict(), self.recs,
                     E.load_consent() if self.consent is None else self.consent, self.reachable)
        if d["decision"] == "none": return None
        if d["decision"] == "auto" or (self.auto_env and not d["needs_consent"]) or self._accepted(d):
            return self.swap(d)
        self.pending = d
        os.makedirs(STATE, exist_ok=True); json.dump(d, open(PENDING, "w"), indent=2)
        return f"[familia] {d['prompt']} Accept: python3 scripts/escalate.py accept"

    def _accepted(self, d):
        try: a = json.load(open(ACCEPT))
        except Exception: return False
        if a.get("target") != d["target"]: return False
        os.remove(ACCEPT)
        if d["crosses_host"]: E.record_consent(self.light, d["target"])  # first yes = consent
        return True

    def check_accept(self):
        if self.pending and self._accepted(self.pending): return self.swap(self.pending)

    def swap(self, d):
        t = d["target"]
        if node_url(self.g, t, self.local_host) is None:
            return f"[familia] cannot reach {t} on {d['host']} (loopback-bound; needs ssh tunnel). Staying on {self.light}."
        if self.g["nodes"][t]["host"] == self.local_host and not self.ensure(t):
            return f"[familia] could not start {t}; staying on {self.light}"
        self.current, self.pending, self.handoff_next = t, None, True
        try: os.remove(PENDING)
        except OSError: pass
        return f"[familia] escalated to {t} on {d['host']} ({d.get('eta_s') or '?'}s est.)"

    def rewrite(self, body):
        self.sig.observe_request(body)
        url, alias = self.upstream()
        body = dict(body, model=alias)
        if self.handoff_next:
            msgs = body.get("messages") or []
            sysm = [m for m in msgs if m.get("role") == "system"][:1]
            turns = [{"role": m["role"], "content": _text(m)} for m in msgs if m.get("role") in ("user", "assistant")]
            problem = turns[-1]["content"] if turns else ""
            h = E.handoff(turns, problem)
            body["messages"] = sysm + [{"role": "user", "content": json.dumps(h)}]
            body.pop("tools", None); body.pop("tool_choice", None)
            self.handoff_next = False
        return url, body

def make_handler(esc, log=sys.stderr):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _fwd(self, method):
            esc.check_accept()
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else None
            url, alias = esc.upstream()
            body = None
            if raw and self.path.endswith("/chat/completions"):
                url, body = esc.rewrite(json.loads(raw)); raw = json.dumps(body).encode()
            target = url.rsplit("/v1", 1)[0] + self.path
            req = urllib.request.Request(target, data=raw, method=method, headers={"Content-Type": "application/json"})
            try: r = urllib.request.urlopen(req, timeout=3600)
            except Exception as e:
                # Upstream failed. Try to escalate/fallback.
                note = esc.after_reply(ok=False)
                if note:
                    # A swap was triggered (e.g., back to light or next target).
                    # Update URL to the new target and retry.
                    url, alias = esc.upstream()
                    target = url.rsplit("/v1", 1)[0] + self.path
                    req = urllib.request.Request(target, data=raw, method=method, headers={"Content-Type": "application/json"})
                    try:
                        r = urllib.request.urlopen(req, timeout=3600)
                        stream = body is not None and body.get("stream")
                        self.send_response(r.status)
                        for k, v in r.headers.items():
                            if k.lower() not in ("content-length", "transfer-encoding", "connection"): self.send_header(k, v)
                        self.end_headers()
                        if body is None:
                            self.wfile.write(r.read()); return
                        text, data = [], b""
                        if stream:
                            for line in r:
                                if line.strip() == b"data: [DONE]": break
                                self.wfile.write(line); self.wfile.flush()
                                if line.startswith(b"data: "):
                                    try: text.append(json.loads(line[6:])["choices"][0]["delta"].get("content") or "")
                                    except Exception: pass
                        else:
                            j = json.load(r); m = j["choices"][0]["message"]; text.append(m.get("content") or "")
                        esc.sig.observe_reply("".join(text))
                        # If we swapped back, we might want to print a note here too, but the initial note is enough.
                        if stream:
                            if note:
                                ch = {"choices": [{"index": 0, "delta": {"content": "\n\n" + note}, "finish_reason": None}]}
                                self.wfile.write(b"data: " + json.dumps(ch).encode() + b"\n\n")
                            self.wfile.write(b"data: [DONE]\n\n")
                        else:
                            if note: m["content"] = (m.get("content") or "") + "\n\n" + note
                            self.wfile.write(json.dumps(j).encode())
                        return
                    except Exception as e2:
                        # Retry also failed.
                        self.send_response(502); self.end_headers(); self.wfile.write(str(e2).encode())
                        if body is not None: esc.sig.failures += 1
                        return
                # No swap possible (e.g., all targets down or manual suggest).
                self.send_response(502); self.end_headers(); self.wfile.write(str(e).encode())
                if body is not None: esc.sig.failures += 1
                return
            stream = body is not None and body.get("stream")
            self.send_response(r.status)
            for k, v in r.headers.items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection"): self.send_header(k, v)
            self.end_headers()
            if body is None:
                self.wfile.write(r.read()); return
            text, data = [], b""
            if stream:
                for line in r:
                    if line.strip() == b"data: [DONE]": break
                    self.wfile.write(line); self.wfile.flush()
                    if line.startswith(b"data: "):
                        try: text.append(json.loads(line[6:])["choices"][0]["delta"].get("content") or "")
                        except Exception: pass
            else:
                j = json.load(r); m = j["choices"][0]["message"]; text.append(m.get("content") or "")
            esc.sig.observe_reply("".join(text))
            note = esc.after_reply(ok=True)
            if note: print(note, file=log, flush=True)
            if stream:
                if note:
                    ch = {"choices": [{"index": 0, "delta": {"content": "\n\n" + note}, "finish_reason": None}]}
                    self.wfile.write(b"data: " + json.dumps(ch).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                if note: m["content"] = (m.get("content") or "") + "\n\n" + note
                self.wfile.write(json.dumps(j).encode())
        def do_POST(self): self._fwd("POST")
        def do_GET(self): self._fwd("GET")
    return H

def serve(esc, port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(esc))  # localhost only
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
