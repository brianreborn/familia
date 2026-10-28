"""Dolphin3-Cyber Q2_K activate helper (#147 Hermes Wiring) — no live fetch, no seatbelt edits."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "activate_guardian_weights.py"
EXPECTED = "8944d35bdd613fe9279198b76eebeb9ab79c09a2bba526988ee3e3297862ea91"


def run(*args, check=False):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def test_dry_run_status_shows_expected_sha():
    r = run()
    assert r.returncode == 0, r.stderr
    assert EXPECTED in r.stdout
    assert "miryam-pentest" in r.stdout
    assert "angel-guardian" in r.stdout
    assert "Boundary ready-check field: models.dolphin3-cyber-8b-q2k.sha256" in r.stdout
    assert "galaxy1" in r.stdout and "galaxy2" in r.stdout


def test_graph_pins_expected_sha_still_planned():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import familia_yaml

    g = familia_yaml.loads((ROOT / "graph.yaml").read_text(encoding="utf-8"))
    assert g["models"]["dolphin3-cyber-8b-q2k"]["sha256"] == EXPECTED
    assert g["nodes"]["miryam-pentest"]["status"] == "planned"
    assert g["nodes"]["angel-guardian"]["status"] == "planned"
    assert g["pentests"]["fleet"]["status"] == "planned"
    assert g["pentests"]["angel"]["status"] == "planned"
    # seatbelts untouched
    assert g["pentests"]["fleet"]["tools"]["allow"] == []
    assert g["pentests"]["fleet"]["launch_test_only"] is True
    assert g["pentests"]["angel"]["tools"]["allow"] == []
    assert g["pentests"]["angel"]["launch_test_only"] is True


def test_activate_refuses_without_weights():
    r = run("--activate")
    assert r.returncode == 2
    assert "weights absent" in r.stderr or "LF_MODEL_FILE" in r.stderr


def test_activate_dry_run_does_not_write(tmp_path):
    src = (ROOT / "graph.yaml").read_text(encoding="utf-8")
    gpath = tmp_path / "graph.yaml"
    gpath.write_text(src, encoding="utf-8")
    before = gpath.read_text(encoding="utf-8")
    r = run("--graph", str(gpath), "--activate")
    assert r.returncode == 2
    assert gpath.read_text(encoding="utf-8") == before


def test_apply_expected_sha_idempotent_dry_run(tmp_path):
    src = (ROOT / "graph.yaml").read_text(encoding="utf-8")
    # force unmeasured
    src2 = src.replace(
        f"sha256: {EXPECTED}",
        "sha256: unmeasured",
        1,
    )
    assert "sha256: unmeasured" in src2
    gpath = tmp_path / "graph.yaml"
    gpath.write_text(src2, encoding="utf-8")
    r = run("--graph", str(gpath), "--apply-expected-sha")
    assert r.returncode == 0, r.stderr
    # dry-run: file unchanged
    assert "unmeasured" in gpath.read_text(encoding="utf-8")
    r2 = run("--graph", str(gpath), "--apply-expected-sha", "--write")
    assert r2.returncode == 0, r2.stderr
    out = gpath.read_text(encoding="utf-8")
    assert EXPECTED in out
    assert "nodes:\n" in out  # still a graph
    # did not flip status
    assert "status: planned" in out


def test_activate_flips_status_when_gguf_present(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import familia_yaml

    gguf = tmp_path / "Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.gguf"
    # size must match registry bytes for activate gate
    nbytes = 3179141248
    # sparse file — do not allocate 3GiB
    fd = os.open(gguf, os.O_CREAT | os.O_WRONLY)
    try:
        os.ftruncate(fd, nbytes)
    finally:
        os.close(fd)

    src = (ROOT / "graph.yaml").read_text(encoding="utf-8")
    gpath = tmp_path / "graph.yaml"
    # point gguf at sparse stub
    text = familia_yaml.set_node_scalar(src, "models", "dolphin3-cyber-8b-q2k", "gguf", str(gguf))
    gpath.write_text(text, encoding="utf-8")

    r = run("--graph", str(gpath), "--activate", "--write")
    assert r.returncode == 0, r.stderr
    g = familia_yaml.loads(gpath.read_text(encoding="utf-8"))
    assert g["nodes"]["miryam-pentest"]["status"] == "active"
    assert g["nodes"]["angel-guardian"]["status"] == "active"
    assert g["pentests"]["fleet"]["status"] == "active"
    assert g["pentests"]["angel"]["status"] == "active"
    # seatbelts untouched
    assert g["pentests"]["fleet"]["tools"]["allow"] == []
    assert g["pentests"]["fleet"]["launch_test_only"] is True
    assert g["pentests"]["fleet"]["requires_operator_confirm"] is True
    assert "miryam" in g["pentests"]["fleet"]["scope"]["allow"]


def test_private_angel_guardian_flip(tmp_path):
    import shutil
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import familia_yaml as fy

    src = ROOT / "generated" / "graph-angel.yaml"
    if not src.is_file():
        pytest.skip("generated/graph-angel.yaml missing")
    gpath = tmp_path / "graph-angel.yaml"
    shutil.copy(src, gpath)
    gguf = tmp_path / "Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.gguf"
    fd = os.open(gguf, os.O_CREAT | os.O_WRONLY)
    try:
        os.ftruncate(fd, 3179141248)
    finally:
        os.close(fd)
    text = gpath.read_text(encoding="utf-8")
    text = fy.set_node_scalar(text, "models", "dolphin3-cyber-8b-q2k", "gguf", str(gguf))
    gpath.write_text(text, encoding="utf-8")
    r = run("--graph", str(gpath), "--activate", "--write")
    assert r.returncode == 0, r.stderr
    g = fy.loads(gpath.read_text(encoding="utf-8"))
    assert g["nodes"]["guardian"]["status"] == "active"
    assert g["pentests"]["angel"]["status"] == "active"
    assert g["pentests"]["angel"]["tools"]["allow"] == []
