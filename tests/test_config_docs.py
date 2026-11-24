"""CFG-RULE-002: every graph schema field has a documented, registered requirement ID (offline)."""
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_config_docs_check():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/config_docs.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_top_level_rule_present():
    assert "docs/config" in (ROOT / "CONTRIBUTING.md").read_text()
