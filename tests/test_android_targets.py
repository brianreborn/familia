import os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "scripts", "android_target.py")

def run(*a, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("ANDROID_")}
    e.update(env or {})
    return subprocess.run([sys.executable, T, *a], capture_output=True, text=True, env=e)

def test_graph_targets():
    assert run("phone7").stdout.split() == ["192.168.1.7", "u0_a439", "8022"]
    assert run("phone8").stdout.split() == ["192.168.1.8", "u0_a414", "8022"]
    assert set(run("--list").stdout.split()) >= {"phone7", "phone8"}

def test_env_override_and_errors():
    assert run("phone7", env={"ANDROID_HOST": "10.0.0.5", "ANDROID_PORT": "2222"}).stdout.split() == ["10.0.0.5", "u0_a439", "2222"]
    assert run("nosuch").returncode != 0
    assert run().returncode != 0

def test_scripts_have_no_hardcoded_targets_or_sshpass():
    for f in ("android_start.sh", "android_multi_start.sh", "watchdog_android.sh"):
        s = open(os.path.join(ROOT, f)).read()
        assert "sshpass" not in s and "StrictHostKeyChecking=no" not in s
        assert not re.search(r"\b\d+\.\d+\.\d+\.\d+\b", s) and not re.search(r"u0_a\d+", s)
        assert subprocess.run(["bash", "-n", os.path.join(ROOT, f)]).returncode == 0
