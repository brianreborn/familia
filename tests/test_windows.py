import copy, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from graph_types import validate_types  # noqa: E402
import validate_graph  # noqa: E402
BASE = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
def w(): x = copy.deepcopy(BASE); return x, x["hosts"]["qodesh"]["windows"]
def has(x, frag):
    e = validate_types(x); assert any(frag in m for m in e), e

def test_qodesh_windows_block():
    win = BASE["hosts"]["qodesh"]["windows"]
    assert win["autostart"] is False and win["avx_required"] is False
    assert os.path.exists(os.path.join(ROOT, *win["start_script"].split("\\")))

def test_windows_checks():
    x, v = w(); v["autostart"] = True; has(x, "autostart true needs startup scheduled-task")
    x, v = w(); v["startup"] = "scheduled-task"; del v["task_name"]; has(x, "needs task_name")
    x, v = w(); del v["start_script"]; has(x, "needs start_script")
    x, v = w(); v["avx_required"] = "no"; has(x, "expected true/false")
    x, v = w(); v["startup"] = "scheduled-task"; v["autostart"] = True; assert validate_types(x) == []

def test_scripts_shape():
    bat = open(os.path.join(ROOT, "scripts/windows/start.bat"), newline="").read()
    assert "E:\\temp\\familia\\models" in bat and "%USERPROFILE%\\familia\\models" in bat
    assert "127.0.0.1" in bat and "AVX" in bat
    ps = open(os.path.join(ROOT, "scripts/windows/install-task.ps1")).read()
    assert "SupportsShouldProcess" in ps and "-AtLogOn" in ps and "RunLevel Limited" in ps
    # opt-in: without -Install the script returns before registering
    assert ps.index("if (-not $Install)") < ps.index("Register-ScheduledTask")
