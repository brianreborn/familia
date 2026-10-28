"""scripts/install-cli.sh: per-user `familia` on PATH (docs/install.md#familia-on-your-path). Temp HOME only."""
import os, shutil, subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "scripts", "install-cli.sh")
SH = shutil.which("dash") or "sh"


def env(home, **kw):
    e = {k: v for k, v in os.environ.items() if not k.startswith("XDG_") and k not in ("PREFIX", "TERMUX_VERSION")}
    e.update(HOME=str(home), PATH="/usr/bin:/bin", **kw)
    return e


def cli(home, *a, script=CLI, **kw):
    return subprocess.run([SH, script, *a], capture_output=True, text=True, env=env(home, **kw),
                          stdin=subprocess.DEVNULL, timeout=60)


def tree(d):
    return sorted(os.path.relpath(os.path.join(r, f), d) for r, ds, fs in os.walk(d) for f in fs + ds)


def test_dry_run_writes_nothing(tmp_path):
    (tmp_path / ".profile").write_text("x=1\n")
    before = tree(tmp_path)
    for a in (["--dry-run"], ["path", "--add", "--dry-run"], ["path", "--remove", "--dry-run"], ["uninstall", "--dry-run"]):
        r = cli(tmp_path, *a)
        assert r.returncode == 0, (a, r.stdout + r.stderr)
    assert tree(tmp_path) == before and (tmp_path / ".profile").read_text() == "x=1\n"
    r = cli(tmp_path, "--dry-run")
    assert "[dry-run] write" in r.stdout and 'export PATH="$HOME/.local/bin:$PATH"' in r.stdout


def test_shim_runs_familia_and_reinstall_is_idempotent(tmp_path):
    r = cli(tmp_path)
    assert r.returncode == 0, r.stderr
    shim = tmp_path / ".local/bin/familia"
    lines = shim.read_text().splitlines()
    assert lines == ["#!/bin/sh", "exec '%s' \"$@\"" % os.path.join(ROOT, "familia")]
    assert not shim.is_symlink() and os.access(shim, os.X_OK)
    out = subprocess.run([str(shim), "help"], capture_output=True, text=True, env=env(tmp_path), cwd=str(tmp_path))
    assert out.returncode == 0 and "familia" in out.stdout
    man = tmp_path / ".local/state/familia/installed.txt"
    snap = (shim.read_text(), man.read_text())
    r = cli(tmp_path)
    assert r.returncode == 0 and "up to date" in r.stdout
    assert (shim.read_text(), man.read_text()) == snap
    assert man.read_text().splitlines()[0] == str(shim)


def test_xdg_and_prefix(tmp_path):
    b = tmp_path / "xb"
    assert cli(tmp_path, XDG_BIN_HOME=str(b), XDG_STATE_HOME=str(tmp_path / "st")).returncode == 0
    assert (b / "familia").exists() and (tmp_path / "st/familia/installed.txt").exists()
    assert cli(tmp_path, "--prefix", str(tmp_path / "pfx")).returncode == 0
    assert (tmp_path / "pfx/bin/familia").exists()
    r = cli(tmp_path, "on-path-check", XDG_BIN_HOME="relative/ignored")
    assert r.returncode == 2  # unknown argument


def test_refuses_foreign_file(tmp_path):
    f = tmp_path / ".local/bin/familia"
    f.parent.mkdir(parents=True)
    f.write_text("#!/bin/sh\necho mine\n")
    r = cli(tmp_path)
    assert r.returncode == 1 and "not a familia shim" in r.stderr
    assert f.read_text() == "#!/bin/sh\necho mine\n"


def test_path_add_remove_only_touch_marked_block(tmp_path):
    p = tmp_path / ".profile"
    p.write_text("export FOO=1\n# >>> other >>>\nkeep\n# <<< other <<<\nalias ll=ls")  # no trailing newline
    r = cli(tmp_path, "path", "--add")  # no terminal, no --yes: refuses
    assert r.returncode == 2 and "x" not in p.read_text().split("ll=ls")[1]
    assert cli(tmp_path, "path", "--add", "--yes").returncode == 0
    once = p.read_text()
    assert once.count("# >>> familia >>>") == 1 and once.startswith("export FOO=1\n# >>> other >>>\nkeep\n")
    assert cli(tmp_path, "path", "--add", "--yes").returncode == 0
    assert p.read_text() == once
    # the block works in a POSIX shell, and does not duplicate an existing entry
    out = subprocess.run([SH, "-c", ". ./.profile; echo $PATH"], capture_output=True, text=True, env=env(tmp_path), cwd=str(tmp_path))
    assert out.stdout.strip() == f"{tmp_path}/.local/bin:/usr/bin:/bin"
    out = subprocess.run([SH, "-c", ". ./.profile; . ./.profile; echo $PATH"], capture_output=True, text=True, env=env(tmp_path), cwd=str(tmp_path))
    assert out.stdout.strip().count(".local/bin") == 1
    assert cli(tmp_path, "path", "--remove", "--yes").returncode == 0
    assert p.read_text() == "export FOO=1\n# >>> other >>>\nkeep\n# <<< other <<<\nalias ll=ls\n"
    r = cli(tmp_path, "path", "--remove", "--yes")
    assert r.returncode == 0 and "nothing to remove" in r.stdout


