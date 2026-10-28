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

Thread safety (#101): ThreadingHTTPServer runs one handler per request. Each
Escalator holds an RLock covering its request path so concurrent requests on the
same session cannot corrupt current/pending/handoff_next/signals. Distinct
clients are isolated when they send X-Familia-Session (preferred) or a Bearer
token; requests with neither share the "default" session (serialized by that
session's lock). True multi-session isolation needs one of those headers —
hermes does not send a session id today.
"""
import json, os, re, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import escalation as E
import familia_auth  # noqa: E402

STATE = os.path.join(E.ROOT, ".cache", "familia")
PENDING = os.path.join(STATE, "escalation-pending.json")
ACCEPT = os.path.join(STATE, "escalation-accept.json")
FAIL_RE = re.compile(r"(error|traceback|failed|exception|exit code [1-9]|FAILED)", re.I)
DEFAULT_SESSION = "default"
SESSION_HEADER = "X-Familia-Session"

def node_url(g, name, local_host):
    """Base URL for a node. Remote nodes need a non-loopback bind (else None: needs a tunnel)."""
    n = g["nodes"][name]
    if n["host"] == local_host: return f"http://127.0.0.1:{n['port']}/v1"
    addr = (g["hosts"].get(n["host"]) or {}).get("addr")
    if n.get("bind", "127.0.0.1").startswith("127.") or not addr: return None
    return f"http://{addr}:{n['port']}/v1"

def alias_for(g, name):
    return next((a for a, x in (g.get("aliases") or {}).items() if x["node"] == name), name)

def session_id_from(headers):
    """Stable session key for per-client Escalator isolation (#101)."""
    s = (headers.get(SESSION_HEADER) or "").strip()
    if s:
        return s
    auth = (headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok:
            return "bearer:" + tok
    return DEFAULT_SESSION

def _pending_path(session_id):
    if not session_id or session_id == DEFAULT_SESSION:
        return PENDING
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", session_id)[:80]
    return os.path.join(STATE, f"escalation-pending-{safe}.json")

class Signals:
    def __init__(self): self.reset()
    def reset(self):
        # failures = tool-result failures (recomputed each request).
        # transport_failures = upstream/HTTP errors (persist across observe_request).
        self.outputs, self.failures, self.transport_failures = [], 0, 0
        self.user_messages, self.t0 = [], time.time()
    def observe_request(self, body):
        msgs = body.get("messages") or []
        users = [m for m in msgs if m.get("role") == "user"]
        if users: self.user_messages = [_text(users[-1])]
        # count failed tool results since the last user turn (does not clear transport_failures)
        last_u = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)
        self.failures = sum(1 for m in msgs[last_u + 1:] if m.get("role") == "tool" and FAIL_RE.search(_text(m)))
    def observe_reply(self, text):
        if text: self.outputs.append(text); self.outputs = self.outputs[-10:]
    def dict(self):
        return {"outputs": self.outputs,
                "failures": self.failures + self.transport_failures,
                "user_messages": self.user_messages,
                "elapsed_s": round(time.time() - self.t0)}

def _text(m):
    c = m.get("content")
    if isinstance(c, list): return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""

class Escalator:
    """State machine: light node <-> target. Pure logic; HTTP lives in Proxy.

    ``lock`` (RLock) must be held for the whole request path that mutates this
    instance (rewrite / observe / after_reply / swap). Concurrent clients on the
    same session serialize; different sessions use different Escalators (#101).
    """
    def __init__(self, g, light, recs, local_host, ensure=None, consent=None, swap_back=True, reachable=None,
                 session_id=DEFAULT_SESSION):
        self.g, self.light, self.recs, self.local_host = g, light, recs, local_host
        self.ensure = ensure or (lambda name: True)
        self.consent, self.swap_back, self.reachable = consent, swap_back, reachable
        self.current, self.pending, self.handoff_next, self.sig = light, None, False, Signals()
        self.auto_env = os.environ.get("FAMILIA_ESCALATE") == "auto"
        self.session_id = session_id or DEFAULT_SESSION
        self.lock = threading.RLock()

    def upstream(self):
        return node_url(self.g, self.current, self.local_host), alias_for(self.g, self.current)

    def after_reply(self, ok):
        """Returns a user-visible note or None."""
        if self.current != self.light:
            if not ok:
                # Heavy (or non-light) upstream failed: fall back so we do not stick forever (#98).
                failed = self.current
                self.current, self.handoff_next = self.light, False
                self.sig.reset()
                return f"[familia] {failed} failed; back on {self.light}"
            if ok and self.swap_back:
                self.current = self.light; self.sig.reset(); return f"[familia] escalation done; back on {self.light}"
            return None
        d = E.decide(self.g, self.light, self.sig.dict(), self.recs,
                     E.load_consent() if self.consent is None else self.consent, self.reachable)
        if d["decision"] == "none": return None
        if d["decision"] == "auto" or (self.auto_env and not d["needs_consent"]) or self._accepted(d):
            return self.swap(d)
        self.pending = d
        path = _pending_path(self.session_id)
        os.makedirs(STATE, exist_ok=True); json.dump(d, open(path, "w"), indent=2)
        return f"[familia] {d['prompt']} Accept: python3 scripts/escalate.py accept"

    def _accepted(self, d):
        try: a = json.load(open(ACCEPT))
        except Exception: return False
        # Optional session key on accept file; absent means default session only.
        if a.get("session", DEFAULT_SESSION) != self.session_id: return False
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
        try: os.remove(_pending_path(self.session_id))
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
            # #106: keep tools / tool_choice so the heavy model can finish tool-using
            # turns (hermes agent sessions). Swap-back still follows the first
            # successful heavy reply (after_reply).
            self.handoff_next = False
        return url, body

class EscalatorPool:
    """Per-session Escalator map. Factory builds a fresh Escalator for a new session id."""
    def __init__(self, factory, seed=None):
        self._factory = factory
        self._lock = threading.Lock()
        self._by = {}
        if seed is not None:
            sid, esc = seed
            esc.session_id = sid
            if not hasattr(esc, "lock") or esc.lock is None:
                esc.lock = threading.RLock()
            self._by[sid] = esc

    def get(self, session_id):
        sid = session_id or DEFAULT_SESSION
        with self._lock:
            e = self._by.get(sid)
            if e is None:
                e = self._factory()
                e.session_id = sid
                self._by[sid] = e
            return e

def make_handler(pool, log=sys.stderr):
    """``pool`` is an EscalatorPool (or any object with get(session_id) -> Escalator)."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _esc(self):
            return pool.get(session_id_from(self.headers))

        def _copy_headers(self, r):
            for k, v in r.headers.items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(k, v)

        def _record_transport_fail(self, esc, body):
            if body is not None:
                esc.sig.transport_failures += 1

        def _502(self, msg):
            self.send_response(502); self.end_headers(); self.wfile.write(str(msg).encode())

        def _write_chat(self, esc, r, body, note, method, raw):
            """Relay a successful chat/completions upstream response; run after_reply(ok=True)."""
            stream = body is not None and body.get("stream")
            if body is None:
                self.send_response(r.status); self._copy_headers(r); self.end_headers()
                self.wfile.write(r.read()); return
            text = []
            if stream:
                self.send_response(r.status); self._copy_headers(r); self.end_headers()
                for line in r:
                    if line.strip() == b"data: [DONE]": break
                    self.wfile.write(line); self.wfile.flush()
                    if line.startswith(b"data: "):
                        try: text.append(json.loads(line[6:])["choices"][0]["delta"].get("content") or "")
                        except Exception: pass
                esc.sig.observe_reply("".join(text))
                esc.sig.transport_failures = 0
                done = esc.after_reply(ok=True)
                if done: print(done, file=log, flush=True); note = note or done
                if note:
                    ch = {"choices": [{"index": 0, "delta": {"content": "\n\n" + note}, "finish_reason": None}]}
                    self.wfile.write(b"data: " + json.dumps(ch).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                return
            # Non-stream: parse BEFORE sending headers (#99).
            try:
                j = json.load(r); m = j["choices"][0]["message"]; text.append(m.get("content") or "")
            except Exception as e:
                self._record_transport_fail(esc, body)
                fb = esc.after_reply(ok=False)
                if fb and self._retry_once(esc, body, method, raw, fb):
                    return
                self._502(f"upstream returned invalid JSON: {e}")
                return
            esc.sig.observe_reply("".join(text))
            esc.sig.transport_failures = 0
            done = esc.after_reply(ok=True)
            if done: print(done, file=log, flush=True); note = note or done
            self.send_response(r.status); self._copy_headers(r); self.end_headers()
            if note: m["content"] = (m.get("content") or "") + "\n\n" + note
            self.wfile.write(json.dumps(j).encode())

        def _retry_once(self, esc, body, method, raw, note):
            url, _alias = esc.upstream()
            target = url.rsplit("/v1", 1)[0] + self.path
            req = urllib.request.Request(target, data=raw, method=method, headers=familia_auth.auth_headers({"Content-Type": "application/json"}, incoming=self.headers))
            try:
                r = urllib.request.urlopen(req, timeout=3600)
            except Exception as e2:
                # Retry failed too. Fall back again so heavy does not stick (#98); do not recurse.
                self._record_transport_fail(esc, body)
                note2 = esc.after_reply(ok=False)
                msg = str(e2)
                if note2: msg = f"{msg}\n{note2}"
                self._502(msg)
                return True
            self._write_chat(esc, r, body, note, method, raw)
            return True

        def _fwd(self, method):
            esc = self._esc()
            # Hold the session lock for the whole request so concurrent clients on
            # the same session cannot interleave rewrite / after_reply / swap (#101).
            with esc.lock:
                esc.check_accept()
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else None
                url, alias = esc.upstream()
                body = None
                if raw and self.path.endswith("/chat/completions"):
                    url, body = esc.rewrite(json.loads(raw)); raw = json.dumps(body).encode()
                target = url.rsplit("/v1", 1)[0] + self.path
                req = urllib.request.Request(target, data=raw, method=method, headers=familia_auth.auth_headers({"Content-Type": "application/json"}, incoming=self.headers))
                try:
                    r = urllib.request.urlopen(req, timeout=3600)
                except Exception as e:
                    # Count transport error BEFORE decide (#100), then escalate/fallback (#98).
                    self._record_transport_fail(esc, body)
                    note = esc.after_reply(ok=False)
                    if note and self._retry_once(esc, body, method, raw, note):
                        return
                    self._502(e)
                    return
                self._write_chat(esc, r, body, None, method, raw)

        def do_POST(self): self._fwd("POST")
        def do_GET(self): self._fwd("GET")
    return H

def serve(esc, port=0):
    """Serve ``esc`` as the default session; other X-Familia-Session values get clones."""
    if not hasattr(esc, "lock") or esc.lock is None:
        esc.lock = threading.RLock()
    esc.session_id = getattr(esc, "session_id", None) or DEFAULT_SESSION

    def factory():
        return Escalator(esc.g, esc.light, esc.recs, esc.local_host,
                         ensure=esc.ensure, consent=esc.consent,
                         swap_back=esc.swap_back, reachable=esc.reachable)

    pool = EscalatorPool(factory, seed=(DEFAULT_SESSION, esc))
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(pool))  # localhost only
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
