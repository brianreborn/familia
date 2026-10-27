"""scripts/install-gum.sh + install.sh wiring for user-local Charm gum."""
import os, subprocess, shutil, stat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUM = os.path.join(ROOT, "scripts", "install-gum.sh")
INSTALL = os.path.join(ROOT, "install.sh")


def test_install_gum_script_parses_and_dry_run_mentions_local_bin(tmp_path):
    assert os.path.isfile(GUM)
    assert subprocess.run(["sh", "-n", GUM], cwd=ROOT).returncode == 0
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["XDG_BIN_HOME"] = str(tmp_path / ".local" / "bin")
    # Hide any real gum on the box PATH.
    env["PATH"] = "/usr/bin:/bin"
    r = subprocess.run(["sh", GUM, "--dry-run"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = r.stderr + r.stdout
    assert "[dry-run]" in out
    assert ".local/bin" in out or str(tmp_path) in out
    assert "gum" in out.lower()


def test_install_sh_dry_run_mentions_gum_and_prelim_stock():
    r = subprocess.run(["sh", INSTALL, "--dry-run"], cwd=ROOT,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    err = r.stderr
    assert "install-gum.sh" in err
    assert "preliminary stock" in err or "deps.sh" in err
    assert "gum" in err.lower()


def test_installers_wire_gum():
    for p in ("install.sh", "install/linux/install.sh", "install/termux/install.sh"):
        s = open(os.path.join(ROOT, p)).read()
        assert "install-gum.sh" in s, p
    ps = open(os.path.join(ROOT, "install/windows/install.ps1")).read()
    assert "install-gum.ps1" in ps
    assert "deps.ps1" in ps
    assert os.path.isfile(os.path.join(ROOT, "scripts/windows/install-gum.ps1"))


def test_prefetch_and_pilot_hud_parse():
    for rel in ("scripts/prefetch-first-models.sh", "scripts/pilot_hud.sh"):
        path = os.path.join(ROOT, rel)
        assert os.path.isfile(path), rel
        assert subprocess.run(["sh", "-n", path], cwd=ROOT).returncode == 0
    r = subprocess.run(["sh", os.path.join(ROOT, "scripts/prefetch-first-models.sh"), "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr + r.stdout
    out = r.stderr + r.stdout
    assert "SmolLM" in out or "ORDNANCE" in out
    r2 = subprocess.run(["sh", os.path.join(ROOT, "scripts/pilot_hud.sh"), "canopy", "TEST"],
                        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0
    assert "PILOT" in (r2.stdout + r2.stderr) or "TEST" in (r2.stdout + r2.stderr)


def test_setup_goals_and_home_mention_prefetch_or_hud():
    sg = open(os.path.join(ROOT, "scripts/setup_goals.sh")).read()
    assert "prefetch-first-models.sh" in sg
    assert "pilot_hud" in sg or "PREFETCHING ORDNANCE" in sg
    home = open(os.path.join(ROOT, "scripts/familia_home.sh")).read()
    assert "install-gum.sh" in home
    assert "prefetch-first-models.sh" in home
    assert "kick_prefetch" in home or "PREFETCHING ORDNANCE" in home
