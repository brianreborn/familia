#!/usr/bin/env python3
"""launch_status.py: familia launch status protocol v1 (docs/protocol/launch-status.md) and the
fleet-wide memory admission budget every launcher uses before it starts a model.

  emit:   launch_status.py emit STATUS CODE --engine E --model M [--rc N] [--evidence TXT] [--params JSON]
  admit:  launch_status.py admit --mib N --pid PID [--tag T]   (exit 0 admitted, 69 LF_OOM_CAP)
  release: launch_status.py release --pid PID
  budget: launch_status.py budget                              (prints the ledger)
Stdlib only."""
import tempfile
import fcntl, json, os, re, signal, sys, time

V = 1
STATUSES = ("READY", "LAUNCH_FAILED", "CRASHED", "KILLED", "EXITED_OK")
# code -> (status, process exit code). Distinct exit code per class.
CODES = {
    "OK_READY": ("READY", 0), "OK_EXIT": ("EXITED_OK", 0),
    "LF_BAD_PARAMS": ("LAUNCH_FAILED", 64), "LF_MISSING_RUNTIME": ("LAUNCH_FAILED", 65),
    "LF_MODEL_FILE": ("LAUNCH_FAILED", 66), "LF_TIMEOUT": ("LAUNCH_FAILED", 67),
    "LF_PORT": ("LAUNCH_FAILED", 68), "LF_OOM_CAP": ("LAUNCH_FAILED", 69), "LF_ENGINE": ("LAUNCH_FAILED", 70), "LF_TOKENIZER": ("LAUNCH_FAILED", 71), "LF_NEED_SPILL": ("LAUNCH_FAILED", 72),
    "CR_SIGNAL": ("CRASHED", 80), "CR_ASSERT": ("CRASHED", 81),
    "CR_OOM_KERNEL": ("CRASHED", 82), "CR_OOM_MEMCG": ("CRASHED", 83), "CR_EXIT": ("CRASHED", 84),
    "KL_WATCHDOG": ("KILLED", 90), "KL_USER": ("KILLED", 91), "KL_OOMD": ("KILLED", 92), "KL_EARLYOOM": ("KILLED", 93),
}
# Per-user state: $XDG_RUNTIME_DIR (0700, owned) else ~/.cache/familia; never shared /tmp.
LEDGER = os.environ.get("FAMILIA_ADMISSION", os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "familia"),
    "familia-admission-%d.json" % os.getuid()))
RESERVE_MIB = int(os.environ.get("FAMILIA_RESERVE_MIB", "1536"))


def record(code, engine, model, params=None, rc=None, sig=None, evidence="", t_ready_s=None, phase=None):
    st, _ = CODES[code]
    if phase is None:
        phase = "launch" if st in ("READY", "LAUNCH_FAILED") else "run"
    return {"v": V, "phase": phase, "status": st, "code": code, "engine": engine, "model": model,
            "params": params or {}, "rc": rc, "signal": sig, "evidence": (evidence or "")[-400:],
            "t_ready_s": t_ready_s, "ts": round(time.time(), 1)}


def emit(rec, stream=None):
    """One JSON line, prefixed so it can be grepped out of mixed logs."""
    print("FAMILIA-LAUNCH " + json.dumps(rec, sort_keys=True), file=stream or sys.stderr, flush=True)
    return rec


def exit_code(code):
    return CODES[code][1]


def from_matrix_class(cls, ready, rc, killer=None, text=""):
    """Map a launch_matrix class + whether READY was reached to a protocol code."""
    if killer in ("earlyoom",):
        return "KL_EARLYOOM"
    if killer == "systemd-oomd":
        return "KL_OOMD"
    if killer in ("matrix-headroom", "watchdog"):
        return "KL_WATCHDOG"
    if killer == "kernel-oom":
        return "CR_OOM_KERNEL"
    if killer == "cgroup-memmax":
        return "CR_OOM_MEMCG"
    if not ready:
        return {"BAD_PARAMS": "LF_BAD_PARAMS", "MISSING_RUNTIME": "LF_MISSING_RUNTIME", "MODEL_FILE": "LF_MODEL_FILE",
                "TOKENIZER": "LF_TOKENIZER", "TIMEOUT": "LF_TIMEOUT", "OOM": "LF_OOM_CAP", "OK": "OK_READY"}.get(cls, "LF_ENGINE")
    if cls == "OK":
        return "OK_READY"
    if re.search(r"GGML_ASSERT|assert", text or ""):
        return "CR_ASSERT"
    return "CR_SIGNAL" if isinstance(rc, int) and rc < 0 else "CR_EXIT"


