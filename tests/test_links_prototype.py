"""probe_links host-RAM record and plan_placement prediction math."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import plan_placement as pp, probe_links as pl  # noqa: E402


def test_host_ram_record():
    r = pl.host_ram(mib=8, reps=2)
    assert r["link"] == "host_ram" and r["GBps_rw"] > r["GBps"] > 0


def test_predict_cpu_uses_read_stream_rate():
    recs = [{"link": "host_ram", "GBps": 10.0, "GBps_rw": 20.0}]
    res = pp.predict(recs, 2e9)
    assert res[0]["placement"] == "cpu" and res[0]["tg_pred"] == 10.0
    assert pp.predict(recs, 2e9, active_frac=0.1)[0]["tg_pred"] == 100.0


def test_layer_stream_selected_when_model_exceeds_vram():
    recs = [{"link": "host_ram", "GBps": 10.0, "GBps_rw": 20.0}, {"vram_free": 256e6},
            {"link": "vram_copy", "GBps": 15.0}, {"link": "pcie_h2d", "how": "pinned", "GBps": 3.0}]
    res = pp.predict(recs, 3e9, layers=30)
    ls = [r for r in res if r["placement"] == "layer-stream"][0]
    assert abs(ls["tg_pred"] - 1 / (1.0 + ls["units"] * 2 * 10e-6)) < 0.01 and 2 * ls["unit_MiB"] * 1048576 <= 256e6 * 0.8
    assert not [r for r in pp.predict(recs, 1e8, layers=30) if r["placement"] == "layer-stream"]


def test_disk_stream_when_ram_budget_short():
    recs = [{"link": "host_ram", "GBps": 10.0, "GBps_rw": 20.0}, {"link": "disk_read", "GBps": 0.5}]
    res = pp.predict(recs, 2e9, ram_budget=1e9)
    assert res[0]["placement"] == "disk-stream" and abs(res[0]["tg_pred"] - 1 / (0.05 + 2.0)) < 0.01
