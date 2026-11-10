"""Race Reviewer: routing race/hang regression tests (#199 routing priority).

Defensive tests only. Upstreams are in-process mock HTTP servers; no models, no
live llama-server, no nexus hosts. Rows map to Routing Test Designer's plan:
  R1 concurrent calls / slots / oversubscribe   R2 route-vs-health TOCTOU
  R3 reconnect mid-tool-call (#149)             R4 timeout + cancel propagation
  R5 mailbox ordering / reply matching
xfail(strict=True) marks a missing guard; see /workspace/reviews/race-routing.md.
"""
import json, os, signal, socket, sys, threading, time, urllib.error, urllib.request
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
    def __init__(self, name, delay=0.0, drop=False, echo=False, gate=None):
        self.name, self.delay, self.drop, self.echo, self.gate = name, delay, drop, echo, gate
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
                    if up.gate is not None: up.gate.wait(10)   # hang until released
                    if up.delay: time.sleep(up.delay)
                    if up.drop:  # processed, then connection lost before reply
                        self.connection.shutdown(socket.SHUT_RDWR); return
                    last = (b.get("messages") or [{}])[-1].get("content", "")
                    out = json.dumps({"choices": [{"message": {"role": "assistant",
                          "content": (last if up.echo else up.name)}}]}).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.end_headers(); self.wfile.write(out)
                except (BrokenPipeError, ConnectionResetError):
                    pass   # caller (the proxy) already gave up, e.g. after its timeout
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


def test_r1_distinct_sessions_refuse_oversubscribe_beyond_sprint():
    up = Upstream("light", delay=0.4)
    _, srv = proxy(graph(up.port, closed_port()))
    with ThreadPoolExecutor(SPRINT + 3) as ex:
        list(ex.map(lambda i: post(srv.server_address[1], session=f"s{i}"), range(SPRINT + 3)))
    srv.shutdown(); up.close()
    assert up.max_inflight <= SPRINT


def test_r1_wait_budget_refuses_oversubscribe(monkeypatch, tmp_path):
    import dispatch
    monkeypatch.setenv("FAMILIA_BUDGET_DIR", str(tmp_path))
    monkeypatch.setattr(dispatch, "threads_in_use", lambda: RESIDENT)
    monkeypatch.setattr(dispatch.time, "sleep", lambda s: None)
    assert dispatch.wait_budget(2, SPRINT, max_wait=0) is True      # 4+2 == 6 ok
    assert dispatch.wait_budget(3, SPRINT, max_wait=-1) is False    # 7 > 6 refused


def _reserve_child(d, q, start, hold):
    import dispatch
    os.setpgid(0, 0)   # own process group, so the parent's finally can killpg the whole group
    os.environ["FAMILIA_BUDGET_DIR"] = d
    dispatch.threads_in_use = lambda: RESIDENT
    start.wait(20)   # all dispatchers race at once
    q.put(dispatch.reserve_budget(2, SPRINT, max_wait=-1))
    hold.wait(20)    # keep the reservation (pid alive) until the parent has every answer


def test_r1_reserve_budget_atomic_across_processes(tmp_path):
    """#244: N dispatchers racing for the last 2 threads -> exactly one wins (was: all).
    Barrier start + Event hold: the winner's pid stays alive until every sibling has answered,
    so a slow sibling can never see the winner as a dead owner and reclaim (no sleep)."""
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    n = 6
    q, start, hold = ctx.Queue(), ctx.Barrier(n), ctx.Event()
    ps = [ctx.Process(target=_reserve_child, args=(str(tmp_path), q, start, hold)) for _ in range(n)]
    [p.start() for p in ps]
    try:
        got = [q.get(timeout=20) for _ in ps]
    finally:
        hold.set()
        [p.join(20) for p in ps]
        for p in ps:   # on failure/timeout: kill each child's whole process group, not just it
            if p.is_alive() and p.pid:
                try: os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError): p.kill()
                p.join(5)
    assert got.count(True) == 1, got


def test_r1_reservation_released_and_dead_owner_reclaimed(monkeypatch, tmp_path):
    import dispatch
    monkeypatch.setenv("FAMILIA_BUDGET_DIR", str(tmp_path))
    monkeypatch.setattr(dispatch, "threads_in_use", lambda: RESIDENT)
    assert dispatch.reserve_budget(2, SPRINT, max_wait=-1) is True
    assert dispatch.reserve_budget(1, SPRINT, max_wait=-1) is False   # 4+2+1 > 6
    dispatch.release_budget(2)
    assert dispatch.reserve_budget(2, SPRINT, max_wait=-1) is True
    dispatch.release_budget(2)
    # a crashed dispatcher's reservation must not leak budget forever
    import subprocess
    dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
    (tmp_path / "thread-budget.json").write_text(json.dumps({str(dead.pid): 2}))
    assert dispatch.reserve_budget(2, SPRINT, max_wait=-1) is True
    assert oct(os.stat(tmp_path / "thread-budget.lock").st_mode & 0o777) == "0o600"


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


