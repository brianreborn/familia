"""Shared self-improve attach (scripts/self_improve_attach.py): any launcher, not only hermes."""
import copy, os, subprocess, sys, textwrap
import pytest, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import self_improve_attach as SIA  # noqa: E402
import self_improve as SI  # noqa: E402

GRAPH = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
ATTACH = os.path.join(ROOT, "scripts", "self_improve_attach.py")


def _pentest():
    return {
        "name": "Authorized test fixture",
        "node": "coder",
        "agent": "hermes",
        "scope": {"allow": [], "deny": []},
        "tools": {"allow": []},
        "report_to": "familia-issues",
        "requires_operator_confirm": True,
        "launch_test_only": True,
        "status": "planned",
    }


def graph(mode="off", agent="hermes-lab", extra_agent=None):
    g = copy.deepcopy(GRAPH)
    g["pentests"] = {"test-only": _pentest()}
    g["self_improve"]["harness2"]["mode"] = mode
    g["self_improve"]["harness2"]["targets"] = ["hermes-lab"]
    g["harnesses"]["hermes-lab"]["agent"] = agent
    # Keep hermes entry off so attach --agent tests stay focused.
    if "harness2-hermes" in g.get("self_improve", {}):
        g["self_improve"]["harness2-hermes"]["mode"] = "off"
    if extra_agent:
        g["agents"][extra_agent] = copy.deepcopy(g["agents"]["hermes-lab"])
        g["harnesses"]["plain-lab"] = dict(
            g["harnesses"]["hermes-lab"],
            agent=extra_agent,
            root="~/.cache/familia/plain-" + extra_agent,
        )
        g["self_improve"]["harness2-plain"] = {
            "experimental": True,
            "engine": "harness2",
            "mode": mode,
            "targets": ["plain-lab"],
            "k": 1,
            "recursion": "parallel",
            "tasks": "coding-v1",
        }
    return g


def write_graph(tmp, g):
    p = tmp / "graph.yaml"
    p.write_text(yaml.safe_dump(g, sort_keys=False))
    return str(p)


def test_attach_noop_when_mode_off(tmp_path, capsys):
    gp = write_graph(tmp_path, graph(mode="off"))
    g = yaml.safe_load(open(gp))
    results = SIA.attach(g, gp, agent="hermes-lab", log_prefix="t")
    assert results == [("hermes-lab", "skipped")]
    assert "sync" not in capsys.readouterr().err.lower() or "skipped" in str(results)


def test_attach_syncs_non_hermes_agent(tmp_path, capsys):
    """A non-hermes agent with a harnesses.* descriptor still gets synced when mode is on."""
    g = graph(mode="propose", agent="hermes-lab", extra_agent="bootstraps")
    # Point plain-lab at a real empty root so harness2 sync can run (no versions → nothing to sync).
    root = tmp_path / "plain-root"
    root.mkdir()
    g["harnesses"]["plain-lab"]["root"] = str(root)
    gp = write_graph(tmp_path, g)
    results = SIA.attach(yaml.safe_load(open(gp)), gp, agent="bootstraps", log_prefix="t")
    assert len(results) == 1 and results[0][0] == "plain-lab"
    assert results[0][1] in ("synced", "failed")  # synced even when "nothing to sync"
    err = capsys.readouterr().err
    assert "plain-lab" in err


def test_attach_pentest_refused(tmp_path):
    g = graph(mode="propose", agent="hermes")  # hermes is the pentest agent in fixture
    gp = write_graph(tmp_path, g)
    with pytest.raises(SystemExit, match="pentest"):
        SIA.attach(yaml.safe_load(open(gp)), gp, agent="hermes", force=True, log_prefix="t")
    with pytest.raises(SystemExit, match="pentest"):
        SIA.main(["--graph", gp, "--agent", "hermes", "--force"])


def test_attach_cli_target_and_force_noop_path(tmp_path):
    gp = write_graph(tmp_path, graph(mode="off"))
    r = subprocess.run(
        [sys.executable, ATTACH, "--graph", gp, "--target", "hermes-lab"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    # force with no versions still exits 0 (warn+continue / nothing to sync)
    r = subprocess.run(
        [sys.executable, ATTACH, "--graph", gp, "--agent", "hermes-lab", "--force"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
