"""#147 Boundary lane: offline guardian ready-check (fixtures only; no live models)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import guardian_ready as gr  # noqa: E402

SCRIPT = os.path.join(ROOT, "scripts", "guardian_ready.py")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_graph(tmp_path, gguf_path: str, sha: str, *, tools_allow=None, launch_test_only=True,
                 confirm=True, node_status="planned", pentest_status="planned"):
    if tools_allow is None:
        tools_allow = []
    # Minimal graph: hosts + one model + one guardian node + one pentest
    allow_yaml = json.dumps(tools_allow)  # JSON list is valid YAML flow
    text = textwrap.dedent(f"""\
        hosts:
          miryam: {{os: linux}}
          angel: {{os: freebsd}}
        models:
          dolphin-fixture:
            gguf: {gguf_path}
            sha256: "{sha}"
            arch: llama
            trained_ctx: 8192
            role: pentest
        nodes:
          miryam-pentest:
            model: dolphin-fixture
            role: guardian
            host: miryam
            runtime: unused
            ctx: 2048
            parallel: 1
            kv_type: q8_0
            flash_attn: false
            offload: {{backend: cpu, ngl: 0, split: none, main_gpu: 0}}
            bind: 127.0.0.1
            port: 18202
            cache_ram_mib: 256
            status: {node_status}
        pentests:
          fleet:
            name: fleet
            node: miryam-pentest
            agent: pentest-ops
            scope:
              allow: [miryam, angel]
              deny: []
            tools:
              allow: {allow_yaml}
            report_to: familia-issues
            requires_operator_confirm: {str(confirm).lower()}
            launch_test_only: {str(launch_test_only).lower()}
            status: {pentest_status}
        """)
    path = tmp_path / "graph.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_role_jsons_dual_disable():
    for path in gr.ROLE_JSONS:
        r = gr.check_role_json(path)
        assert r["ok"], r["errors"]
        assert r["tools_allow"] == []
        assert r["launch_test_only"] is True


def test_live_graph_seatbelts_ok_weights_not_ready():
    """Repo graph: seatbelts OK, weights absent → exit 2 (not 1)."""
    report = gr.run_check(os.path.join(ROOT, "graph.yaml"))
    assert report["ok_seatbelts"] is True
    assert report["weights_ready"] is False
    assert report["exit_hint"] == 2
    states = {n["node"]: (n.get("weight") or {}).get("state") for n in report["nodes"]}
    assert "miryam-pentest" in states
    assert "angel-guardian" in states
    assert states["miryam-pentest"] in ("MISSING", "UNMEASURED")
    assert states["angel-guardian"] in ("MISSING", "UNMEASURED")


def test_cli_live_graph_exit_2():
    r = subprocess.run(
        [sys.executable, SCRIPT, "--graph", os.path.join(ROOT, "graph.yaml")],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 2, r.stdout + r.stderr


def test_fixture_missing_gguf_exit_2(tmp_path):
    missing = str(tmp_path / "no-such.gguf")
    graph = _write_graph(tmp_path, missing, "unmeasured")
    report = gr.run_check(graph)
    assert report["ok_seatbelts"] is True
    assert report["weights_ready"] is False
    assert report["exit_hint"] == 2
    assert report["nodes"][0]["weight"]["state"] == "MISSING"


def test_fixture_present_unmeasured_exit_2(tmp_path):
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"fake-gguf-bytes")
    graph = _write_graph(tmp_path, str(gguf), "unmeasured")
    report = gr.run_check(graph)
    assert report["ok_seatbelts"] is True
    assert report["exit_hint"] == 2
    assert report["nodes"][0]["weight"]["state"] == "UNMEASURED"
    assert report["nodes"][0]["weight"]["ready"] is False


def test_fixture_wrong_sha_exit_2(tmp_path):
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"fake-gguf-bytes")
    graph = _write_graph(tmp_path, str(gguf), "ab" * 32)
    report = gr.run_check(graph)
    assert report["ok_seatbelts"] is True
    assert report["exit_hint"] == 2
    assert report["nodes"][0]["weight"]["state"] == "MISMATCH"


def test_fixture_ready_exit_0(tmp_path):
    data = b"familia-guardian-fixture-weight"
    gguf = tmp_path / "ready.gguf"
    gguf.write_bytes(data)
    graph = _write_graph(tmp_path, str(gguf), _sha(data))
    report = gr.run_check(graph)
    assert report["ok_seatbelts"] is True
    assert report["weights_ready"] is True
    assert report["exit_hint"] == 0
    assert report["nodes"][0]["weight"]["state"] == "READY"
    # Fail-closed: ready-check must not rewrite the graph
    text = open(graph, encoding="utf-8").read()
    assert "status: planned" in text
    assert "status: active" not in text


def test_fixture_tools_allow_nonempty_exit_1(tmp_path):
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"x")
    graph = _write_graph(
        tmp_path, str(gguf), _sha(b"x"), tools_allow=["scan.http"]
    )
    report = gr.run_check(graph)
    assert report["ok_seatbelts"] is False
    assert report["exit_hint"] == 1
    assert any("tools.allow" in e for e in report["errors"])


def test_fixture_launch_test_only_false_exit_1(tmp_path):
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"x")
    graph = _write_graph(
        tmp_path, str(gguf), _sha(b"x"), launch_test_only=False
    )
    report = gr.run_check(graph)
    assert report["ok_seatbelts"] is False
    assert report["exit_hint"] == 1
    assert any("launch_test_only" in e for e in report["errors"])


def test_fixture_missing_confirm_exit_1(tmp_path):
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"x")
    graph = _write_graph(tmp_path, str(gguf), _sha(b"x"), confirm=False)
    report = gr.run_check(graph)
    assert report["ok_seatbelts"] is False
    assert report["exit_hint"] == 1
    assert any("requires_operator_confirm" in e for e in report["errors"])


def test_cli_json_ready(tmp_path):
    data = b"json-ready"
    gguf = tmp_path / "r.gguf"
    gguf.write_bytes(data)
    graph = _write_graph(tmp_path, str(gguf), _sha(data))
    r = subprocess.run(
        [sys.executable, SCRIPT, "--graph", graph, "--json"],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["ok_seatbelts"] is True
    assert payload["weights_ready"] is True
    assert payload["exit_hint"] == 0
