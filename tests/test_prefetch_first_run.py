"""#190 first-run gap: prefetch syncs pins when the bootstraps manifest is missing."""
import os, shutil, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "prefetch-first-models.sh")


def _tree(tmp_path, with_manifest):
    r = tmp_path / "fam"
    (r / "scripts").mkdir(parents=True); (r / "lib").mkdir()
    shutil.copy(SCRIPT, r / "scripts" / "prefetch-first-models.sh")
    shutil.copy(os.path.join(ROOT, "lib", "msg.mk"), r / "lib" / "msg.mk")
    (r / "scripts" / "add_model.py").write_text("")
    if with_manifest:
        m = r / "code-bootstraps-llama.cpp" / "config"; m.mkdir(parents=True)
        (m / "models-manifest.json").write_text("{}")
    return r


def _dry(r):
    return subprocess.run(["sh", str(r / "scripts" / "prefetch-first-models.sh"), "--dry-run"],
                          capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)


def test_dry_run_plans_pin_sync_when_manifest_missing(tmp_path):
    out = _dry(_tree(tmp_path, with_manifest=False))
    assert out.returncode == 0
    assert "sync_pins.py" in out.stdout and "first run" in out.stdout


def test_no_pin_sync_when_manifest_present(tmp_path):
    out = _dry(_tree(tmp_path, with_manifest=True))
    assert out.returncode == 0 and "sync_pins.py" not in out.stdout
