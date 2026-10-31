"""Race Reviewer: routing race/hang regression tests (#199 routing priority).

Defensive tests only. Upstreams are in-process mock HTTP servers; no models, no
live llama-server, no nexus hosts. Rows map to Routing Test Designer's plan:
  R1 concurrent calls / slots / oversubscribe   R2 route-vs-health TOCTOU
  R3 reconnect mid-tool-call (#149)             R4 timeout + cancel propagation
  R5 mailbox ordering / reply matching
xfail(strict=True) marks a missing guard; see /workspace/reviews/race-routing.md.
"""
import json, os, socket, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "scripts"), os.path.join(HERE, "..", "scripts", "dogfood")]
import escalation_proxy as EP  # noqa: E402
import reconnect_selfheal as RS  # noqa: E402

RESIDENT, SPRINT = 4, 6  # nexus thread locks; never lower


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("FAMILIA_API_KEY", "test-instance-key")
    monkeypatch.setattr(EP, "STATE", str(tmp_path))
    monkeypatch.setattr(EP, "PENDING", str(tmp_path / "pending.json"))
    monkeypatch.setattr(EP, "ACCEPT", str(tmp_path / "accept.json"))


class Upstream:
    """Mock llama-server. Tracks receipts, in-flight max, and client disconnects."""
    def __init__(self, name, delay=0.0, drop=False, echo=False):
        self.name, self.delay, self.drop, self.echo = name, delay, drop, echo
        self.seen, self.inflight, self.max_inflight = [], 0, 0
        self.mu = threading.Lock()
        up = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with up.mu:
                    up.seen.append(b); up.inflight += 1
                    up.max_inflight = max(up.max_inflight, up.inflight)
                try:
                    if up.delay: time.sleep(up.delay)
                    if up.drop:  # processed, then connection lost before reply
                        self.connection.shutdown(socket.SHUT_RDWR); return
                    last = (b.get("messages") or [{}])[-1].get("content", "")
                    out = json.dumps({"choices": [{"message": {"role": "assistant",
                          "content": (last if up.echo else up.name)}}]}).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.end_headers(); self.wfile.write(out)
                finally:
                    with up.mu: up.inflight -= 1
        # Fake upstream must not be the bottleneck: default backlog 5 overflows on
        # FreeBSD under the 64-burst and the proxy then 502s (R7, not R6).
        srv_cls = type("_UpSrv", (ThreadingHTTPServer,), {"request_queue_size": 128})
        self.srv = srv_cls(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self): self.srv.shutdown(); self.srv.server_close()


def closed_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def graph(pl, ph):
    return {"hosts": {"h": {}}, "aliases": {"light-a": {"node": "light"}, "heavy-a": {"node": "heavy"}},
            "nodes": {"light": {"host": "h", "port": pl, "model": "m", "escalates_to": ["heavy"],
                                "escalation": {"mode": "off"}},
                      "heavy": {"host": "h", "port": ph, "model": "m2"}}}


def proxy(g, current="light", ensure=None):
    esc = EP.Escalator(g, "light", {}, "h", ensure=ensure, consent={}, reachable=None)
    esc.current = current
    return esc, EP.serve(esc)


def post(port, content="hi", session=None, timeout=10):
    h = {"Content-Type": "application/json"}
    if session: h[EP.SESSION_HEADER] = session
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", headers=h,
        data=json.dumps({"model": "x", "messages": [{"role": "user", "content": content}]}).encode())
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# ---------------- R1 concurrent calls / slots / oversubscribe ----------------

def test_r1_same_session_concurrent_calls_never_share_slot():
    up = Upstream("light", delay=0.15)
    _, srv = proxy(graph(up.port, closed_port()))
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda i: post(srv.server_address[1], f"c{i}"), range(6)))
    assert all(s == 200 for s, _ in res) and up.max_inflight == 1 and len(up.seen) == 6
    srv.shutdown(); up.close()


def test_r1_pool_no_double_assignment_of_session():
    made = []
    pool = EP.EscalatorPool(lambda: made.append(object()) or type("E", (), {})())
    barrier = threading.Barrier(16)
    def grab(_): barrier.wait(); return pool.get("s1")
    with ThreadPoolExecutor(16) as ex: got = list(ex.map(grab, range(16)))
    assert len(made) == 1 and all(g is got[0] for g in got)


