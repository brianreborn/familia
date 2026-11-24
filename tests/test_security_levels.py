"""Security node levels (docs/security-levels.md): presets, toggles, confirmation, fail-closed, no graph edits."""
import copy
import hashlib
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import security_levels as SL  # noqa: E402
import start_graph  # noqa: E402
import validate_graph  # noqa: E402

GRAPH_PATH = os.path.join(ROOT, "graph.yaml")
GRAPH = validate_graph.load(GRAPH_PATH)
SPEC = SL.load_spec()
GUARDS = ("nodes.fleet-guardian", "nodes.freebsd-guardian")
SEATS = ("pentests.fleet", "pentests.freebsd-guardian")
NO_ENV = {}


def g():
    return copy.deepcopy(GRAPH)


def st(level=None, enable=(), disable=(), confirmed=()):
    return {"level": level, "enable": list(enable), "disable": list(disable), "confirmed": list(confirmed)}


def on(p):
    return {k for k, e in p["entries"].items() if e["status"] == "active"}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_spec_defines_the_four_presets_in_data():
    assert list(SPEC["levels"]) == ["off", "guardian", "pentest", "full"]
    assert SPEC["sets"]["pentest"]["confirm"] is True
    assert SPEC["sets"]["pentest"]["requires"] == ["guardian"]


def test_members_found_by_role_and_section():
    m = SL.set_members(g(), SPEC)
    assert set(m["guardian"]) == {("nodes", "fleet-guardian"), ("nodes", "freebsd-guardian")}
    assert set(m["pentest"]) == {("pentests", "fleet"), ("pentests", "freebsd-guardian")}
    assert m["other"] == []
    # a new fail-closed node with another role lands in `other` (full only)
    x = g()
    x["nodes"]["extra-defender"] = dict(x["nodes"]["fleet-guardian"], role="pentest", port=18299)
    assert ("nodes", "extra-defender") in SL.set_members(x, SPEC)["pentest"]


def test_no_override_is_a_noop():
    x = g()
    p = SL.apply(x, state=st(), environ=NO_ENV)
    assert p["source"] is None and p["level"] == "graph" and x == GRAPH


@pytest.mark.parametrize("level,expect", [
    ("off", set()),
    ("guardian", set(GUARDS)),
    ("pentest", set(GUARDS) | set(SEATS)),
    ("full", set(GUARDS) | set(SEATS)),
])
def test_each_preset(level, expect):
    x = g()
    p = SL.apply(x, state=st(level, confirmed=["pentest"]), environ=NO_ENV)
    assert on(p) == expect
    for key in GUARDS + SEATS:
        sec, name = key.split(".")
        assert x[sec][name]["status"] == ("active" if key in expect else "planned")


def test_overlay_changes_status_only():
    x = g()
    SL.apply(x, state=st("off"), environ=NO_ENV)
    y = g()
    for sec in ("nodes", "pentests"):
        for name in y[sec]:
            y[sec][name]["status"] = x[sec][name]["status"]
    assert x == y


def test_pentest_needs_a_recorded_confirmation_even_from_env():
    x = g()
    p = SL.apply(x, state=st(), environ={"FAMILIA_SECURITY_LEVEL": "pentest"})
    assert on(p) == set(GUARDS)
    assert any("typed confirmation" in w for w in p["warnings"])
    x = g()
    p = SL.apply(x, level="full", state=st(confirmed=["pentest"]), environ=NO_ENV)
    assert on(p) >= set(SEATS)


def test_precedence_flag_env_file():
    s = st("guardian")
    assert SL.plan(g(), state=s, environ=NO_ENV)["level"] == "guardian"
    assert SL.plan(g(), state=s, environ={"FAMILIA_SECURITY_LEVEL": "off"})["level"] == "off"
    assert SL.plan(g(), state=s, level="full", environ={"FAMILIA_SECURITY_LEVEL": "off"})["level"] == "full"


def test_unknown_level_is_a_clear_error():
    with pytest.raises(SL.SecurityLevelError, match="choose one of: off, guardian, pentest, full"):
        SL.plan(g(), state=st(), level="max", environ=NO_ENV)


