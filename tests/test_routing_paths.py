"""Routing path robustness (platform routing-paths): graph/tool paths with spaces, non-ASCII
(NFC/NFD), backslashes and Windows reserved names. Windows cases are simulated with ntpath so
they run on any OS. Correctness tests only."""
import copy, ntpath, os, subprocess, sys, unicodedata
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


def _serve_split(argv_line):
    """serve.sh expands `$args` unquoted: sh splits on IFS (space, tab, newline)."""
    import re
    return [w for w in re.split(r"[ \t\n]+", argv_line) if w]


@pytest.mark.parametrize("gguf", ["/models/my model.gguf", "/models/日本語 モデル.gguf",
                                  "/models/tab\there.gguf", "/models/plain-ünï.gguf", "/models/back\\slash.gguf"])
def test_server_args_survive_serve_sh_word_split_or_fail_closed(gguf):
    """A model path that sh would split must never reach llama-server as a wrong argv."""
    x = g(); node = "coder"; x["models"][x["nodes"][node]["model"]]["gguf"] = gguf
    try:
        argv = validate_graph.server_args(x, node)
    except SystemExit as e:
        assert "whitespace" in str(e)          # fail closed with a clear message
        assert any(c.isspace() for c in gguf)
        return
    assert _serve_split(" ".join(argv)) == argv, "serve.sh would launch llama-server with a split -m path"
    assert argv[argv.index("-m") + 1] == gguf


@pytest.mark.parametrize("spill", ["spill dir", "spill\u3000wide", "spill-ñ"])
def test_slot_save_path_with_whitespace_fails_closed(tmp_path, spill):
    spill = str(tmp_path / spill)
    x = g(); node = "coder"; x["nodes"][node]["spill_path"] = spill
    try:
        argv = validate_graph.server_args(x, node)
    except SystemExit as e:
        assert "whitespace" in str(e); return
    assert _serve_split(" ".join(argv)) == argv


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
