#!/usr/bin/env python3
"""SSH nexus PoC (familia #22 stage 1, DESIGN.md Transports: "SSH. A host and a path.").

The hub is a plain directory on one declared host; members reach it over ssh
with a key only (BatchMode, no passwords, StrictHostKeyChecking=accept-new).
Nothing runs on the hub except sh, cat, mkdir, sha256sum and rsync (or scp/sftp
when the member has no rsync, e.g. Windows OpenSSH; NEXUS_COPY=rsync|scp forces one).

  nexus.py [--graph graph.yaml] --transport lan-nexus --as phone7 register
  nexus.py ... peers
  nexus.py ... put FILE [--kind model|kv]      -> prints sha256 key
  nexus.py ... ls
  nexus.py ... get KEY DEST                     (KEY = sha256 or name)

Layout on hub: <root>/peers/<host>.json, <root>/artifacts/<sha256>/{<name>,meta.json}
"""
import argparse, hashlib, json, os, shlex, shutil, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import transport_graph as tg

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

class Nexus:
    def __init__(s, g, tname, me):
        s.t = tg.transport(g, tname, "ssh"); s.me = me
        if me not in s.t["members"]: raise SystemExit(f"nexus: {me!r} is not a member of {tname}")
        s.hub = tg.host(g, s.t["hub"]); s.root = s.t["root"]
        s.mine = tg.host(g, me)
        key = os.path.expanduser(s.t["identity"])
        s.opts = ["-i", key, "-p", str(s.hub["port"]), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                  "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
                  "-o", f"StrictHostKeyChecking={s.t['host_key_policy']}", "-o", "ConnectTimeout=10"]
        if os.environ.get("NEXUS_KNOWN_HOSTS"): s.opts += ["-o", "UserKnownHostsFile=" + os.environ["NEXUS_KNOWN_HOSTS"]]
        s.dest = f"{s.hub['user']}@{s.hub['addr']}"
    def r(s, path): return path.replace("~", "$HOME", 1) if path.startswith("~") else shlex.quote(path)
    def ssh(s, cmd, inp=None):
        p = subprocess.run(["ssh", *s.opts, s.dest, cmd], input=inp, capture_output=True, text=True)
        if p.returncode: raise SystemExit(f"nexus: ssh {s.dest} failed ({p.returncode}): {p.stderr.strip()}")
        return p.stdout
    def copier(s):
        c = os.environ.get("NEXUS_COPY") or ("rsync" if shutil.which("rsync") else "scp")
        if c not in ("rsync", "scp"): raise SystemExit(f"nexus: NEXUS_COPY={c!r} (want rsync|scp)")
        if not shutil.which(c): raise SystemExit(f"nexus: {c} not found on PATH")
        return c
    def rsync(s, src, dst):
        """Copy one file; src/dst are local paths or '<dest>:<home-relative path>'."""
        if s.copier() == "rsync":
            e = "ssh " + " ".join(shlex.quote(o) for o in s.opts)
            cmd = ["rsync", "-a", "--partial", "-e", e, src, dst]
        else:   # scp/sftp (Windows OpenSSH has no rsync): -P is the port flag; remote path stays $HOME-relative
            o = ["-P" if x == "-p" else x for x in s.opts]
            cmd = ["scp", "-q", *o, src, dst]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode: raise SystemExit(f"nexus: {cmd[0]} failed ({p.returncode}): {p.stderr.strip()}")
    def register(s):
        rec = dict(name=s.me, **{k: s.mine[k] for k in tg.HOST_KEYS}, ts=int(time.time()))
        R = s.r(s.root)
        s.ssh(f"umask 077; mkdir -p {R}/peers {R}/artifacts && cat > {R}/peers/{shlex.quote(s.me)}.json", json.dumps(rec))
        print(f"registered {s.me} at {s.dest}:{s.root}")
    def peers(s):
        out = s.ssh(f"for p in {s.r(s.root)}/peers/*.json; do [ -f \"$p\" ] && cat \"$p\" && echo; done; true")
        for line in out.splitlines():
            if line.strip(): p = json.loads(line); print(f"{p['name']}\t{p['user']}@{p['addr']}:{p['port']}\t{p['kind']}")
    def put(s, f, kind):
        h, name = sha256(f), os.path.basename(f)
        d = f"{s.root}/artifacts/{h}"
        s.ssh(f"umask 077; mkdir -p {s.r(d)}")
        rd = d.replace("~/", "", 1) if d.startswith("~/") else d   # rsync remote paths are $HOME-relative
        s.rsync(f, f"{s.dest}:{rd}/{name}")
        got = s.ssh(f"sha256sum {s.r(d)}/{shlex.quote(name)}").split()[0]
        if got != h: raise SystemExit(f"nexus: hub sha256 {got} != local {h}")
        meta = json.dumps(dict(sha256=h, name=name, kind=kind, size=os.path.getsize(f), from_=s.me, ts=int(time.time())))
        s.ssh(f"cat > {s.r(d)}/meta.json", meta)
        print(h)
    def entries(s):
        out = s.ssh(f"for m in {s.r(s.root)}/artifacts/*/meta.json; do [ -f \"$m\" ] && cat \"$m\" && echo; done; true")
        return [json.loads(l) for l in out.splitlines() if l.strip()]
    def ls(s):
        for e in s.entries(): print(f"{e['sha256']}\t{e['kind']}\t{e['size']}\t{e['name']}\tfrom {e['from_']}")
    def get(s, key, dest):
        m = [e for e in s.entries() if e["sha256"].startswith(key) or e["name"] == key]
        if len(m) != 1: raise SystemExit(f"nexus: key {key!r} matches {len(m)} artifacts (need exactly 1)")
        e = m[0]; d = f"{s.root}/artifacts/{e['sha256']}/{e['name']}"
        rd = d.replace("~/", "", 1) if d.startswith("~/") else d
        if os.path.isdir(dest): dest = os.path.join(dest, e["name"])
        s.rsync(f"{s.dest}:{rd}", dest)
        if sha256(dest) != e["sha256"]: os.unlink(dest); raise SystemExit("nexus: sha256 mismatch after get; removed")
        print(f"{dest}\t{e['sha256']}")

def main(a=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="graph.yaml"); ap.add_argument("--transport", required=True)
    ap.add_argument("--as", dest="me", required=True)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("register"); sp.add_parser("peers"); sp.add_parser("ls")
    p = sp.add_parser("put"); p.add_argument("file"); p.add_argument("--kind", choices=["model", "kv", "other"], default="other")
    p = sp.add_parser("get"); p.add_argument("key"); p.add_argument("dest")
    o = ap.parse_args(a)
    g = tg.load(o.graph); errs = tg.validate_transports(g)
    if errs: [print("graph: ERROR:", e, file=sys.stderr) for e in errs]; return 1
    n = Nexus(g, o.transport, o.me)
    {"register": n.register, "peers": n.peers, "ls": n.ls}.get(o.cmd, lambda: None)()
    if o.cmd == "put": n.put(o.file, o.kind)
    if o.cmd == "get": n.get(o.key, o.dest)
    return 0

if __name__ == "__main__": sys.exit(main())
