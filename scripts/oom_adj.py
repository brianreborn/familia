"""#112: mark familia model/bench/harness children as first-to-kill (oom_score_adj +500..+1000).
Raising oom_score_adj needs no privilege. Protected processes (connector, dogfood loop,
kill watcher) are NOT touched here; they go on earlyoom --avoid via scripts/tune/*-memory.sh."""
import os

DEFAULT = int(os.environ.get("FAMILIA_OOM_ADJ", "900"))


def clamp(n):
    return max(500, min(1000, int(n)))


def set_self(n=DEFAULT, path="/proc/self/oom_score_adj"):
    """Best effort; never raises (non-Linux, read-only /proc)."""
    try:
        with open(path, "w") as f:
            f.write(str(clamp(n)))
        return True
    except OSError:
        return False


def preexec(n=DEFAULT):
    """preexec_fn for subprocess.Popen: child gets oom_score_adj n (inherited by its children)."""
    return lambda: set_self(n)
