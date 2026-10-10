#!/usr/bin/env python3
"""isolated_remote adapter for `ssh chat.hf.co` (familia docs/isolated-compute.md).

chat.hf.co is a full-screen TUI that needs a PTY: pexpect on POSIX, pywinpty on
Windows. We type the prompt, press enter, and scrape the reply until the screen
is quiet. ANSI codes are stripped and our own typed echo is removed.

Limits (never let the remote compact for us):
  context_tokens        model window (TBD for Qwen/Qwen3.8-27B via Inference Providers)
  compaction_threshold  fill at which the service compacts or truncates (TBD; unmeasured)
  safety_margin         tokens kept free below the threshold
  max_fill              = compaction_threshold - safety_margin
The adapter estimates tokens per session (~4 chars/token, or a tokenizer if
one is given). When the next turn would pass max_fill, it closes the session
and opens a new one that carries a compact local summary.
If the threshold is unknown, the default is 0.8 * context_tokens.

  hfchat.py "prompt" [--context-tokens N] [--threshold N] [--margin N] [--timeout S]
Exit codes: 0 reply, 3 no reply in time, 5 provider refused (402 credits / auth).
"""
import argparse, os, re, sys, threading, time

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][A-Za-z0-9]|\x1b[=>]")
CHROME = re.compile(r"^(enter send|esc stop|Ask anything|🤗 ssh chat|Type /model|[⣾⣽⣻⢿⡿⣟⣯⣷] )")
REFUSAL = re.compile(r"error: (40[0-9]|429|5\d\d)[^\n]*")

def clean(t):
    out = []
    for l in ANSI.sub("\n", t).splitlines():
        l = l.strip(" \u2503\u2502\r")
        if re.search(r"\w", l) and (not out or out[-1] != l): out.append(l)
    return out

def est_tokens(text, tok=None):
    return len(tok(text)) if tok else max(1, (len(text) + 3) // 4)

class Limits:
    def __init__(s, context_tokens, compaction_threshold=None, safety_margin=None, prefill_ratio=None):
        s.context_tokens = context_tokens
        s.compaction_threshold = compaction_threshold or int(0.8 * context_tokens)   # TBD until measured
        s.safety_margin = safety_margin if safety_margin is not None else max(512, context_tokens // 20)
        s.max_fill = s.compaction_threshold - s.safety_margin
        s.prefill_ratio = prefill_ratio if prefill_ratio is not None else s.max_fill / context_tokens
    def validate(s):
        e = []
        if not 0 < s.compaction_threshold <= s.context_tokens: e.append("compaction_threshold must be in (0, context_tokens]")
        if s.max_fill <= 0: e.append("max_fill = compaction_threshold - safety_margin must be > 0")
        if s.prefill_ratio * s.context_tokens > s.max_fill: e.append(f"prefill_ratio*context ({s.prefill_ratio*s.context_tokens:.0f}) > max_fill ({s.max_fill})")
        return e

class Pty:
    def __init__(s, cmd, cols=150, rows=40):
        s.buf, s.lock = [], threading.Lock()
        if os.name == "nt":
            from winpty import PtyProcess
            s.p = PtyProcess.spawn(cmd, dimensions=(rows, cols)); s._read = lambda: s.p.read(4096)
            s.write = s.p.write; s.close = lambda: s.p.terminate(True)
        else:
            import pexpect
            s.p = pexpect.spawn(cmd, encoding="utf-8", dimensions=(rows, cols), timeout=None)
            s._read = lambda: s.p.read_nonblocking(4096, timeout=1); s.write = s.p.send
            s.close = lambda: s.p.terminate(force=True)
        threading.Thread(target=s._pump, daemon=True).start()
    def _pump(s):
        while True:
            try: d = s._read()
            except Exception as ex:
                if type(ex).__name__ == "TIMEOUT": continue
                break
            with s.lock: s.buf.append((time.time(), d))
    def since(s, t):
        with s.lock: return "".join(d for ts, d in s.buf if ts >= t)
    def last_rx(s):
        with s.lock: return s.buf[-1][0] if s.buf else 0

class HFChat:
    def __init__(s, limits, endpoint="chat.hf.co", tok=None):
        s.lim, s.endpoint, s.tok = limits, endpoint, tok
        s.pty, s.used, s.log, s.rotations = None, 0, [], 0
    def open(s, carry=None):
        if s.pty: s.pty.close()
        s.pty = Pty(f"ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new {s.endpoint}")
        t = time.time(); time.sleep(6); s.used = 0
        s.banner = clean(s.pty.since(t))
        if carry: s.send("Context summary from an earlier session (keep in mind, no reply needed beyond OK):\n" + carry)
    def summary(s, budget):
        text = "\n".join(f"{r}: {m}" for r, m in s.log); keep = budget * 4
        return text[-keep:]
    def send(s, prompt, timeout=120, quiet=4.0):
        need = est_tokens(prompt, s.tok)
        if s.pty and s.used + need * 2 > s.lim.max_fill:   # *2: leave room for the reply
            s.rotations += 1; s.open(carry=s.summary(s.lim.max_fill // 8))
        elif not s.pty: s.open()
        t0 = time.time()
        for ch in prompt.replace("\n", " "): s.pty.write(ch); time.sleep(0.01)
        time.sleep(0.2); s.pty.write("\r")
        while time.time() - t0 < timeout:
            time.sleep(0.5)
            raw = s.pty.since(t0); m = REFUSAL.search(ANSI.sub("", raw))
            if m: return dict(ok=False, code=5, error=m.group(0)[:300], latency_s=time.time() - t0)
            if time.time() - s.pty.last_rx() > quiet and time.time() - t0 > quiet + 1:
                lines = [l for l in clean(raw) if not CHROME.match(l) and l not in prompt and prompt[:20] not in l and l != "you"]
                reply = "\n".join(l for l in lines if l != s.model_line())
                if reply.strip():
                    s.used += need + est_tokens(reply, s.tok); s.log += [("user", prompt), ("assistant", reply)]
                    return dict(ok=True, code=0, reply=reply, latency_s=time.time() - t0, used_tokens=s.used, rotations=s.rotations)
        return dict(ok=False, code=3, error="no reply before timeout", latency_s=time.time() - t0)
    def model_line(s):
        for l in getattr(s, "banner", []):
            if l.startswith("🤗 ") and "/" in l: return l
        return None
    def close(s):
        if s.pty: s.pty.write("\x03"); time.sleep(0.5); s.pty.close(); s.pty = None

def main(a=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt"); ap.add_argument("--endpoint", default="chat.hf.co")
    ap.add_argument("--context-tokens", type=int, default=32768, help="TBD for the default model; 32768 is a conservative placeholder")
    ap.add_argument("--threshold", type=int); ap.add_argument("--margin", type=int); ap.add_argument("--prefill-ratio", type=float)
    ap.add_argument("--timeout", type=float, default=120)
    o = ap.parse_args(a)
    lim = Limits(o.context_tokens, o.threshold, o.margin, o.prefill_ratio)
    errs = lim.validate()
    if errs: print("hfchat: limits invalid:\n  " + "\n  ".join(errs), file=sys.stderr); return 2
    c = HFChat(lim, o.endpoint)
    try: r = c.send(o.prompt, o.timeout)
    finally: c.close()
    print(("\n".join(c.banner[-6:]) + "\n---\n") if getattr(c, "banner", None) else "", end="")
    print(r.get("reply") or r.get("error")); print(f"[latency {r['latency_s']:.1f}s, max_fill {lim.max_fill}]", file=sys.stderr)
    return r["code"]

if __name__ == "__main__":
    sys.exit(main())
