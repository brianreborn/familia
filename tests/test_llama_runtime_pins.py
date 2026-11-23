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


def test_b12032_runtime_record_has_lfm3_capability_table():
    record = llama_flags.load("b12032")

    assert record["commit"] == "dde879bc4f954b809892fd0d660515f42536394a"
    assert "lfm3" in record["archs"]
    for flag in ("--jinja", "--api-key-file", "--spec-type", "--spec-ngram-mod-n-match"):
        assert llama_flags.supports(record, flag) is True


def test_angel_b12359_runtime_has_measured_help_and_source_tables():
    graph = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
    runtime = graph["runtimes"]["llama-b12359-freebsd"]
    record = llama_flags.load("b12359")

    assert runtime["commit"] == record["commit"] == "2a8600387b40f2820d17973067020ce11377904d"
    assert "gpt-oss" in record["archs"]
    assert "qwen35" in record["archs"]
    for flag in ("--jinja", "--api-key-file", "--spec-type", "--chat-template-kwargs"):
        assert llama_flags.supports(record, flag) is True
