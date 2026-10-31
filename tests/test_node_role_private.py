"""Private topology: type-named nodes; no host-prefixed keys on angel."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import familia_yaml  # noqa: E402
import node_role as nr  # noqa: E402


def _fleet():
    return familia_yaml.loads(open(os.path.join(ROOT, "graph.yaml"), encoding="utf-8").read())


def test_infer_role_angel_chat_vs_coder():
    g = _fleet()
    assert nr.infer_role("angel-coder", g["nodes"]["angel-coder"], g) == "coder"
    assert nr.infer_role("angel-chat", g["nodes"]["angel-chat"], g) == "chat"
    assert nr.infer_role("coder", g["nodes"]["coder"], g) == "coder"


def test_private_angel_type_names_only():
    g = _fleet()
    priv = nr.private_topology(g, "angel")
    nodes = priv["nodes"]
    assert set(nodes) == {"coder", "chat", "guardian"}
    assert nodes["guardian"]["host"] == "angel"
    assert nodes["guardian"]["role"] == "guardian"
    assert nodes["guardian"]["status"] == "planned"
    assert nodes["coder"]["host"] == "angel"
    assert nodes["coder"]["model"] == "nanbeige43-33b-q4km"
    assert nodes["coder"]["status"] == "active"
    assert nodes["chat"]["status"] == "planned"
    assert nodes["coder"]["role"] == "coder"
    assert nodes["chat"]["role"] == "chat"
    for name in nodes:
        assert not nr.is_host_prefixed(name, g)


def test_resolve_model_assign_rejects_typos_and_paths():
    g = _fleet()
    assert nr.resolve_model_assign(g, "qwen35-2b-q4km") == "qwen35-2b-q4km"
    assert nr.resolve_model_assign(g, "coder:default") == "qwen35-2b-q4km"
    with pytest.raises(ValueError, match="unknown models"):
        nr.resolve_model_assign(g, "qwen35-2b")
    with pytest.raises(ValueError, match="must be a models: key"):
        nr.resolve_model_assign(g, "models/coder/x.gguf")


def _genenv(tmp_path):
    env = dict(os.environ)
    env["FAMILIA_GENERATED_DIR"] = str(tmp_path)
    return env


def test_generate_graph_cli_angel(tmp_path):
    r = subprocess.run(env=_genenv(tmp_path), args=
        [sys.executable, os.path.join(ROOT, "scripts", "generate_graph.py"), "angel"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert "angel-coder→coder" in r.stdout or "angel-coder->coder" in r.stdout or "→coder" in r.stdout
    out = os.path.join(str(tmp_path), "graph-angel.yaml")
    g = familia_yaml.loads(open(out, encoding="utf-8").read())
    assert set(g["nodes"]) == {"coder", "chat", "guardian"}


def test_modify_graph_host_list_and_bad_model(tmp_path):
    env = _genenv(tmp_path)
    subprocess.run(env=env, args=
        [sys.executable, os.path.join(ROOT, "scripts", "generate_graph.py"), "angel"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    r = subprocess.run(env=env, args=
        [sys.executable, os.path.join(ROOT, "scripts", "modify_graph.py"),
         "--host", "angel", "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "coder:" in r.stdout and "host=angel" in r.stdout
    assert "angel-coder" not in r.stdout
    bad = subprocess.run(env=env, args=
        [sys.executable, os.path.join(ROOT, "scripts", "modify_graph.py"),
         "--host", "angel", "--assign-model", "coder=qwen35-2b", "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0
    assert "unknown models" in bad.stderr or "unknown models" in bad.stdout


def test_infer_role_guardian_from_pentest_model():
    g = _fleet()
    assert nr.infer_role("miryam-pentest", g["nodes"]["miryam-pentest"], g) == "guardian"
    assert nr.prefer_public_role("pentest") == "guardian"


def test_private_miryam_includes_guardian():
    g = _fleet()
    priv = nr.private_topology(g, "miryam")
    assert "guardian" in priv["nodes"]
    assert priv["nodes"]["guardian"]["role"] == "guardian"
    assert "guardian" in (priv.get("aliases") or {})
