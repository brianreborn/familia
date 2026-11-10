"""Routing path robustness (platform routing-paths): graph/tool paths with spaces, non-ASCII
(NFC/NFD), backslashes and Windows reserved names. Windows cases are simulated with ntpath so
they run on any OS. Correctness tests only."""
import copy, json, ntpath, os, shlex, subprocess, sys, unicodedata
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import config_paths  # noqa: E402
import validate_graph  # noqa: E402
from graph_types import validate_types  # noqa: E402

BASE = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
def g(): return copy.deepcopy(BASE)

CAFE_NFC = unicodedata.normalize("NFC", "café")
CAFE_NFD = unicodedata.normalize("NFD", "café")
NAMES = ["with space", "日本語 ディレクトリ", "Кириллица", CAFE_NFC, CAFE_NFD, "back\\slash", "emoji 🦙"]


@pytest.mark.parametrize("d", NAMES)
def test_graph_path_preserves_exact_codepoints(tmp_path, d):
    p = tmp_path / d / "graph.yaml"
    for got in (config_paths.graph_path(str(p)),
                config_paths.graph_path(environ={"FAMILIA_GRAPH": str(p)})):
        assert got == str(p)          # no NFC/NFD folding, no splitting, already absolute
        assert os.path.isabs(got)


def _validate_copy(tmp_path, d):
    dst = tmp_path / d; dst.mkdir()
    (dst / "graph.yaml").write_bytes(open(os.path.join(ROOT, "graph.yaml"), "rb").read())
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "validate_graph.py"),
                        "--graph", str(dst / "graph.yaml"), "--no-files"],
                       capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    errs = sorted(l.replace(str(dst), "<DIR>") for l in r.stderr.splitlines() if "ERROR" in l)
    return r.returncode, errs


@pytest.mark.parametrize("d", NAMES)
def test_validate_graph_same_verdict_from_unusual_dir(tmp_path, d):
    """A graph copied to an odd directory validates exactly like the same graph in a plain one."""
    assert _validate_copy(tmp_path, d) == _validate_copy(tmp_path, "plain")


@pytest.mark.parametrize("gguf", ["/models/my model.gguf", "/models/日本語 モデル.gguf", "/models/tab\there.gguf",
                                  "/models/plain-ünï.gguf", "/models/back\\slash.gguf", "/models/it's.gguf",
                                  "/models/" + CAFE_NFD + " x.gguf"])
def test_server_args_keep_unusual_model_path_and_quote_round_trips(gguf):
    x = g(); node = "coder"; x["models"][x["nodes"][node]["model"]]["gguf"] = gguf
    argv = validate_graph.server_args(x, node)
    assert argv[argv.index("-m") + 1] == gguf
    assert shlex.split(shlex.join(argv)) == argv           # what --args prints and serve.sh evals


@pytest.mark.parametrize("bad", ["/models/new\nline.gguf", "/models/nul\0.gguf"])
def test_newline_or_nul_in_launch_arg_still_refused(bad):
    x = g(); node = "coder"; x["models"][x["nodes"][node]["model"]]["gguf"] = bad
    with pytest.raises(SystemExit, match="newline or NUL"):
        validate_graph.server_args(x, node)


@pytest.mark.parametrize("spill", ["spill dir", "spill\ttab", "spill\u3000wide", "spill-ñ"])
def test_slot_save_path_with_spaces_round_trips(tmp_path, spill):
    spill = str(tmp_path / spill)
    x = g(); node = "coder"; x["nodes"][node]["spill_path"] = spill
    argv = validate_graph.server_args(x, node)
    assert argv[argv.index("--slot-save-path") + 1] == spill
    assert shlex.split(shlex.join(argv)) == argv


