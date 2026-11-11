"""spec_bench must not let extra args override the loopback --host (DESIGN.md Security)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "perf"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import spec_bench as sb  # noqa: E402


def test_extra_overrides_host_detects_flag_and_equals():
    assert sb.extra_overrides_host(["--temp", "0.2"]) is False
    assert sb.extra_overrides_host([]) is False
    assert sb.extra_overrides_host(["--host", "0.0.0.0"]) is True
    assert sb.extra_overrides_host(["--n-predict", "16", "--host=0.0.0.0"]) is True


def test_run_refuses_host_in_extra():
    out = sb.run(None, "x", ["--host", "0.0.0.0"], "log")
    assert "refusing --host" in out["error"]
    out = sb.run(None, "x", ["--n-predict", "16", "--host=0.0.0.0"], "log")
    assert "refusing --host" in out["error"]
