"""#89: harness/base stays short; lean drops unused aux; measure_prompt runs."""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh

def test_base_prompt_under_500_chars():
    sp = open(os.path.join(ROOT, "harness/base/systemprompt.md")).read()
    gr = open(os.path.join(ROOT, "harness/base/guardrails.md")).read()
    assert len(sp) < 500 and len(gr) < 400
    assert "No new tools" in gr or "No new tools" in sp or "no new tools" in gr.lower()

def test_lean_aux_drop_narrows_only():
    assert set(hh.LEAN_AUX_DROP).issubset(set(hh.AUX_TASKS))
    # must not drop mcp (official plugins) or compression/skills_hub (core)
    for keep in ("mcp", "compression", "skills_hub", "approval"):
        assert keep not in hh.LEAN_AUX_DROP

def test_measure_prompt_cli():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/measure_prompt.py")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "harness2 base:" in r.stdout
    assert "hermes lean:" in r.stdout
