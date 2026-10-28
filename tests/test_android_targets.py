import os, re, subprocess, sys, textwrap
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "scripts", "android_target.py")

def run(*a, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("ANDROID_")}
    e.update(env or {})
    return subprocess.run([sys.executable, T, *a], capture_output=True, text=True, env=e)

def _overlay_env(tmp_path):
    overlay = tmp_path / "hosts.local.yaml"
    overlay.write_text(textwrap.dedent("""\
        hosts:
          phone7:
            addr: 10.0.0.7
            user: u0_a439
            port: 8022
          phone8:
            addr: 10.0.0.8
            user: u0_a414
            port: 8022
    """), encoding="utf-8")
    return {"FAMILIA_HOSTS_OVERLAY": str(overlay)}

def test_graph_targets(tmp_path):
    env = _overlay_env(tmp_path)
    assert run("phone7", env=env).stdout.split() == ["10.0.0.7", "u0_a439", "8022"]
    assert run("phone8", env=env).stdout.split() == ["10.0.0.8", "u0_a414", "8022"]
    assert set(run("--list", env=env).stdout.split()) >= {"phone7", "phone8"}

def test_env_override_and_errors(tmp_path):
    env = _overlay_env(tmp_path)
    assert run("phone7", env={**env, "ANDROID_HOST": "10.0.0.5", "ANDROID_PORT": "2222"}).stdout.split() == ["10.0.0.5", "u0_a439", "2222"]
    assert run("nosuch", env=env).returncode != 0
    assert run(env=env).returncode != 0

def test_scripts_have_no_hardcoded_targets_or_sshpass():
    for f in ("android_start.sh", "android_multi_start.sh", "watchdog_android.sh"):
        s = open(os.path.join(ROOT, f)).read()
        assert "sshpass" not in s and "StrictHostKeyChecking=no" not in s
        assert not re.search(r"\b\d+\.\d+\.\d+\.\d+\b", s) and not re.search(r"u0_a\d+", s)
        assert subprocess.run(["bash", "-n", os.path.join(ROOT, f)]).returncode == 0