def test_validate_graph_cli_args_are_shell_quoted(tmp_path):
    """`validate_graph.py --args` output (serve.sh input) splits back to the exact -m path."""
    gguf = "/models/my dir/日本語\tq.gguf"
    gp = os.path.join(ROOT, "graph.yaml")
    r = subprocess.run([sys.executable, "-c", (
        "import sys, yaml; sys.path.insert(0, sys.argv[1]); import validate_graph as vg\n"
        "g = vg.load(sys.argv[2]); m = g['models'][g['nodes']['coder']['model']]; m['gguf'] = sys.argv[3]\n"
        "vg.load = lambda p: g\n"
        "vg.validate = lambda *a, **k: ([], {})   # main's graph has known unrelated errors; test the printer\n"
        "sys.exit(vg.main(['--graph', sys.argv[2], '--no-files', '--args', 'coder']))"),
        os.path.join(ROOT, "scripts"), gp, gguf], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    argv = shlex.split(r.stdout.strip())
    assert argv[argv.index("-m") + 1] == gguf


STUB_RUNTIME = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = a[a.index("--log-file") + 1]
if a[a.index("-ngl") + 1] != "0" and os.environ.get("STUB_VULKAN_FAIL"):
    open(log, "w").write("ggml_vulkan: error: no device\\n"); sys.exit(1)
json.dump(a, open(os.environ["STUB_OUT"], "w"))
"""


@pytest.fixture
def serve_tree(tmp_path):
    """Real serve.sh + lib/msg.mk; stub validate_graph prints shlex.join(argv); stub runtime dumps argv."""
    import shutil
    t = tmp_path / "repo"; (t / "scripts").mkdir(parents=True); (t / "lib").mkdir()
    shutil.copy(os.path.join(ROOT, "scripts", "serve.sh"), t / "scripts" / "serve.sh")
    shutil.copy(os.path.join(ROOT, "lib", "msg.mk"), t / "lib" / "msg.mk")
    (t / "scripts" / "licenses.py").write_text("raise SystemExit(0)\n")
    rt = tmp_path / "rt dir ü" / "llama-server"; rt.parent.mkdir(); rt.write_text(STUB_RUNTIME); rt.chmod(0o755)
    out = tmp_path / "argv.json"
    env = dict(os.environ, FAMILIA_MEMCAP="0", FAMILIA_GUARD="0", FAMILIA_LOG_DIR=str(tmp_path / "logs"),
               STUB_OUT=str(out))
    env.pop("FAMILIA_HOST", None)

    def run(model_name, extra=(), ngl="0", vulkan_fail=False, cwd=None):
        model = tmp_path / "models" / model_name; model.parent.mkdir(exist_ok=True); model.write_bytes(b"GGUF")
        argv = [str(rt), "-m", str(model), "-ngl", ngl, "--alias", "a b"]
        (t / "scripts" / "validate_graph.py").write_text(
            "import shlex\nprint(shlex.join(%r))\n" % (argv,))
        e = dict(env, **({"STUB_VULKAN_FAIL": "1"} if vulkan_fail else {}))
        r = subprocess.run(["sh", str(t / "scripts" / "serve.sh"), "coder", *extra], env=e,
                           cwd=str(cwd or tmp_path), capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        got = json.load(open(out))
        return argv, got
    return run


@pytest.mark.parametrize("name", ["my model.gguf", "tab\there.gguf", "日本語 モデル.gguf", CAFE_NFD + ".gguf",
                                  "it's \"q\".gguf", "back\\slash $HOME.gguf"])
def test_serve_sh_passes_unusual_paths_exactly(serve_tree, name):
    argv, got = serve_tree(name, extra=["--threads", "2", "--extra arg"])
    i = got.index("--log-file")
    assert got[:i] == argv[1:]                               # server args byte-exact, in order
    assert got[i + 2:] == ["--threads", "2", "--extra arg"]  # caller extras kept as given


def test_serve_sh_vulkan_cpu_retry_keeps_paths(serve_tree):
    argv, got = serve_tree("my model ü.gguf", ngl="7", vulkan_fail=True)
    assert got[got.index("-m") + 1] == argv[argv.index("-m") + 1]
    assert got[got.index("-ngl") + 1] == "0"
    assert got[got.index("--log-file") + 1].endswith(".log.cpu")
    assert got[got.index("--alias") + 1] == "a b"


def _win_reserved(name):
    isr = getattr(ntpath, "isreserved", None)
    if isr: return isr(name)
    stem = name.rstrip(" .").split(".")[0].upper()
    return name != name.rstrip(" .") or stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                                    *(f"LPT{i}" for i in range(1, 10))}


@pytest.mark.parametrize("name", ["CON", "nul", "Prn", "aux", "com1", "LPT9", "con.d", "coder.", "coder "])
def test_windows_reserved_node_names_rejected(name):
    """Node names become file names (slots/<node>, serve-<node>.log, start.bat units);
    a reserved device name or a trailing dot/space cannot be a Windows file."""
    assert _win_reserved(name)        # the simulation itself agrees this is unsafe on Windows
    x = g(); n = copy.deepcopy(x["nodes"]["coder"]); n["status"] = "planned"; n["port"] = 1 + max(
        v["port"] for v in x["nodes"].values())
    x["nodes"][name] = n
    e = validate_types(x)
    assert any(f"nodes.{name}" in m and "Windows" in m for m in e), e


@pytest.mark.parametrize("name", ["coder-2", "console", "nullable", "con-x", "comx"])
def test_ordinary_node_names_not_flagged(name):
    assert not _win_reserved(name)
    x = g(); n = copy.deepcopy(x["nodes"]["coder"]); n["status"] = "planned"; n["port"] = 1 + max(
        v["port"] for v in x["nodes"].values())
    x["nodes"][name] = n
    assert not any("Windows" in m for m in validate_types(x))


@pytest.mark.parametrize("p,parts", [
    (r"E:\temp\familia\models\my model.gguf", ("E:", "my model.gguf")),
    ("C:\\Users\\Jos\u00e9 P\u00e9rez\\familia\\graph.yaml", ("C:", "graph.yaml")),
    (r"\\server\share\familia\graph.yaml", (r"\\server\share", "graph.yaml")),
])
def test_windows_style_paths_split_cleanly(p, parts):
    """%USERPROFILE% with spaces / non-ASCII and UNC paths keep drive and file name intact."""
    drive, rest = ntpath.splitdrive(p)
    assert drive == parts[0] and ntpath.basename(rest) == parts[1]


@pytest.mark.parametrize("name", ["star*.gguf", "q?.gguf", "[ab].gguf", "*", "glob [*?] mix.gguf"])
def test_serve_sh_does_not_glob_expand_paths(serve_tree, tmp_path, name):
    """Unquoted $args used to pathname-expand * ? [..] against the cwd; "$@" must not."""
    cwd = tmp_path / "models"; cwd.mkdir(exist_ok=True)
    for decoy in ("starX.gguf", "qZ.gguf", "a.gguf", "b.gguf", "zzz"):
        (cwd / decoy).write_bytes(b"")
    argv, got = serve_tree(name, extra=["*", "--x=[ab]"], cwd=cwd)
    i = got.index("--log-file")
    assert got[:i] == argv[1:]
    assert got[i + 2:] == ["*", "--x=[ab]"]
