"""Non-English prompts through the tool router (platform routing-l10n): CJK, RTL (Arabic,
Hebrew), Cyrillic, combining marks, emoji; LANG=C/POSIX vs a UTF-8 locale. Routing decisions
and tool args must be identical and byte-for-byte intact (after JSON decode)."""
import copy, json, os, subprocess, sys, textwrap, threading, unicodedata, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import escalation as E  # noqa: E402
import escalation_proxy as EP  # noqa: E402

PROMPTS = {
    "cjk": "请帮我修复这个函数：读取「設定.yaml」并列出所有ノード",
    "arabic": "من فضلك أصلح الدالة واقرأ الملف \u202bإعدادات.yaml\u202c",
    "hebrew": "בבקשה תקן את הפונקציה וקרא את הקובץ הגדרות.yaml",
    "cyrillic": "Пожалуйста, исправь функцию и прочитай файл настройки.yaml",
    "combining_nfd": unicodedata.normalize("NFD", "Ça va? Réessaie l'élément «café» ñandú"),
    "emoji": "fix it 🦙🔧 — ZWJ family 👨‍👩‍👧 and flag 🇯🇵, skin 👍🏽",
    "mixed_bidi": "abc אבג 123 عربي ДЕФ 中文 e\u0301",
}
TOOL_ARGS = {k: json.dumps({"path": f"/data/{v[:12]}.txt", "pattern": v}, ensure_ascii=False) for k, v in PROMPTS.items()}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("FAMILIA_API_KEY", "test-instance-key")
    for k, f in (("STATE", ""), ("PENDING", "p.json"), ("ACCEPT", "a.json")):
        monkeypatch.setattr(EP, k, str(tmp_path / f))


def mock(name, seen, replies=None):
    it = iter(replies or [])
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"])); seen.append((name, json.loads(raw)))
            txt = next(it, "same answer")
            out = json.dumps({"choices": [{"message": {"role": "assistant", "content": txt}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
    s = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]


def graph(pl, ph, mode, phrases=None):
    esc = {"mode": mode}
    if phrases: esc["triggers"] = {"phrases": phrases}
    return {"hosts": {"h": {}}, "aliases": {},
            "nodes": {"light": {"host": "h", "port": pl, "model": "smollm2", "escalates_to": ["heavy"], "escalation": esc},
                      "heavy": {"host": "h", "port": ph, "model": "qwen35-2b"}}}


def post(port, body, headers=None):
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})}))
    return json.load(r)["choices"][0]["message"]["content"]


TOOLS = [{"type": "function", "function": {"name": "grep_search", "description": "搜索 / بحث / поиск 🔎",
          "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}}}]


@pytest.mark.parametrize("lang", sorted(PROMPTS))
def test_prompt_and_tool_args_reach_upstream_intact(lang):
    seen = []; g = graph(mock("light", seen, [f"r{i}" for i in range(9)]), mock("heavy", seen), "suggest")
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": PROMPTS[lang]},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
             "function": {"name": "grep_search", "arguments": TOOL_ARGS[lang]}}]},
            {"role": "tool", "tool_call_id": "c1", "content": PROMPTS[lang]}]
    body = {"model": "x", "messages": msgs, "tools": TOOLS, "tool_choice": "auto"}
    try:
        out = post(p, body)
    finally:
        srv.shutdown()
    assert out == "r0"                                         # no escalation note: routing unchanged
    name, got = seen[-1]
    assert name == "light"
    assert got["messages"] == msgs and got["tools"] == TOOLS   # exact code points, NFD kept as NFD
    assert got["messages"][2]["tool_calls"][0]["function"]["arguments"] == TOOL_ARGS[lang]


@pytest.mark.parametrize("lang", sorted(PROMPTS))
def test_handoff_to_heavy_keeps_non_english_problem_and_tools(lang, monkeypatch):
    seen = []; g = graph(mock("light", seen), mock("heavy", seen), "auto")
    esc = EP.Escalator(g, "light", [], "h", consent={}); srv = EP.serve(esc); p = srv.server_address[1]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": PROMPTS[lang]}]
    try:
        for _ in range(3): post(p, {"model": "x", "messages": msgs})
        post(p, {"model": "x", "messages": msgs, "tools": TOOLS})
    finally:
        srv.shutdown()
    name, got = seen[-1]
    assert name == "heavy" and got["tools"] == TOOLS
    assert json.loads(got["messages"][-1]["content"])["open_problem"] == PROMPTS[lang]


