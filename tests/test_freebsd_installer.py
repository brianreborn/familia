"""install/freebsd/install-familia.sh: POSIX sh, opt-in root, pinned refs, 0600 key, launcher guards."""
import os, shutil, subprocess, stat
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "install" / "freebsd" / "install-familia.sh"
DEPS = REPO / "install" / "freebsd" / "deps.sh"
HELP_OK = "--api-key-file FNAME"
LLAMA_SHA = "c3df4b7e22a1ac38da663552d19e649dd97ca936"


def _env(tmp_path, help_text=HELP_OK, with_llama=True, version="version: 11969 (c3df4b7)", built_sha=LLAMA_SHA):
    log = tmp_path / "calls.log"
    shim = tmp_path / "bin"; shim.mkdir()
    for name in ("sudo", "doas", "pkg"):
        p = shim / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit 99\n'); p.chmod(0o755)
    home = tmp_path / "home"; home.mkdir()
    if with_llama:  # reuse-existing-build path (skill §4); no real llama.cpp build on the box
        rt = home / ".local/share/familia/runtime/b11969"; rt.mkdir(parents=True)
        p = rt / "llama-server"
        (rt / ".built-sha").write_text(built_sha + "\n")
        p.write_text('#!/bin/sh\nif [ "${1:-}" = --help ]; then echo "' + help_text + '"; exit 0; fi\n'
                     'if [ "${1:-}" = --version ]; then echo "' + version + '"; exit 0; fi\n'
                     f'echo "llama-server $*" >> "{log}"\n'
                     f'echo "LANG=$LANG LC_CTYPE=${{LC_CTYPE:-}} LC_ALL=${{LC_ALL:-}}" >> "{log}"\nenv | grep "^LLAMA" >> "{log}" || true\n')
        p.chmod(0o755)
    src = tmp_path / "src"; src.mkdir()
    g = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    (src / "README").write_text("x\n")
    for a in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "s"]):
        subprocess.run(["git", *a], cwd=src, check=True, env=g, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}", "HOME": str(home),
           "FAMILIA_REPO_URL": str(src), "FAMILIA_ALLOW_NON_FREEBSD": "yes",
           "FAMILIA_REF_OVERRIDE": sha, "FAMILIA_TEST_MODE": "1",
           "PYTHONUSERBASE": os.environ.get("PYTHONUSERBASE", os.path.expanduser("~/.local"))}
    for v in ("LANG", "LC_ALL", "LC_CTYPE"):
        env.pop(v, None)
    return log, env


