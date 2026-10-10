#!/usr/bin/env python3
"""C2C stage 1 (familia #22): ship one llama-server slot KV file between two
nodes that run the *same* model, runtime build, per-slot ctx and KV types.

Uses only stock llama-server features:
  --slot-save-path DIR            (both servers)
  POST /slots/{id}?action=save    {"filename": NAME}  -> DIR/NAME on source
  POST /slots/{id}?action=restore {"filename": NAME}  <- DIR/NAME on dest

  kv_ship.py check   --src URL --dst URL --src-model GGUF --dst-model GGUF
  kv_ship.py ship    --src URL --src-dir DIR --dst URL --dst-dir DIR [--slot 0]
                     --via local|nexus|bt [--name kv.bin] [nexus/bt args...]
                     [--dst-ssh USER@HOST --dst-nexus PATH --dst-graph PATH]

Cross-host (--dst-ssh): kv_ship runs on the source host; the destination
model sha256, the nexus get, the sha256 check and the sidecar all run on the
destination over the same key-only ssh. --dst URL is reached directly or via
an ssh -L tunnel, so both servers can stay bound to 127.0.0.1.

Transport (--via):
  local  copy the file (loopback test / same host)
  nexus  scripts/nexus/nexus.py put/get (feat/transport-poc), kind kv
  bt     scripts/bt/mktorrent.py + seed.sh / fetch.sh (feat/transport-poc)

Compatibility is checked BEFORE save/restore; a mismatch refuses the ship.
A sidecar NAME.meta.json carries the fingerprint and the file sha256, and the
destination re-checks both before restore.
"""
import argparse, hashlib, json, os, shlex, shutil, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]

def rsh(dest, cmd, inp=None):
    p = subprocess.run(["ssh", *SSH_OPTS, dest, cmd], input=inp, capture_output=True, text=True)
    if p.returncode: raise SystemExit(f"kv_ship: ssh {dest} failed ({p.returncode}): {p.stderr.strip()}")
    return p.stdout

def rpath(p):  # ~ must expand on the remote side, everything else quoted
    return "$HOME" + shlex.quote(p[1:]) if p.startswith("~/") else shlex.quote(p)

def http(url, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read() or b"{}")

def fingerprint(url, model_path=None, ssh=None):
    """What must match on both ends. Taken from the live server, plus the GGUF sha256."""
    p = http(url.rstrip("/") + "/props")
    s = p.get("default_generation_settings", {})
    slots = http(url.rstrip("/") + "/slots")
    fp = {"build_info": p.get("build_info"),
          "model_path_name": os.path.basename(p.get("model_path", "") or ""),
          "n_ctx_slot": s.get("n_ctx") or (slots[0].get("n_ctx") if slots else None),
          "total_slots": p.get("total_slots"),
          # cache types aren't exposed by /props on every build; caller passes them via --kv
          }
    if model_path and ssh: fp["model_sha256"] = rsh(ssh, "sha256sum " + rpath(model_path)).split()[0]
    elif model_path: fp["model_sha256"] = sha256(model_path)
    return fp

def compare(a, b, kv_a, kv_b):
    errs = []
    for k in ("build_info", "n_ctx_slot", "model_sha256"):
        if a.get(k) is None or b.get(k) is None: errs.append(f"{k}: unknown on one end ({a.get(k)!r} vs {b.get(k)!r}); refusing")
        elif a[k] != b[k]: errs.append(f"{k}: {a[k]!r} != {b[k]!r}")
    if kv_a != kv_b: errs.append(f"kv types: {kv_a} != {kv_b}")
    return errs

