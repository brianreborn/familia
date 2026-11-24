"""hosts.local.yaml connection overlay + privacy lint (#104)."""
import os, sys, textwrap
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hosts_overlay as ho  # noqa: E402
import yaml  # noqa: E402


def test_tracked_graph_has_no_private_literals():
    path = os.path.join(ROOT, "graph.yaml")
    errs = ho.privacy_lint_path(path)
    assert errs == [], errs


def test_privacy_lint_rejects_rfc1918_and_termux(tmp_path):
    g = tmp_path / "g.yaml"
    g.write_text(textwrap.dedent("""\
        version: 2
        hosts:
          phone7:
            kind: phone
            measured: false
            gpus: null
            addr: 192.168.1.7
            user: u0_a439
            port: 8022
        meshes: {}
    """), encoding="utf-8")
    errs = ho.privacy_lint_path(g)
    assert any("192.168.1.7" in e for e in errs), errs
    assert any("u0_a439" in e for e in errs), errs


def test_merge_overlay_fills_placeholders(tmp_path, monkeypatch):
    graph = {
        "_path": str(tmp_path / "graph.yaml"),
        "hosts": {
            "phone7": {"kind": "phone", "addr": "REPLACE_ME", "user": "REPLACE_ME", "port": 8022},
            "miryam": {"kind": "laptop", "addr": "REPLACE_ME", "user": "REPLACE_ME", "port": 22},
        },
        "meshes": {
            "lan-bt": {"type": "bittorrent", "tracker": "miryam", "bind": "REPLACE_ME",
                       "port": 6969, "private": True, "client": "aria2c",
                       "members": ["miryam", "phone7"]},
        },
    }
    overlay = {
        "hosts": {
            "phone7": {"addr": "10.0.0.7", "user": "u0_a1", "port": 8022},
            "miryam": {"addr": "10.0.0.9", "user": "op", "port": 22},
        }
    }
    ho.merge_connection_overlay(graph, overlay=overlay)
    assert graph["hosts"]["phone7"]["addr"] == "10.0.0.7"
    assert graph["hosts"]["phone7"]["user"] == "u0_a1"
    assert graph["meshes"]["lan-bt"]["bind"] == "10.0.0.9"  # from tracker addr


def test_resolve_overlay_env_and_xdg(tmp_path, monkeypatch):
    overlay = tmp_path / "custom.yaml"
    overlay.write_text("hosts:\n  x: {addr: 10.0.0.1}\n", encoding="utf-8")
    monkeypatch.setenv("FAMILIA_HOSTS_OVERLAY", str(overlay))
    assert ho.resolve_overlay_path(environ=os.environ) == overlay
    monkeypatch.delenv("FAMILIA_HOSTS_OVERLAY")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "hosts.local.yaml").write_text("hosts: {}\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(cfg.parent), "HOME": str(tmp_path)}
    # config_dir uses XDG_CONFIG_HOME/familia — put file there
    fam = tmp_path / "familia"
    fam.mkdir()
    (fam / "hosts.local.yaml").write_text("hosts: {}\n", encoding="utf-8")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert ho.resolve_overlay_path(environ=env) == fam / "hosts.local.yaml"


def test_android_target_uses_overlay(tmp_path, monkeypatch):
    import subprocess
    graph = tmp_path / "graph.yaml"
    graph.write_text(textwrap.dedent("""\
        hosts:
          phone7:
            kind: phone
            addr: REPLACE_ME
            user: REPLACE_ME
            port: 8022
    """), encoding="utf-8")
    overlay = tmp_path / "hosts.local.yaml"
    overlay.write_text(textwrap.dedent("""\
        hosts:
          phone7:
            addr: 10.0.0.5
            user: u0_a9
            port: 2222
    """), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANDROID_")}
    env["FAMILIA_HOSTS_OVERLAY"] = str(overlay)
    script = os.path.join(ROOT, "scripts", "android_target.py")
    r = subprocess.run([sys.executable, script, "phone7", "--graph", str(graph)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["10.0.0.5", "u0_a9", "2222"]


def test_android_target_without_overlay_fails(tmp_path, monkeypatch):
    import subprocess
    graph = tmp_path / "graph.yaml"
    graph.write_text(textwrap.dedent("""\
        hosts:
          phone7:
            kind: phone
            addr: REPLACE_ME
            user: REPLACE_ME
            port: 8022
    """), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANDROID_")}
    env["FAMILIA_HOSTS_OVERLAY"] = str(tmp_path / "missing.yaml")
    script = os.path.join(ROOT, "scripts", "android_target.py")
    r = subprocess.run([sys.executable, script, "phone7", "--graph", str(graph)],
                       capture_output=True, text=True, env=env)
    assert r.returncode != 0
