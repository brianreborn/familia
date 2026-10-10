#!/usr/bin/env python3
"""Measure this host and write hosts.<name> into graph.yaml (one-click installers).

Only values read from the running system are written as measured. Fields that
cannot be read are omitted (never guessed). An existing host block is replaced
only with --force; otherwise it is left alone and the measurement printed.
Stdlib only. Usage:
  host_measure.py --name NAME [--graph graph.yaml] [--kind laptop|desktop|phone]
                  [--reserve-mib N] [--dry-run] [--force]
"""
import argparse, datetime, os, platform, re, subprocess, sys

def _meminfo_mib():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    if sys.platform == "darwin":
        try:
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) // 1048576
        except Exception:
            pass
    return None

def _cpu():
    try:
        with open("/proc/cpuinfo") as f:
            txt = f.read()
        for key in ("model name", "Hardware", "Processor"):
            m = re.search(r"^%s\s*:\s*(.+)$" % key, txt, re.M)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    if sys.platform == "darwin":
        try:
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        except Exception:
            pass
    return platform.processor() or None

def _os():
    if os.environ.get("TERMUX_VERSION") or os.path.isdir("/data/data/com.termux"):
        return "android"
    return {"darwin": "macos"}.get(sys.platform, "linux" if sys.platform.startswith("linux") else sys.platform)

def _flags():
    try:
        with open("/proc/cpuinfo") as f:
            m = re.search(r"^(flags|Features)\s*:\s*(.+)$", f.read(), re.M)
        if m:
            fl = set(m.group(2).split())
            return sorted(fl & {"avx", "avx2", "avx512f", "f16c", "fma", "sse4_2", "asimd", "asimddp", "i8mm", "sve"})
    except OSError:
        pass
    return None

def measure(kind, reserve):
    stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    out = [("kind", kind), ("measured", "true"), ("measured_at", "'%s'" % stamp),
           ("measured_by", "install/host_measure.py"), ("os", _os())]
    cpu = _cpu()
    if cpu:
        out.append(("cpu", "'%s'" % cpu.replace("'", "''")))
    out.append(("threads", str(os.cpu_count())))
    ram = _meminfo_mib()
    if ram:
        out.append(("ram_mib", str(ram)))
    fl = _flags()
    if fl is not None:
        out.append(("cpu_flags", "[%s]" % ", ".join(fl)))
    out.append(("reserve_ram_mib", "%d                # policy (installer default), not measured; see docs/ram-safety.md" % reserve))
    out.append(("gpus", "[]                     # not probed by installer; add after measuring"))
    return out

def render(name, fields):
    return "  %s:\n" % name + "".join("    %s: %s\n" % kv for kv in fields)

def upsert(text, name, block, force):
    m = re.search(r"^hosts:\s*\n", text, re.M)
    if not m:
        raise SystemExit("host_measure: no top-level hosts: in graph")
    start = m.end()
    end_m = re.search(r"^\S", text[start:], re.M)
    end = start + end_m.start() if end_m else len(text)
    sect = text[start:end]
    h = re.search(r"^  %s:\s*\n" % re.escape(name), sect, re.M)
    if h:
        if not force:
            return None
        nxt = re.search(r"^  \S", sect[h.end():], re.M)
        hend = h.end() + (nxt.start() if nxt else len(sect[h.end():].rstrip("\n")) + 1)
        sect = sect[:h.start()] + block + sect[hend:]
    else:
        body = sect.rstrip("\n") + "\n"
        sect = body + block + sect[len(body):]
    return text[:start] + sect + text[end:]

def default_reserve(ram):
    # docs/ram-safety.md: small hosts keep >= 3 GiB free; never aim for high RAM.
    if not ram:
        return 3072
    return 3072 if ram < 12288 else 4096

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--graph", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "graph.yaml"))
    ap.add_argument("--kind", default="laptop")
    ap.add_argument("--reserve-mib", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", a.name):
        raise SystemExit("host_measure: name must match [a-z0-9][a-z0-9_-]*")
    reserve = a.reserve_mib if a.reserve_mib is not None else default_reserve(_meminfo_mib())
    block = render(a.name, measure(a.kind, reserve))
    with open(a.graph) as f:
        text = f.read()
    new = upsert(text, a.name, block, a.force)
    sys.stdout.write(block)
    if new is None:
        print("host_measure: hosts.%s exists; left unchanged (use --force to replace)" % a.name, file=sys.stderr)
        return 0
    if a.dry_run:
        print("host_measure: dry run, graph not written", file=sys.stderr)
        return 0
    tmp = a.graph + ".tmp"
    with open(tmp, "w") as f:
        f.write(new)
    os.replace(tmp, a.graph)
    print("host_measure: wrote hosts.%s to %s" % (a.name, a.graph), file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
