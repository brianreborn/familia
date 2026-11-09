"""#124: hermes_harness resolve_hermes — snap / FreeBSD ports / PATH / env."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh


def _exists_set(present):
    present = set(present)
    return lambda p: bool(p) and p in present


def test_env_overrides_win(monkeypatch):
    b, py, sp = hh.resolve_hermes(
        environ={"HERMES_BIN": "/opt/h/bin/hermes", "HERMES_PY": "/opt/h/bin/python",
                 "HERMES_SP": "/opt/h/lib"},
        exists=lambda p: True,
        which=lambda n: None,
        system="Linux",
        run=lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
        missing="defaults",
    )
    assert (b, py, sp) == ("/opt/h/bin/hermes", "/opt/h/bin/python", "/opt/h/lib")


def test_linux_snap_when_present():
    b, py, sp = hh.resolve_hermes(
        environ={},
        exists=_exists_set([hh.SNAP_BIN, hh.SNAP_PY, hh.SNAP_SP]),
        which=lambda n: None,
        system="Linux",
        missing="defaults",
    )
    assert b == hh.SNAP_BIN and py == hh.SNAP_PY and sp == hh.SNAP_SP


def test_freebsd_ports_layout_preferred():
    """Angel/Uriel pkg: bin + python shebang path + libdir (not site-packages)."""
    present = {hh.FREEBSD_BIN, hh.FREEBSD_LIB, "/usr/local/bin/python3.12"}

    def which(n):
        return None

    # shebang read: fake via exists-only derive — inject HERMES_PY unset, mock _read_shebang
    real_read = hh._read_shebang

    def fake_shebang(path):
        if path == hh.FREEBSD_BIN:
            return "/usr/local/bin/python3.12"
        return real_read(path)

    hh_read = hh._read_shebang
    try:
        hh._read_shebang = fake_shebang
        b, py, sp = hh.resolve_hermes(
            environ={},
            exists=_exists_set(present),
            which=which,
            system="FreeBSD",
            run=lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
            missing="defaults",
        )
    finally:
        hh._read_shebang = hh_read
    assert b == hh.FREEBSD_BIN
    assert py == "/usr/local/bin/python3.12"
    assert sp == hh.FREEBSD_LIB


def test_freebsd_ignores_snap_path_strings():
    """On FreeBSD, even if a caller claims snap exists, ports bin wins when present."""
    present = {hh.FREEBSD_BIN, hh.FREEBSD_LIB, hh.SNAP_BIN}

    def fake_shebang(path):
        return "/usr/local/bin/python3.12" if path == hh.FREEBSD_BIN else None

    old = hh._read_shebang
    hh._read_shebang = fake_shebang
    try:
        b, py, sp = hh.resolve_hermes(
            environ={},
            exists=lambda p: p in present or p == "/usr/local/bin/python3.12",
            which=lambda n: None,
            system="FreeBSD",
            run=lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
            missing="defaults",
        )
    finally:
        hh._read_shebang = old
    assert b == hh.FREEBSD_BIN
    assert sp == hh.FREEBSD_LIB


def test_path_search_hermes_agent():
    def which(n):
        return {"hermes-agent": "/home/u/.local/bin/hermes-agent"}.get(n)

    b, py, sp = hh.resolve_hermes(
        environ={"HERMES_PY": "/home/u/.local/venv/bin/python",
                 "HERMES_SP": "/home/u/.local/venv/lib/python3.12/site-packages"},
        exists=_exists_set([]),
        which=which,
        system="Linux",
        missing="defaults",
    )
    assert b == "/home/u/.local/bin/hermes-agent"
    assert py.endswith("python")
    assert "site-packages" in sp


def test_missing_dies_actionable():
    with pytest.raises(SystemExit):
        hh.resolve_hermes(
            environ={},
            exists=_exists_set([]),
            which=lambda n: None,
            system="FreeBSD",
            missing="die",
        )


def test_ensure_hermes_updates_globals(monkeypatch):
    monkeypatch.setenv("HERMES_BIN", "/x/hermes-agent")
    monkeypatch.setenv("HERMES_PY", "/x/python")
    monkeypatch.setenv("HERMES_SP", "/x/lib/hermes-agent")
    # exists must see the env bin
    monkeypatch.setattr(hh, "_path_exists", lambda p: True)
    monkeypatch.setattr(hh, "resolve_hermes", lambda **kw: ("/x/hermes-agent", "/x/python", "/x/lib/hermes-agent"))
    b, py, sp = hh.ensure_hermes()
    assert hh.HERMES_BIN == b == "/x/hermes-agent"
    assert hh.HERMES_SP == "/x/lib/hermes-agent"


def test_hermes_prefix_nonsnap_uses_py(monkeypatch):
    hh.HERMES_BIN = "/usr/local/bin/hermes-agent"
    hh.HERMES_PY = "/usr/local/bin/python3.12"
    hh.HERMES_SP = "/usr/local/lib/hermes-agent"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": '{"system":"","volatile":"","tools":[]}', "stderr": ""})()

    monkeypatch.setattr(hh.subprocess, "run", fake_run)
    out = hh.hermes_prefix("/tmp/fake-home")
    assert out["tools"] == []
    assert calls and calls[0][0] == "/usr/local/bin/python3.12"
    assert "-c" in calls[0]


def test_load_graph_host_scope(tmp_path, monkeypatch):
    """File checks honor host= so angel validation ignores box GGUFs."""
    import validate_graph as vg
    seen = {}

    def fake_validate(g, check_files=True, host=None):
        seen["check_files"] = check_files
        seen["host"] = host
        return [], {}

    monkeypatch.setattr(vg, "validate", fake_validate)
    gpath = tmp_path / "g.yaml"
    gpath.write_text("hosts: {}\nnodes: {}\n")
    hh.load_graph(str(gpath), check_files=True, host="angel")
    assert seen == {"check_files": True, "host": "angel"}
    hh.load_graph(str(gpath), check_files=False, host=None)
    assert seen["check_files"] is False


def test_single_agent_render_allows_below_min_ctx(capsys, monkeypatch):
    import copy
    import yaml
    import hermes_modes as hm
    g = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    # Synthetic node below hermes min_ctx 64000 (angel-coder is now 65536 / #125).
    base = g["nodes"].get("angel-coder") or g["nodes"]["coder"]
    g["nodes"]["small-ctx"] = dict(copy.deepcopy(base), ctx=32768, parallel=1, port=19999, status="active")
    # single_agent refuses nodes on another fleet host; pretend we run on the node's host.
    monkeypatch.setattr(hm.socket, "gethostname", lambda: g["nodes"]["small-ctx"]["host"])
    g2, name = hm.single_agent(g, "hermes", "small-ctx", enforce_min_ctx=False)
    assert name == "hermes@small-ctx"
    assert g2["agents"][name]["context_length"] == 32768
    err = capsys.readouterr().err
    assert "continuing for --render-only" in err
    with pytest.raises(SystemExit):
        hm.single_agent(g, "hermes", "small-ctx", enforce_min_ctx=True)


def test_angel_coder_meets_hermes_min_ctx(monkeypatch):
    """#125: angel-coder.ctx 65536 clears agents.hermes.min_ctx 64000."""
    import yaml
    import hermes_modes as hm
    g = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    if "angel-coder" not in g.get("nodes", {}):
        pytest.skip("no angel-coder in graph")
    assert hm.slot(g["nodes"]["angel-coder"]) >= g["agents"]["hermes"]["min_ctx"]
    monkeypatch.setattr(hm.socket, "gethostname", lambda: g["nodes"]["angel-coder"]["host"])
    g2, name = hm.single_agent(g, "hermes", "angel-coder", enforce_min_ctx=True)
    assert name == "hermes@angel-coder"
    assert g2["agents"][name]["context_length"] == 65536