@pytest.mark.xfail(strict=True, reason="R1: proxy has no admission cap; distinct sessions all "
                   "hit upstream at once (escalation_proxy.py:325 ThreadingHTTPServer, no semaphore)")
def test_r1_distinct_sessions_refuse_oversubscribe_beyond_sprint():
    up = Upstream("light", delay=0.4)
    _, srv = proxy(graph(up.port, closed_port()))
    with ThreadPoolExecutor(SPRINT + 3) as ex:
        list(ex.map(lambda i: post(srv.server_address[1], session=f"s{i}"), range(SPRINT + 3)))
    srv.shutdown(); up.close()
    assert up.max_inflight <= SPRINT


def test_r1_wait_budget_refuses_oversubscribe(monkeypatch):
    import dispatch
    monkeypatch.setattr(dispatch, "threads_in_use", lambda: RESIDENT)
    monkeypatch.setattr(dispatch.time, "sleep", lambda s: None)
    assert dispatch.wait_budget(2, SPRINT, max_wait=0) is True      # 4+2 == 6 ok
    assert dispatch.wait_budget(3, SPRINT, max_wait=-1) is False    # 7 > 6 refused


def test_r1_threads_in_use_counts_comma_threads():
    from bench_guard import threads_in_use
    ps = "llama-server -t 4 --port 1\n/usr/bin/llama-cli --threads 2,6\npython x -t 9\n"
    assert threads_in_use(ps) == 10


# ---------------- R2 routing decision TOCTOU vs health/spawn ----------------

def test_r2_backend_dies_after_route_chosen_clean_fallback_no_stale_port():
    light, heavy = Upstream("light"), Upstream("heavy")
    g = graph(light.port, heavy.port)
    esc, srv = proxy(g, current="heavy", ensure=lambda n: True)
    heavy.close()                                     # dies between "healthy" and dispatch
    s, body = post(srv.server_address[1])
    assert s == 200 and body.startswith("light")      # retried on light, clean
    assert esc.current == "light"
    n_heavy = len(heavy.seen)
    post(srv.server_address[1])
    assert len(heavy.seen) == n_heavy                  # never re-dialed the dead port
    srv.shutdown(); light.close()


@pytest.mark.xfail(strict=True, reason="R2: _retry_once resends raw body rewritten for the FAILED "
                   "node (model alias of heavy, handoff msgs) to light (escalation_proxy.py:262)")
def test_r2_fallback_retry_uses_fallback_node_alias():
    light = Upstream("light")
    esc, srv = proxy(graph(light.port, closed_port()), current="heavy")
    post(srv.server_address[1])
    srv.shutdown(); light.close()
    assert light.seen and light.seen[-1]["model"] == "light-a"


@pytest.mark.xfail(strict=True, reason="R2: ensure()/health only at swap time "
                   "(escalation_proxy.py:150); dispatch at :284-298 does not re-check")
def test_r2_health_rechecked_at_dispatch_after_swap():
    light, heavy = Upstream("light"), Upstream("heavy")
    calls = []
    esc, srv = proxy(graph(light.port, heavy.port), ensure=lambda n: calls.append(n) or True)
    esc.swap({"target": "heavy", "host": "h"})
    post(srv.server_address[1])
    srv.shutdown(); light.close(); heavy.close()
    assert len(calls) >= 2


# ---------------- R3 reconnect mid-tool-call (#149) ----------------

@pytest.mark.xfail(strict=True, reason="R3: upstream processed then dropped; fallback retry "
                   "re-executes the same turn on light — no request-id/idempotency (:303/:259)")
def test_r3_drop_mid_call_no_duplicate_execution():
    light, heavy = Upstream("light"), Upstream("heavy", drop=True)
    _, srv = proxy(graph(light.port, heavy.port), current="heavy")
    post(srv.server_address[1], "tool result: ok")
    srv.shutdown(); light.close(); heavy.close()
    assert len(light.seen) + len(heavy.seen) == 1


