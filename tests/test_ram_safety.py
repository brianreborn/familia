"""RAM safety: estimated + reserve must fit; small hosts keep ~2 GiB free."""
import os, sys
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import validate_graph as vg  # noqa: E402

CODER = os.path.expanduser("~/.local/share/gguf/models/coder/Qwen3.5-2B-Q4_K_M.gguf")
EMBED = os.path.expanduser("~/.local/share/gguf/models/embed/embeddinggemma-2-Q8_0.gguf")
pytestmark = pytest.mark.skipif(
    not (os.path.isfile(CODER) and os.path.isfile(EMBED)),
    reason="coder and embedding GGUF fixtures are required",
)


@pytest.fixture(autouse=True)
def _as_miryam(monkeypatch):
    # These fixtures model miryam's nodes; validate() scopes file/RAM checks to the local host.
    monkeypatch.setenv("FAMILIA_HOST", "miryam")
    monkeypatch.setattr(vg, "host_swap_total_mib", lambda: None)  # not this machine's real swap
    monkeypatch.setattr(vg, "live_ram_mib", lambda: None)  # model miryam's snapshot, not this box (#224)


def _totals(errs, totals, host="miryam"):
    # #224: validate() returns {} when it stops early (schema errors, host scope); show why
    # instead of a bare KeyError.
    assert host in totals, (f"no RAM total for {host!r}; validate errors: {errs}; warnings: {vg.WARNINGS}")
    return totals[host]


def _base():
    g = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    g["_path"] = os.path.join(ROOT, "graph.yaml")
    return g


def test_baseline_fits_raised_reserve():
    errs, totals = vg.validate(_base())
    ram_errs = [e for e in errs if "RAM" in e or "free after" in e or "OOM" in e]
    assert ram_errs == [], ram_errs
    assert _totals(errs, totals) < 4000  # coder+embed ~3479


@pytest.mark.proving_ground  # depends on local model files / host fleet state
def test_estimated_plus_reserve_fails():
    g = _base()
    g["hosts"]["miryam"]["reserve_ram_mib"] = 5000  # coder+embed ~3479 + reserve exceeds 7270
    errs, totals = vg.validate(g)
    # A node that no longer fits ram_mib - reserve is a hard error (no silent OOM; LF_NEED_SPILL).
    assert any("exceeds host 'miryam' usable" in e and "reserve_ram_mib 5000" in e and "OOM" in e
               for e in errs), (errs, vg.WARNINGS)


def test_small_host_free_floor():
    g = _base()
    g["hosts"]["miryam"]["ram_mib"] = 5000
    g["hosts"]["miryam"]["reserve_ram_mib"] = 200  # budget alone would pass; floor must catch it
    errs, totals = vg.validate(g)
    assert any("2048 MiB provisional floor" in w for w in vg.WARNINGS), vg.WARNINGS


def test_overcommit_is_hard_error():
    g = _base()
    g["hosts"]["miryam"]["ram_mib"] = 1000  # estimate > physical RAM
    g["hosts"]["miryam"]["reserve_ram_mib"] = 0  # else the reserve >= ram_mib check fires first and hides it
    errs, totals = vg.validate(g)
    assert any("overcommit" in e for e in errs), errs