# ---- fleet-wide admission budget ------------------------------------------------------------
def _avail():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"):
            return int(l.split()[1]) // 1024
    return 0


def _rss(pid):
    try:
        for l in open("/proc/%d/status" % pid):
            if l.startswith("VmRSS:"):
                return int(l.split()[1]) // 1024
    except OSError:
        return None
    return 0


def _locked(fn):
    os.makedirs(os.path.dirname(LEDGER), mode=0o700, exist_ok=True)
    lfd = os.open(LEDGER + ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(lfd, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            led = json.load(open(LEDGER))
        except Exception:
            led = {}
        led = {p: r for p, r in led.items() if _rss(int(p)) is not None}  # drop dead pids
        out = fn(led)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(LEDGER), prefix=".admission-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(led, f)
            os.replace(tmp, LEDGER)
        except BaseException:
            try: os.unlink(tmp)
            except OSError: pass
            raise
        return out


def outstanding(led):
    """MiB reserved but not yet resident: what live launches may still grow into."""
    return sum(max(0, r["mib"] - (_rss(int(p)) or 0)) for p, r in led.items())


def _total():
    for l in open("/proc/meminfo"):
        if l.startswith("MemTotal"):
            return int(l.split()[1]) // 1024
    return 0


def admit(mib, pid, tag="", avail=None, total=None):
    """Reserve mib (the launch's estimated peak; it is also its hard cap) for pid.
    Admitted only if sum(live reservations) + mib <= MemTotal - reserve AND mib fits in
    MemAvailable - reserve - other launches' outstanding growth. Else LF_OOM_CAP. (ok, detail)."""
    def f(led):
        tot = (total if total is not None else _total()) - RESERVE_MIB
        used = sum(r["mib"] for r in led.values())
        free = (avail if avail is not None else _avail()) - RESERVE_MIB - outstanding(led)
        if used + mib > tot:
            return False, "need %d MiB, reserved %d of %d (MemTotal-%d reserve), %d live launches" % (mib, used, tot, RESERVE_MIB, len(led))
        if mib > free:
            return False, "need %d MiB, MemAvailable budget %d MiB (reserve %d, outstanding %d)" % (mib, free, RESERVE_MIB, outstanding(led))
        led[str(pid)] = {"mib": int(mib), "tag": tag, "t": time.time()}
        return True, "admitted %d MiB (reserved %d/%d)" % (mib, used + mib, tot)
    return _locked(f)


def release(pid):
    return _locked(lambda led: led.pop(str(pid), None) is not None)


def main(argv):
    if not argv:
        print(__doc__); return 2
    cmd, a = argv[0], argv[1:]
    g = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    if cmd == "emit":
        # argv after "emit" is: CODE [--engine E] [--model M] ...
        if not a or a[0].startswith("-"):
            print("launch_status.py emit: need CODE (e.g. LF_OOM_CAP)", file=sys.stderr); return 2
        code = a[0]
        rec = record(code, g("--engine", ""), g("--model", ""), json.loads(g("--params", "{}")),
                     int(g("--rc")) if g("--rc") else None, None, g("--evidence", ""))
        emit(rec); return exit_code(code)
    if cmd == "admit":
        ok, why = admit(int(g("--mib")), int(g("--pid", os.getppid())), g("--tag", ""))
        print(("familia-admission: " + why), file=sys.stderr)
        return 0 if ok else exit_code("LF_OOM_CAP")
    if cmd == "release":
        release(int(g("--pid", os.getppid()))); return 0
    if cmd == "budget":
        print(json.dumps(_locked(lambda led: dict(led)), indent=1)); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
