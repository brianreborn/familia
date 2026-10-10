"""RAM safety: estimated + reserve must fit; small hosts keep ~2 GiB free."""
import os, sys, copy
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import validate_graph as vg  # noqa: E402

CODER = os.path.expanduser("~/.local/share/gguf/models/coder/Qwen3.5-2B-Q4_K_M.gguf")
EMBED = os.path.expanduser("~/.local/share/gguf/models/embed/embeddinggemma-2-Q8_0.gguf")


def _base():
    g = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    g["_path"] = os.path.join(ROOT, "graph.yaml")
    return g


def test_baseline_fits_raised_reserve():
    if not (os.path.isfile(CODER) and os.path.isfile(EMBED)):
        return  # skip when GGUFs are absent
    errs, total = vg.validate(_base())
    ram_errs = [e for e in errs if "RAM" in e or "free after" in e or "OOM" in e]
    assert ram_errs == [], ram_errs
    assert total < 4000  # coder+embed ~3479


def test_estimated_plus_reserve_fails():
    if not os.path.isfile(CODER):
        return
    g = _base()
    # Drop embed so we only need coder; inflate reserve past miryam.
    g["nodes"] = {"coder": g["nodes"]["coder"]}
    g["agents"]["hermes"]["edges"] = {"model": "coder"}
    g["host"]["reserve_ram_mib"] = 5000  # 2928 + 5000 > 7270
    errs, total = vg.validate(g)
    assert any("reserve" in e and "exceeds host ram_mib" in e for e in errs), errs


def test_small_host_free_floor():
    if not (os.path.isfile(CODER) and os.path.isfile(EMBED)):
        return
    g = _base()
    g["host"]["ram_mib"] = 5000
    g["host"]["reserve_ram_mib"] = 200  # budget alone would pass; floor must catch it
    errs, total = vg.validate(g)
    assert any("2048 MiB floor" in e for e in errs), errs