def _sh(args, env, shell="sh"):
    return subprocess.run([shell, str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)


def _installed(tmp_path, **kw):
    log, env = _env(tmp_path, **kw)
    r = _sh(["--yes"], env)
    assert r.returncode == 0, r.stderr
    home = Path(env["HOME"])
    model = tmp_path / "m.gguf"; model.write_text("")
    return log, {**env, "FAMILIA_MODEL": str(model)}, home / ".local/bin/familia-start", home


def _launch(launch, env, *args):
    return subprocess.run(["sh", str(launch), *args], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("shell", ["sh", "dash", "posh"])
@pytest.mark.parametrize("script", [SCRIPT, DEPS])
def test_syntax(shell, script):
    if not shutil.which(shell):
        pytest.skip(shell)
    subprocess.run([shell, "-n", str(script)], check=True)


@pytest.mark.parametrize("script", [SCRIPT, DEPS])
def test_shellcheck(script):
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck")
    subprocess.run(["shellcheck", "-s", "sh", "-x", str(script)], check=True, cwd=script.parent)


def test_missing_deps_halts_without_root(tmp_path):
    log, env = _env(tmp_path, with_llama=False)
    if shutil.which("cmake") and shutil.which("c++"):
        pytest.skip("box has cmake+c++; nothing missing")
    r = _sh([], env)
    assert r.returncode != 0 and "missing dependencies" in r.stderr
    r = _sh(["--auto-deps"], env)  # no tty: must refuse, never call sudo/doas/pkg
    assert r.returncode != 0
    assert not log.exists() or not log.read_text()


def test_dry_run_changes_nothing(tmp_path):
    log, env = _env(tmp_path)
    before = sorted(p for p in Path(env["HOME"]).rglob("*"))
    r = _sh(["--dry-run"], env)
    assert r.returncode == 0, r.stderr
    assert sorted(Path(env["HOME"]).rglob("*")) == before


def test_pinned_ref_checked_out_and_verified(tmp_path):
    log, env, launch, home = _installed(tmp_path)
    head = subprocess.run(["git", "-C", str(home / ".local/share/familia/repo"), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == env["FAMILIA_REF_OVERRIDE"]


def test_pinned_ref_missing_refused(tmp_path):
    log, env = _env(tmp_path)
    r = _sh(["--yes"], {**env, "FAMILIA_REF_OVERRIDE": "0" * 40})
    assert r.returncode != 0
    r = _sh(["--yes"], {**env, "FAMILIA_REF_OVERRIDE": "main"})
    assert r.returncode != 0 and "40-hex" in r.stderr


def test_script_pins_constants():
    t = SCRIPT.read_text()
    assert "LLAMA_TAG=b11969" in t and "LLAMA_SHA=c3df4b7e22a1ac38da663552d19e649dd97ca936" in t
    assert "\nFAMILIA_REF=" in t and "llama-cpp" not in t.split("Pinned llama.cpp")[1].split("\n")[0]


@pytest.mark.parametrize("prefix", ["/tmp/a b", "/tmp/a$(x)", "/tmp/a`x`", "/tmp/../etc", "rel/dir", "/tmp/a\"b"])
def test_b1_unsafe_prefix_refused(tmp_path, prefix):
    log, env = _env(tmp_path)
    r = _sh(["--yes", "--prefix", prefix], env)
    assert r.returncode != 0
    assert not (tmp_path / "home/.local/bin/familia-start").exists()


def test_b1_unsafe_bin_dir_refused(tmp_path):
    log, env = _env(tmp_path)
    r = _sh(["--yes"], {**env, "FAMILIA_BIN_DIR": "/tmp/x;y"})
    assert r.returncode != 0


def test_install_key_and_f6_refusals(tmp_path):
    log, env, launch, home = _installed(tmp_path)
    key = home / ".config/familia/api.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600 and len(key.read_text()) == 64
    for extra in ("--host 0.0.0.0", "--port=1", "--api-key x", "--ssl-key-file k", "--path /"):
        r = _launch(launch, {**env, "FAMILIA_EXTRA": extra})
        assert r.returncode == 2 and "refusing" in r.stderr, extra
    assert _launch(launch, env, "--host=0.0.0.0").returncode == 2
    assert _launch(launch, {**env, "FAMILIA_BIND": "0.0.0.0"}).returncode == 2
    key.chmod(0o644)
    r = _launch(launch, env); assert r.returncode == 2 and "0600" in r.stderr
    key.chmod(0o600)
    r = _launch(launch, env); assert r.returncode == 0, r.stderr
    call = log.read_text()
    assert "--host 127.0.0.1" in call and f"--api-key-file {key}" in call
    assert "sudo" not in call and "doas" not in call and "pkg " not in call
    k1 = key.read_text(); assert _sh(["--yes"], env).returncode == 0; assert key.read_text() == k1


def test_b2_key_owner_mismatch_refused(tmp_path):
    log, env, launch, home = _installed(tmp_path)
    fake = tmp_path / "fakeid"; fake.mkdir()
    (fake / "id").write_text("#!/bin/sh\necho 4242\n"); (fake / "id").chmod(0o755)
    r = _launch(launch, {**env, "PATH": f"{fake}:{env['PATH']}"})
    assert r.returncode == 2 and "not owned" in r.stderr


def test_b3_llama_env_scrubbed(tmp_path):
    log, env, launch, home = _installed(tmp_path)
    r = _launch(launch, {**env, "LLAMA_API_KEY": "x", "LLAMA_ARG_SSL_KEY_FILE": "/k",
                         "LLAMA_ARG_STATIC_PATH": "/", "LLAMA_ARG_HOST": "0.0.0.0"})
    assert r.returncode == 0, r.stderr
    assert "LLAMA" not in "\n".join(l for l in log.read_text().splitlines() if not l.startswith("llama-server"))


@pytest.mark.parametrize("model", ["../m.gguf", "a/../../m.gguf", "sub/m.gguf", "/nonexistent/m.gguf"])
def test_b4_model_paths_refused(tmp_path, model):
    log, env, launch, home = _installed(tmp_path)
    r = _launch(launch, {**env, "FAMILIA_MODEL": model})
    assert r.returncode == 2


def test_b4_bare_model_name_ok(tmp_path):
    log, env, launch, home = _installed(tmp_path)
    r = _launch(launch, {**env, "FAMILIA_MODEL": "m.gguf"})
    assert r.returncode == 0
    assert str(home / ".local/share/familia/models/m.gguf") in log.read_text()


def test_na_lang_default_and_nb_localhost(tmp_path):
    log, env, launch, home = _installed(tmp_path)
    assert _launch(launch, {**env, "FAMILIA_BIND": "localhost"}).returncode == 0
    t = log.read_text()
    assert "--host 127.0.0.1" in t and "LANG=C.UTF-8" in t
    assert _launch(launch, {**env, "LANG": "de_DE.UTF-8"}).returncode == 0
    assert "LANG=de_DE.UTF-8" in log.read_text()


def test_nc_python311_fallback(tmp_path):
    log, env = _env(tmp_path)
    py = shutil.which("python3")
    lim = tmp_path / "lim"; lim.mkdir()
    for d in os.environ["PATH"].split(":") + [str(tmp_path / "bin")]:
        if not os.path.isdir(d):
            continue
        for n in os.listdir(d):
            if n.startswith("python") or (lim / n).exists():
                continue
            (lim / n).symlink_to(os.path.join(d, n))
    (lim / "python3.11").symlink_to(py)
    r = _sh(["--yes"], {**env, "PATH": str(lim)})
    assert "missing dependencies" not in r.stderr or "python3" not in r.stderr.split("missing dependencies")[1].split("\n")[0], r.stderr


def test_nc_missing_python_named_python3(tmp_path):
    t = SCRIPT.read_text()
    assert 'missing="$missing python3"' in t


def test_llama_without_api_key_file_refused(tmp_path):
    log, env = _env(tmp_path, help_text="--api-key KEY")
    r = _sh(["--yes"], env)
    assert r.returncode != 0 and "--api-key-file" in r.stderr


def test_l1_ref_override_refused_outside_test_mode(tmp_path):
    log, env = _env(tmp_path)
    env.pop("FAMILIA_TEST_MODE")
    r = _sh(["--yes"], env)
    assert r.returncode != 0 and "test-only" in r.stderr
    assert not (Path(env["HOME"]) / ".local/share/familia/repo").exists()
    r = _sh(["--dry-run"], env)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("kw", [{"built_sha": "0" * 40}, {"version": "version: 11000 (deadbee)"}])
def test_l2_stale_build_not_reused(tmp_path, kw):
    log, env = _env(tmp_path, **kw)
    r = _sh(["--yes"], {**env, "FAMILIA_LLAMA_URL": str(tmp_path / "nonexistent")})
    assert "already built" not in r.stderr
    assert r.returncode != 0  # tries to rebuild (or halts on missing cmake), never reuses


def test_l2_verified_build_reused(tmp_path):
    log, env = _env(tmp_path)
    r = _sh(["--yes"], env)
    assert r.returncode == 0 and "already built and verified" in r.stderr


@pytest.mark.parametrize("loc,want_ctype,want_lang", [
    ({}, "C.UTF-8", "C.UTF-8"),
    ({"LANG": "C"}, "C.UTF-8", "C.UTF-8"),
    ({"LANG": "POSIX"}, "C.UTF-8", "C.UTF-8"),
    ({"LC_ALL": "C", "LANG": "de_DE.UTF-8"}, "C.UTF-8", "de_DE.UTF-8"),
    ({"LANG": "ja_JP.UTF-8"}, "", "ja_JP.UTF-8"),
])
def test_na_locale_utf8(tmp_path, loc, want_ctype, want_lang):
    log, env, launch, home = _installed(tmp_path)
    assert _launch(launch, {**env, **loc}).returncode == 0
    line = [l for l in log.read_text().splitlines() if l.startswith("LANG=")][-1]
    assert f"LANG={want_lang} " in line and f"LC_CTYPE={want_ctype} " in line
    assert "LC_ALL=C" not in line and "LC_ALL=POSIX" not in line