LOCAL_PHRASES = [
    ("Используй большую модель", "Пожалуйста, используй большую модель для этого"),
    ("استخدم النموذج الكبير", "من فضلك استخدم النموذج الكبير الآن"),
    ("השתמש במודל הגדול", "בבקשה השתמש במודל הגדול"),
    ("réessaie", unicodedata.normalize("NFD", "Bon, réessaie encore")),           # NFC phrase, NFD text
    (unicodedata.normalize("NFD", "réessaie"), unicodedata.normalize("NFC", "Bon, réessaie encore")),
    ("升级", "请升级到大模型"),                                                         # CJK: no spaces between words
    ("大きいモデル", "大きいモデルを使ってください"),
]


@pytest.mark.parametrize("phrase,msg", LOCAL_PHRASES, ids=[f"p{i}" for i in range(len(LOCAL_PHRASES))])
def test_localized_escalation_phrases_fire(phrase, msg):
    trig = dict(E.DEFAULT_TRIGGERS, phrases=[phrase])
    assert E.stuck_reasons({"user_messages": [msg]}, trig), (phrase, msg)


@pytest.mark.parametrize("msg", ["不要升级", "не используй большую модель"])
def test_non_english_text_does_not_fire_english_default_phrases(msg):
    assert E.stuck_reasons({"user_messages": [msg]}, E.DEFAULT_TRIGGERS) == []


def test_non_ascii_session_ids_do_not_share_pending_state():
    """Distinct non-ASCII X-Familia-Session ids must not collapse onto one pending file."""
    ids = ["用户", "客户", "пользователь", "משתמש", "🦙", "🐪"]
    paths = {EP._pending_path(s) for s in ids}
    assert len(paths) == len(ids), sorted(paths)
    for pth in paths:
        assert os.path.basename(pth).isascii()


DRIVER = textwrap.dedent('''\
    import json, os, sys, threading, urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    sys.path.insert(0, sys.argv[1]); import escalation_proxy as EP
    EP.STATE = os.environ["TMPDIR"]
    EP.PENDING, EP.ACCEPT = os.path.join(EP.STATE, "p.json"), os.path.join(EP.STATE, "a.json")
    seen = []
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            out = json.dumps({"choices": [{"message": {"role": "assistant", "content": seen[-1]["messages"][-1]["content"]}}]}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(out)
    up = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=up.serve_forever, daemon=True).start()
    g = {"hosts": {"h": {}}, "aliases": {}, "nodes": {"light": {"host": "h", "port": up.server_address[1], "model": "m",
         "escalates_to": ["heavy"], "escalation": {"mode": "suggest", "triggers": {"phrases": [os.environ["PHRASE"]]}}},
         "heavy": {"host": "h", "port": up.server_address[1], "model": "m2"}}}
    srv = EP.serve(EP.Escalator(g, "light", [], "h", consent={}))
    msgs = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    res = []
    for m in msgs:
        r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions",
            data=json.dumps({"model": "x", "messages": [{"role": "user", "content": m}]}).encode(),
            headers={"Content-Type": "application/json"}))
        res.append(json.load(r)["choices"][0]["message"]["content"])
    srv.shutdown(); up.shutdown()
    sys.stdout.buffer.write(json.dumps({"replies": res, "upstream": [s["messages"] for s in seen]}).encode())
    ''')


def _run_locale(tmp_path, loc):
    d = tmp_path / loc.replace(".", "_"); d.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("LC_") and k not in ("LANG", "PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(LANG=loc, LC_ALL=loc, TMPDIR=str(d), FAMILIA_API_KEY="k")
    if loc in ("C", "POSIX"): env.update(PYTHONCOERCECLOCALE="0", PYTHONUTF8="0")
    msgs = list(PROMPTS.values()) + ["please upgrade 请"]
    drv = tmp_path / "driver.py"; drv.write_bytes(DRIVER.encode("ascii"))
    env["PHRASE"] = "upgrade"   # env must be ASCII-safe under LANG=C; CJK phrase routing is covered above
    r = subprocess.run([sys.executable, str(drv), os.path.join(ROOT, "scripts")], env=env,
                       input=json.dumps(msgs).encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout)


def test_lang_c_and_posix_route_identically_to_utf8(tmp_path):
    utf8 = _run_locale(tmp_path, "C.UTF-8")
    for loc in ("C", "POSIX"):
        assert _run_locale(tmp_path, loc) == utf8
    assert utf8["upstream"][0][0]["content"] == list(PROMPTS.values())[0]
