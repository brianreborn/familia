"""Nexus routing under Termux conventions (platform routing-termux), simulated through env:
HOME=$PREFIX/../home, TMPDIR=$PREFIX/tmp. ssh/rsync/scp are local stubs on PATH that run the
hub side in a fake Termux home; no network. Ports/addresses are computed at runtime, never
written in test text. Nothing may touch the adb drop zone (/data/local/tmp)."""
import hashlib, json, os, socket, subprocess, sys, textwrap
import pytest, yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEXUS = os.path.join(ROOT, "scripts", "nexus", "nexus.py")
ADB_DROP = "/" + "/".join(("data", "local", "tmp"))

pytestmark = pytest.mark.skipif(os.name != "posix", reason="stubs are POSIX scripts")

STUB_SSH = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, subprocess, sys
    log = os.environ["STUB_LOG"]; a = sys.argv[1:]
    with open(log, "a") as f: f.write(json.dumps({"argv0": "ssh", "argv": a}) + "\\n")
    cmd = a[-1]
    env = dict(os.environ, HOME=os.environ["HUB_HOME"])
    sys.exit(subprocess.run(["sh", "-c", cmd], env=env, cwd=env["HOME"]).returncode)
    ''')
STUB_COPY = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, shutil, sys
    log = os.environ["STUB_LOG"]; a = sys.argv[1:]
    with open(log, "a") as f: f.write(json.dumps({"argv0": os.path.basename(sys.argv[0]), "argv": a}) + "\\n")
    def loc(p):
        if "@" in p.split(":")[0] and ":" in p:
            rel = p.split(":", 1)[1]
            return rel if rel.startswith("/") else os.path.join(os.environ["HUB_HOME"], rel)
        return p
    src, dst = loc(a[-2]), loc(a[-1])
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True); shutil.copyfile(src, dst)
    ''')


