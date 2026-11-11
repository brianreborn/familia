"""Launcher argv pass-through (#279, ported from swarm/platform/routing-extra-args onto main).

The original branch made FAMILIA_EXTRA a shell-quoted argv loaded with eval. Main has since made
FAMILIA_EXTRA deliberately whitespace-split (F-6, 0c7e4ef) so the token guard and llama-server see
the same tokens, so that part is NOT ported (see the PR). What is ported: the generated
familia-start (Linux and Termux) passes its own arguments to llama-server exactly, after they pass
the same override check, instead of checking them and then dropping them.

The launcher is rendered from its real heredoc and run against a stub llama-server (POSIX only)."""
import json, os, re, subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMUX = os.path.join(ROOT, "install", "termux", "install.sh")
LINUX = os.path.join(ROOT, "install", "linux", "install.sh")
STUB = "#!/usr/bin/env python3\nimport json, os, sys\njson.dump(sys.argv[1:], open(os.environ['STUB_OUT'], 'w'))\n"
HEREDOC = re.compile(r'cat > "\$LAUNCH" <<EOS\n(.*?)\nEOS\n', re.S)


def _render(tmp_path, kind):
    m = HEREDOC.search(open(TERMUX if kind == "termux" else LINUX, encoding="utf-8").read())
    assert m, "launcher heredoc not found"
    out = tmp_path / "familia-start"
    pfx = tmp_path / "pfx"
    subprocess.run(["sh", "-c", 'cat > "$1" <<EOS\n' + m.group(1) + "\nEOS\n", "sh", str(out)], check=True,
                   env=dict(os.environ, PREFIX_DIR=str(pfx), PREFIX=str(pfx), VKDIR=str(tmp_path / "vk")))
    return out


@pytest.fixture(params=["termux", "linux"])
def launcher(tmp_path, request):
    if os.name != "posix":
        pytest.skip("POSIX sh")
    script = _render(tmp_path, request.param)
    bindir = tmp_path / "bin"; bindir.mkdir()
    for d in (bindir, tmp_path / "pfx" / "runtime" / "current"):      # termux: PATH; linux: $PREFIX runtime
        d.mkdir(parents=True, exist_ok=True)
        (d / "llama-server").write_text(STUB); (d / "llama-server").chmod(0o755)
    model = tmp_path / "my model.gguf"; model.write_bytes(b"GGUF")
    key = tmp_path / "home" / "api.key"; key.parent.mkdir(); key.write_text("k" * 32); key.chmod(0o600)
    cwd = tmp_path / "cwd"; cwd.mkdir()
    for decoy in ("a.gguf", "b.gguf", "starX", "zz"):
        (cwd / decoy).write_bytes(b"")
    out = tmp_path / "argv.json"

    def run(*args, extra=None, ok=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("FAMILIA_", "LLAMA_"))}
        env.update(PATH=f"{bindir}:{os.environ['PATH']}", HOME=str(key.parent), FAMILIA_MODEL=str(model),
                   FAMILIA_API_KEY_FILE=str(key), STUB_OUT=str(out))
        if extra is not None:
            env["FAMILIA_EXTRA"] = extra
        r = subprocess.run(["sh", str(script), *args], env=env, cwd=str(cwd), capture_output=True, text=True, timeout=30)
        if not ok:
            return r
        assert r.returncode == 0, r.stderr
        a = json.load(open(out))
        assert a[a.index("-m") + 1] == str(model)
        i = a.index("--api-key-file")
        assert a[i + 1] == str(key)
        return a[i + 2:]                                   # everything after the key
    return run


TRICKY = ["--alias", "my model", "--chat-template-file", "/t/日本語 テンプレ.jinja", "*", "[ab].gguf",
          "star?", "it's", 'say "hi"', "$HOME", "back\\slash", "e\u0301"]


def test_launcher_positional_args_pass_exactly(launcher):
    assert launcher(*TRICKY) == TRICKY


def test_launcher_plain_familia_extra_whitespace_split_unglobbed(launcher):
    assert launcher(extra="--temp 0.7 -b 512 *.gguf") == ["--temp", "0.7", "-b", "512", "*.gguf"]


def test_launcher_positional_then_familia_extra(launcher):
    assert launcher("--x", "a b", extra="--y z") == ["--x", "a b", "--y", "z"]


def test_launcher_no_extra(launcher):
    assert launcher() == []


@pytest.mark.parametrize("argv", [["--host", "0.0.0.0"], ["--port=1"], ["--api-key-file", "/k"], ["--ssl-key-file", "c"], ["--path", "/x"]])
def test_launcher_override_in_argv_still_refused(launcher, argv):
    r = launcher("-t", "2", *argv, ok=False)
    assert r.returncode == 2 and "refusing" in r.stderr, r.stderr


def test_systemd_unit_passes_no_argv_and_no_extra_in_execstart():
    """Under systemd FAMILIA_EXTRA arrives only via EnvironmentFile; ExecStart passes no argv."""
    src = open(LINUX, encoding="utf-8").read()
    unit = re.search(r'cat > "\$UNIT" <<EOS\n(.*?)\nEOS\n', src, re.S).group(1)
    assert "ExecStart=$LAUNCH" in unit.splitlines() and "FAMILIA_EXTRA" not in unit
