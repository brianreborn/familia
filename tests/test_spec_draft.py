import os, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import yaml, bench_guard as BG
from graph_types import validate_types

G = yaml.safe_load(open(os.path.join(HERE, "graph.yaml")))

def test_draft_pairing_declared_and_typed():
    sp = G["speculative"]["coder-draft"]
    assert sp["mode"] == "draft" and sp["draft"] in G["models"] and sp["target"] in G["nodes"]
    assert not [e for e in validate_types(G) if "coder-draft" in e]

def test_draft_args_pass_bench_guard():
    a = ["llama-server", "-m", "t.gguf", "-md", "d.gguf", "--spec-type", "draft-simple", "--spec-draft-n-max", "8",
         "--spec-draft-n-min", "0", "--spec-draft-p-min", "0.75", "-ngld", "0"]
    out = BG.modern_args(a, "b11374"); assert out == a   # every flag exists in b11374
    out = BG.modern_args(["llama-server", "-m", "t", "-md", "d", "--draft-max", "8"])  # unknown build: legacy spelling rewritten
    assert "--spec-draft-n-max" in out and "draft-simple" in out

def test_served_args_include_draft_when_enabled(tmp_path):
    g = yaml.safe_load(open(os.path.join(HERE, "graph.yaml")))
    for s in g["speculative"].values(): s["status"] = "planned"
    g["speculative"]["coder-draft"]["status"] = "experimental"
    p = tmp_path / "g.yaml"; yaml.safe_dump(g, open(p, "w"))
    out = subprocess.run([sys.executable, os.path.join(HERE, "scripts", "validate_graph.py"), "--graph", str(p), "--no-files", "--args", "coder"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-500:]
    assert "-md " in out.stdout and "--spec-type draft-simple" in out.stdout and "--spec-draft-n-max" in out.stdout


def test_opt_in_default_emits_no_draft_flags():
    """coder-draft stays planned: fleet-wide silent on is forbidden (#91)."""
    out = subprocess.run([sys.executable, os.path.join(HERE, "scripts", "validate_graph.py"),
                          "--graph", os.path.join(HERE, "graph.yaml"), "--no-files", "--args", "coder"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-500:]
    assert "-md " not in out.stdout and "draft-simple" not in out.stdout


def test_params_shape_helper_and_registry_example():
    import specdec_seatbelts as S
    shape = S.params_shape(G, "coder-draft")
    assert shape["llama_server_flags"]["--spec-draft-n-max"] == 8
    assert os.path.isfile(os.path.join(HERE, "registry/examples/specdec-coder-draft-params.json"))


def test_harness2_start_path_imports_seatbelt():
    """Harness² start_node must call preflight_node (source hook; no live spawn)."""
    src = open(os.path.join(HERE, "scripts", "harness2.py")).read()
    assert "specdec_seatbelts" in src and "preflight_node" in src
    src2 = open(os.path.join(HERE, "scripts", "start_graph.py")).read()
    assert "specdec_seatbelts" in src2 and "preflight_node" in src2
