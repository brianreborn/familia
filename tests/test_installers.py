import os, re, subprocess, sys, shutil, yaml
import pytest
from types import SimpleNamespace
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HM = os.path.join(ROOT, "scripts", "host_measure.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import host_measure
from graph_types import validate_types
import validate_graph

def _run(*a):
    return subprocess.run([sys.executable, HM, *a], capture_output=True, text=True)

def test_host_measure_insert_and_idempotent(tmp_path):
    g = tmp_path / "graph.yaml"; shutil.copy(os.path.join(ROOT, "graph.yaml"), g)
    before = yaml.safe_load(open(g))
    assert _run("--name", "newhost", "--graph", str(g), "--kind", "laptop").returncode == 0
    after = yaml.safe_load(open(g))
    h = after["hosts"]["newhost"]
    assert h["measured"] is True and h["ram_mib"] > 0 and h["reserve_ram_mib"] >= 3072
    assert {k: v for k, v in after.items() if k != "hosts"} == {k: v for k, v in before.items() if k != "hosts"}
    snap = g.read_text()
    assert _run("--name", "newhost", "--graph", str(g), "--kind", "laptop").returncode == 0
    assert g.read_text() == snap  # existing host untouched without --force

def test_host_measure_dry_run_and_force(tmp_path):
    g = tmp_path / "graph.yaml"; shutil.copy(os.path.join(ROOT, "graph.yaml"), g)
    snap = g.read_text()
    assert _run("--name", "x1", "--graph", str(g), "--kind", "laptop", "--dry-run").returncode == 0
    assert g.read_text() == snap
    assert _run("--name", "shalom", "--graph", str(g), "--force", "--kind", "phone").returncode == 0
    d = yaml.safe_load(open(g))["hosts"]
    assert d["shalom"]["measured"] is True and set(d) == set(yaml.safe_load(snap)["hosts"])

def test_host_measure_freebsd_sysctl_facts_are_graph_schema_compatible(tmp_path, monkeypatch):
    monkeypatch.setattr(host_measure, "sys", SimpleNamespace(platform="freebsd14"))
    monkeypatch.setattr(host_measure.os, "cpu_count", lambda: 4)

    def check_output(command, **kwargs):
        return {"hw.physmem": "8589934592", "hw.model": "FreeBSD Test CPU"}[command[-1]]

    monkeypatch.setattr(host_measure.subprocess, "check_output", check_output)
    fields = host_measure.measure("laptop", 3072)
    measured = yaml.safe_load(host_measure.render("angel", fields))["angel"]
    assert measured["os"] == "freebsd"
    assert measured["cpu"] == "FreeBSD Test CPU"
    assert measured["threads"] == 4
    assert measured["ram_mib"] == 8192

    text = open(os.path.join(ROOT, "graph.yaml")).read()
    updated = host_measure.upsert(text, "angel", host_measure.render("angel", fields), True)
    graph_path = tmp_path / "graph.yaml"
    graph_path.write_text(updated)
    candidate = validate_graph.load(str(graph_path))
    assert validate_types(candidate) == []

def test_existing_unknown_host_kind_requires_explicit_choice():
    text = open(os.path.join(ROOT, "graph.yaml")).read()
    assert host_measure.existing_kind(text, "angel") == "desktop"
    assert host_measure.existing_kind(text, "shalom") == "unknown"
    result = _run("--name", "shalom", "--graph", os.path.join(ROOT, "graph.yaml"), "--dry-run")
    assert result.returncode != 0
    assert "specify --kind" in result.stderr

def test_bad_name(tmp_path):
    assert _run("--name", "Bad Name", "--graph", os.path.join(ROOT, "graph.yaml"), "--dry-run").returncode != 0

def test_installer_shapes():
    for p in ("install/linux/install.sh", "install/termux/install.sh"):
        s = open(os.path.join(ROOT, p)).read()
        assert "--uninstall" in s and "--dry-run" in s and "host_measure.py" in s
        assert subprocess.run(["sh", "-n", os.path.join(ROOT, p)]).returncode == 0
    lin = open(os.path.join(ROOT, "install/linux/install.sh")).read()
    assert "digest" in lin and "sha256 mismatch" in lin and "refusing unverified" in lin
    assert 'git -C "$SOURCE_ROOT" branch --show-current' in lin
    assert 'git -C "$PREFIX/repo" pull --ff-only' in lin
    assert '--set-upstream-to="origin/$BRANCH"' in lin
    assert '--branch) shift; [ -n "${1:-}" ] || die "--branch needs a branch name"; BRANCH=$1; SELECT_BRANCH=1 ;;' in lin
    assert "FreeBSD is source-build-only" in lin
    assert not re.search(r"\b[0-9a-f]{64}\b", lin)  # no hardcoded hashes
    termux = open(os.path.join(ROOT, "install/termux/install.sh")).read()
    assert 'git -C "$SOURCE_ROOT" branch --show-current' in termux
    assert '--set-upstream-to="origin/$BRANCH"' in termux
    assert '--branch) shift; [ -n "${1:-}" ] || die "--branch needs a branch name"; BRANCH=$1; SELECT_BRANCH=1 ;;' in termux
    ps = open(os.path.join(ROOT, "install/windows/install.ps1")).read()
    assert "SupportsShouldProcess" in ps and "Get-FileHash" in ps and "refusing unverified" in ps
    assert "branch --show-current" in ps and "--set-upstream-to=origin/$Branch" in ps
    assert "-Uninstall" in ps or "$Uninstall" in ps
    assert not re.search(r"\b[0-9a-f]{64}\b", ps)
    assert not re.search(r"-Verb\s+RunAs|RunAs", ps)  # never elevates

def test_first_time_setup_routes_freebsd_into_source_build(tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    uname = shim / "uname"
    uname.write_text("#!/bin/sh\necho FreeBSD\n")
    uname.chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", FAMILIA_NO_TTY="1")
    r = subprocess.run(["sh", os.path.join(ROOT, "scripts/setup_goals.sh"),
                        "first-time", "--dry-run"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"[dry-run] sh {ROOT}/install/deps.sh --install --profile build" in r.stdout
    assert f"[dry-run] would run: sh {ROOT}/install/freebsd/install-familia.sh" in r.stdout

@pytest.mark.skipif(sys.platform.startswith("freebsd"),
                    reason="install/linux/install.sh refuses FreeBSD by design (source-build only)")
def test_linux_installer_accepts_branch_and_dry_runs_clone(tmp_path):
    env = dict(os.environ, FAMILIA_PREFIX=str(tmp_path / "prefix"),
               FAMILIA_BIN_DIR=str(tmp_path / "bin"))
    r = subprocess.run(["sh", os.path.join(ROOT, "install/linux/install.sh"),
                        "--dry-run", "--no-runtime", "--name", "testhost",
                        "--branch", "feat/llama.cpp-0.7.0"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[dry-run] git clone -q --branch feat/llama.cpp-0.7.0" in r.stderr


def _ps_text():
    return open(os.path.join(ROOT, "install/windows/install.ps1")).read()


def _pwsh_or_skip(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh not installed")
    # CimCmdlets is Windows-only; strip that line to exercise the uninstall branch on Linux.
    script = tmp_path / "i.ps1"
    script.write_text("\n".join(l for l in _ps_text().splitlines() if "Import-Module CimCmdlets" not in l))
    for d in ("ad", "lad"):
        (tmp_path / d).mkdir(exist_ok=True)
    return pwsh, script


def _ps_run(pwsh, script, tmp_path, *args):
    nogit = tmp_path / "nogit-bin"  # PATH without git: exercises the .git/config parser
    nogit.mkdir(exist_ok=True)
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "lad"), APPDATA=str(tmp_path / "ad"),
               COMPUTERNAME="x", PATH=str(nogit))
    return subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(script), *args],
                          env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


def _install_tree(tmp_path, models_path=None, pre=None, marker=True,
                  origin="https://github.com/brianreborn/familia.git"):
    pre = pre or tmp_path / "pre"
    for d in (pre / "repo" / ".git", pre / "runtime", pre / "models"):
        d.mkdir(parents=True)
    (pre / "repo" / ".git" / "config").write_text(
        '[core]\n\tbare = false\n[remote "origin"]\n\turl = %s\n' % origin)
    (pre / "models" / "in.gguf").write_text("")
    if marker:
        lines = ["familia_install=1", "prefix=%s" % pre]
        if models_path:
            lines.append("models_path=%s" % models_path)
        (pre / ".familia-install").write_text("\n".join(lines) + "\n")
    return pre


def _ext(tmp_path):
    ext = tmp_path / "ext" / "familia" / "models"
    ext.mkdir(parents=True)
    (ext / "x.gguf").write_text("")
    return ext


def _symlink_or_skip(src, dst, **kw):
    try:
        os.symlink(src, dst, **kw)
    except (OSError, NotImplementedError) as e:  # Windows CI without Developer Mode/admin
        pytest.skip("symlinks unavailable: %s" % e)


def test_windows_purge_structure():
    """#32 r2: static checks (run even without pwsh)."""
    ps = _ps_text()
    assert "if ($Purge) { $Uninstall = $true }" in ps
    assert "[switch]$PurgeExternalModels" in ps
    assert "no valid familia marker file" in ps and "'.familia-install'" in ps
    guard = ps.split("function Read-Marker")[0]
    for v in ("$HOME", "$env:USERPROFILE", "$env:APPDATA", "$env:LOCALAPPDATA", "$env:SystemRoot",
              "$env:ProgramFiles", "${env:ProgramFiles(x86)}", "$env:ProgramData", "$env:TEMP", "System32"):
        assert v in guard
    assert "drive/filesystem root" in ps and "ToLowerInvariant" in ps
    assert "ReparsePoint" in ps and "[IO.Directory]::Delete($full, $false)" in ps
    assert "-bnot [IO.FileAttributes]::ReadOnly" in ps
    assert "'\\\\?\\'" in ps  # long-path form on PS 5.1
    assert "Remove-Item -Recurse" not in ps.split("if ($Name -notmatch")[0]
    assert "IsInputRedirected" in ps
    assert "-Encoding utf8" in ps and "-Encoding ascii -LiteralPath $marker" not in ps
    assert "0xFEFF" in ps
    assert "refusing to install into existing non-empty" in ps
    assert "\\familia\\models" in ps


def test_windows_purge_prefix_models_reported_removed(tmp_path):
    """Platform r1: no E:\\temp -> models under $Prefix; purge must delete and say so."""
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _install_tree(tmp_path)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge", "-WhatIf")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (pre / "models" / "in.gguf").exists()
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not pre.exists()
    assert "models removed" in r.stdout and "kept" not in r.stdout


def test_windows_purge_readonly_files(tmp_path):
    """Platform r2 blocker: git marks .git/objects read-only; purge must still finish."""
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _install_tree(tmp_path)
    obj = pre / "repo" / ".git" / "objects" / "pack"
    obj.mkdir(parents=True)
    f = obj / "p.pack"
    f.write_text("x")
    os.chmod(f, 0o444)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not pre.exists()


def test_windows_purge_external_models_needs_record_and_confirm(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    ext = _ext(tmp_path)
    pre = _install_tree(tmp_path, ext)  # recorded, not confirmed -> kept, reported
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ext / "x.gguf").exists() and not pre.exists() and "kept: " in r.stdout
    pre = _install_tree(tmp_path)  # not recorded, even with switch -> kept
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-ModelsPath", str(ext), "-Purge", "-PurgeExternalModels")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ext / "x.gguf").exists() and "not recorded" in r.stdout
    pre = _install_tree(tmp_path, ext)  # recorded and confirmed -> removed
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge", "-PurgeExternalModels")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not ext.exists() and "models removed" in r.stdout


@pytest.mark.parametrize("which", ["not_familia_models", "home"])
def test_windows_purge_refuses_bad_recorded_models(tmp_path, which):
    """Boundary r2 (b): recorded models_path must be guarded and end in familia/models."""
    pwsh, script = _pwsh_or_skip(tmp_path)
    if which == "home":
        bad = os.path.expanduser("~")
    else:
        bad = tmp_path / "stuff"
        bad.mkdir(); (bad / "keep").write_text("")
    pre = _install_tree(tmp_path, bad)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge", "-PurgeExternalModels")
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(bad) and "keeping it" in r.stdout


def test_windows_uninstall_requires_marker(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _install_tree(tmp_path, marker=False)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge")
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "no valid familia marker" in out and "-AdoptInstall" in out
    assert (pre / "models" / "in.gguf").exists() and (pre / "repo").exists()


def test_windows_uninstall_rejects_foreign_marker(tmp_path):
    """Boundary r2 (d): a marker copied from another prefix does not count."""
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _install_tree(tmp_path, marker=False)
    (pre / ".familia-install").write_text("familia_install=1\nprefix=%s\n" % (tmp_path / "other"))
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge")
    assert r.returncode != 0 and (pre / "repo").exists()


def test_windows_marker_utf8_bom_ok(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _install_tree(tmp_path, pre=tmp_path / "Jos\u00e9" / "pre", marker=False)
    (pre / ".familia-install").write_bytes(
        b"\xef\xbb\xbf" + ("familia_install=1\nprefix=%s\n" % pre).encode("utf-8"))
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge")
    assert r.returncode == 0 and not pre.exists(), r.stdout + r.stderr


@pytest.mark.parametrize("which", ["root", "home", "appdata", "localappdata", "home_case_slash"])
def test_windows_refuses_dangerous_prefix(tmp_path, which):
    pwsh, script = _pwsh_or_skip(tmp_path)
    home = os.path.expanduser("~")
    target = {"root": "/", "home": home, "appdata": str(tmp_path / "ad"),
              "localappdata": str(tmp_path / "lad"),
              "home_case_slash": home + "/"}[which]
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", target, "-Purge", "-WhatIf")
    assert r.returncode != 0 and "refusing -Prefix" in (r.stdout + r.stderr), r.stdout + r.stderr


def test_windows_refuses_reparse_prefix(tmp_path):
    """Boundary r2 (c)."""
    pwsh, script = _pwsh_or_skip(tmp_path)
    real = _install_tree(tmp_path)
    link = tmp_path / "linkpre"
    _symlink_or_skip(real, link, target_is_directory=True)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(link), "-Purge")
    assert r.returncode != 0 and "junction/symlink" in (r.stdout + r.stderr)
    assert (real / "repo").exists()


def test_windows_purge_does_not_follow_links(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(); (outside / "keep.txt").write_text("precious")
    pre = _install_tree(tmp_path)
    _symlink_or_skip(outside, pre / "repo" / "link", target_is_directory=True)
    _symlink_or_skip(outside / "keep.txt", pre / "models" / "filelink")
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-Purge")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not pre.exists()
    assert (outside / "keep.txt").read_text() == "precious"


def test_windows_adopt_structure():
    ps = _ps_text()
    assert "[switch]$AdoptInstall" in ps and "[switch]$ConfirmAdopt" in ps
    assert "-AdoptInstall (add -ConfirmAdopt" in ps
    assert ps.index("if ($AdoptInstall)") > ps.index("drive/filesystem root")
    adopt = ps[ps.index("if ($AdoptInstall)"):ps.index("if ($Purge) { $Uninstall = $true }")]
    assert "Remove-Safe" not in adopt and "Remove-Item" not in adopt  # never deletes
    assert "Write-Marker $prefixModels" in adopt  # never records external models


def test_windows_adopt_install(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = tmp_path / "lad" / "familia"
    pre.mkdir(parents=True)
    run = lambda *a: _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), *a)
    r = run("-AdoptInstall", "-ConfirmAdopt")  # empty dir: not a familia layout
    assert r.returncode != 0 and "does not look like" in (r.stdout + r.stderr)
    _install_tree(tmp_path, pre=pre, marker=False)
    r = run("-Purge", "-AdoptInstall", "-ConfirmAdopt")  # adopt never combined with purge
    assert r.returncode != 0 and (pre / "repo").exists()
    r = run("-AdoptInstall")  # non-interactive without confirm
    assert r.returncode != 0 and "-ConfirmAdopt" in (r.stdout + r.stderr)
    assert not (pre / ".familia-install").exists()
    r = run("-AdoptInstall", "-ConfirmAdopt", "-WhatIf")
    assert r.returncode == 0 and not (pre / ".familia-install").exists(), r.stdout + r.stderr
    ext = _ext(tmp_path)
    r = run("-AdoptInstall", "-ConfirmAdopt", "-ModelsPath", str(ext))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT recorded" in r.stdout and "E:\\temp\\familia\\models" in r.stdout  # older-install hint
    assert all(ord(c) < 128 for c in r.stdout)
    m = (pre / ".familia-install").read_text(encoding="utf-8-sig")
    assert "familia_install=1" in m and "adopted=1" in m and str(ext) not in m
    r = run("-Purge", "-PurgeExternalModels")
    assert r.returncode == 0 and not pre.exists(), r.stdout + r.stderr
    assert (ext / "x.gguf").exists()  # adoption never makes external models deletable


def test_windows_adopt_only_under_localappdata(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _install_tree(tmp_path, marker=False)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-AdoptInstall", "-ConfirmAdopt")
    assert r.returncode != 0 and "not under LOCALAPPDATA" in (r.stdout + r.stderr)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", os.path.expanduser("~"), "-AdoptInstall", "-ConfirmAdopt")
    assert r.returncode != 0 and "refusing -Prefix" in (r.stdout + r.stderr)


def test_windows_install_refuses_unmarked_nonempty_prefix(tmp_path):
    """Boundary r2 (a)."""
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = tmp_path / "somedir"
    pre.mkdir(); (pre / "important.txt").write_text("")
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-DryRun", "-NoRuntime")
    assert r.returncode != 0 and "refusing to install into existing non-empty" in (r.stdout + r.stderr)


def test_windows_reinstall_keeps_recorded_models_path(tmp_path):
    """Boundary r2 (d): reinstall preserves the original models_path (dry-run; later Windows-only steps may fail on Linux)."""
    pwsh, script = _pwsh_or_skip(tmp_path)
    ext = _ext(tmp_path)
    pre = _install_tree(tmp_path, ext)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-DryRun", "-NoRuntime")
    assert ("models %s," % ext) in r.stdout, r.stdout + r.stderr



def test_windows_no_e_temp_default():
    """Boundary r4 (1): external models only via explicit -ModelsPath."""
    ps = _ps_text()
    low = ps.lower()
    assert "test-path 'e:\\temp" not in low and "$modelspath = 'e:" not in low  # never a default again
    assert "$ModelsPath = $prefixModels" in ps


def _adopt_tree(tmp_path, **kw):
    pre = tmp_path / "lad" / "familia"
    _install_tree(tmp_path, pre=pre, marker=False, **kw)
    return pre


def test_windows_adopt_refuses_extra_entry(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)
    (pre / "notes.txt").write_text("")
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-AdoptInstall", "-ConfirmAdopt")
    assert r.returncode != 0 and "unexpected entry" in (r.stdout + r.stderr)
    assert not (pre / ".familia-install").exists()


@pytest.mark.parametrize("origin", ["https://github.com/evil/familia.git",
                                    "https://github.com/brianreborn/familia-fork.git", ""])
def test_windows_adopt_refuses_wrong_origin(tmp_path, origin):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path, origin=origin)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-AdoptInstall", "-ConfirmAdopt")
    assert r.returncode != 0 and "repo origin" in (r.stdout + r.stderr), r.stdout + r.stderr


@pytest.mark.parametrize("origin", ["git@github.com:brianreborn/familia.git",
                                    "https://github.com/brianreborn/familia"])
def test_windows_adopt_accepts_origin_forms(tmp_path, origin):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path, origin=origin)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-AdoptInstall", "-ConfirmAdopt")
    assert r.returncode == 0 and (pre / ".familia-install").exists(), r.stdout + r.stderr


def test_windows_adopt_refuses_git_symlink(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)
    real = tmp_path / "realgit"
    shutil.move(str(pre / "repo" / ".git"), str(real))
    _symlink_or_skip(real, pre / "repo" / ".git", target_is_directory=True)
    r = _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-AdoptInstall", "-ConfirmAdopt")
    assert r.returncode != 0 and "junction/symlink" in (r.stdout + r.stderr), r.stdout + r.stderr



def _adopt(pwsh, script, tmp_path, pre):
    return _ps_run(pwsh, script, tmp_path, "-Prefix", str(pre), "-AdoptInstall", "-ConfirmAdopt")


def _write_cfg(pre, text):
    (pre / "repo" / ".git" / "config").write_text(text)


GOOD = "https://github.com/brianreborn/familia.git"


def test_windows_adopt_parser_valid(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)
    _write_cfg(pre, '[core]\n\tbare = false\n[remote "upstream"]\n\turl = https://evil/x\n'
                    '[remote "origin"]\n\turl = %s\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n' % GOOD)
    r = _adopt(pwsh, script, tmp_path, pre)
    assert r.returncode == 0 and (pre / ".familia-install").exists(), r.stdout + r.stderr


@pytest.mark.parametrize("cfg", [
    '[remote "origin"]\n\turl = %s\n[remote "origin"]\n\turl = https://github.com/evil/familia.git\n' % GOOD,
    '[remote "origin"]\n\turl = %s\n\turl = %s\n' % (GOOD, GOOD),
    '[remote "upstream"]\n\turl = %s\n' % GOOD,
], ids=["two-origins-last-evil", "two-urls", "upstream-only"])
def test_windows_adopt_parser_refuses(tmp_path, cfg):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)
    _write_cfg(pre, cfg)
    r = _adopt(pwsh, script, tmp_path, pre)
    assert r.returncode != 0 and "origin" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert not (pre / ".familia-install").exists()


def test_windows_adopt_refuses_gitdir_file(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)
    shutil.rmtree(pre / "repo" / ".git")
    (pre / "repo" / ".git").write_text("gitdir: /elsewhere/.git\n")
    r = _adopt(pwsh, script, tmp_path, pre)
    assert r.returncode != 0 and "is a file" in (r.stdout + r.stderr), r.stdout + r.stderr


def test_windows_adopt_git_failure_refuses_without_parser(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)  # valid config file present: parser would accept it
    git = tmp_path / "nogit-bin" / "git"
    git.parent.mkdir(exist_ok=True)
    git.write_text("#!/bin/sh\nexit 128\n")
    os.chmod(git, 0o755)
    r = _adopt(pwsh, script, tmp_path, pre)
    assert r.returncode != 0 and "git config failed (exit 128)" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert not (pre / ".familia-install").exists()


def test_windows_adopt_git_empty_output_refuses(tmp_path):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)
    git = tmp_path / "nogit-bin" / "git"
    git.parent.mkdir(exist_ok=True)
    git.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(git, 0o755)
    r = _adopt(pwsh, script, tmp_path, pre)
    assert r.returncode != 0 and "found 0" in (r.stdout + r.stderr), r.stdout + r.stderr


@pytest.mark.parametrize("entry", ["repo", "runtime", "models", ".familia-install"])
def test_windows_adopt_refuses_reparse_entries(tmp_path, entry):
    pwsh, script = _pwsh_or_skip(tmp_path)
    pre = _adopt_tree(tmp_path)
    real = tmp_path / ("real-" + entry.strip("."))
    if entry == ".familia-install":
        real.write_text("familia_install=1\nprefix=%s\n" % (tmp_path / "other"))
    else:
        shutil.move(str(pre / entry), str(real))
    _symlink_or_skip(real, pre / entry, target_is_directory=real.is_dir())
    r = _adopt(pwsh, script, tmp_path, pre)
    assert r.returncode != 0 and "junction/symlink" in (r.stdout + r.stderr), r.stdout + r.stderr
