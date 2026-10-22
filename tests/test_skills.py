import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import skills  # noqa: E402
import graph_types  # noqa: E402

SCRIPT = os.path.join(ROOT, "scripts", "skills.py")
CAT = skills.load_catalog(os.path.join(ROOT, "skills", "catalog.json"))


def test_seed_catalog_valid():
    assert skills.validate_catalog(CAT) == []
    ids = {s["id"]: s for s in CAT["skills"]}
    assert ids["green-probe"]["status"] == "bundled" and ids["green-probe"]["home"] == "green-zkillz"
    assert ids["artemis-android-skill"]["status"] == "available" and ids["artemis-android-skill"]["license"] == "Apache-2.0"
    assert ids["goclaw-skills"]["status"] == "license-blocked"
    assert "Anthropic proprietary" in ids["goclaw-skills"]["parts"]["pdf"]


def test_catalog_schema_errors():
    bad = copy.deepcopy(CAT)
    s = bad["skills"][0]
    s["commit"] = "main"; s["status"] = "maybe"; s["extra"] = 1; del s["license"]
    bad["skills"].append(dict(bad["skills"][1]))  # duplicate id
    bad["skills"][-2]["status"] = "license-blocked"; bad["skills"][-2].pop("blocked_reason", None)
    errs = " ".join(skills.validate_catalog(bad))
    for frag in ("40-character", "not one of", "unknown field 'extra'", "missing required field 'license'",
                 "duplicate id", "blocked_reason"):
        assert frag in errs, frag


def graph(**agents):
    return {"agents": {"hermes": {"skills": agents.get("hermes", [])}},
            "pentests": {"pt": {"agent": "hermes", "skills": agents.get("pt", [])}}}


def test_graph_checks():
    assert skills.check_graph_skills(graph(hermes=["green-probe", "etioz"]), CAT) == []
    e = " ".join(skills.check_graph_skills(graph(hermes=["goclaw-skills", "nope"]), CAT))
    assert "license-blocked" in e and "not in skills/catalog.json" in e
    e = " ".join(skills.check_graph_skills(graph(pt=["green-probe"]), CAT))
    assert "pentest roles never get tool-adding skills" in e
    assert skills.check_graph_skills(graph(pt=["etioz"]), CAT) == []


def test_graph_types_runs_skills_check():
    import familia_yaml
    g = familia_yaml.load(os.path.join(ROOT, "graph.yaml"))
    g["pentests"] = {"android-fleet": {"agent": "hermes", "skills": ["green-deploy"],
                                       "tools": {"allow": []}}}
    errs = " ".join(graph_types.validate_types(g))
    assert "tool-adding" in errs


PENTEST_GRAPH_YAML = """pentests:
  android-fleet:
    name: Test pentest role
    node: coder
    agent: hermes
    scope: {allow: [], deny: []}
    tools: {allow: []}
    report_to: familia-issues
    requires_operator_confirm: true
    launch_test_only: true
    status: planned

"""


def env(tmp_path, pentest=False):
    g = tmp_path / "graph.yaml"
    if not g.exists():
        text = open(os.path.join(ROOT, "graph.yaml"), encoding="utf-8").read()
        g.write_text(text)
    if pentest and "pentests:" not in g.read_text():
        text = g.read_text()
        g.write_text(text.replace("kv_channels:\n", PENTEST_GRAPH_YAML + "kv_channels:\n"))
    e = dict(os.environ, FAMILIA_GRAPH=str(g), FAMILIA_LICENSE_ACCEPT_FILE=str(tmp_path / "acc.json"), FAMILIA_NO_TTY="1")
    for k in ("FAMILIA_ACCEPT_LICENSES", "FAMILIA_ACCEPT_UNKNOWN_LICENSES", "FAMILIA_MENU_PIPE"):
        e.pop(k, None)
    return e, g


def run(tmp_path, *args, inp=None, extra=None, pentest=False):
    e, g = env(tmp_path, pentest=pentest)
    e.update(extra or {})
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=e,
                          input=inp, stdin=None if inp is not None else subprocess.DEVNULL), g


def test_cli_enable_flow(tmp_path):
    before = None
    r, g = run(tmp_path, "enable", "green-probe", "--dry-run")
    before = g.read_text()
    assert r.returncode == 0 and "[dry-run]" in r.stdout
    r, g = run(tmp_path, "enable", "goclaw-skills")
    assert r.returncode == 1 and "license-blocked" in r.stderr and g.read_text() == before
    r, g = run(tmp_path, "enable", "artemis-android-skill")
    assert r.returncode == 1 and "not vendored" in r.stderr
    r, g = run(tmp_path, "enable", "etioz", "--agent", "android-fleet", "--dry-run", pentest=True)
    assert r.returncode == 0
    r, g = run(tmp_path, "enable", "green-probe", "--agent", "android-fleet", pentest=True)
    assert r.returncode == 1 and "pentest" in r.stderr
    # licenses: no terminal -> refuse and leave the graph alone
    before = g.read_text()
    r, g = run(tmp_path, "enable", "etioz")
    assert r.returncode in (2, 3) and g.read_text() == before
    r, g = run(tmp_path, "enable", "etioz", "--yes", extra={"FAMILIA_ACCEPT_UNKNOWN_LICENSES": "yes"})
    assert r.returncode == 0, r.stderr
    txt = g.read_text()
    assert "    skills: [etioz]" in txt and "# hermes-agent MINIMUM_CONTEXT_LENGTH" in txt
    r, g = run(tmp_path, "list", "--json")
    assert [s for s in json.loads(r.stdout) if s["id"] == "etioz"][0]["enabled"] is True
    r, g = run(tmp_path, "disable", "etioz")
    assert r.returncode == 0 and "    skills: []" in g.read_text()


def test_menu_pipe_and_no_tty(tmp_path):
    r, _ = run(tmp_path, "menu")
    assert r.returncode == 2 and "no terminal" in r.stderr and "green-probe" in r.stdout
    r, g = run(tmp_path, "menu", inp="9\n7\ns\n", extra={"FAMILIA_MENU_PIPE": "1", "FAMILIA_ACCEPT_LICENSES": "yes",
                                                        "FAMILIA_ACCEPT_UNKNOWN_LICENSES": "yes"})
    assert r.returncode == 0, r.stderr
    assert "license-blocked and can't be enabled" in r.stdout
    assert "skills: [etioz]" in g.read_text()


def test_vendor_and_help(tmp_path):
    r, _ = run(tmp_path, "vendor", "artemis-android-skill")
    assert r.returncode == 2 and "--dry-run" in r.stderr
    r, _ = run(tmp_path, "vendor", "artemis-android-skill", "--dry-run")
    assert r.returncode == 0 and "d73abe6c49d6fc3c09245774ae9f85caf6e108bd" in r.stdout
    r, _ = run(tmp_path, "--help")
    assert r.returncode == 0 and "Example:" in r.stdout