def test_seat_is_off_when_its_node_is_off():
    p = SL.plan(g(), state=st(enable=["pentest"], disable=["guardian"], confirmed=["pentest"]), environ=NO_ENV)
    assert not (on(p) & set(SEATS))


def test_toggle_on_graph_base_leaves_other_entries_as_declared():
    x = g(); x["nodes"]["freebsd-guardian"]["status"] = "planned"
    p = SL.plan(x, state=st(disable=["pentest"]), environ=NO_ENV)
    assert p["entries"]["nodes.freebsd-guardian"]["why"] == "as declared in graph.yaml"
    assert p["entries"]["nodes.freebsd-guardian"]["status"] == "planned"
    assert p["entries"]["nodes.fleet-guardian"]["status"] == "active"
    assert p["entries"]["pentests.fleet"]["status"] == "planned"


def test_fail_closed_routing_is_the_same_at_every_level():
    declared, _ = validate_graph.validate(g(), check_files=False)
    for level in SPEC["levels"]:
        x = g()
        SL.apply(x, state=st(level, confirmed=["pentest"]), environ=NO_ENV)
        errs, _ = validate_graph.validate(x, check_files=False)
        # a level never adds a validation error; only guardian artifact errors can differ
        assert set(errs) <= set(declared), (level, errs)
        if level == "off":
            assert not [e for e in errs if "guardian" in e], errs
        nodes, _remote, gateways, omitted, _rg = start_graph.local_topology(x, "miryam")
        assert "fleet-guardian" not in nodes
        routed = {a for _n, _gw, aliases in gateways for a in aliases}
        assert not routed & {"guardian", "pentest", "defender"}
        for n, nd in x["nodes"].items():
            assert not set(nd.get("escalates_to") or []) & {"fleet-guardian", "freebsd-guardian"}


# ---- CLI: toggling, idempotency, confirmation, graph.yaml untouched

def change(tmp_path, cmd, arg, **kw):
    return SL.change(g(), SPEC, tmp_path / "security.local.yaml", cmd, arg, check_files=False,
                     environ=NO_ENV, **kw)


def test_toggle_and_idempotent(tmp_path, capsys):
    path = tmp_path / "security.local.yaml"
    assert change(tmp_path, "level", "guardian") == 0
    first = path.read_text()
    assert 'level: "guardian"' in first
    capsys.readouterr()
    assert change(tmp_path, "level", "guardian") == 0
    assert "no change" in capsys.readouterr().out and path.read_text() == first
    change(tmp_path, "disable", "guardian")
    assert SL.load_state(path)["disable"] == ["guardian"]
    change(tmp_path, "enable", "guardian")
    s = SL.load_state(path)
    assert s["enable"] == ["guardian"] and s["disable"] == []
    change(tmp_path, "level", "off")
    s = SL.load_state(path)
    assert s == st("off")
    p = SL.plan(g(), state=s, environ=NO_ENV)
    assert on(p) == set()


def test_off_in_a_hand_written_file_is_not_a_boolean(tmp_path):
    f = tmp_path / "s.yaml"; f.write_text("level: off\n")
    assert SL.load_state(f)["level"] == "off"


def test_pentest_confirm_typed_no_tty_refused(tmp_path):
    path = tmp_path / "security.local.yaml"
    with pytest.raises(SL.SecurityLevelError, match="no --yes"):
        change(tmp_path, "level", "pentest", isatty=lambda: False)
    assert not path.exists()
    with pytest.raises(SL.SecurityLevelError, match="not confirmed"):
        change(tmp_path, "level", "pentest", isatty=lambda: True, ask=lambda _p: "yes")
    assert not path.exists()
    change(tmp_path, "level", "pentest", isatty=lambda: True, ask=lambda _p: "pentest")
    assert SL.load_state(path)["confirmed"] == ["pentest"]
    # lowering drops the confirmation; raising again asks again
    change(tmp_path, "level", "guardian")
    assert SL.load_state(path)["confirmed"] == []
    with pytest.raises(SL.SecurityLevelError):
        change(tmp_path, "enable", "pentest", isatty=lambda: False)


