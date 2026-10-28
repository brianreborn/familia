"""Every graph.yaml model with a db id must have a registry/models/<db>.json entry."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_every_graph_model_db_is_registered():
    graph = yaml.safe_load((ROOT / "graph.yaml").read_text())
    missing = [
        f"{name}: {m['db']}"
        for name, m in (graph.get("models") or {}).items()
        if isinstance(m, dict) and m.get("db")
        and not (ROOT / "registry" / "models" / f"{m['db']}.json").is_file()
    ]
    assert not missing, "graph models without registry entry: " + ", ".join(missing)
