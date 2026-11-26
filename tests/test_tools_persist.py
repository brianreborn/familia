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


READ_ONLY = "read_file,file_glob_search,grep_search,get_info"


def test_tools_saved_0600_and_reapplied(tmp_path):
    env = _env(tmp_path)
    assert tp.apply_args("127.0.0.1", 9941, ["--temp", "0.3", "--tools", "all"], env=env) == [
        "--temp", "0.3", "--tools", "all"]
    path = tp.state_path(9941, env)
    assert (stat.S_IMODE(os.stat(path).st_mode) & 0o777) == 0o600
    assert os.stat(path).st_uid == os.getuid()
    with open(path, encoding="ascii") as fh:
        assert fh.read().strip() == READ_ONLY
    parent = os.path.dirname(path)
    assert (stat.S_IMODE(os.stat(parent).st_mode) & 0o777) == 0o700
    assert os.stat(parent).st_uid == os.getuid()
    assert tp.apply_args("127.0.0.1", 9941, ["--temp", "0.3"], env=env) == [
        "--temp", "0.3", "--tools", READ_ONLY]


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


def test_launcher_bind_matches_familia_tools_check():
    """Same allowlist as the shell check: 127.0.0.1, ::1, localhost. Not 127/8."""
    assert tp._launcher_bind("127.0.0.1")
    assert tp._launcher_bind("::1")
    assert tp._launcher_bind("[::1]")
    assert tp._launcher_bind("localhost")
    for bind in ("127.0.0.2", "::ffff:127.0.0.1", "0.0.0.0", "::", "LOCALHOST", "192.168.1.1"):
        assert not tp._launcher_bind(bind)
        assert validate_graph._loopback("127.0.0.2") is True


def test_saved_tools_refused_on_127_0_0_2(tmp_path):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.2", 9941, [], env=env)
    assert ei.value.code == 2


def test_explicit_cli_overwrites_saved_list(tmp_path):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    assert tp.apply_args("127.0.0.1", 9941, ["--tools", "grep_search"], env=env) == ["--tools", "grep_search"]
    assert tp.apply_args("127.0.0.1", 9941, [], env=env) == ["--tools", "grep_search"]


def test_write_tools_are_not_persisted(tmp_path):
    env = _env(tmp_path)
    assert tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file,write_file"], env=env) == [
        "--tools", "read_file,write_file"]
    with open(tp.state_path(9941, env), encoding="ascii") as fh:
        assert fh.read().strip() == "read_file"
    assert tp.apply_args("127.0.0.1", 9941, [], env=env) == ["--tools", "read_file"]


def _plant(env, text, mode=0o600):
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    path = tp.state_path(9941, env)
    with open(path, "w", encoding="ascii") as fh:
        fh.write(text)
    os.chmod(path, mode)
    return path


def test_planted_all_is_refused(tmp_path):
    env = _env(tmp_path)
    _plant(env, "all\n")
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.1", 9941, [], env=env)
    assert ei.value.code == 2


def test_empty_truncated_and_unknown_files_are_refused(tmp_path):
    env = _env(tmp_path)
    for text in ("", "   \n", "read_fil\n", "*\n", "not_a_tool\n"):
        _plant(env, text)
        with pytest.raises(SystemExit) as ei:
            tp.apply_args("127.0.0.1", 9941, [], env=env)
        assert ei.value.code == 2, text


def test_group_writable_parent_is_refused(tmp_path):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    parent = os.path.dirname(tp.state_path(9941, env))
    os.chmod(parent, 0o770)
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.1", 9941, [], env=env)
    assert ei.value.code == 2


def test_familia_dir_symlink_is_refused(tmp_path):
    env = _env(tmp_path)
    base = tmp_path / "config"
    base.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, base / "familia")
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    assert ei.value.code == 2


def test_wrong_owner_is_refused(tmp_path, monkeypatch):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    real = os.fstat

    def fstat(fd):
        st = real(fd)
        if stat.S_ISREG(st.st_mode) and st.st_size > 0:
            return type("S", (), {
                "st_mode": st.st_mode, "st_uid": st.st_uid + 1, "st_size": st.st_size})()
        return st

    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.1", 9941, [], env=env)
    assert ei.value.code == 2


def test_read_uses_nofollow_and_skips_lstat(tmp_path, monkeypatch):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    seen = []
    real_open = os.open
    real_lstat = os.lstat

    def opened(path, flags, *args, **kwargs):
        if os.path.basename(str(path)) == "9941":
            seen.append(flags)
        if args:
            return real_open(path, flags, args[0])
        if "mode" in kwargs:
            return real_open(path, flags, kwargs["mode"])
        return real_open(path, flags)

    def lstat(path):
        if os.path.basename(str(path)) == "9941":
            raise AssertionError("lstat on the tools file")
        return real_lstat(path)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "lstat", lstat)
    assert tp.apply_args("127.0.0.1", 9941, [], env=env) == ["--tools", "read_file"]
    assert seen and seen[0] & os.O_NOFOLLOW