def test_r2_fallback_retry_uses_fallback_node_alias():
    light = Upstream("light")
    esc, srv = proxy(graph(light.port, closed_port()), current="heavy")
    post(srv.server_address[1])
    srv.shutdown(); light.close()
    assert light.seen and light.seen[-1]["model"] == "light-a"


def test_r2_health_rechecked_at_dispatch_after_swap():
    light, heavy = Upstream("light"), Upstream("heavy")
    calls = []
    esc, srv = proxy(graph(light.port, heavy.port), ensure=lambda n: calls.append(n) or True)
    esc.swap({"target": "heavy", "host": "h"})
    post(srv.server_address[1])
    srv.shutdown(); light.close(); heavy.close()
    assert len(calls) >= 2


def test_r2_retry_health_checks_fallback_before_redial():
    light = Upstream("light")
    calls = []
    def ensure(n):
        calls.append(n); return n != "light"          # fallback node fails its health check
    esc, srv = proxy(graph(light.port, closed_port()), current="heavy", ensure=ensure)
    s, _ = post(srv.server_address[1])
    srv.shutdown(); light.close()
    assert "light" in calls                            # checked before the retry
    assert s == 502 and not light.seen                 # not dialed blind


def test_r2_retry_resends_original_body_not_handoff():
    light = Upstream("light")
    esc, srv = proxy(graph(light.port, closed_port()), current="heavy")
    esc.handoff_next = True                            # heavy body would be handoff-compacted
    post(srv.server_address[1], "original question")
    srv.shutdown(); light.close()
    msgs = light.seen[-1]["messages"]
    assert light.seen[-1]["model"] == "light-a"
    assert any("original question" == m.get("content") for m in msgs)


# ---------------- R3 reconnect mid-tool-call (#149) ----------------

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


def test_r4_proxy_timeout_is_finite_and_bounded(monkeypatch):
    """Behavioural: a hung upstream (accepts, never answers) is cut off by the proxy's
    upstream timeout, answered 502 in bounded time, and the session lock is released."""
    monkeypatch.setattr(EP, "UPSTREAM_TIMEOUT_S", 0.5)
    gate = threading.Event()
    up = Upstream("light", gate=gate)
    esc, srv = proxy(graph(up.port, closed_port()))
    try:
        t0 = time.monotonic(); s, _ = post(srv.server_address[1], timeout=10)
        assert s == 502 and time.monotonic() - t0 < 3, (s, time.monotonic() - t0)
        assert len(up.seen) == 1                      # one attempt, no retry of a sent request
        assert esc.lock.acquire(timeout=1); esc.lock.release()
        gate.set()                                    # upstream healthy again: served
        assert post(srv.server_address[1], timeout=10) == (200, "light")
    finally:
        gate.set(); srv.shutdown(); up.close()


def test_r4_retry_path_timeout_is_finite_and_bounded(monkeypatch):
    """The fallback retry (_retry_once) has its own bounded upstream timeout too."""
    monkeypatch.setattr(EP, "UPSTREAM_TIMEOUT_S", 0.5)
    gate = threading.Event()
    light = Upstream("light", gate=gate)
    esc, srv = proxy(graph(light.port, closed_port()), current="heavy")   # heavy refused -> retry
    try:
        t0 = time.monotonic(); s, _ = post(srv.server_address[1], timeout=10)
        assert s == 502 and time.monotonic() - t0 < 3, (s, time.monotonic() - t0)
        assert len(light.seen) == 1 and esc.current == "light"
        assert esc.lock.acquire(timeout=1); esc.lock.release()
    finally:
        gate.set(); srv.shutdown(); light.close()


# ---------------- R5 mailbox ordering / reply matching ----------------

def test_r5_replies_matched_to_requests_under_concurrency():
    up = Upstream("light", delay=0.05, echo=True)
    _, srv = proxy(graph(up.port, closed_port()))
    ids = [f"req-{i}" for i in range(12)]
    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda r: post(srv.server_address[1], r, session=r.split("-")[1]), ids))
    assert [b for _, b in res] == ids
    srv.shutdown(); up.close()


def _raw_post(s, content, session):
    """POST over an already-connected socket ``s``; returns the reply content."""
    body = json.dumps({"model": "x", "messages": [{"role": "user", "content": content}]}).encode()
    req = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
           f"{EP.SESSION_HEADER}: {session}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body
    with s:
        s.sendall(req)
        data = b""
        while True:
            c = s.recv(65536)
            if not c: break
            data += c
    return data


