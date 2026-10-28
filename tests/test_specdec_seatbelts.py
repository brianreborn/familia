"""Race seatbelts for draft-simple speculative decoding (#91)."""
import copy
import os
import sys

import pytest
import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import specdec_seatbelts as S  # noqa: E402
import validate_graph  # noqa: E402

G = yaml.safe_load(open(os.path.join(HERE, "graph.yaml")))


def _enable_draft(g=None, **kw):
    x = copy.deepcopy(g or G)
    for s in x["speculative"].values():
        s["status"] = "planned"
    sp = x["speculative"]["coder-draft"]
    sp["status"] = "experimental"
    sp.update(kw)
    return x


def test_planned_is_noop():
    assert S.enabled_draft_edges(G, "coder") == []
    ok, e, w = S.preflight_node(G, "coder", check_files=False)
    assert ok and e == [] and w == []
    assert S.draft_argv_flags(G, "coder") == []


def test_params_shape_records_target_and_draft():
    shape = S.params_shape(G, "coder-draft")
    assert shape["mode"] == "draft" and shape["spec_type"] == "draft-simple"
    assert shape["target"]["model"] == "qwen35-2b-q4km"
    assert shape["draft"]["model"] == "qwen35-08b-q4km"
    assert shape["draft"]["draft_max"] == 8
    assert shape["llama_server_flags"]["--spec-type"] == "draft-simple"
    assert shape["live_measure"] == "deferred"
    # registry example stays in sync
    ex = os.path.join(HERE, "registry/examples/specdec-coder-draft-params.json")
    import json
    got = json.load(open(ex))
    assert got["target"]["model"] == shape["target"]["model"]
    assert got["draft"]["sha256"] == shape["draft"]["sha256"]


def test_draft_argv_flags_match_server_args():
    x = _enable_draft()
    flags = S.draft_argv_flags(x, "coder")
    assert flags[0] == "-md" and "--spec-type" in flags and "draft-simple" in flags
    a = validate_graph.server_args(x, "coder")
    for f in ("-md", "--spec-type", "--spec-draft-n-max", "--spec-draft-n-min", "--spec-draft-p-min", "-ngld"):
        assert f in a
    assert a[a.index("--spec-type") + 1] == "draft-simple"
    assert a[a.index("-md") + 1] == flags[1]


def test_refuse_missing_draft_gguf(tmp_path):
    x = _enable_draft()
    x["models"]["qwen35-08b-q4km"] = dict(x["models"]["qwen35-08b-q4km"])
    x["models"]["qwen35-08b-q4km"]["gguf"] = str(tmp_path / "missing-draft.gguf")
    ok, errs, _ = S.preflight_node(x, "coder", check_files=True)
    assert not ok and any("draft file not found" in e for e in errs)


def test_refuse_threads_above_sprint():
    x = _enable_draft()
    x["nodes"]["coder"] = dict(x["nodes"]["coder"])
    x["nodes"]["coder"]["threads"] = S.THREAD_BUDGET_SPRINT + 1
    ok, errs, warns = S.preflight_node(x, "coder", check_files=False)
    assert not ok and any("sprint budget" in e for e in errs)


def test_warn_threads_above_resident():
    x = _enable_draft()
    x["nodes"]["coder"] = dict(x["nodes"]["coder"])
    # coder default is 3 (<= resident); bump to 5
    x["nodes"]["coder"]["threads"] = S.THREAD_BUDGET_RESIDENT + 1
    # isolate host peers so combined does not trip sprint refuse
    for n in x["nodes"].values():
        if n.get("host") == "miryam" and n is not x["nodes"]["coder"]:
            n["status"] = "planned"
    ok, errs, warns = S.preflight_node(x, "coder", check_files=False)
    assert ok and errs == []
    assert any("resident budget" in w for w in warns)


def test_refuse_same_host_oversubscribe():
    x = _enable_draft()
    x["nodes"]["coder"] = dict(x["nodes"]["coder"])
    x["nodes"]["coder"]["threads"] = 3
    # invent a peer on miryam with high threads
    peer = copy.deepcopy(x["nodes"]["coder"])
    peer["port"] = 19999
    peer["threads"] = 4
    peer["status"] = "active"
    x["nodes"]["coder-peer"] = peer
    ok, errs, _ = S.preflight_node(x, "coder", check_files=False)
    assert not ok and any("cpu_oversubscribed" in e or "sprint" in e for e in errs)


def test_validate_no_files_applies_thread_budget():
    validate_graph.WARNINGS.clear()
    x = _enable_draft()
    x["nodes"]["coder"] = dict(x["nodes"]["coder"])
    x["nodes"]["coder"]["threads"] = 9
    errs, _ = validate_graph.validate(x, check_files=False)
    assert any("sprint budget" in e for e in errs)