def test_fsync_file_then_replace_then_dir(tmp_path, monkeypatch):
    order = []
    real_fsync = os.fsync
    real_replace = os.replace

    def fsync(fd):
        st = os.fstat(fd)
        order.append("dir" if stat.S_ISDIR(st.st_mode) else "file")
        return real_fsync(fd)

    def replace(src, dst):
        order.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=_env(tmp_path))
    assert order == ["file", "replace", "dir"]


def test_dir_fsync_skipped_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "nt")
    called = []
    monkeypatch.setattr(os, "open", lambda *a, **k: called.append(a))
    tp._fsync_dir(str(tmp_path))
    assert called == []


def test_replace_retries_permission_error_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "nt")
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.write_text("x")
    tries = {"n": 0}
    real = os.replace

    def replace(a, b):
        tries["n"] += 1
        if tries["n"] < 3:
            raise PermissionError("busy")
        return real(a, b)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(tp.time, "sleep", lambda _s: None)
    tp._replace(str(src), str(dst))
    assert tries["n"] == 3
    assert dst.read_text() == "x"


def test_fchmod_falls_back_to_chmod(monkeypatch, tmp_path):
    monkeypatch.delattr(os, "fchmod", raising=False)
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    mode = stat.S_IMODE(os.stat(tp.state_path(9941, env)).st_mode) & 0o777
    assert mode == 0o600


def test_short_write_is_refused(monkeypatch, tmp_path):
    real = os.write

    def write(fd, data):
        raw = bytes(data)
        if raw.startswith(b"read_file"):
            return 0
        return real(fd, data)

    monkeypatch.setattr(os, "write", write)
    with pytest.raises(SystemExit) as ei:
        tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=_env(tmp_path))
    assert ei.value.code == 2


def test_read_holds_the_lock(tmp_path, monkeypatch):
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    held = []
    real = tp._read_saved

    def wrapped(port, env_):
        fd = os.open(tp.lock_path(env_), os.O_RDWR)
        try:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append("free")
                fcntl.flock(fd, fcntl.LOCK_UN)
            except BlockingIOError:
                held.append("held")
        finally:
            os.close(fd)
        return real(port, env_)

    monkeypatch.setattr(tp, "_read_saved", wrapped)
    assert tp.apply_args("127.0.0.1", 9941, [], env=env) == ["--tools", "read_file"]
    assert held == ["held"]


def test_decide_sees_the_write_that_landed_before_the_lock(tmp_path):
    import threading
    env = _env(tmp_path)
    tp.apply_args("127.0.0.1", 9941, ["--tools", "read_file"], env=env)
    lock = tp._acquire_lock(env)
    path = tp.state_path(9941, env)
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    os.write(fd, b"grep_search\n")
    os.close(fd)
    os.chmod(path, 0o600)
    done = {}

    def run():
        done["args"] = tp.apply_args("127.0.0.1", 9941, [], env=env)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(0.2)
    assert thread.is_alive()
    lock.release()
    thread.join(2)
    assert done["args"] == ["--tools", "grep_search"]


def test_stale_all_narrows_to_the_fleet_list(tmp_path, monkeypatch):
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    monkeypatch.setenv("FAMILIA_GENERATED_DIR", str(gen_dir))
    path = gen_dir / "graph-angel.yaml"
    path.write_text("placeholder\n")
    fleet = _graph({"angel-coder": _node(tools=["read_file", "grep_search"])})
    graph = _graph({"coder": _node(tools="all")})
    graph["_path"] = str(path)
    assert tp.restore_server_tools(graph, fleet=fleet) == 1
    assert graph["nodes"]["coder"]["server_tools"] == ["read_file", "grep_search"]
    assert validate_graph.tools_argv(graph, "coder") == ["--tools", "read_file,grep_search"]


def test_explicit_all_without_a_matching_fleet_policy_is_preserved(tmp_path, monkeypatch):
    """A standalone generated graph is authoritative, not a read-only fallback."""
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    monkeypatch.setenv("FAMILIA_GENERATED_DIR", str(gen_dir))
    path = gen_dir / "graph-note9.yaml"
    path.write_text("placeholder\\n")
    graph = _graph({"coder": _node(tools="all")})
    graph["_path"] = str(path)
    assert tp.restore_server_tools(graph, fleet=_graph({})) == 0
    assert graph["nodes"]["coder"]["server_tools"] == "all"
    assert validate_graph.tools_argv(graph, "coder") == ["--tools", "all"]


def test_live_fleet_all_is_not_narrowed(tmp_path, monkeypatch):
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    monkeypatch.setenv("FAMILIA_GENERATED_DIR", str(gen_dir))
    path = gen_dir / "graph-angel.yaml"
    path.write_text("placeholder\n")
    fleet = _graph({"angel-coder": _node(tools="all")})
    graph = _graph({"coder": _node(tools="all")})
    graph["_path"] = str(path)
    assert tp.restore_server_tools(graph, fleet=fleet) == 0
    assert graph["nodes"]["coder"]["server_tools"] == "all"


def test_windows_launcher_skips_the_hook(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert tp.launcher_persists_tools() is False
    text = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "windows", "start.bat"),
                encoding="ascii").read()
    assert "skipped" in text and "tools_persist.py" in text


def test_read_only_names_match_validate_graph():
    assert list(tp.READ_ONLY_TOOLS) == list(validate_graph.READ_ONLY_TOOLS)
