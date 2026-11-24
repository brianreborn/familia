"""F-10: install/linux/install.sh generated launcher requires an API key on every bind."""
import os, re, shutil, subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "install/linux/install.sh")).read()
BLOCK = re.search(r"# BEGIN familia-linux-key.*?\n(.*?)# END familia-linux-key", SRC, re.S).group(1).replace("\\$", "$")
pytestmark = pytest.mark.skipif(not shutil.which("sh") or not shutil.which("stat"), reason="needs sh+stat")


def run(script, env):
    return subprocess.run(["sh", "-c", BLOCK + script], env={"PATH": os.environ["PATH"], **env}, capture_output=True, text=True)


def gate(env):
    return run('familia_key_args; printf "KF=[%s]\\n" "$FAMILIA_KF"', env)


def _key(tmp_path, content="k" * 32, mode=0o600):
    k = tmp_path / ".config" / "familia" / "api.key"; k.parent.mkdir(parents=True, exist_ok=True)
    k.write_bytes(content.encode()); k.chmod(mode); return k


@pytest.mark.parametrize("bind", [None, "127.0.0.1", "::1", "0.0.0.0"])
def test_key_required_on_every_bind(tmp_path, bind):
    env = {"HOME": str(tmp_path)}
    if bind: env["FAMILIA_BIND"] = bind
    r = gate(env); assert r.returncode == 2 and "required on every bind (loopback included)" in r.stderr, r.stderr


def test_default_key_used_and_mode_enforced(tmp_path):
    k = _key(tmp_path)
    token = k.read_text()
    r = gate({"HOME": str(tmp_path)})
    inst = tmp_path / ".config" / "familia" / "instances" / "9941" / "api-keys"
    assert r.returncode == 0 and f"KF=[{inst}]" in r.stdout, r.stderr
    assert token in inst.read_text() and (inst.stat().st_mode & 0o777) == 0o600
    assert "migrated API key" in r.stderr and "#419" in r.stderr and token not in r.stderr
    assert k.read_text() == token
    inst.chmod(0o644)
    r = gate({"HOME": str(tmp_path)})
    assert r.returncode == 2 and "0600" in r.stderr


def test_port_selects_key_and_legacy_does_not_override(tmp_path):
    """Same rule as Termux: the instance file for the port wins over api.key."""
    for port, token in (("9941", "key-aaa"), ("9950", "key-bbb")):
        p = tmp_path / ".config" / "familia" / "instances" / port / "api-keys"
        p.parent.mkdir(parents=True)
        p.write_text("# llama-server API key(s), one per line\n" + token + "\n")
        p.chmod(0o600)
    legacy = _key(tmp_path, content="legacy-ccc")
    env = {"HOME": str(tmp_path), "TERMUX_VERSION": "0.118", "PREFIX": "/data/data/com.termux/files/usr"}
    r = gate(env)
    inst_a = tmp_path / ".config" / "familia" / "instances" / "9941" / "api-keys"
    assert r.returncode == 0 and f"KF=[{inst_a}]" in r.stdout, r.stderr
    assert "legacy-ccc" not in r.stdout and "key-bbb" not in r.stdout
    r = gate({**env, "FAMILIA_PORT": "9950"})
    inst_b = tmp_path / ".config" / "familia" / "instances" / "9950" / "api-keys"
    assert r.returncode == 0 and f"KF=[{inst_b}]" in r.stdout, r.stderr
    assert legacy.read_text() == "legacy-ccc"


def test_env_file_override_wins_and_seeds_the_instance_file(tmp_path):
    kf = tmp_path / "explicit"
    kf.write_text("e" * 32)
    kf.chmod(0o600)
    r = gate({"HOME": str(tmp_path), "FAMILIA_API_KEY_FILE": str(kf)})
    assert r.returncode == 0 and f"KF=[{kf}]" in r.stdout, r.stderr
    inst = tmp_path / ".config" / "familia" / "instances" / "9941" / "api-keys"
    assert (inst.stat().st_mode & 0o777) == 0o600 and ("e" * 32) in inst.read_text()


def test_symlink_refused(tmp_path):
    k = _key(tmp_path); link = tmp_path / "link"; link.symlink_to(k)
    r = gate({"HOME": str(tmp_path), "FAMILIA_API_KEY_FILE": str(link)}); assert r.returncode == 2 and "symlink" in r.stderr


@pytest.mark.parametrize("content", ["k" * 32 + "\n", "k" * 32 + "\r\n", "ab cd", "ab\ncd", ""])
def test_key_content_rule(tmp_path, content):
    _key(tmp_path, content); r = gate({"HOME": str(tmp_path)})
    assert r.returncode == 2 and ("CR/LF/whitespace" in r.stderr or "empty" in r.stderr), r.stderr


def test_env_scrub():
    r = run('familia_env_scrub; env | grep "^LLAMA" || true', {"LLAMA_API_KEY": "e", "LLAMA_ARG_API_KEY_FILE": "/tmp/e", "LLAMA_ARG_HOST": "0.0.0.0", "LLAMA_CACHE": "keep"})
    assert "LLAMA_API_KEY=" not in r.stdout and "LLAMA_ARG_" not in r.stdout and "LLAMA_CACHE=keep" in r.stdout


def test_launcher_wiring_and_install_key_generation(tmp_path):
    i = SRC.index("# END familia-linux-key"); tail = SRC[i:SRC.index("EOS", i)]
    assert tail.index("familia_key_args") < tail.index("familia_env_scrub") < tail.index("exec ")
    assert '--api-key-file "\\$FAMILIA_KF"' in tail
    j = SRC.index('FAMILIA_KEY_DEFAULT="$HOME'); k = SRC.index("\nfi\n", j) + 4
    sh = "say(){ echo \"$*\"; }; die(){ echo \"$*\" >&2; exit 1; }; DRY=0\n" + SRC[j:k]
    r = subprocess.run(["sh", "-c", sh + sh], env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    kf = tmp_path / ".config" / "familia" / "api.key"
    assert re.fullmatch(r"[0-9a-f]{64}", kf.read_bytes().decode()) and (kf.stat().st_mode & 0o777) == 0o600
    assert r.stdout.count("generated API key") == 1
