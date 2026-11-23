"""Guardian power-level changes preserve the dual-disable seatbelts."""
import hashlib
import os
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "guardian_power.py")


def invoke(graph, *args):
    return subprocess.run(
        [sys.executable, SCRIPT, "--graph", str(graph), "--role", "fleet", *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def fixture_graph(tmp_path):
    graph = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml"), encoding="utf-8"))
    weights = tmp_path / "guardian.gguf"
    weights.write_bytes(b"test weights")
    model = graph["models"]["dolphin3-cyber-8b-q2k"]
    model["gguf"] = str(weights)
    model["sha256"] = hashlib.sha256(weights.read_bytes()).hexdigest()
    path = tmp_path / "graph.yaml"
    path.write_text(yaml.safe_dump(graph, sort_keys=False), encoding="utf-8")
    return path


def test_model_only_preview_requires_real_sha_and_keeps_seatbelts(tmp_path):
    path = fixture_graph(tmp_path)
    before = path.read_text(encoding="utf-8")
    result = invoke(path, "--level", "model-only")
    assert result.returncode == 0, result.stderr
    assert "tools.allow=[], launch_test_only=true" in result.stdout
    assert path.read_text(encoding="utf-8") == before


def test_model_only_write_changes_status_only(tmp_path):
    path = fixture_graph(tmp_path)
    result = invoke(path, "--level", "model-only", "--write")
    assert result.returncode == 0, result.stderr
    graph = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert graph["nodes"]["fleet-guardian"]["status"] == "active"
    assert graph["pentests"]["fleet"]["status"] == "active"
    assert graph["pentests"]["fleet"]["tools"]["allow"] == []
    assert graph["pentests"]["fleet"]["launch_test_only"] is True
    assert graph["pentests"]["fleet"]["requires_operator_confirm"] is True


def test_disable_plans_node_and_preserves_seatbelts(tmp_path):
    path = fixture_graph(tmp_path)
    graph = yaml.safe_load(path.read_text(encoding="utf-8"))
    graph["nodes"]["fleet-guardian"]["status"] = "active"
    graph["pentests"]["fleet"]["status"] = "active"
    path.write_text(yaml.safe_dump(graph, sort_keys=False), encoding="utf-8")
    result = invoke(path, "--level", "disabled", "--write")
    assert result.returncode == 0, result.stderr
    graph = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert graph["nodes"]["fleet-guardian"]["status"] == "planned"
    assert graph["pentests"]["fleet"]["status"] == "planned"
    assert graph["pentests"]["fleet"]["tools"]["allow"] == []


def test_tool_enabled_level_is_rejected(tmp_path):
    result = invoke(fixture_graph(tmp_path), "--level", "tools-confirm", "--write")
    assert result.returncode == 2
    assert "per-action confirmation is implemented" in result.stderr


def test_model_only_rejects_missing_weights_without_writing(tmp_path):
    path = fixture_graph(tmp_path)
    graph = yaml.safe_load(path.read_text(encoding="utf-8"))
    graph["models"]["dolphin3-cyber-8b-q2k"]["gguf"] = str(tmp_path / "absent.gguf")
    path.write_text(yaml.safe_dump(graph, sort_keys=False), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    result = invoke(path, "--level", "model-only", "--write")
    assert result.returncode == 2
    assert "weights missing" in result.stderr
    assert path.read_text(encoding="utf-8") == before
