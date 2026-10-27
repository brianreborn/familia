#!/usr/bin/env python3
"""Measure this host and write hosts.<name> into graph.yaml (one-click installers).

Only values read from the running system are written as measured. Fields that
cannot be read are omitted (never guessed). An existing host block is replaced
only with --force; otherwise it is left alone and the measurement printed.
Stdlib only. Usage:
  host_measure.py --name NAME [--graph graph.yaml] [--kind desktop|laptop|phone|tablet|notebook|1U|2U|3U|console|appliance|drone|watch]
                  [--reserve-mib N] [--dry-run] [--force]
An explicit --kind is required when the graph has no known kind for this host.
"""
import argparse, os, platform, re, socket, subprocess, sys


def _sysctl(name):
    try:
        return subprocess.check_output(["sysctl", "-n", name], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None

def _meminfo_mib():
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform.startswith("freebsd"):
        value = _sysctl("hw.physmem")
        return int(value) // 1048576 if value and value.isdigit() else None
    if sys.platform == "darwin":
        value = _sysctl("hw.memsize")
        return int(value) // 1048576 if value and value.isdigit() else None
    if sys.platform == "win32":
        try:
            import ctypes
            class _MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong) for n in ("tot", "avail", "tpf", "apf", "tv", "av", "aev")]
            m = _MS(); m.len = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.tot // 1048576
        except Exception:
            pass
    return None

def _cpu():
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo") as f:
                txt = f.read()
            for key in ("model name", "Hardware", "Processor"):
                m = re.search(r"^%s\s*:\s*(.+)$" % key, txt, re.M)
                if m:
                    return m.group(1).strip()
        except OSError:
            return None
    if sys.platform.startswith("freebsd"):
        return _sysctl("hw.model")
    if sys.platform == "darwin":
        return _sysctl("machdep.cpu.brand_string")
    return platform.processor() or None

def _os():
    if os.environ.get("TERMUX_VERSION") or os.path.isdir("/data/data/com.termux"):
        return "android"
    if sys.platform.startswith("freebsd"):
        return "freebsd"
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux" if sys.platform.startswith("linux") else sys.platform)

def measure(kind, reserve):
    from box_archetypes import MEASURABLE_HOST_KINDS, OBSOLETE_HOST_KINDS, shape_for
    if kind in OBSOLETE_HOST_KINDS:
        raise ValueError(OBSOLETE_HOST_KINDS[kind])
    if kind not in MEASURABLE_HOST_KINDS:
        raise ValueError(
            "kind must be one of %s; unknown hosts need an explicit kind"
            % sorted(MEASURABLE_HOST_KINDS)
        )
    # Prefer shape reserve when caller used installer default path — reserve arg still wins.
    _ = shape_for(kind)  # document coupling; reserve already chosen by caller
    short = socket.gethostname().split(".", 1)[0]
    # Termux / many Android images: OS hostname is useless and collides.
    if short.lower() == "localhost":
        local_names_val = "[]                  # omit localhost (collides); use hostname_pin / --name"
        print(
            "host_measure: warning: OS hostname is localhost; "
            "omitting from local_names (use hostname_pin / --name)",
            file=sys.stderr,
        )
    else:
        local_names_val = "[%s]             # OS hostname(s) that resolve to this graph host" % short
    out = [("kind", kind), ("measured", "true"), ("os", _os()),
           ("local_names", local_names_val)]
    cpu = _cpu()
    if not cpu:
        raise ValueError("could not measure CPU model on this host")
    out.append(("cpu", "'%s'" % cpu.replace("'", "''")))
    threads = os.cpu_count()
    if not threads:
        raise ValueError("could not measure logical CPU count on this host")
    out.append(("threads", str(threads)))
    ram = _meminfo_mib()
    if not ram:
        raise ValueError("could not measure physical RAM on this host")
    out.append(("ram_mib", str(ram)))
    out.append(("reserve_ram_mib", "%d                # policy (installer default), not measured; see docs/ram-safety.md" % reserve))
    out.append(("gpus", "null                   # inventory unknown; measure GPUs before GPU offload"))
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

def existing_kind(text, name):
    m = re.search(r"^hosts:\s*\n", text, re.M)
    if not m:
        return None
    end_m = re.search(r"^\S", text[m.end():], re.M)
    section = text[m.end():m.end() + end_m.start()] if end_m else text[m.end():]
    lines = section.splitlines()
    header = re.compile(r"^  %s:\s*(?:#.*)?$" % re.escape(name))
    kind = re.compile(r"^    kind:\s*([A-Za-z0-9_-]+)\s*(?:#.*)?$")
    for i, line in enumerate(lines):
        if not header.match(line):
            continue
        for field in lines[i + 1:]:
            if re.match(r"^  \S", field):
                break
            match = kind.match(field)
            if match:
                return match.group(1)
        return None
    return None

def default_reserve(ram):
    # docs/ram-safety.md: small hosts keep >= 3 GiB free; never aim for high RAM.
    if not ram:
        return 3072
    return 3072 if ram < 12288 else 4096

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--graph", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "graph.yaml"))
    from box_archetypes import MEASURABLE_HOST_KINDS, OBSOLETE_HOST_KINDS, shape_for
    ap.add_argument("--kind", choices=sorted(MEASURABLE_HOST_KINDS))
    ap.add_argument("--reserve-mib", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", a.name):
        raise SystemExit("host_measure: name must match [a-z0-9][a-z0-9_-]*")
    with open(a.graph) as f:
        text = f.read()
    old_kind = existing_kind(text, a.name)
    if (old_kind is None or old_kind == "unknown") and a.kind is None:
        raise SystemExit("host_measure: host kind is unknown; identify it and specify --kind")
    kind = a.kind or old_kind
    if kind in OBSOLETE_HOST_KINDS:
        raise SystemExit("host_measure: " + OBSOLETE_HOST_KINDS[kind])
    if a.reserve_mib is not None:
        reserve = a.reserve_mib
    else:
        shape_reserve = shape_for(kind).get("reserve_ram_mib")
        measured = _meminfo_mib()
        # Use shape hint when present; still floor via default_reserve for tiny hosts.
        reserve = max(default_reserve(measured), int(shape_reserve or 0)) if shape_reserve else default_reserve(measured)
        if measured and measured < 12288 and kind in ("laptop", "notebook", "phone", "tablet", "watch", "drone"):
            reserve = default_reserve(measured)  # small hosts keep ram-safety floor, not server shape
    try:
        block = render(a.name, measure(kind, reserve))
    except ValueError as error:
        raise SystemExit(f"host_measure: {error}") from error
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
    try:
        _scripts = os.path.dirname(os.path.abspath(__file__))
        if _scripts not in sys.path:
            sys.path.insert(0, _scripts)
        from hostname_pin import write_pin
        write_pin(a.name)
        print("host_measure: pinned local graph host %s" % a.name, file=sys.stderr)
    except Exception as e:
        print("host_measure: warning: could not write hostname pin (%s)" % e, file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