def test_r3_drop_on_light_is_clean_error_not_hang():
    light = Upstream("light", drop=True)
    _, srv = proxy(graph(light.port, closed_port()))
    t0 = time.time(); s, _ = post(srv.server_address[1], timeout=10)
    assert s == 502 and time.time() - t0 < 5 and len(light.seen) == 1  # no retry loop
    s2, _ = post(srv.server_address[1], timeout=10)                     # lock released
    assert s2 == 502
    srv.shutdown(); light.close()


def test_r3_reconnect_backoff_bounded():
    sched = [RS.backoff_seconds(i) for i in range(1, 40)]
    assert sched[0] == 30 and max(sched) == 900 and sched == sorted(sched)
    for i in range(1, 40):
        assert 0 < RS.backoff_with_jitter(i, jitter=0.5) <= 900


# ---------------- R4 timeout + cancel propagation ----------------

@pytest.mark.xfail(strict=True, reason="R4: caller cancel is not propagated; session lock held "
                   "for the whole upstream call (timeout=3600, escalation_proxy.py:280/:298)")
def test_r4_caller_cancel_frees_session_slot():
    up = Upstream("light", delay=2.0)
    _, srv = proxy(graph(up.port, closed_port()))
    p = srv.server_address[1]
    with pytest.raises(Exception): post(p, timeout=0.3)   # caller gives up
    up.delay = 0
    t0 = time.time(); post(p, timeout=10)
    srv.shutdown(); up.close()
    assert time.time() - t0 < 1.0


def test_r4_upstream_error_releases_lock_no_orphan_inflight():
    up = Upstream("light")
    esc, srv = proxy(graph(closed_port(), closed_port()))
    assert post(srv.server_address[1])[0] == 502
    assert esc.lock.acquire(timeout=1); esc.lock.release()
    srv.shutdown(); up.close()


def test_r4_proxy_timeout_is_finite_and_bounded():
    src = open(EP.__file__).read()
    # Guard against someone dropping the timeout entirely (hang forever).
    assert src.count("urlopen(req, timeout=") == 2


# ---------------- R5 mailbox ordering / reply matching ----------------

def test_r5_replies_matched_to_requests_under_concurrency():
    up = Upstream("light", delay=0.05, echo=True)
    _, srv = proxy(graph(up.port, closed_port()))
    ids = [f"req-{i}" for i in range(12)]
    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda r: post(srv.server_address[1], r, session=r.split("-")[1]), ids))
    assert [b for _, b in res] == ids
    srv.shutdown(); up.close()


class _OrderedGrantLock:
    """Test stand-in for the per-session lock (escalation_proxy.py:106/:280).

    threading.RLock documents no FIFO guarantee for waiters; this lock models that
    deterministically. The first acquirer holds it; its release() waits until
    ``expect - 1`` waiters are queued, then grants them in ``policy`` order
    ("lifo" = legal-but-unfair non-arrival order, "fifo" = arrival order).
    Reentrant like RLock. No sleeps decide the outcome; waits are bounded only as
    a hang guard.
    """
    def __init__(self, expect, policy):
        self.expect, self.policy = expect, policy
        self.cond = threading.Condition(threading.Lock())
        self.owner, self.depth, self.waiters, self.arrivals, self.next = None, 0, [], 0, None

    def acquire(self, blocking=True, timeout=-1):
        me = threading.get_ident()
        with self.cond:
            self.arrivals += 1
            if self.owner == me:
                self.depth += 1; return True
            if self.owner is None and not self.waiters and self.next is None:
                self.owner, self.depth = me, 1; return True
            self.waiters.append(me); self.cond.notify_all()
            assert self.cond.wait_for(lambda: self.next == me, timeout=20), "grant hang"
            self.next, self.owner, self.depth = None, me, 1
            return True

    def release(self):
        with self.cond:
            self.depth -= 1
            if self.depth: return
            self.cond.wait_for(lambda: len(self.waiters) >= self.expect - 1 or self.expect <= 1, timeout=20)
            self.expect = 0  # only gate the first hand-off
            self.owner = None
            if self.waiters:
                self.next = self.waiters.pop() if self.policy == "lifo" else self.waiters.pop(0)
            self.cond.notify_all()

    __enter__ = acquire
    def __exit__(self, *a): self.release()


