import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import licenses  # noqa: E402
import familia_yaml  # noqa: E402

SCRIPT = os.path.join(ROOT, "scripts", "licenses.py")


@pytest.mark.parametrize("lic,cat,flag", [
    ("apache-2.0", "permissive", None),
    ("MIT", "permissive", None),
    ("BSD-3-Clause", "permissive", None),
    ("lfm1.0 (LICENSE)", "custom", "not OSI-approved"),
    ("cc-by-nc-4.0", "restrictive", "non-commercial"),
    ("Tencent HY Community License Agreement (not valid in the EU, UK and South Korea)", "restrictive", "region-limited"),
    ("apache-2.0 (adapter) + Gemma 4 terms for the base weights", "restrictive", "acceptable-use policy"),
    ("unknown", "unknown", "unknown"),
    ("not stated on the model card", "unknown", "unknown"),
    ("", "unknown", "unknown"),
    ("WTFPL-ish house license", "unknown", "unrecognized license"),
    ("GPL-3.0", "copyleft", "copyleft"),
])
def test_classify(lic, cat, flag):
    c, flags = licenses.classify(lic)
    assert c == cat
    if flag:
        assert flag in flags


GRAPH = """version: 2
models:
  m1:
    gguf: x.gguf
    db: nope--missing
nodes:
  n1:
    model: m1
    host: h
    runtime: r1
    status: active
runtimes:
  r1:
    kind: llama-server
    build: b1
agents:
  hermes:
    kind: hermes-agent
    skills: [etioz]
"""


def run(tmp_path, *args, env=None):
    g = tmp_path / "graph.yaml"
    if not g.exists():
        g.write_text(GRAPH)
    e = dict(os.environ, FAMILIA_LICENSE_ACCEPT_FILE=str(tmp_path / "acc.json"), FAMILIA_NO_TTY="1")
    e.pop("FAMILIA_ACCEPT_LICENSES", None); e.pop("FAMILIA_ACCEPT_UNKNOWN_LICENSES", None)
    e.update(env or {})
    return subprocess.run([sys.executable, SCRIPT, *args, "--graph", str(g)], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, env=e)


def test_unknown_blocks_until_explicit(tmp_path):
    r = run(tmp_path, "check")
    assert r.returncode == 1 and "licenses.py review" in r.stderr
    r = run(tmp_path, "review")              # no terminal
    assert r.returncode == 2 and "--yes" in r.stderr
    r = run(tmp_path, "review", "--yes")     # model has no db entry -> unknown
    assert r.returncode == 3 and "UNKNOWN" in r.stdout
    assert not (tmp_path / "acc.json").exists()
    r = run(tmp_path, "review", "--yes", "--accept-unknown")
    assert r.returncode == 0 and "Licenses for your current familia selection" in r.stdout
    acc = json.loads((tmp_path / "acc.json").read_text())
    assert acc["accepted_unknown"] and len(acc["selection_sha256"]) == 64
    assert run(tmp_path, "check").returncode == 0
    assert run(tmp_path, "gate").returncode == 0


def test_change_reasks(tmp_path):
    assert run(tmp_path, "review", "--yes", "--accept-unknown").returncode == 0
    assert run(tmp_path, "check").returncode == 0
    assert run(tmp_path, "check", "--add-skill", "artemis-android-skill").returncode == 1
    (tmp_path / "graph.yaml").write_text(GRAPH.replace("[etioz]", "[etioz, green-probe]"))
    assert run(tmp_path, "check").returncode == 1


def test_env_yes_and_json(tmp_path):
    r = run(tmp_path, "gate", env={"FAMILIA_ACCEPT_LICENSES": "yes", "FAMILIA_ACCEPT_UNKNOWN_LICENSES": "yes"})
    assert r.returncode == 0, r.stderr
    r = run(tmp_path, "check", "--json")
    d = json.loads(r.stdout)
    assert d["accepted"] is True
    kinds = {i["kind"] for i in d["items"]}
    assert {"model", "skill", "engine", "component"} <= kinds
    sk = [i for i in d["items"] if i["kind"] == "skill"][0]
    assert sk["license"] == "BSD-3-Clause"


def test_help_and_usage():
    r = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "Example:" in r.stdout
    r = subprocess.run([sys.executable, SCRIPT, "bogus"], capture_output=True, text=True)
    assert r.returncode == 2 and "--help" in r.stderr


def test_real_graph_lists_everything():
    items, digest = licenses.selection(os.path.join(ROOT, "graph.yaml"))
    assert len(digest) == 64
    ids = " ".join(i["id"] for i in items)
    assert "familia" in ids and "llama.cpp" in ids
    for i in items:
        if i["id"].split(" @ ")[0] in ("green-roomz", "green-agentz"):
            assert "Light-ware" in i["license"], i  # familia#75


def test_stdlib_yaml_matches_pyyaml_on_graph():
    yaml = pytest.importorskip("yaml")
    path = os.path.join(ROOT, "graph.yaml")
    a = yaml.safe_load(open(path, encoding="utf-8"))
    b = familia_yaml.load(path, force_stdlib=True)
    for sec in ("models", "nodes", "runtimes", "agents", "pentests"):
        for name, v in (a.get(sec) or {}).items():
            for k, x in v.items():
                if not isinstance(x, str):
                    assert b[sec][name][k] == x, (sec, name, k)


def test_set_node_list_keeps_comments():
    t = "agents:\n  hermes:\n    kind: hermes-agent   # keep me\n    aliases:\n      main: coder\n\nfleets: {}\n"
    t2 = familia_yaml.set_node_list(t, "agents", "hermes", "skills", ["a", "b"])
    assert "# keep me" in t2 and "    skills: [a, b]\n" in t2
    t3 = familia_yaml.set_node_list(t2, "agents", "hermes", "skills", [])
    assert "    skills: []" in t3 and t3.count("skills:") == 1
    with pytest.raises(KeyError):
        familia_yaml.set_node_list(t, "agents", "nobody", "skills", [])
