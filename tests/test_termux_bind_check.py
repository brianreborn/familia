"""familia-start bind/key-file gate (install/termux/install.sh, generated launcher)."""
import os, re, shutil, subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "install/termux/install.sh")).read()
BLOCK = re.search(r"# BEGIN familia-bind-check.*?\n(.*?)# END familia-bind-check", SRC, re.S).group(1).replace("\\$", "$")
pytestmark = pytest.mark.skipif(not shutil.which("sh") or not shutil.which("stat"), reason="needs sh+stat")


def run(script, env):
    return subprocess.run(["sh", "-c", BLOCK + script], env={"PATH": os.environ["PATH"], **env}, capture_output=True, text=True)


@pytest.mark.parametrize("addr,ok", [
    ("127.0.0.1", True), ("127.1.2.3", True), ("localhost", True), ("::1", True),
    ("127.example", False), ("127.0.0.1.evil.com", False), ("127.0.0", False), ("127.0.0.256", False),
    ("127.0.0.1a", False), ("127..0.1", False), ("0.0.0.0", False), ("192.168.1.36", False), ("", False),
])
def test_is_loopback(addr, ok):
    r = run('is_loopback "$A" && echo YES || echo NO', {"A": addr})
    assert r.stdout.strip() == ("YES" if ok else "NO"), (addr, r.stderr)


def gate(env):
    return run('familia_key_args; printf "KF=[%s]\\n" "$FAMILIA_KF"', env)


@pytest.mark.parametrize("bind", [None, "127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0", "127.example"])
def test_key_required_on_every_bind_including_loopback(tmp_path, bind):
    env = {"HOME": str(tmp_path)}
    if bind is not None: env["FAMILIA_BIND"] = bind
    r = gate(env); assert r.returncode == 2 and "required on every bind (loopback included)" in r.stderr, r.stderr


def test_loopback_uses_default_key_file(tmp_path):
    k = tmp_path / ".config" / "familia" / "api.key"; k.parent.mkdir(parents=True); k.write_text("x"); k.chmod(0o600)
    r = gate({"HOME": str(tmp_path)}); assert r.returncode == 0, r.stderr; assert f"KF=[{k}]" in r.stdout
    k.chmod(0o644); r = gate({"HOME": str(tmp_path)}); assert r.returncode == 2 and "0600" in r.stderr


def test_launcher_always_passes_key_file_and_install_generates_it():
    assert 'is_loopback "\\$B" && return 0' not in SRC
    assert '[ -n "\\$FAMILIA_KF" ] || { echo "familia-start: no API key; refusing" >&2; exit 2; }\nset -- --api-key-file "\\$FAMILIA_KF"' in SRC
    i = SRC.index('FAMILIA_KEY_DEFAULT="$HOME/.config/familia/api.key"'); assert i < SRC.index('cat > "$LAUNCH"')
    assert "umask 077" in SRC[i:i + 600] and "/dev/urandom" in SRC[i:i + 600] and "chmod 600" in SRC[i:i + 600]


def test_install_key_generation_snippet(tmp_path):
    i = SRC.index('FAMILIA_KEY_DEFAULT="$HOME'); j = SRC.index("\nfi\n", i) + 4
    sh = "say(){ echo \"$*\"; }; DRY=0\n" + SRC[i:j]
    r = subprocess.run(["sh", "-c", sh + sh], env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    k = tmp_path / ".config" / "familia" / "api.key"
    assert re.fullmatch(r"[0-9a-f]{64}", k.read_text()) and (k.stat().st_mode & 0o777) == 0o600
    assert r.stdout.count("generated API key") == 1  # second run keeps the existing key


def _prefixes(path):
    return [l.strip() for l in open(path) if l.strip() and not l.strip().startswith("#")]


def test_shared_prefix_list_matches_green_roomz_format():
    # familia config/shared-storage-prefixes.txt is a documented duplicate of green-roomz's list
    # (one prefix per line; equal-or-under after realpath). The launcher's inline case list must
    # cover every prefix (base and base/*); optional cross-check against a green-roomz checkout.
    got = set(re.search(r'case "\\\$KF" in (/storage[^)]*)\)', SRC).group(1).split("|"))
    mine = _prefixes(os.path.join(ROOT, "config/shared-storage-prefixes.txt"))
    for p in mine:
        base = p.rstrip("/"); assert base in got and base + "/*" in got, f"launcher case list missing {base}"
    gz = os.environ.get("GRZ_PREFIX_LIST")
    if gz and os.path.exists(gz): assert sorted(_prefixes(gz)) == sorted(mine)


def test_key_file_with_spaces_is_quoted(tmp_path):
    kf = tmp_path / "my key"; kf.write_text("k"); kf.chmod(0o600)
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(kf)})
    assert r.returncode == 0, r.stderr; assert f"KF=[{kf}]" in r.stdout


