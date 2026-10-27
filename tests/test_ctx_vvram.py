"""64K / software-VVRAM coherent policy (docs/vvram-ssd/LAYER.md)."""
import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ctx_vvram as cv  # noqa: E402
import validate_graph as vg  # noqa: E402
import launch_status as ls  # noqa: E402


def _graph():
    return vg.load(os.path.join(ROOT, "graph.yaml"))


def test_vvram_spill_configured_angel_coder():
    g = _graph()
    assert cv.vvram_spill_configured(g["nodes"]["angel-coder"]) is True
    assert cv.vvram_spill_configured(g["nodes"]["coder"]) is False


def test_miryam_coder_64k_fits_without_swap_budget():
    g = _graph()
    assert g["nodes"]["coder"]["ctx"] >= 64000
    errs = vg.check_vvram_policy(g)
    assert not any("nodes.coder:" in e for e in errs), errs


def test_oversize_without_vvram_is_hard_error():
    g = _graph()
    n = copy.deepcopy(g["nodes"]["coder"])
    n["load_mode"] = "none"
    n.pop("swap_budget_mib", None)
    n.pop("spill_path", None)
    n["slot_save"] = False
    n["cache_ram_mib"] = 50000
    g2 = copy.deepcopy(g)
    g2["nodes"]["coder-oversized"] = n
    errs = vg.check_vvram_policy(g2)
    assert any("coder-oversized" in e and "LF_NEED_SPILL" in e for e in errs), errs


def test_admit_peak_mmap_bounded():
    g = copy.deepcopy(_graph())
    n = g["nodes"]["coder"]
    n["load_mode"] = "mmap"
    n["swap_budget_mib"] = 24576
    n["spill_path"] = "~/.cache/familia/spill/coder"
    n["cache_ram_mib"] = 512
    peak = vg.admit_peak_mib(g, "coder")
    assert peak < 8192 and isinstance(peak, int)


def test_lf_need_spill_code():
    assert ls.CODES["LF_NEED_SPILL"][0] == "LAUNCH_FAILED"
    assert ls.exit_code("LF_NEED_SPILL") == 72


def test_coder_server_args_ctx_and_spill():
    g = _graph()
    a = vg.server_args(g, "coder")
    assert a[a.index("-c") + 1] == "65536"
    assert a[a.index("--slot-save-path") + 1].endswith("spill/coder")