def _ordered_arrivals(monkeypatch, policy, n=6):
    """Send n numbered requests on ONE session, each only after the previous one has
    reached the session lock (so submission order == lock arrival order, no timing
    luck). Returns the order in which the upstream received them."""
    locks = []
    orig = EP.Escalator.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.lock = _OrderedGrantLock(n, policy); locks.append(self.lock)
    monkeypatch.setattr(EP.Escalator, "__init__", init)
    up = Upstream("light", delay=0.0, echo=True)
    _, srv = proxy(graph(up.port, closed_port()))
    port = srv.server_address[1]
    ts = []
    for i in range(n):
        t = threading.Thread(target=post, args=(port, f"S:{i:03d}", "S", 30)); t.start(); ts.append(t)
        lk = next((l for l in locks if l.arrivals), None)
        deadline = time.time() + 20
        while (lk is None or lk.arrivals < i + 1) and time.time() < deadline:
            time.sleep(0.002); lk = next((l for l in locks if l.arrivals), None)
        assert lk is not None and lk.arrivals >= i + 1, "request never reached the session lock"
    for t in ts: t.join()
    srv.shutdown(); up.close()
    got = [int(b["messages"][-1]["content"].split(":")[1]) for b in up.seen]
    assert sorted(got) == list(range(n)), f"lost requests: {got}"
    return got


def test_r5_guard_order_follows_lock_grant_order(monkeypatch):
    """Deterministic guard: with a FIFO-granting lock the proxy forwards in arrival
    order, so the harness itself introduces no reordering."""
    assert _ordered_arrivals(monkeypatch, "fifo") == list(range(6))


@pytest.mark.xfail(strict=True, reason="R5: per-session order is only whatever order the session "
                   "lock grants (escalation_proxy.py:106/:280); RLock has no FIFO guarantee and the "
                   "proxy has no sequence number of its own")
def test_r5_per_sender_fifo_preserved(monkeypatch):
    got = _ordered_arrivals(monkeypatch, "lifo")
    assert got == list(range(6)), f"out-of-order upstream arrivals for one session: {got}"


# ---------------- R6 accept-backlog burst ----------------

BURST = 64


def _burst(port, n):
    """n raw sockets connect+send at a barrier; returns list of (ok, detail)."""
    bar = threading.Barrier(n)
    out = [None] * n

    def one(i):
        body = json.dumps({"model": "x", "messages": [{"role": "user", "content": f"b{i}"}]}).encode()
        req = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
               f"{EP.SESSION_HEADER}: s{i}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body
        try:
            bar.wait()
            with socket.create_connection(("127.0.0.1", port), timeout=20) as s:
                s.sendall(req)
                data = b""
                while True:
                    c = s.recv(65536)
                    if not c: break
                    data += c
            head, _, rb = data.partition(b"\r\n\r\n")
            ok = head.startswith(b"HTTP/1.") and b" 200 " in head.split(b"\r\n")[0]
            out[i] = (ok and json.loads(rb)["choices"][0]["message"]["content"] == f"b{i}", head[:40])
        except Exception as e:  # ECONNRESET / ECONNREFUSED land here
            out[i] = (False, repr(e))

    ts = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in ts: t.start()
    for t in ts: t.join()
    return out


def test_r6_burst_connections_all_answered():
    """Behavioural half: on Linux the kernel rounds tiny backlogs up / SYN-retries, so this
    usually passes here; on angel (FreeBSD) backlog 5 gave ECONNRESET. Kept strict (no xfail)."""
    up = Upstream("light", delay=0.01, echo=True)
    _, srv = proxy(graph(up.port, closed_port()))
    try:
        res = _burst(srv.server_address[1], BURST)
    finally:
        srv.shutdown(); up.close()
    bad = [(i, d) for i, (ok, d) in enumerate(res) if not ok]
    assert not bad, f"{len(bad)}/{BURST} burst connections failed: {bad[:5]}"


@pytest.mark.xfail(strict=True, reason="R6: ThreadingHTTPServer default request_queue_size=5 "
                   "(escalation_proxy.py:325); FreeBSD resets a 12+ burst. Harden to >=128")
def test_r6_listen_backlog_covers_burst():
    up = Upstream("light")
    _, srv = proxy(graph(up.port, closed_port()))
    q = srv.request_queue_size
    srv.shutdown(); up.close()
    assert q >= BURST, f"listen backlog {q} < burst {BURST}"
