"""#85: lean hermes prompt profile on small nodes, and the on-disk prompt-prefix cache."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import hermes_harness as hh  # noqa: E402
import prompt_cache as pc  # noqa: E402


def test_profile_auto_follows_host_size():
    g = {"hosts": {"small": {"ram_mib": 7270}, "big": {"ram_mib": 32768}, "ph": {"kind": "phone", "ram_mib": 12000}}}
    assert hh.prompt_profile(g, {}, {"host": "small"}) == "lean"
    assert hh.prompt_profile(g, {}, {"host": "big"}) == "full"
    assert hh.prompt_profile(g, {}, {"host": "ph"}) == "lean"
    assert hh.prompt_profile(g, {"prompt_profile": "full"}, {"host": "small"}) == "full"
    assert hh.prompt_profile(g, {"prompt_profile": "lean"}, {"host": "big"}) == "lean"


def test_lean_only_narrows():
    assert hh.lean_toolsets({"platform_toolsets": {"cli": ["browser", "terminal", "file", "web"]}}) == ["terminal", "file"]
    assert hh.lean_toolsets({}) == list(hh.LEAN_TOOLSETS)
    assert "browser" not in hh.LEAN_TOOLSETS and "delegation" not in hh.LEAN_TOOLSETS


def test_render_lean_for_miryam_coder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    g = yaml.safe_load(open(os.path.join(ROOT, "graph.yaml")))
    user = tmp_path / "user.yaml"
    user.write_text(yaml.safe_dump({"platform_toolsets": {"cli": ["browser", "terminal", "file", "skills", "vision"]},
                                    "agent": {"disabled_toolsets": ["search"]}}))
    home, base, n, name = hh.render(g, "hermes", user_cfg_path=str(user))
    cfg = yaml.safe_load(open(os.path.join(home, "config.yaml")))
    assert cfg["platform_toolsets"]["cli"] == ["terminal", "file", "skills"]
    assert cfg["agent"]["disabled_toolsets"] == ["search"]   # disabling is untouched
    assert hh.prompt_profile(g, g["agents"]["hermes"], n) == "lean"


def test_prompt_cache_does_not_import_agents():
    src = open(os.path.join(ROOT, "scripts", "prompt_cache.py")).read()
    assert "hermes" not in src.split('"""', 2)[2] and "harness2" not in src.split('"""', 2)[2]


class Fake(BaseHTTPRequestHandler):
    files, calls = set(), []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        Fake.calls.append((self.path, body))
        out, code = {}, 200
        if self.path == "/apply-template":
            out = {"prompt": "<tools>T</tools>SYS VOL-123<|im_start|>user\n" + body["messages"][1]["content"] + "<|im_end|>"}
        elif self.path == "/tokenize":
            out = {"tokens": [ord(c) for c in body["content"]]}
        elif "action=restore" in self.path:
            if body["filename"] in Fake.files:
                out = {"n_restored": 5}
            else:
                code = 400
        elif "action=save" in self.path:
            Fake.files.add(body["filename"])
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_warm_then_restore():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        text = pc.stable_prefix(base, "SYS VOL-123", [{"x": 1}], volatile="VOL-123")
        assert text == "<tools>T</tools>SYS "
        toks = pc.prefix_tokens(base, text)
        assert len(toks) == len(text) - 1      # last token dropped
        assert pc.warm(base, toks, log=lambda m: None)[0] == "warmed"
        assert any(p == "/completion" and b["n_predict"] == 0 for p, b in Fake.calls)
        Fake.calls.clear()
        assert pc.warm(base, toks, log=lambda m: None)[0] == "restored"
        assert not any(p == "/completion" for p, _ in Fake.calls)
        assert pc.name_for(toks) != pc.name_for(toks + [1])
    finally:
        srv.shutdown()


def test_warm_never_raises():
    assert pc.warm("http://127.0.0.1:9", [1, 2], log=lambda m: None)[0] == "skipped"


def test_slot_save_path_in_server_args(tmp_path, monkeypatch):
    import validate_graph as vg
    monkeypatch.setenv("HOME", str(tmp_path))
    g = vg.load(os.path.join(ROOT, "graph.yaml"))
    # Default slots dir when spill_path unset; coder now has spill_path — strip it for this check.
    g["nodes"]["coder"].pop("spill_path", None)
    a = vg.server_args(g, "coder")
    assert a[a.index("--slot-save-path") + 1] == os.path.join(str(tmp_path), ".cache/familia/slots/coder")


def test_unstable_line_cuts_prefix(monkeypatch):
    p = "<tools>T</tools>A\nPython toolchain: x\nB VOL<|im_start|>user\n" + pc.SPLIT
    monkeypatch.setattr(pc, "_post", lambda *a: {"prompt": p})
    assert pc.stable_prefix("x", "s", [], "VOL", unstable=("Python toolchain:",)) == "<tools>T</tools>A\n"
    assert pc.stable_prefix("x", "s", [], "VOL") == "<tools>T</tools>A\nPython toolchain: x\nB "

def test_spill_path_in_server_args(tmp_path, monkeypatch):
    import validate_graph as vg
    monkeypatch.setenv("HOME", str(tmp_path))
    g = vg.load(os.path.join(ROOT, "graph.yaml"))
    a = vg.server_args(g, "angel-coder")
    want = os.path.join(str(tmp_path), ".cache/familia/spill/angel-coder")
    assert a[a.index("--slot-save-path") + 1] == want

