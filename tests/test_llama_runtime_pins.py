import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import llama_flags  # noqa: E402
import validate_graph  # noqa: E402


def load_json(path):
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def test_active_b11944_runtime_matches_its_capability_table():
    graph = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
    runtime = graph["runtimes"]["llama-b11944"]
    record = llama_flags.load("b11944")

    assert runtime["commit"] == record["commit"] == "1b4554eff124a8f0033bc09b3f708a5e51cbda15"
    assert "lfm3" in record["archs"]
    for flag in ("--jinja", "--api-key-file", "--spec-type", "--spec-ngram-mod-n-match"):
        assert llama_flags.supports(record, flag) is True


def test_code_bootstraps_release_pin_has_lfm3_capability_table():
    release = load_json(os.path.join(ROOT, "code-bootstraps-llama.cpp", "config", "llama-release.json"))
    assert release["tag"] == "b12032"
    cpu_asset = next(asset for asset in release["assets"]
                     if asset["platform"] == "linux-x64" and asset["variant"] == "cpu")
    record = llama_flags.load(release["tag"])

    assert record["commit"] == release["commit"]
    assert "lfm3" in record["archs"]
    assert cpu_asset["file"].startswith("llama-b12032-")
    for flag in ("--jinja", "--api-key-file", "--spec-type", "--spec-ngram-mod-n-match"):
        assert llama_flags.supports(record, flag) is True