def _write(path, text, mode=0o755):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, mode)   # installed console scripts are executable
    return str(path)


LEGACY = "#!/v/bin/python3\nimport sys\nfrom agent.legacy_cli import main\nsys.exit(main())\n"
FULL = "#!/v/bin/python3\nimport sys\nfrom hermes_cli.main import main\nsys.exit(main())\n"


def test_path_prefers_full_cli_over_legacy_runner(tmp_path):
    """pip/uv/install.sh: `hermes-agent` is agent.legacy_cli (no -z/-t/desktop); use `hermes`."""
    legacy = _write(tmp_path / "bin" / "hermes-agent", LEGACY)
    full = _write(tmp_path / "bin" / "hermes", FULL)
    b, _py, _sp = hh.resolve_hermes(
        environ={"HERMES_PY": "/v/bin/python3", "HERMES_SP": "/v/lib"},
        exists=lambda p: os.path.exists(p) or p in ("/v/bin/python3", "/v/lib"),
        which=lambda n: {"hermes-agent": legacy, "hermes": full}.get(n),
        system="Linux", missing="defaults")
    assert b == full


def test_path_keeps_non_legacy_hermes_agent(tmp_path):
    """Packaged wrappers named hermes-agent (ports, distro) are the full CLI: keep them."""
    wrapper = _write(tmp_path / "bin" / "hermes-agent", "#!/bin/sh\nexec python3 -m hermes_cli.main \"$@\"\n")
    _write(tmp_path / "bin" / "hermes", FULL)
    b, _py, _sp = hh.resolve_hermes(
        environ={"HERMES_PY": "/v/bin/python3", "HERMES_SP": "/v/lib"},
        exists=lambda p: os.path.exists(p) or p in ("/v/bin/python3", "/v/lib"),
        which=lambda n: wrapper if n == "hermes-agent" else None,
        system="Linux", missing="defaults")
    assert b == wrapper


