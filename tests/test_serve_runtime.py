"""scripts/serve.sh refuses to start a node whose runtime binary is missing (#84)."""
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tree(tmp_path, binpath):
    s = tmp_path / "scripts"
    s.mkdir()
    shutil.copy(os.path.join(ROOT, "scripts", "serve.sh"), s / "serve.sh")
    (s / "validate_graph.py").write_text("print(%r)\n" % (binpath + " -m " + str(tmp_path / "m.gguf") + " -ngl 0"))
    (s / "licenses.py").write_text("")
    (tmp_path / "m.gguf").write_bytes(b"GGUF")
    (tmp_path / "graph.yaml").write_text("")
    return s / "serve.sh"


def test_missing_runtime_is_a_clear_error(tmp_path):
    sh = _tree(tmp_path, str(tmp_path / "no" / "llama-server"))
    p = subprocess.run(["sh", str(sh), "coder"], capture_output=True, text=True,
                       env=dict(os.environ, FAMILIA_MEMCAP="0"), timeout=60)
    assert p.returncode == 1 and "runtime" in p.stderr and "not starting" in p.stderr, p.stderr


def test_present_runtime_is_started(tmp_path):
    b = tmp_path / "rt" / "llama-server"
    b.parent.mkdir()
    b.write_text("#!/bin/sh\necho started\n")
    b.chmod(0o755)
    sh = _tree(tmp_path, str(b))
    p = subprocess.run(["sh", str(sh), "coder"], capture_output=True, text=True,
                       env=dict(os.environ, FAMILIA_MEMCAP="0"), timeout=60)
    assert "started" in p.stdout, (p.stdout, p.stderr)
