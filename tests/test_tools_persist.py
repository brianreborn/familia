"""#630: --tools survives a restart and a stale generated graph."""
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import tools_persist as tp
import validate_graph


def _env(tmp_path):
    return {"XDG_CONFIG_HOME": str(tmp_path / "config"), "HOME": str(tmp_path)}


def test_tools_saved_0600_and_reapplied(tmp_path):
    env = _env(tmp_path)
    assert tp.apply_args("127.0.0.1", 9941, ["--temp", "0.3", "--tools", "all"], env=env) == [
        "--temp", "0.3", "--tools", "all"]
    path = tp.state_path(9941, env)
    assert (stat.S_IMODE(os.stat(path).st_mode) & 0o777) == 0o600
    with open(path, encoding="ascii") as fh:
        assert fh.read().strip() == "all"
    parent = os.path.dirname(path)
    assert (stat.S_IMODE(os.stat(parent).st_mode) & 0o777) == 0o700
    assert tp.apply_args("127.0.0.1", 9941, ["--temp", "0.3"], env=env) == [
        "--temp", "0.3", "--tools", "all"]


def test_tools_none_clears_the_save(tmp_path):
    env = _env(tmp_path)
    tp.apply_args("::1", "9941", ["--tools=all"], env=env)
    assert tp.apply_args("localhost", 9941, ["--tools", "none"], env=env) == []
    assert tp.apply_args("[::1]", 9941, [], env=env) == []


def test_saved_tools_refused_off_loopback(tmp_path):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "all"], env=env)
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("0.0.0.0", 9941, [], env=env)
    assert ei.value.code == 2


def test_tools_on_non_loopback_are_not_saved(tmp_path):
    env = _env(tmp_path)
    with pytest.raises(SystemExit):
        tp.apply_args("192.168.1.9", 9941, ["--tools", "all"], env=env)
    assert not os.path.exists(tp.state_path(9941, env))


def test_symlink_state_is_refused(tmp_path):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "all"], env=env)
    path = tp.state_path(9941, env)
    other = tmp_path / "other"
    other.write_text("all\n")
    os.unlink(path)
    os.symlink(other, path)
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.1", 9941, [], env=env)
    assert ei.value.code == 2


def test_group_readable_state_is_refused(tmp_path):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "all"], env=env)
    path = tp.state_path(9941, env)
    os.chmod(path, 0o640)
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.1", 9941, [], env=env)
    assert ei.value.code == 2


def test_invalid_tool_token_refused(tmp_path):
    env = _env(tmp_path)
    with pytest.raises(SystemExit):
        tp.apply_args("127.0.0.1", 9941, ["--tools", "rm -rf"], env=env)


def _node(host="angel", role="coder", port=18200, tools=None):
    node = {"role": role, "model": "m", "host": host, "bind": "127.0.0.1", "port": port}
    if tools is not None:
        node["server_tools"] = tools
    return node


def _graph(nodes):
    return {"nodes": nodes, "models": {"m": {"role": "coder"}}}


def test_generated_graph_restores_server_tools(tmp_path, monkeypatch):
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    monkeypatch.setenv("FAMILIA_GENERATED_DIR", str(gen_dir))
    path = gen_dir / "graph-angel.yaml"
    path.write_text("placeholder\n")
    fleet = _graph({"angel-coder": _node(tools="all")})
    graph = _graph({"coder": _node()})
    graph["_path"] = str(path)
    assert tp.restore_server_tools(graph, fleet=fleet) == 1
    assert graph["nodes"]["coder"]["server_tools"] == "all"
    assert validate_graph.tools_argv(graph, "coder") == ["--tools", "all"]


def test_explicit_opt_out_on_generated_graph_wins(tmp_path, monkeypatch):
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    monkeypatch.setenv("FAMILIA_GENERATED_DIR", str(gen_dir))
    path = gen_dir / "graph-angel.yaml"
    path.write_text("placeholder\n")
    fleet = _graph({"angel-coder": _node(tools="all")})
    graph = _graph({"coder": _node(tools=[])})
    graph["_path"] = str(path)
    assert tp.restore_server_tools(graph, fleet=fleet) == 0
    assert graph["nodes"]["coder"]["server_tools"] == []
    assert validate_graph.tools_argv(graph, "coder") == []


def test_fleet_graph_is_not_rewritten(tmp_path):
    graph = _graph({"coder": _node()})
    graph["_path"] = str(tmp_path / "graph.yaml")
    fleet = _graph({"angel-coder": _node(tools="all")})
    assert tp.restore_server_tools(graph, fleet=fleet) == 0
    assert "server_tools" not in graph["nodes"]["coder"]


def test_disagreeing_fleet_nodes_are_not_copied(tmp_path, monkeypatch):
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    monkeypatch.setenv("FAMILIA_GENERATED_DIR", str(gen_dir))
    path = gen_dir / "graph-angel.yaml"
    path.write_text("placeholder\n")
    fleet = _graph({
        "coder-a": _node(port=1, tools="all"),
        "coder-b": _node(port=2, tools=["read_file"]),
    })
    graph = _graph({"coder": _node(port=9)})
    graph["_path"] = str(path)
    assert tp.restore_server_tools(graph, fleet=fleet) == 0
    assert "server_tools" not in graph["nodes"]["coder"]


def test_same_port_breaks_a_role_tie(tmp_path, monkeypatch):
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    monkeypatch.setenv("FAMILIA_GENERATED_DIR", str(gen_dir))
    path = gen_dir / "graph-angel.yaml"
    path.write_text("placeholder\n")
    fleet = _graph({
        "coder-a": _node(port=18200, tools="all"),
        "coder-b": _node(port=18299, tools=["read_file"]),
    })
    graph = _graph({"coder": _node(port=18200)})
    graph["_path"] = str(path)
    assert tp.restore_server_tools(graph, fleet=fleet) == 1
    assert graph["nodes"]["coder"]["server_tools"] == "all"


def test_loopback_matches_validate_graph():
    for bind in ("127.0.0.1", "127.0.0.2", "localhost", "::1", "[::1]", "::ffff:127.0.0.1",
                 "0.0.0.0", "::", "192.168.1.1", "LOCALHOST"):
        assert tp._loopback(bind) is validate_graph._loopback(bind)
