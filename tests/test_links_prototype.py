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