def test_key_file_symlink_refused(tmp_path):
    kf = tmp_path / "real"; kf.write_text("k"); kf.chmod(0o600); ln = tmp_path / "link"; ln.symlink_to(kf)
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(ln)})
    assert r.returncode == 2 and "symlink" in r.stderr


def test_key_file_bad_mode_refused(tmp_path):
    kf = tmp_path / "k"; kf.write_text("k"); kf.chmod(0o644)
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(kf)})
    assert r.returncode == 2 and "0600" in r.stderr


def test_key_file_missing_refused(tmp_path):
    r = gate({"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(tmp_path / "nope")})
    assert r.returncode == 2 and "missing" in r.stderr


def test_launcher_passes_key_as_single_arg():
    assert '"\\$@" \\${FAMILIA_EXTRA:-}' in SRC and "KEYARGS" not in SRC


def test_sshd_disables_password_auth():
    assert "PasswordAuthentication no" in SRC
    i = SRC.index('if [ "$SSHD" = 1 ]; then\n  # Key auth'); assert SRC.index("PasswordAuthentication no", i) < SRC.index("run sshd", i)


LINUX_SRC = open(os.path.join(ROOT, "install/linux/install.sh")).read()


@pytest.mark.parametrize("extra", [
    "--host 0.0.0.0", "-t 4 --port=1", "--api-key x", "--api-key-file /tmp/k", "--ssl-key-file k", "--hostname x", "-c 8 --ssl-cert-file c",
    "--path /tmp/evil", "--path=/x",
])
def test_familia_extra_override_refused(extra):
    r = run('familia_extra_check; echo PASSED', {"FAMILIA_EXTRA": extra})
    assert r.returncode == 2 and "PASSED" not in r.stdout and "refusing" in r.stderr, (extra, r.stderr)


@pytest.mark.parametrize("extra", ["", "-t 4 --temp 0.7", "--n-predict 64 *"])
def test_familia_extra_benign_passes_unglobbed(extra):
    r = run('familia_extra_check; set -- ${FAMILIA_EXTRA:-}; [ $# -gt 0 ] && printf "[%s]" "$@"; true', {"FAMILIA_EXTRA": extra})
    assert r.returncode == 0, r.stderr
    assert r.stdout == "".join(f"[{t}]" for t in extra.split()), r.stdout


def test_familia_extra_check_wired_into_both_launchers():
    assert 'familia_key_args\nfamilia_extra_check "\\$@"\n' in SRC
    assert 'familia_extra_check "\\$@"\n' in LINUX_SRC
    for src in (SRC, LINUX_SRC):
        assert "--api-key*|--ssl*|--path*" in src


@pytest.mark.parametrize("argv", [["--host", "0.0.0.0"], ["-t", "4", "--port=1"], ["--path", "/x"], ["--api-key-file", "k"], ["--ssl-cert-file", "c"]])
def test_familia_extra_check_refuses_argv(argv):
    # F-7: the launcher's own "$@" is checked too, before set -- replaces it.
    r = subprocess.run(["sh", "-c", BLOCK + 'familia_extra_check "$@"; echo PASSED', "sh", *argv],
                       env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
    assert r.returncode == 2 and "PASSED" not in r.stdout, (argv, r.stderr)


def test_familia_extra_check_benign_argv_passes():
    r = subprocess.run(["sh", "-c", BLOCK + 'familia_extra_check "$@"; echo PASSED', "sh", "-t", "4"],
                       env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
    assert r.returncode == 0 and "PASSED" in r.stdout


def test_set_f_documented_and_left_on():
    # Boundary Reviewer: noglob stays on so the unquoted ${FAMILIA_EXTRA} in exec cannot glob.
    for src in (SRC, LINUX_SRC):
        assert "set -f is turned on here and deliberately LEFT ON" in src
    r = run('familia_extra_check; case $- in *f*) echo NOGLOB;; esac', {"FAMILIA_EXTRA": "-t 4"})
    assert "NOGLOB" in r.stdout


# --- Senior Developer F-7 / F-8 / F-9 ---------------------------------------------------------
def _key(tmp_path):
    k = tmp_path / "real" / "k"; k.parent.mkdir(); k.write_text("x"); k.chmod(0o600); return k


def test_f7_key_path_resolved_before_shared_storage_check(tmp_path):
    k = _key(tmp_path); (tmp_path / "via").symlink_to(k.parent)
    r = run('familia_key_args; echo "KF=$FAMILIA_KF"', {"FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(tmp_path / "via" / "k")})
    assert r.returncode == 0 and f"KF={k}" in r.stdout, r.stderr  # resolved path is what gets used
    # A symlinked parent landing on shared storage: stub realpath to report the resolved target.
    stub = tmp_path / "bin"; stub.mkdir(); rp = stub / "realpath"
    rp.write_text("#!/bin/sh\necho /storage/emulated/0/k\n"); rp.chmod(0o755)
    r = subprocess.run(["sh", "-c", BLOCK + "familia_key_args; echo PASSED"], capture_output=True, text=True,
                       env={"PATH": f"{stub}:{os.environ['PATH']}", "FAMILIA_BIND": "0.0.0.0", "FAMILIA_API_KEY_FILE": str(tmp_path / "via" / "k")})
    assert r.returncode == 2 and "PASSED" not in r.stdout and "(resolved) is on shared/adb storage" in r.stderr, r.stderr


SSHD_BLOCK = re.search(r"# BEGIN familia-sshd-verify.*?\n(.*?)# END familia-sshd-verify", SRC, re.S).group(1)


def _sshd_t(tmp_path, out, rc=0, cfg="PasswordAuthentication no\nKbdInteractiveAuthentication no\n"):
    stub = tmp_path / "sbin"; stub.mkdir(exist_ok=True); f = stub / "sshd"
    f.write_text(f"#!/bin/sh\n[ \"$1\" = -T ] || {{ echo RESTART-ATTEMPT >&2; exit 9; }}\necho \"$*\" > {tmp_path}/argv\nprintf '%s\\n' '{out}'\nexit {rc}\n"); f.chmod(0o755)
    c = tmp_path / "cfg"; c.write_text(cfg)
    return subprocess.run(["sh", "-c", SSHD_BLOCK + f'familia_sshd_verify "{c}" && echo OK'], capture_output=True, text=True,
                          env={"PATH": f"{stub}:{os.environ['PATH']}"})


@pytest.mark.parametrize("out,ok", [
    ("port 8022\npasswordauthentication no\nkbdinteractiveauthentication no", True),
    ("passwordauthentication yes\nkbdinteractiveauthentication no", False),
    ("passwordauthentication no\nkbdinteractiveauthentication yes", False),
    ("passwordauthentication no", False),
])
def test_f8_sshd_T_effective_config(tmp_path, out, ok):
    r = _sshd_t(tmp_path, out)
    assert ("OK" in r.stdout) == ok, r.stderr
    assert "RESTART-ATTEMPT" not in r.stderr


def test_f8_sshd_T_failure_refuses(tmp_path):
    r = _sshd_t(tmp_path, "bad config", rc=255)
    assert "OK" not in r.stdout and "failed" in r.stderr and "sshd -T -C user=" in r.stderr


GOOD_T = "passwordauthentication no\nkbdinteractiveauthentication no"


def test_f8b_sshd_T_uses_connection_spec(tmp_path):
    import getpass
    r = _sshd_t(tmp_path, GOOD_T); assert "OK" in r.stdout, r.stderr
    argv = (tmp_path / "argv").read_text().split()
    assert argv[:2] == ["-T", "-C"] and argv[2] == f"user={getpass.getuser()},addr=127.0.0.1,host=localhost" and argv[3] == "-f"


@pytest.mark.parametrize("cfg,ok", [
    ("PasswordAuthentication no\nMatch User bob\n  PasswordAuthentication yes\n", False),
    ("PasswordAuthentication no\nMatch Address 10.0.0.0/8\n\tKbdInteractiveAuthentication YES\n", False),
    ("Match all\n  ChallengeResponseAuthentication yes\n", False),
    ("Match Group x\n  HostbasedAuthentication yes\n", False),
    ("Match User bob\n  PubkeyAuthentication yes\n  PasswordAuthentication no\n", True),
    ("PasswordAuthentication yes\nPasswordAuthentication no\n", True),  # global; sshd -T decides
])
def test_f8b_match_block_enabling_auth_refused(tmp_path, cfg, ok):
    r = _sshd_t(tmp_path, GOOD_T, cfg=cfg)
    assert ("OK" in r.stdout) == ok, r.stderr
    if not ok: assert "Match block" in r.stderr


def test_f8b_running_sshd_not_restarted_note():
    assert "A running sshd keeps its old config; it is not restarted here." in SRC


def test_f8_verify_runs_after_config_written_before_start():
    i_write = SRC.index("printf 'KbdInteractiveAuthentication no\\n' >> \"$SSHD_CFG\"")
    i_ver = SRC.index('familia_sshd_verify "$SSHD_CFG" || exit 1')
    i_start = SRC.index("  run sshd\n")
    assert i_write < i_ver < i_start


def test_f9_bracketed_ipv6_loopback_passed_bare(tmp_path):
    k = _key(tmp_path)
    r = run('familia_key_args; echo "B=$B"', {"FAMILIA_BIND": "[::1]", "FAMILIA_API_KEY_FILE": str(k)})
    assert r.returncode == 0 and "B=::1\n" in r.stdout
    assert "H=::1" in LINUX_SRC and '--host "\\$H"' in LINUX_SRC


@pytest.mark.parametrize("content,ok", [
    ("k" * 32, True), ("k" * 32 + "\n", False), ("k" * 32 + "\r\n", False), ("ab\ncd", False), ("ab cd", False), ("\tabc", False), ("", False),
])
def test_key_content_rule_no_cr_lf_whitespace(tmp_path, content, ok):
    k = tmp_path / ".config" / "familia" / "api.key"; k.parent.mkdir(parents=True)
    k.write_bytes(content.encode()); k.chmod(0o600)
    r = gate({"HOME": str(tmp_path)})
    if ok: assert r.returncode == 0, r.stderr
    else: assert r.returncode == 2 and ("CR/LF/whitespace" in r.stderr or "empty" in r.stderr), r.stderr


def test_install_writes_key_with_printf_no_newline():
    i = SRC.index('FAMILIA_KEY_DEFAULT="$HOME'); assert "printf '%s'" in SRC[i:i + 700]


def test_env_scrub_unsets_llama_key_and_arg_vars():
    env = {"LLAMA_API_KEY": "evil", "LLAMA_ARG_API_KEY_FILE": "/tmp/evil", "LLAMA_ARG_HOST": "0.0.0.0", "LLAMA_ARG_N_GPU_LAYERS": "99", "LLAMA_CACHE": "keep"}
    r = run('familia_env_scrub; env | grep "^LLAMA" || true', env)
    assert r.returncode == 0, r.stderr
    assert "LLAMA_API_KEY=" not in r.stdout and "LLAMA_ARG_" not in r.stdout and "LLAMA_CACHE=keep" in r.stdout
    assert SRC.index("\nfamilia_env_scrub\n") < SRC.index("exec llama-server")
