"""FAMILIA_EXTRA / launcher argv under F-6 (platform routing-extra-args, re-cut on development).

F-6 (Boundary) stays authoritative: FAMILIA_EXTRA is split on whitespace under set -f, any
--host* --port* --api-key* --ssl* --path* token refuses the whole launch, and the launcher's own
argv is checked and then dropped (F-7). This file renders the real familia-start heredocs from
install/termux/install.sh and install/linux/install.sh and runs them against a stub llama-server.
Nothing is eval'd: quoted and '='-joined forms are refused or reach llama-server literally, never
unquoted into a bind/port/key/TLS/path override. Windows start.bat is checked statically only
(cmd.exe is not run here)."""
import json, os, re, subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMUX = os.path.join(ROOT, "install", "termux", "install.sh")
LINUX = os.path.join(ROOT, "install", "linux", "install.sh")
START_BAT = os.path.join(ROOT, "scripts", "windows", "start.bat")
STUB = "#!/usr/bin/env python3\nimport json, os, sys\njson.dump(sys.argv[1:], open(os.environ['STUB_OUT'], 'w'))\n"
HEREDOC = re.compile(r'cat > "\$LAUNCH" <<EOS\n(.*?)\nEOS\n', re.S)


def _body(path):
    m = HEREDOC.search(open(path, encoding="utf-8").read())
    assert m, f"launcher heredoc not found in {path}"
    return m.group(1)


def _render(tmp_path, path):
    out = tmp_path / "familia-start"
    subprocess.run(["sh", "-c", f'cat > "$1" <<EOS\n{_body(path)}\nEOS\n', "sh", str(out)], check=True,
                   env=dict(os.environ, PREFIX_DIR=str(tmp_path / "pfx"), VKDIR=str(tmp_path / "vk"),
                            PREFIX=str(tmp_path / "pfx")))
    return out


