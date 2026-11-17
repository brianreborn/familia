"""scripts/model_pick.py (#398): headless catalog picker, host default, export dry-run."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICK = os.path.join(ROOT, "scripts", "model_pick.py")


def run(*args, **env):
    e = dict(os.environ, FAMILIA_NO_TTY="1", FAMILIA_HOST="not-a-graph-host", NO_COLOR="")
    e.pop("FAMILIA_GRAPH", None)
    e.update(env)
    return subprocess.run([sys.executable, PICK, *args], cwd=ROOT, capture_output=True, text=True,
                          env=e, stdin=subprocess.DEVNULL, timeout=120)


def listing(*args, **env):
    r = run("list", "--json", *args, **env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_help_has_usage():
    r = run("--help")
    assert r.returncode == 0 and "usage" in r.stdout.lower()


def test_role_models_rank_first_and_fit_budget():
    cat = listing("--host", "miryam", "--role", "coder")
    assert cat["budget_mib"] == 7270 - 3072
    top = cat["models"][0]
    assert top["role"] == "coder" and top["fits"] is True
    assert all(m["present"] is None for m in cat["models"])  # remote host: presence unknown


def test_too_big_models_flagged_and_sorted_last():
    cat = listing("--host", "miryam")
    big = [m for m in cat["models"] if m["fits"] is False]
    assert big, "expected at least one model over miryam's budget"
    idx = [i for i, m in enumerate(cat["models"]) if m["fits"] is False]
    assert min(idx) > max(i for i, m in enumerate(cat["models"]) if m["fits"] is True)


def test_search_filters_all_words():
    cat = listing("--host", "miryam", "--query", "qwen 2b")
    assert cat["models"] and all("qwen" in m["key"].lower() and "2b" in m["key"].lower() for m in cat["models"])


def test_enter_means_host_default():
    d = run("default", "--host", "miryam", "--role", "coder")
    assert d.returncode == 0 and d.stdout.strip() == "qwen35-2b-q4km"  # the model miryam's coder node runs
    p = run("pick", "--host", "miryam", "--role", "coder", "--choice", "")
    assert p.stdout.strip() == d.stdout.strip()


def test_pick_by_number_and_key_and_miss():
    assert run("pick", "--host", "miryam", "--role", "coder", "--choice", "2").returncode == 0
    r = run("pick", "--host", "miryam", "--choice", "qwen35-08b-q4km")
    assert r.returncode == 0 and r.stdout.strip() == "qwen35-08b-q4km"
    assert run("pick", "--host", "miryam", "--choice", "no-such-model-zzz").returncode == 1


def test_unknown_host_fails_soft():
    r = run("list", "--host", "nope")
    assert r.returncode != 0 and "no host" in r.stderr


def test_export_dry_run_writes_nothing(tmp_path):
    r = run("export", "--host", "box", "--role", "coder", "--model", "qwen35-08b-q4km",
            FAMILIA_GENERATED_DIR=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "dry run" in r.stdout and "qwen35-08b-q4km" in r.stdout
    assert list(tmp_path.iterdir()) == []


def test_export_write_goes_to_generated_only(tmp_path):
    before = open(os.path.join(ROOT, "graph.yaml"), encoding="utf-8").read()
    r = run("export", "--host", "box", "--role", "coder", "--model", "qwen35-08b-q4km", "--write",
            FAMILIA_GENERATED_DIR=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    out = tmp_path / "graph-pick-box.yaml"
    text = out.read_text(encoding="ascii")
    assert "model: qwen35-08b-q4km" in text
    assert open(os.path.join(ROOT, "graph.yaml"), encoding="utf-8").read() == before


def test_export_rejects_bad_pick(tmp_path):
    r = run("export", "--host", "box", "--role", "coder", "--model", "lfm3-17b-uncensored-q4km", "--write",
            FAMILIA_GENERATED_DIR=str(tmp_path))
    assert r.returncode == 1 and "ERRORS for this pick" in r.stdout
    assert not (tmp_path / "graph-pick-box.yaml").exists()


def test_export_unregistered_model_says_add_first():
    r = run("export", "--host", "box", "--model", "loose-file.gguf")
    assert r.returncode != 0 and "Add a model" in r.stderr


def test_local_gguf_scan_only_on_this_host(tmp_path):
    (tmp_path / "Tiny-Q4_0.gguf").write_bytes(b"GGUF" + b"\0" * 64)
    (tmp_path / "mmproj-x.gguf").write_bytes(b"GGUF")
    env = dict(FAMILIA_MODEL_DIRS=str(tmp_path), FAMILIA_MODEL_DIRS_ONLY="1")
    keys = [m["key"] for m in listing("--host", "miryam", FAMILIA_HOST="miryam", **env)["models"]]
    assert "Tiny-Q4_0.gguf" in keys and "mmproj-x.gguf" not in keys
    keys = [m["key"] for m in listing("--host", "miryam", **env)["models"]]
    assert "Tiny-Q4_0.gguf" not in keys


def test_output_is_ascii_and_uncolored_off_tty():
    r = run("list", "--host", "box", "--role", "chat")
    assert r.returncode == 0
    r.stdout.encode("ascii")
    assert "\033[" not in r.stdout


def test_arch_the_host_cannot_run_is_not_default():
    cat = listing("--host", "box", "--role", "chat")
    lfm3 = [m for m in cat["models"] if m["arch"] == "lfm3"]
    assert lfm3 and all(m["arch_ok"] is False for m in lfm3)
    d = run("default", "--host", "box", "--role", "chat").stdout.strip()
    assert d not in {m["key"] for m in lfm3}