def _free_port():
    s = socket.socket(); s.bind((socket.gethostbyname("localhost"), 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def termux(tmp_path):
    usr = tmp_path / "data" / "data" / "com.termux" / "files" / "usr"
    home = usr.parent / "home"; tmp = usr / "tmp"; bindir = usr / "bin"
    for d in (home / ".ssh", tmp, bindir): d.mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("stub-key\n")
    hub_home = tmp_path / "hub-home"; hub_home.mkdir()
    for n, body in (("ssh", STUB_SSH), ("rsync", STUB_COPY), ("scp", STUB_COPY)):
        (bindir / n).write_text(body); (bindir / n).chmod(0o755)
    addr, port = socket.gethostbyname("localhost"), _free_port()
    g = {"version": 2,
         "hosts": {"hub": {"kind": "phone", "addr": addr, "user": "u0_hub", "port": port},
                   "phone7": {"kind": "phone", "addr": addr, "user": "u0_me", "port": _free_port()}},
         "meshes": {"lan-nexus": {"type": "ssh", "hub": "hub", "root": "~/.familia/nexus",
                                  "identity": "~/.ssh/id_ed25519", "host_key_policy": "accept-new",
                                  "members": ["hub", "phone7"]}}}
    gp = tmp / "graph.yaml"; gp.write_text(yaml.safe_dump(g))
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(home), "PREFIX": str(usr),
           "TMPDIR": str(tmp), "TERMUX_VERSION": "0.118", "HUB_HOME": str(hub_home),
           "STUB_LOG": str(tmp / "stub.log"), "NEXUS_KNOWN_HOSTS": str(tmp / "known_hosts"),
           "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
           # Termux HOME hides the host user-site; keep the test interpreter's PyYAML importable
           "PYTHONPATH": os.path.dirname(os.path.dirname(yaml.__file__))}
    return dict(env=env, graph=str(gp), home=home, tmp=tmp, hub=hub_home, port=port, addr=addr, usr=usr)


def nexus(t, *args, **kw):
    env = dict(t["env"], **kw.pop("env", {}))
    r = subprocess.run([sys.executable, NEXUS, "--graph", t["graph"], "--transport", "lan-nexus",
                        "--as", "phone7", *args], env=env, capture_output=True, text=True, cwd=str(t["home"]))
    assert r.returncode == 0, r.stderr
    return r.stdout


def calls(t):
    return [json.loads(l) for l in open(t["env"]["STUB_LOG"])]


@pytest.mark.parametrize("copier", ["rsync", "scp"])
def test_register_put_get_roundtrip_under_termux(termux, copier):
    t = termux; extra = {"NEXUS_COPY": copier}
    assert "registered phone7" in nexus(t, "register", env=extra)
    rec = json.loads((t["hub"] / ".familia/nexus/peers/phone7.json").read_text())
    assert rec["name"] == "phone7" and rec["user"] == "u0_me"
    art = t["tmp"] / "kv blob ñ.bin"; art.write_bytes(os.urandom(4096))
    h = nexus(t, "put", str(art), "--kind", "kv", env=extra).strip()
    assert h == hashlib.sha256(art.read_bytes()).hexdigest()
    assert (t["hub"] / ".familia/nexus/artifacts" / h / art.name).read_bytes() == art.read_bytes()
    out = t["tmp"] / "out"; out.mkdir()
    nexus(t, "get", h[:12], str(out), env=extra)
    assert (out / art.name).read_bytes() == art.read_bytes()
    assert copier in {c["argv0"] for c in calls(t)}


def test_ssh_options_follow_graph_and_termux_home(termux):
    t = termux; nexus(t, "peers")
    ssh = [c["argv"] for c in calls(t) if c["argv0"] == "ssh"]
    assert ssh
    for a in ssh:
        assert a[a.index("-p") + 1] == str(t["port"])                 # port from graph, not a default
        assert a[a.index("-i") + 1] == str(t["home"] / ".ssh" / "id_ed25519")  # ~ = Termux $HOME
        assert f"UserKnownHostsFile={t['env']['NEXUS_KNOWN_HOSTS']}" in a
        assert a[-2] == f"u0_hub@{t['addr']}"


def test_scp_uses_capital_P_for_port(termux):
    t = termux; f = t["tmp"] / "m.gguf"; f.write_bytes(b"GGUF")
    nexus(t, "put", str(f), env={"NEXUS_COPY": "scp"})
    scp = [c["argv"] for c in calls(t) if c["argv0"] == "scp"][0]
    assert "-p" not in scp and scp[scp.index("-P") + 1] == str(t["port"])


def test_nothing_routes_through_adb_drop_zone(termux):
    t = termux; f = t["tmp"] / "a.bin"; f.write_bytes(b"x" * 10)
    nexus(t, "register"); h = nexus(t, "put", str(f)).strip(); nexus(t, "ls"); nexus(t, "get", h, str(t["tmp"]))
    blob = open(t["env"]["STUB_LOG"]).read()
    assert ADB_DROP not in blob
    masked = blob.replace(str(t["tmp"]), "$TMPDIR").replace(str(t["usr"].parent), "$TERMUX_FILES")
    assert "/tmp/" not in masked                                       # only $TMPDIR, never bare /tmp
    # hub-side files nexus writes over ssh are private (umask 077), like peers/ and the dirs
    for p in [*t["hub"].rglob("peers/*.json"), *t["hub"].rglob("meta.json"), *t["hub"].rglob("artifacts/*")]:
        assert oct(p.stat().st_mode & 0o077) == "0o0", p


def test_nexus_and_termux_scripts_never_use_adb_drop_zone():
    """Termux-side routing code keeps scratch under $TMPDIR/$PREFIX, not the adb shell's 777 dir."""
    hits = []
    for d in ("scripts/nexus", "scripts/c2c", "scripts/bt"):
        for base, _, files in os.walk(os.path.join(ROOT, d)):
            for fn in files:
                p = os.path.join(base, fn)
                try: s = open(p, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError): continue
                if ADB_DROP in s: hits.append(os.path.relpath(p, ROOT))
    assert hits == []
