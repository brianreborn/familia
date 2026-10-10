import os, re, subprocess, sys, shutil, yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HM = os.path.join(ROOT, "scripts", "host_measure.py")

def _run(*a):
    return subprocess.run([sys.executable, HM, *a], capture_output=True, text=True)

def test_host_measure_insert_and_idempotent(tmp_path):
    g = tmp_path / "graph.yaml"; shutil.copy(os.path.join(ROOT, "graph.yaml"), g)
    before = yaml.safe_load(open(g))
    assert _run("--name", "newhost", "--graph", str(g)).returncode == 0
    after = yaml.safe_load(open(g))
    h = after["hosts"]["newhost"]
    assert h["measured"] is True and h["ram_mib"] > 0 and h["reserve_ram_mib"] >= 3072
    assert {k: v for k, v in after.items() if k != "hosts"} == {k: v for k, v in before.items() if k != "hosts"}
    snap = g.read_text()
    assert _run("--name", "newhost", "--graph", str(g)).returncode == 0
    assert g.read_text() == snap  # existing host untouched without --force

def test_host_measure_dry_run_and_force(tmp_path):
    g = tmp_path / "graph.yaml"; shutil.copy(os.path.join(ROOT, "graph.yaml"), g)
    snap = g.read_text()
    assert _run("--name", "x1", "--graph", str(g), "--dry-run").returncode == 0
    assert g.read_text() == snap
    assert _run("--name", "shalom", "--graph", str(g), "--force", "--kind", "phone").returncode == 0
    d = yaml.safe_load(open(g))["hosts"]
    assert d["shalom"]["measured"] is True and set(d) == set(yaml.safe_load(snap)["hosts"])

def test_bad_name(tmp_path):
    assert _run("--name", "Bad Name", "--graph", os.path.join(ROOT, "graph.yaml"), "--dry-run").returncode != 0

def test_installer_shapes():
    for p in ("install/linux/install.sh", "install/termux/install.sh"):
        s = open(os.path.join(ROOT, p)).read()
        assert "--uninstall" in s and "--dry-run" in s and "host_measure.py" in s
        assert subprocess.run(["sh", "-n", os.path.join(ROOT, p)]).returncode == 0
    lin = open(os.path.join(ROOT, "install/linux/install.sh")).read()
    assert "digest" in lin and "sha256 mismatch" in lin and "refusing unverified" in lin
    assert not re.search(r"\b[0-9a-f]{64}\b", lin)  # no hardcoded hashes
    ps = open(os.path.join(ROOT, "install/windows/install.ps1")).read()
    assert "SupportsShouldProcess" in ps and "Get-FileHash" in ps and "refusing unverified" in ps
    assert "-Uninstall" in ps or "$Uninstall" in ps
    assert not re.search(r"\b[0-9a-f]{64}\b", ps)
    assert not re.search(r"-Verb\s+RunAs|RunAs", ps)  # never elevates