def _fifo_violations(senders=4, per=16, delay=0.03, stagger=0.01):
    """Per-session numbered requests; returns {session: arrival seq list} where out of order."""
    up = Upstream("light", delay=delay, echo=True)
    _, srv = proxy(graph(up.port, closed_port()))
    port = srv.server_address[1]
    start = threading.Barrier(senders)
    ts = []

    def sender(sid):
        start.wait()
        inner = []
        for n in range(per):  # submit in order; later ones queue behind the session lock
            # #248: connect on this thread so arrival (accept) order is the submit order.
            # A thread-per-request connect lets client scheduling reorder arrivals before
            # the proxy ever sees them, which is not a proxy bug.
            s = socket.create_connection(("127.0.0.1", port), timeout=30)
            t = threading.Thread(target=_raw_post, args=(s, f"{sid}:{n:03d}", sid)); t.start(); inner.append(t)
            time.sleep(stagger)
        for t in inner: t.join()

    for k in range(senders):
        t = threading.Thread(target=sender, args=(f"S{k}",)); t.start(); ts.append(t)
    for t in ts: t.join()
    srv.shutdown(); up.close()
    per_s = {}
    for b in up.seen:
        sid, n = b["messages"][-1]["content"].split(":")
        per_s.setdefault(sid, []).append(int(n))
    # Every request must have arrived; a short count means a transport error (see R6), not R5.
    assert sorted(len(v) for v in per_s.values()) == [per] * senders, f"lost requests: {per_s}"
    return {k: v for k, v in per_s.items() if v != sorted(v)}


def test_r5_per_sender_fifo_preserved():
    bad = _fifo_violations()
    assert not bad, f"out-of-order arrivals per session: {bad}"


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


def test_r6_listen_backlog_covers_burst():
    up = Upstream("light")
    _, srv = proxy(graph(up.port, closed_port()))
    q = srv.request_queue_size
    srv.shutdown(); up.close()
    assert q >= BURST, f"listen backlog {q} < burst {BURST}"


def test_r5_fairlock_grants_by_arrival_seq_not_wake_order():
    """#248 deterministic: waiters that reach the lock out of arrival order still run in seq order."""
    lk = EP.FairLock()
    lk.acquire(seq=EP.next_seq())
    seqs = [EP.next_seq() for _ in range(3)]  # arrival order: seqs[0] < seqs[1] < seqs[2]
    order, ts = [], []

    def w(seq):
        lk.acquire(seq=seq)
        order.append(seq)
        lk.release()

    def wait_waiting(pred):
        deadline = time.monotonic() + 5
        with lk._cv:
            while not pred():
                left = deadline - time.monotonic()
                assert left > 0, f"waiters never queued: {sorted(lk._waiting)}"
                lk._cv.wait(min(left, 0.01))

    for i in (2, 0, 1):  # threads reach acquire() in this (wrong) order
        seq = seqs[i]
        t = threading.Thread(target=w, args=(seq,), daemon=True); t.start(); ts.append(t)
        wait_waiting(lambda: seq in lk._waiting)
    wait_waiting(lambda: len(lk._waiting) == 3)
    lk.release()
    for t in ts:
        t.join(5)
        assert not t.is_alive(), "FairLock waiter thread hung"
    assert order == seqs


# ---------------- R7 concurrent forwards to one upstream stay capped ----------------

def test_r7_proxy_caps_concurrent_forwards_to_upstream():
    """R7 regression, covered by the R1 (#244) global upstream cap (FAMILIA_UPSTREAM_CAP, default 6).
    Deterministic: upstream handlers block on an Event and count in-flight; no backlog/OS reliance."""
    N, release = 16, threading.Event()
    st = {"inflight": 0, "max": 0}; mu = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            with mu:
                st["inflight"] += 1; st["max"] = max(st["max"], st["inflight"])
            try:
                release.wait(10)
                out = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.end_headers(); self.wfile.write(out)
            finally:
                with mu: st["inflight"] -= 1

    want = min(N, EP.UPSTREAM_CAP)
    # The cap is process-global: start only once no earlier test still holds an upstream slot.
    end = time.monotonic() + 10
    while EP._inflight[0] and time.monotonic() < end: time.sleep(0.02)
    assert EP._inflight[0] == 0, f"{EP._inflight[0]} upstream slots still held by an earlier test"
    up = type("_UpSrv", (ThreadingHTTPServer,), {"request_queue_size": 128, "daemon_threads": True})(("127.0.0.1", 0), H)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    _, srv = proxy(graph(up.server_address[1], closed_port()))
    ex = ThreadPoolExecutor(N)
    futs = []
    try:
        futs = [ex.submit(post, srv.server_address[1], f"c{i}", f"s{i}", 30) for i in range(N)]
        end = time.monotonic() + 10   # fill every slot the cap allows ...
        while time.monotonic() < end and st["inflight"] < want: time.sleep(0.01)
        time.sleep(0.3)               # ... and give an over-cap forward a chance to show up
        release.set()
        # Drain first, THEN sample: a cap that leaks while queued requests are let through
        # (during the drain) must show up in the peak too.
        res = [f.result(timeout=30) for f in futs]
    finally:
        # Servers close even when a request above failed or timed out (no leaked listeners).
        release.set()
        ex.shutdown(wait=True)
        srv.shutdown(); srv.server_close(); up.shutdown(); up.server_close()
    observed = st["max"]
    assert [s for s, _ in res] == [200] * N, res
    # == not <=: a proxy that over-throttles (e.g. one request at a time) must fail too.
    assert observed == want, f"upstream saw {observed} concurrent forwards (want min(N={N}, cap={EP.UPSTREAM_CAP}))"
