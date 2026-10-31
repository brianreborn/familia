"""Offline tests for the RouterBench cached-response scorer (synthetic fixture only)."""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import routerbench_scorer as RB

FIX = ROOT / "tests" / "fixtures" / "routerbench" / "synthetic_wide.jsonl"


@pytest.fixture
def data():
    return RB.load(str(FIX))


def test_load_detects_models_and_rows(data):
    recs, models = data
    assert models == ["big", "mid", "tiny"]
    assert len(recs) == 6 and recs[0]["scores"] == {"big": 1.0, "mid": 1.0, "tiny": 1.0}


def test_env_var_path(monkeypatch):
    monkeypatch.setenv(RB.DATA_ENV, str(FIX))
    recs, _ = RB.load()
    assert len(recs) == 6


def test_missing_path_errors(monkeypatch, tmp_path):
    monkeypatch.delenv(RB.DATA_ENV, raising=False)
    with pytest.raises(SystemExit):
        RB.load()
    with pytest.raises(SystemExit):
        RB.load(str(tmp_path / "nope.pkl"))


def test_single_models_and_best_single(data):
    recs, models = data
    t = RB.single_model_table(recs, models)
    assert t["tiny"]["quality"] == pytest.approx(2 / 6) and t["tiny"]["total_cost"] == pytest.approx(0.006)
    assert t["mid"]["quality"] == pytest.approx(3 / 6) and t["mid"]["total_cost"] == pytest.approx(0.06)
    assert t["big"]["quality"] == pytest.approx(4 / 6) and t["big"]["total_cost"] == pytest.approx(0.6)
    assert RB.best_single(t) == "big"


def test_oracle_best_quality_cheapest_tiebreak(data):
    recs, _ = data
    o = RB.evaluate(recs, RB.oracle_choice)
    assert o["quality"] == pytest.approx(5 / 6)
    assert o["total_cost"] == pytest.approx(0.123)
    assert o["picks"] == {"big": 1, "mid": 2, "tiny": 3}


def test_report_routes_policy(tmp_path, data):
    recs, models = data
    routes = tmp_path / "routes.jsonl"
    # route gsm8k to mid, everything else to big
    routes.write_text("\n".join(json.dumps({"sample_id": r["sample_id"],
                                            "model": "mid" if r["eval_name"] == "gsm8k" else "big"})
                                for r in recs))
    rep = RB.report(recs, models, f"routes:{routes}")
    p = rep["policy"]
    assert p["quality"] == pytest.approx(4 / 6) and p["total_cost"] == pytest.approx(0.42)
    assert rep["vs_best_single"]["quality_delta"] == pytest.approx(0.0)
    assert rep["vs_best_single"]["cost_ratio"] == pytest.approx(0.7)
    assert rep["vs_oracle"]["quality_gap"] == pytest.approx(1 / 6)
    assert p["by_eval"]["gsm8k"] == {"n": 2, "quality": 1.0, "total_cost": pytest.approx(0.02)}


def test_routes_missing_sample_is_skipped(tmp_path, data):
    recs, models = data
    routes = tmp_path / "r.jsonl"
    routes.write_text(json.dumps({"sample_id": "s1", "model": "tiny"}))
    p = RB.evaluate(recs, RB.make_policy(f"routes:{routes}", models))
    assert p["n"] == 1 and p["skipped_no_cached_response"] == 5


def test_random_policy_is_seeded(data):
    recs, models = data
    a = RB.evaluate(recs, RB.make_policy("random", models, seed=1))
    b = RB.evaluate(recs, RB.make_policy("random", models, seed=1))
    assert a == b


def test_filters_and_csv(tmp_path, data):
    recs, _ = RB.load(str(FIX), evals=["mmlu"], models=["tiny", "big"])
    assert len(recs) == 2 and set(recs[0]["scores"]) == {"tiny", "big"}
    rows = [json.loads(l) for l in FIX.read_text().splitlines()]
    p = tmp_path / "rb.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    crecs, cmodels = RB.load(str(p))
    assert cmodels == data[1] and [r["scores"] for r in crecs] == [r["scores"] for r in data[0]]


def test_pickle_wide_frame(tmp_path, data):
    pd = pytest.importorskip("pandas")
    rows = [json.loads(l) for l in FIX.read_text().splitlines()]
    rows[4]["mid"] = float("nan")  # missing cached score -> model skipped for that row
    p = tmp_path / "routerbench_0shot.pkl"
    pd.DataFrame(rows).to_pickle(p)
    recs, models = RB.load(str(p), allow_pickle=True)
    assert models == data[1] and "mid" not in recs[4]["scores"]
    assert RB.main(["--data", str(p), "--allow-pickle", "--brief"]) == 0


def _write_pickle(tmp_path):
    pd = pytest.importorskip("pandas")
    rows = [json.loads(l) for l in FIX.read_text().splitlines()]
    p = tmp_path / "rb.pickle"
    pd.DataFrame(rows).to_pickle(p)
    return p


def test_pickle_refused_by_default(tmp_path):
    p = _write_pickle(tmp_path)
    with pytest.raises(SystemExit, match="parquet, JSONL or CSV"):
        RB.load(str(p))
    with pytest.raises(SystemExit, match="refusing to load pickle"):
        RB.main(["--data", str(p), "--brief"])


def test_env_var_cannot_enable_pickle(tmp_path, monkeypatch):
    p = _write_pickle(tmp_path)
    monkeypatch.setenv(RB.DATA_ENV, str(p))
    for k in ("ROUTERBENCH_ALLOW_PICKLE", "ALLOW_PICKLE"):
        monkeypatch.setenv(k, "1")
    with pytest.raises(SystemExit, match="refusing to load pickle"):
        RB.main(["--brief"])
    with pytest.raises(SystemExit, match="refusing to load pickle"):
        RB.load()


def test_pickle_to_parquet_requires_flag(tmp_path):
    import routerbench_pickle_to_parquet as C
    p = _write_pickle(tmp_path)
    with pytest.raises(SystemExit, match="--allow-pickle"):
        C.main([str(p)])
    assert not p.with_suffix(".parquet").exists()


def test_pickle_to_parquet_converter(tmp_path):
    pytest.importorskip("pyarrow")
    import routerbench_pickle_to_parquet as C
    p = _write_pickle(tmp_path)
    assert C.main([str(p), "--allow-pickle"]) == 0
    recs, models = RB.load(str(p.with_suffix(".parquet")))
    assert models == RB.load(str(FIX))[1] and len(recs) == len(RB.load(str(FIX))[0])


def test_cli(capsys):
    assert RB.main(["--data", str(FIX), "--policy", "single:tiny", "--brief"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["best_single"]["model"] == "big" and out["policy"]["quality"] == pytest.approx(2 / 6)
    assert "by_eval" not in out["policy"]


def test_no_routerbench_data_committed():
    d = ROOT / "tests" / "fixtures" / "routerbench"
    assert sorted(p.name for p in d.iterdir()) == ["README.md", "synthetic_wide.jsonl"]
