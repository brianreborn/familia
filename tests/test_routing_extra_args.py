"""Extra launcher args without word splitting (platform routing-extra-args).

POSIX: the Termux launcher that install/termux/install.sh generates is rendered from its real
heredoc and run against a stub llama-server. Windows: scripts/windows/start.bat is checked
statically only; cmd.exe is NOT run here (no Windows runtime test)."""
import json, os, re, shlex, subprocess, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, "install", "termux", "install.sh")
START_BAT = os.path.join(ROOT, "scripts", "windows", "start.bat")

STUB = "#!/usr/bin/env python3\nimport json, os, sys\njson.dump(sys.argv[1:], open(os.environ['STUB_OUT'], 'w'))\n"


def _render_launcher(tmp_path):
    src = open(INSTALL, encoding="utf-8").read()
    m = re.search(r'cat > "\$LAUNCH" <<EOS\n(.*?)\nEOS\n', src, re.S)
    assert m, "launcher heredoc not found"
    body = m.group(1)
    out = tmp_path / "familia-start"
    script = f'cat > "$1" <<EOS\n{body}\nEOS\n'
    subprocess.run(["sh", "-c", script, "sh", str(out)], check=True,
                   env=dict(os.environ, PREFIX_DIR=str(tmp_path / "pfx"), VKDIR=str(tmp_path / "vk")))
    return out


@pytest.fixture
def launcher(tmp_path):
    if os.name != "posix": pytest.skip("POSIX sh")
    l = _render_launcher(tmp_path)
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / "llama-server").write_text(STUB); (bindir / "llama-server").chmod(0o755)
    model = tmp_path / "my model ü.gguf"; model.write_bytes(b"GGUF")
    cwd = tmp_path / "cwd"; cwd.mkdir()
    for decoy in ("a.gguf", "b.gguf", "starX", "zz"): (cwd / decoy).write_bytes(b"")
    out = tmp_path / "argv.json"

    def run(*args, extra=None):
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAMILIA_MODEL=str(model), STUB_OUT=str(out))
        env.pop("FAMILIA_EXTRA", None)
        if extra is not None: env["FAMILIA_EXTRA"] = extra
        r = subprocess.run(["sh", str(l), *args], env=env, cwd=str(cwd), capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        a = json.load(open(out))
        assert a[a.index("-m") + 1] == str(model)
        return a[a.index("-c") + 2:]                      # everything after the fixed args
    return run


TRICKY = ["--alias", "my model", "--chat-template-file", "/t/日本語 テンプレ.jinja", "*", "[ab].gguf",
          "star?", "it's", 'say "hi"', "$HOME", "back\\slash", "e\u0301"]


def test_launcher_positional_args_pass_exactly(launcher):
    assert launcher(*TRICKY) == TRICKY


def test_launcher_familia_extra_is_quoted_argv_not_split_or_globbed(launcher):
    assert launcher(extra=shlex.join(TRICKY)) == TRICKY


def test_launcher_plain_familia_extra_backward_compatible(launcher):
    assert launcher(extra="--temp 0.7 -b 512") == ["--temp", "0.7", "-b", "512"]


def test_launcher_positional_then_familia_extra(launcher):
    assert launcher("--x", "a b", extra="--y 'c d'") == ["--x", "a b", "--y", "c d"]


def test_launcher_no_extra(launcher):
    assert launcher() == []


def test_launcher_has_no_unquoted_extra_expansion():
    src = open(INSTALL, encoding="utf-8").read()
    assert not re.search(r'(?<!")\\\$\{FAMILIA_EXTRA:-\}(?!")', src.split("eval")[-1].split("\n", 1)[1])
    assert '"\\$@"' in src


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
        assert not re.search(r"%[A-Za-z_]+%", l), l       # %-expanded "!" would be eaten
    # every path / value is quoted so spaces in %USERPROFILE% / models dir survive
    for v in ("BIN", "MODEL", "LOG"):
        assert f'"!{v}!"' in launch
    assert ">>" in launch and '"!LOG!"' in launch.split(">>", 1)[1]


def test_start_bat_delayed_expansion_not_enabled_before_paths_are_set():
    """Enabling it earlier would eat '!' in %USERPROFILE%/FAMILIA_MODELS during the set lines."""
    code = _code(_bat())
    first = next(n for n, l in enumerate(code) if "enabledelayedexpansion" in l.lower())
    assert all("set \"" not in l.lower() for l in code[first + 1:])


def test_start_bat_documents_raw_fragment_contract():
    doc = "\n".join(_bat())
    assert "raw Windows command-line fragment" in doc and "CommandLineToArgvW" in doc


def _cmdline_to_argv(s):
    """Reference CommandLineToArgvW splitting (MS C runtime rules) for the documentation example."""
    args, cur, inq, i, have = [], [], False, 0, False
    while i < len(s):
        c = s[i]
        if c == "\\":
            j = i
            while j < len(s) and s[j] == "\\": j += 1
            n = j - i
            if j < len(s) and s[j] == '"':
                cur.append("\\" * (n // 2)); have = True
                if n % 2: cur.append('"'); i = j + 1
                else: i = j
            else:
                cur.append("\\" * n); i = j; have = True
            continue
        if c == '"': inq = not inq; have = True
        elif c in " \t" and not inq:
            if have: args.append("".join(cur)); cur, have = [], False
        else: cur.append(c); have = True
        i += 1
    if have: args.append("".join(cur))
    return args


def test_documented_extra_example_splits_as_intended():
    line = next(l for l in _bat() if 'set "FAMILIA_EXTRA=' in l)
    frag = line.split('set "FAMILIA_EXTRA=', 1)[1].rsplit('"', 1)[0]
    assert _cmdline_to_argv(frag) == ["--alias", "my model", "--chat-template-file", "C:\\Users\\Jos Perez\\t.jinja"]
