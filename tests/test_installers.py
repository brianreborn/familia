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


def test_windows_purge_implies_uninstall_and_removes_models(tmp_path):
    """#32: -Purge alone must not install, and must remove an external models dir."""
    import shutil, subprocess
    ps = open(os.path.join(ROOT, "install/windows/install.ps1")).read()
    assert "if ($Purge) { $Uninstall = $true }" in ps
    pwsh = shutil.which("pwsh")
    if not pwsh:
        import pytest
        pytest.skip("pwsh not installed")
    # CimCmdlets is Windows-only; strip that line to exercise the uninstall branch on Linux.
    script = tmp_path / "i.ps1"
    script.write_text("\n".join(l for l in ps.splitlines() if "Import-Module CimCmdlets" not in l))
    pre, models = tmp_path / "pre", tmp_path / "m"
    for d in (pre / "repo", pre / "runtime", models):
        d.mkdir(parents=True)
    (models / "x.gguf").write_text("")
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path), COMPUTERNAME="x")
    base = [pwsh, "-NoProfile", "-File", str(script), "-Prefix", str(pre), "-ModelsPath", str(models), "-Purge"]
    subprocess.run(base + ["-WhatIf"], env=env, check=True, capture_output=True)
    assert (models / "x.gguf").exists() and (pre / "repo").exists()
    subprocess.run(base, env=env, check=True, capture_output=True)
    assert not models.exists() and not pre.exists()