@pytest.fixture(params=["termux", "linux"])
def launcher(tmp_path, request):
    if os.name != "posix":
        pytest.skip("POSIX sh")
    script = _render(tmp_path, TERMUX if request.param == "termux" else LINUX)
    bindir = tmp_path / "bin"; bindir.mkdir()
    for d in (bindir, tmp_path / "pfx" / "runtime" / "current"):
        d.mkdir(parents=True, exist_ok=True)
        (d / "llama-server").write_text(STUB); (d / "llama-server").chmod(0o755)
    model = tmp_path / "m.gguf"; model.write_bytes(b"GGUF")
    key = tmp_path / "keys" / "api.key"; key.parent.mkdir(); key.write_text("k" * 16); key.chmod(0o600)
    cwd = tmp_path / "cwd"; cwd.mkdir()
    for decoy in ("a.gguf", "b.gguf", "--host=0.0.0.0", "zz"):
        (cwd / decoy).write_bytes(b"")
    out = tmp_path / "argv.json"

    def run(*argv, extra=None):
        env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp_path), "FAMILIA_MODEL": str(model),
               "FAMILIA_API_KEY_FILE": str(key), "STUB_OUT": str(out)}
        if extra is not None:
            env["FAMILIA_EXTRA"] = extra
        if out.exists():
            out.unlink()
        r = subprocess.run(["sh", str(script), *argv], env=env, cwd=str(cwd), capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            assert not out.exists(), "llama-server ran although the launcher failed"
            return r, None
        a = json.load(open(out))
        i = a.index("--api-key-file")
        assert a[i + 1] == str(key) and a.count("--api-key-file") == 1
        assert a[a.index("--host") + 1] == "127.0.0.1" and a.count("--host") == 1 and a.count("--port") == 1
        return r, a[i + 2:]
    return run


@pytest.mark.parametrize("extra,want", [
    (None, []), ("", []),
    ("--temp 0.7 -b 512", ["--temp", "0.7", "-b", "512"]),
    ("  -t\t4   --n-predict 64 ", ["-t", "4", "--n-predict", "64"]),
    ("--n-predict 64 * [ab].gguf ?z", ["--n-predict", "64", "*", "[ab].gguf", "?z"]),   # set -f: no glob
    ("--alias café-日本", ["--alias", "café-日本"]),
])
def test_plain_extra_reaches_llama_server_exactly(launcher, extra, want):
    r, tail = launcher(extra=extra)
    assert tail == want, r.stderr


@pytest.mark.parametrize("extra", [
    "--host 0.0.0.0", "--host=0.0.0.0", "-t 4 --port=1", "--api-key-file=/tmp/k", "--ssl-key-file k", "--path=/x",
    # quoted forms: never unquoted (no eval), refused before llama-server runs
    "'--host' 0.0.0.0", '"--host" 0.0.0.0', "'--host=0.0.0.0'", '"--port=1"', "\\--host 0.0.0.0",
    "--alias 'my model'", '--alias "my model"', "-t 4 it's",
    # glob that would match a decoy file named --host=0.0.0.0 in cwd: set -f keeps it literal and it is refused
    "--host*",
])
def test_override_and_quoted_extra_refused_before_exec(launcher, extra):
    r, tail = launcher(extra=extra)
    assert r.returncode == 2 and tail is None and "refusing" in r.stderr, (extra, r.stderr)


def test_glob_matching_override_decoy_is_not_expanded(launcher):
    # '*' would expand to the decoy file '--host=0.0.0.0' if globbing were on; it must stay '*'.
    r, tail = launcher(extra="--n-predict 1 *")
    assert tail == ["--n-predict", "1", "*"], r.stderr


@pytest.mark.parametrize("argv", [["--host", "0.0.0.0"], ["--host=0.0.0.0"], ["-t", "4", "--port=1"], ["--api-key=x"]])
def test_override_argv_refused(launcher, argv):
    r, tail = launcher(*argv)
    assert r.returncode == 2 and tail is None, r.stderr


@pytest.mark.parametrize("argv", [["-t", "4"], ["'--host'", "0.0.0.0"], ["--alias", "my model"]])
def test_argv_is_never_forwarded(launcher, argv):
    # F-7 (Boundary): argv is checked, then dropped; a literal-quote token cannot become --host.
    r, tail = launcher(*argv)
    assert r.returncode == 0 and tail == [], r.stderr


@pytest.mark.parametrize("path", [TERMUX, LINUX], ids=["termux", "linux"])
def test_launcher_never_evals(path):
    code = [l for l in _body(path).splitlines() if not l.lstrip().startswith("#")]
    assert not any(re.search(r"(^|[;&|\s])eval(\s|$)", l) for l in code)


@pytest.mark.parametrize("path", [TERMUX, LINUX], ids=["termux", "linux"])
def test_literal_check_runs_after_f6_check(path):
    body = _body(path)
    i = body.index('\nfamilia_extra_check "\\$@"\n')
    assert body[i:].startswith('\nfamilia_extra_check "\\$@"\nfamilia_extra_literal_check\n')
    assert "--host*|--port*|--api-key*|--ssl*|--path*" in body      # F-6 list untouched


def test_literal_check_identical_in_both_launchers():
    pat = re.compile(r"familia_extra_literal_check\(\) \{\n.*?\n\}\n", re.S)
    t, l = pat.search(_body(TERMUX)), pat.search(_body(LINUX))
    assert t and l and t.group(0) == l.group(0)


# ---- Windows start.bat: static checks only (cmd.exe semantics, not executed) ----------------

def _bat():
    return open(START_BAT, encoding="utf-8", newline="").read().splitlines()


def _code(lines):
    return [l for l in lines if l.strip() and not l.lstrip().lower().startswith(("rem", "::"))]


def test_start_bat_never_expands_extra_with_percent():
    """%FAMILIA_EXTRA% is parsed by cmd (phase 1): & | < > ^ would split/redirect the launch."""
    assert not any("%FAMILIA_EXTRA%" in l for l in _code(_bat()))


def test_start_bat_launch_uses_delayed_expansion_only():
    code = _code(_bat())
    i = next(n for n, l in enumerate(code) if l.lstrip().startswith('"!BIN!"'))
    launch, echo = code[i], code[i - 1]
    assert any(l.strip().lower() == "setlocal enabledelayedexpansion" for l in code[:i])
    assert "!FAMILIA_EXTRA!" in launch
    for l in (launch, echo, code[i + 1]):
        assert not re.search(r"%[A-Za-z_]+%", l), l
    for v in ("BIN", "MODEL", "LOG"):
        assert f'"!{v}!"' in launch


def test_start_bat_delayed_expansion_not_enabled_before_paths_are_set():
    code = _code(_bat())
    first = next(n for n, l in enumerate(code) if "enabledelayedexpansion" in l.lower())
    assert all("set \"" not in l.lower() for l in code[first + 1:])