def test_missing_model_is_a_clear_error_not_a_crash(tmp_path):
    x = g()
    x["models"][x["nodes"]["fleet-guardian"]["model"]]["gguf"] = str(tmp_path / "absent.gguf")
    env = {"FAMILIA_HOST": "miryam", "XDG_STATE_HOME": str(tmp_path)}
    with pytest.raises(SL.SecurityLevelError, match="not on this machine"):
        SL.change(x, SPEC, tmp_path / "s.yaml", "level", "guardian", environ=env)
    assert not (tmp_path / "s.yaml").exists()
    assert SL.model_state(x, "fleet-guardian", "miryam")[0] == "missing"
    assert SL.model_state(x, "freebsd-guardian", "miryam")[0] == "remote"


def run_cli(tmp_path, *args, stdin=subprocess.DEVNULL, extra_env=None):
    env = dict(os.environ, FAMILIA_SECURITY_OVERRIDE=str(tmp_path / "security.local.yaml"))
    env.pop("FAMILIA_SECURITY_LEVEL", None)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "security_levels.py"), *args],
                          capture_output=True, text=True, env=env, stdin=stdin)


def test_cli_end_to_end_keeps_graph_yaml_byte_identical(tmp_path):
    before = sha(GRAPH_PATH)
    for args in (["list"], ["status"], ["off", "--no-files"], ["guardian", "--no-files"],
                 ["guardian", "--no-files"], ["disable", "guardian", "--no-files"], ["status", "--json"],
                 ["full", "--no-files"], ["clear"]):
        r = run_cli(tmp_path, *args)
        assert r.returncode in (0, 1), (args, r.stderr)
        assert "Traceback" not in r.stderr
    assert sha(GRAPH_PATH) == before
    r = run_cli(tmp_path, "guardian", "--no-files")
    assert r.returncode == 0
    r = run_cli(tmp_path, "status")
    assert "security level: guardian" in r.stdout and "[off] pentests.fleet" in r.stdout
    assert "never started by `familia start`" in r.stdout
    assert sha(GRAPH_PATH) == before


def test_cli_has_no_yes_bypass(tmp_path):
    r = run_cli(tmp_path, "pentest", "--yes")
    assert r.returncode == 2 and "unrecognized arguments: --yes" in r.stderr
    r = run_cli(tmp_path, "pentest", "--no-files")  # stdin is not a terminal
    assert r.returncode == 1 and "typed confirmation" in r.stderr
    assert not (tmp_path / "security.local.yaml").exists()


def test_bad_override_file_is_refused(tmp_path):
    (tmp_path / "security.local.yaml").write_text("level: [x]\n")
    r = run_cli(tmp_path, "status")
    assert r.returncode == 1 and "level must be a level name" in r.stderr


def test_start_dry_run_takes_security_level(tmp_path):
    env = {"FAMILIA_HOST": "miryam", "XDG_STATE_HOME": str(tmp_path), "FAMILIA_SINGLE_NODE": "0"}
    base = [sys.executable, os.path.join(ROOT, "scripts", "start_graph.py"), "--dry-run", "--fleet"]
    run_env = dict(os.environ, **env)
    r = subprocess.run(base + ["--security-level=off"], capture_output=True, text=True, env=run_env)
    assert "security level off (from --security-level)" in r.stderr, r.stderr
    assert "fleet-guardian" not in r.stdout.split("active local nodes:")[-1].splitlines()[0]
    r = subprocess.run(base + ["--security-level=max"], capture_output=True, text=True, env=run_env)
    assert r.returncode != 0 and "choose one of" in (r.stderr + r.stdout)
    r = subprocess.run(base, capture_output=True, text=True, env=dict(run_env, FAMILIA_SECURITY_LEVEL="guardian"))
    assert "security level guardian (from FAMILIA_SECURITY_LEVEL)" in r.stderr


def test_validate_graph_applies_the_level(tmp_path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "validate_graph.py"), "--graph", GRAPH_PATH,
                        "--no-files"], capture_output=True, text=True,
                       env=dict(os.environ, FAMILIA_SECURITY_LEVEL="bogus"))
    assert r.returncode == 1 and "security level" in r.stderr


def test_override_file_is_gitignored_and_lookup_reuses_config_dir(tmp_path):
    assert "/security.local.yaml" in open(os.path.join(ROOT, ".gitignore")).read()
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert SL.resolve_override_path(GRAPH_PATH, env, for_write=True) == tmp_path / "familia" / "security.local.yaml"