def transfer(args, src_file, dst_file):
    if args.via == "local":
        shutil.copyfile(src_file, dst_file); return
    if args.via == "nexus":
        nx = [sys.executable, args.nexus or os.path.join(HERE, "..", "nexus", "nexus.py"), "--graph", args.graph, "--transport", args.transport]
        key = subprocess.run(nx + ["--as", args.src_host, "put", src_file, "--kind", "kv"], check=True, capture_output=True, text=True).stdout.split()[-1]
        if args.dst_ssh:
            rnx = ["python3", rpath(args.dst_nexus), "--graph", rpath(args.dst_graph), "--transport", shlex.quote(args.transport)]
            print(rsh(args.dst_ssh, " ".join(rnx + ["--as", shlex.quote(args.dst_host), "get", key[:16], rpath(dst_file)])).strip()); return
        subprocess.run(nx + ["--as", args.dst_host, "get", key, dst_file], check=True); return
    if args.via == "bt":
        bt = os.path.join(HERE, "..", "bt")
        tor = src_file + ".torrent"
        subprocess.run([sys.executable, os.path.join(bt, "mktorrent.py"), src_file, args.tracker, tor], check=True)
        seed = subprocess.Popen(["sh", os.path.join(bt, "seed.sh"), tor, src_file])
        try: subprocess.run(["sh", os.path.join(bt, "fetch.sh"), tor, dst_file], check=True)
        finally: seed.terminate()
        return
    raise SystemExit(f"unknown --via {args.via}")

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "ship"])
    ap.add_argument("--src", required=True); ap.add_argument("--dst", required=True)
    ap.add_argument("--src-model", required=True); ap.add_argument("--dst-model", required=True)
    ap.add_argument("--src-kv", default="f16/f16", help="cache-type-k/cache-type-v of source")
    ap.add_argument("--dst-kv", default="f16/f16")
    ap.add_argument("--src-dir"); ap.add_argument("--dst-dir"); ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--dst-slot", type=int); ap.add_argument("--name", default="c2c-slot.bin")
    ap.add_argument("--via", choices=["local", "nexus", "bt"], default="local")
    ap.add_argument("--graph", default="graph.yaml"); ap.add_argument("--transport")
    ap.add_argument("--src-host"); ap.add_argument("--dst-host"); ap.add_argument("--nexus"); ap.add_argument("--tracker")
    ap.add_argument("--dst-ssh", help="USER@HOST: destination dir/model live on that host (needs --via nexus)")
    ap.add_argument("--dst-nexus"); ap.add_argument("--dst-graph")
    a = ap.parse_args(argv)
    if a.dst_ssh and a.via != "nexus": ap.error("--dst-ssh needs --via nexus")
    if a.dst_ssh and not (a.dst_nexus and a.dst_graph): ap.error("--dst-ssh needs --dst-nexus and --dst-graph (paths on the destination)")
    fa, fb = fingerprint(a.src, a.src_model), fingerprint(a.dst, a.dst_model, a.dst_ssh)
    errs = compare(fa, fb, a.src_kv, a.dst_kv)
    if errs:
        print("kv_ship: INCOMPATIBLE, not shipping:\n  " + "\n  ".join(errs), file=sys.stderr); return 2
    print(f"kv_ship: compatible (build {fa['build_info']}, n_ctx_slot {fa['n_ctx_slot']}, model {fa['model_sha256'][:12]})")
    if a.cmd == "check": return 0
    if not (a.src_dir and a.dst_dir): ap.error("ship needs --src-dir and --dst-dir (each server's --slot-save-path)")
    r = http(f"{a.src.rstrip('/')}/slots/{a.slot}?action=save", {"filename": a.name})
    src_file = os.path.join(a.src_dir, a.name)
    meta = dict(fa, kv=a.src_kv, file_sha256=sha256(src_file), n_saved=r.get("n_saved"))
    print(f"kv_ship: saved slot {a.slot}: {r.get('n_saved')} tokens, {r.get('n_written')} bytes")
    dst_file = (a.dst_dir.rstrip("/") + "/" + a.name) if a.dst_ssh else os.path.join(a.dst_dir, a.name)
    transfer(a, src_file, dst_file)
    got = rsh(a.dst_ssh, "sha256sum " + rpath(dst_file)).split()[0] if a.dst_ssh else sha256(dst_file)
    if got != meta["file_sha256"]:
        print("kv_ship: sha256 mismatch after transfer; not restoring", file=sys.stderr); return 3
    if a.dst_ssh: rsh(a.dst_ssh, "cat > " + rpath(dst_file + ".meta.json"), json.dumps(meta, indent=1))
    else:
        with open(dst_file + ".meta.json", "w") as f: json.dump(meta, f, indent=1)
    ds = a.slot if a.dst_slot is None else a.dst_slot
    r2 = http(f"{a.dst.rstrip('/')}/slots/{ds}?action=restore", {"filename": a.name})
    print(f"kv_ship: restored slot {ds}: {r2.get('n_restored')} tokens")
    print(json.dumps({"saved": meta["n_saved"], "restored": r2.get("n_restored"), "sha256": meta["file_sha256"]}))
    return 0 if r2.get("n_restored") == meta["n_saved"] else 4

if __name__ == "__main__":
    sys.exit(main())