def test_uninstall_removes_only_manifest_files(tmp_path):
    bin_ = tmp_path / ".local/bin"
    bin_.mkdir(parents=True)
    (bin_ / "other").write_text("keep")
    p = tmp_path / ".profile"
    p.write_text("a=1\n")
    assert cli(tmp_path).returncode == 0
    assert cli(tmp_path, "path", "--add", "--yes").returncode == 0
    r = cli(tmp_path, "uninstall")  # no terminal: preview only
    assert r.returncode == 0 and "nothing removed" in r.stdout and (bin_ / "familia").exists()
    r = cli(tmp_path, "uninstall", "--yes")
    assert r.returncode == 0, r.stderr
    assert sorted(os.listdir(bin_)) == ["other"] and p.read_text() == "a=1\n"
    assert not (tmp_path / ".local/state/familia").exists()
    assert "nothing recorded" in cli(tmp_path, "uninstall", "--yes").stdout


def test_uninstall_keeps_a_replaced_file(tmp_path):
    assert cli(tmp_path).returncode == 0
    f = tmp_path / ".local/bin/familia"
    f.write_text("#!/bin/sh\necho replaced by the user\n")
    r = cli(tmp_path, "uninstall", "--yes")
    assert "keep" in r.stdout and f.read_text().endswith("user\n")


def test_man_page_and_completion_linked_when_present(tmp_path):
    co = tmp_path / "checkout"
    (co / "scripts").mkdir(parents=True)
    shutil.copy(CLI, co / "scripts")
    shutil.copytree(os.path.join(ROOT, "lib"), co / "lib")
    shutil.copy(os.path.join(ROOT, "familia"), co / "familia")
    (co / "man").mkdir(); (co / "man/familia.1").write_text(".TH FAMILIA 1\n")
    (co / "completions").mkdir(); (co / "completions/familia.bash").write_text("complete -W x familia\n")
    home = tmp_path / "h"; home.mkdir()
    r = cli(home, script=str(co / "scripts/install-cli.sh"))
    assert r.returncode == 0, r.stderr
    m = home / ".local/share/man/man1/familia.1"
    c = home / ".local/share/bash-completion/completions/familia"
    assert os.readlink(m) == str(co / "man/familia.1") and os.readlink(c) == str(co / "completions/familia.bash")
    assert len((home / ".local/state/familia/installed.txt").read_text().splitlines()) == 3
    assert cli(home, "uninstall", "--yes", script=str(co / "scripts/install-cli.sh")).returncode == 0
    assert not m.is_symlink() and not c.is_symlink() and (co / "man/familia.1").exists()


def test_absent_man_page_is_skipped(tmp_path):
    if os.path.exists(os.path.join(ROOT, "man", "familia.1")):
        pytest.skip("this checkout has a man page")
    r = cli(tmp_path)
    assert r.returncode == 0 and "no man page" in r.stdout


def test_termux_uses_prefix_bin(tmp_path):
    pfx = tmp_path / "data/data/com.termux/files/usr"
    r = cli(tmp_path, PREFIX=str(pfx))
    assert r.returncode == 0 and (pfx / "bin/familia").exists()


def test_installers_wire_it_in_with_no_path():
    for p in ("install.sh", "install/linux/install.sh", "install/termux/install.sh"):
        s = open(os.path.join(ROOT, p)).read()
        assert "install-cli.sh" in s and "--no-path" in s, p
        assert "install-gum.sh" in s, p
    ps = open(os.path.join(ROOT, "install/windows/install.ps1")).read()
    assert "install-cli.ps1" in ps and "NoPath" in ps
    w = open(os.path.join(ROOT, "scripts/windows/install-cli.ps1")).read()
    assert "HKCU:\\Environment" in w and "SupportsShouldProcess" in w and "DoNotExpandEnvironmentNames" in w


@pytest.mark.skipif(not shutil.which("pwsh"), reason="pwsh not installed: Windows install-cli.ps1 parse untested here")
def test_windows_script_parses():
    for p in ("scripts/windows/install-cli.ps1", "install/windows/install.ps1"):
        r = subprocess.run(["pwsh", "-NoProfile", "-Command",
                            "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e); if ($e) { $e; exit 1 }" % os.path.join(ROOT, p)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