def test_explicit_legacy_bin_wins_but_warns(tmp_path, capsys):
    legacy = _write(tmp_path / "bin" / "hermes-agent", LEGACY)
    b, _py, _sp = hh.resolve_hermes(
        environ={"HERMES_BIN": legacy, "HERMES_PY": "/v/bin/python3", "HERMES_SP": "/v/lib"},
        exists=lambda p: True, which=lambda n: None, system="Linux", missing="die")
    assert b == legacy
    assert "legacy single-query runner" in capsys.readouterr().err


def test_snap_site_packages_follows_snap_python(monkeypatch):
    """Upstream moved its runtime to python 3.14; the snap SP is no longer assumed to be 3.12."""
    sp314 = "/snap/hermes-agent/current/lib/python3.14/site-packages"
    monkeypatch.setattr(hh.glob, "glob", lambda pat: [hh.SNAP_SP, sp314] if pat.startswith("/snap/") else [])
    b, py, sp = hh.resolve_hermes(environ={}, exists=_exists_set([hh.SNAP_BIN, hh.SNAP_PY, hh.SNAP_SP, sp314]),
                                  which=lambda n: None, system="Linux", missing="defaults")
    assert b == hh.SNAP_BIN and sp == sp314


# --- Boundary fix-forward (c): HERMES_BIN / sibling pick must be a safe executable -----------------

def _die_env(b):
    return {"HERMES_BIN": b, "HERMES_PY": "/v/bin/python3", "HERMES_SP": "/v/lib"}


def test_exec_problem_rules(tmp_path):
    ok = _write(tmp_path / "ok", FULL)
    assert hh.exec_problem(ok) is None
    assert hh.exec_problem("bin/hermes") == "not an absolute path"
    assert hh.exec_problem(str(tmp_path)) == "not a regular file"
    assert hh.exec_problem(_write(tmp_path / "noexec", FULL, mode=0o644)) == "not executable"
    assert hh.exec_problem(_write(tmp_path / "ww", FULL, mode=0o757)) == "world-writable"
    assert hh.exec_problem(str(tmp_path / "absent")).startswith("cannot stat")
    link = tmp_path / "link"; link.symlink_to(ok)
    assert hh.exec_problem(str(link)) is None          # symlink to a safe file is fine (snap /snap/bin/*)


@pytest.mark.parametrize("bad", ["relative/hermes", "DIR", "NOEXEC", "WW"])
def test_launch_refuses_unsafe_hermes_bin(tmp_path, bad, capsys):
    paths = {"DIR": str(tmp_path), "NOEXEC": _write(tmp_path / "n" / "hermes", FULL, mode=0o644),
             "WW": _write(tmp_path / "w" / "hermes", FULL, mode=0o777)}
    b = paths.get(bad, bad)
    with pytest.raises(SystemExit):
        hh.resolve_hermes(environ=_die_env(b), exists=lambda p: True, which=lambda n: None,
                          system="Linux", missing="die")
    assert "refusing to launch" in capsys.readouterr().err


def test_launch_accepts_safe_hermes_bin(tmp_path):
    b = _write(tmp_path / "bin" / "hermes", FULL)
    assert hh.resolve_hermes(environ=_die_env(b), exists=lambda p: True, which=lambda n: None,
                             system="Linux", missing="die")[0] == b


def test_sibling_hermes_not_taken_when_world_writable(tmp_path, capsys):
    legacy = _write(tmp_path / "bin" / "hermes-agent", LEGACY)
    _write(tmp_path / "bin" / "hermes", FULL, mode=0o777)
    b, _py, _sp = hh.resolve_hermes(
        environ={"HERMES_PY": "/v/bin/python3", "HERMES_SP": "/v/lib"},
        exists=lambda p: os.path.exists(p) or p in ("/v/bin/python3", "/v/lib"),
        which=lambda n: legacy if n == "hermes-agent" else None, system="Linux", missing="defaults")
    assert b == legacy
    assert "world-writable" in capsys.readouterr().err
