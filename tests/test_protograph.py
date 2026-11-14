"""scripts/protograph.py + skills/protograph (#399): recipe -> valid graph, dry run, confirm before write."""
import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import protograph  # noqa: E402
import validate_graph as vg  # noqa: E402

PG = ROOT / "scripts" / "protograph.py"
EX = ROOT / "skills" / "protograph" / "examples"
SINGLE = EX / "single-chat.recipe.yaml"


def run(*args, **env):
    e = dict(os.environ, FAMILIA_NO_TTY="1")
    e.pop("FAMILIA_GRAPH", None)
    e.update(env)
    return subprocess.run([sys.executable, str(PG), *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, env=e, stdin=subprocess.DEVNULL, timeout=120)


def recipe():
    return yaml.safe_load(SINGLE.read_text())


def test_skill_doc_is_agent_agnostic_and_has_frontmatter():
    text = (ROOT / "skills" / "protograph" / "SKILL.md").read_text(encoding="ascii")
    assert text.startswith("---\nname: protograph\n")
    assert "Dry run first" in text and "scripts/protograph.py" in text


@pytest.mark.parametrize("path", sorted(EX.glob("*.recipe.yaml")), ids=lambda p: p.name)
def test_sample_recipes_emit_valid_graphs(path):
    g, _ = protograph.build(yaml.safe_load(path.read_text()), str(EX))
    errs, _ = vg.validate(copy.deepcopy(g), check_files=False)
    assert errs == []


def test_single_matches_example_single_node_shape():
    g, _ = protograph.build(recipe())
    ex = yaml.safe_load((ROOT / "examples" / "graphs" / "single-node.yaml").read_text())
    assert set(g) == set(ex)
    assert g["nodes"]["chat"]["model"] == "mchat" and g["aliases"]["chat"]["node"] == "chat"


def test_defaults_are_written_explicitly_and_listed():
    g, plan = protograph.build(recipe())
    n = g["nodes"]["chat"]
    for k in ("parallel", "kv_type", "flash_attn", "bind", "cache_ram_mib", "status"):
        assert k in n
    assert any("kv_type" in l and "recipe default" in l for l in plan)


@pytest.mark.parametrize("mutate,msg", [
    (lambda r: r.pop("protograph"), "protograph: 1"),
    (lambda r: r["host"].pop("ram_mib"), "host: missing ram_mib"),
    (lambda r: r.update(nodes=[]), "at least one node"),
    (lambda r: r["nodes"].append(dict(r["nodes"][0])), "duplicate node"),
    (lambda r: r["nodes"][0].update(model="nope"), "not in models"),
    (lambda r: r["nodes"][0].update(bind="0.0.0.0"), "not loopback"),
    (lambda r: r.update(bogus=1), "unknown recipe key"),
    (lambda r: r["models"]["mchat"].pop("sha256"), "missing sha256"),
])
def test_incomplete_or_unsafe_recipes_rejected(mutate, msg):
    r = recipe()
    mutate(r)
    with pytest.raises(protograph.RecipeError, match=msg):
        protograph.build(r)


def test_over_budget_is_an_error(tmp_path):
    big = tmp_path / "big.gguf"
    with open(big, "wb") as f:
        f.truncate(64 * 1048576)
    r = recipe()
    r["host"].update(ram_mib=2100, reserve_ram_mib=2048)
    r["models"]["mchat"]["gguf"] = str(big)
    g, _ = protograph.build(r)
    errs, ram, _ = protograph.check(g)
    assert any("OVER BUDGET" in e for e in errs)


def test_from_graph_never_copies_addr_user():
    g, plan = protograph.build(yaml.safe_load((EX / "from-host.recipe.yaml").read_text()), str(EX))
    h = g["hosts"]["box"]
    assert h["addr"] == "REPLACE_ME" and h["user"] == "REPLACE_ME"
    assert any("copied from the reference graph" in l for l in plan)


def test_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "g.yaml"
    r = run(SINGLE, "--out", out)
    assert r.returncode == 0, r.stderr
    assert "dry run: nothing written" in r.stdout and not out.exists()
    r.stdout.encode("ascii")


def test_write_new_file_then_refuse_overwrite_without_yes(tmp_path):
    out = tmp_path / "g.yaml"
    assert run(SINGLE, "--out", out, "--write").returncode == 0
    first = out.read_text()
    assert yaml.safe_load(first)["version"] == 2
    out.write_text("# hand edits\n")
    r = run(SINGLE, "--out", out, "--write")
    assert r.returncode == 1 and "--yes" in r.stderr
    assert out.read_text() == "# hand edits\n"
    r = run(SINGLE, "--out", out, "--write", "--yes")
    assert r.returncode == 0 and out.read_text() == first
    baks = list(tmp_path.glob("g.yaml.bak-*"))
    assert len(baks) == 1 and baks[0].read_text() == "# hand edits\n"


def test_invalid_graph_not_written(tmp_path):
    bad = tmp_path / "bad.recipe.yaml"
    r = recipe()
    r["nodes"][0]["ctx"] = 4096       # differs from the model card without override_reasons
    bad.write_text(yaml.safe_dump(r))
    out = tmp_path / "g.yaml"
    res = run(bad, "--out", out, "--write")
    assert res.returncode == 1 and not out.exists()
    assert run(bad, "--check").returncode == 1


def test_check_ok():
    r = run(SINGLE, "--check")
    assert r.returncode == 0 and "protograph: OK" in r.stdout


def test_runtime_bin_and_url_not_accepted_from_recipe():
    r = recipe()
    r["runtime"] = {
        "name": "custom-rt",
        "build": "b1000",
        "commit": "abc1234",
        "supported_archs": ["llama"],
        "backends": ["cpu"],
        "bin": "/tmp/malicious/llama-server",
        "url": "http://evil.com/llama-server",
    }
    g, _ = protograph.build(r)
    rt = g["runtimes"]["custom-rt"]
    assert "bin" not in rt
    assert "url" not in rt


def test_tr4_fail_closed_role_override_refused():
    r = recipe()
    r["models"]["mchat"]["role"] = "guardian"
    r["nodes"][0]["role"] = "coder"
    with pytest.raises(protograph.RecipeError, match="fail-closed models cannot be overridden"):
        protograph.build(r)


def test_gateway_port_conflict_with_node_refused():
    r = recipe()
    r["gateway"] = {"port": r["nodes"][0]["port"]}
    with pytest.raises(protograph.RecipeError, match="gateway port .* conflicts with node port"):
        protograph.build(r)
