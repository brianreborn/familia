"""familia pages of the settings panel (scripts/panel_familia.py) and its accessibility check.

They run against the code-bootstraps-llama.cpp panel when that checkout is present
(sh scripts/configure.sh fetches it) and are skipped otherwise.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
CB = next((p for p in (os.path.join(ROOT, "code-bootstraps-llama.cpp"), os.path.join(ROOT, "..", "code-bootstraps-llama.cpp"))
           if os.path.isfile(os.path.join(p, "scripts", "panel.py"))), None)
pytestmark = pytest.mark.skipif(CB is None, reason="code-bootstraps-llama.cpp checkout not present")
EXTRA = os.path.join(ROOT, "scripts", "panel_familia.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    g = tmp_path / "graph.yaml"
    shutil.copy(os.path.join(ROOT, "graph.yaml"), g)
    acc = tmp_path / "accept.json"
    monkeypatch.setenv("FAMILIA_GRAPH", str(g))
    monkeypatch.setenv("FAMILIA_LICENSE_ACCEPT_FILE", str(acc))
    sys.path.insert(0, os.path.join(CB, "scripts"))
    spec = importlib.util.spec_from_file_location("cb_panel", os.path.join(CB, "scripts", "panel.py"))
    panel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(panel)
    monkeypatch.setattr(panel, "UNDO_DIR", str(tmp_path / "undo"))
    monkeypatch.setattr(panel, "ENV_PATH", str(tmp_path / "panel.env"))
    import licenses
    monkeypatch.setattr(licenses, "ACCEPT_FILE", str(acc))
    extra = panel.load_extra(EXTRA)
    app = panel.App(extra)
    return panel, app, extra, g, acc


def post(panel, app, path, **fields):
    form = {k: [v] if isinstance(v, str) else v for k, v in fields.items()}
    form["token"] = [panel.TOKEN]
    return app.route("POST", path, form_=form)


def test_every_page_passes_the_accessibility_check(env):
    panel, app, *_ = env
    from lib import a11y_check
    pages = panel.all_pages_html(app)
    assert len(pages) >= 15
    bad = [(w, p) for w, h in pages for p in a11y_check.problems(h)]
    assert bad == []


def test_familia_pages_listed_first(env):
    _, app, *_ = env
    s, h = app.route("GET", "/")
    assert s == 200
    for pid in ("skills", "licenses", "hermes", "harness2", "models", "launch-basics"):
        assert '/p/%s"' % pid in h
    assert h.index("/p/skills") < h.index("/p/launch-basics")


def test_skills_preview_writes_nothing_then_save_and_undo(env):
    panel, app, _, g, acc = env
    before = g.read_text()
    s, h = post(panel, app, "/p/skills/preview", agent="hermes", **{"skill.etioz": "1"})
    assert s == 200 and "Switch on etioz for hermes" in h and "Licenses you accept" in h
    assert g.read_text() == before and not acc.exists()
    # Save without ticking the license box is refused, nothing written.
    s, h = post(panel, app, "/p/skills/save", agent="hermes", do="save", **{"skill.etioz": "1"})
    assert s == 400 and "Tick the box" in h and g.read_text() == before
    s, h = post(panel, app, "/p/skills/save", agent="hermes", do="save", accept_licenses="1", accept_unknown="1",
                **{"skill.etioz": "1"})
    assert s == 200, h
    after = g.read_text()
    assert "skills: [etioz]" in after
    # graph.yaml comments are kept: only one line was added.
    assert [l for l in before.splitlines() if "#" in l] == [l for l in after.splitlines() if "#" in l]
    assert len(after.splitlines()) == len(before.splitlines()) + 1
    import licenses
    items, digest = licenses.selection(str(g))
    assert licenses.accepted(digest, items) and json.loads(acc.read_text())["how"] == "panel"
    # The terminal tool agrees with what the panel recorded.
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "licenses.py"), "check", "--quiet"],
                       env=dict(os.environ), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    s, h = post(panel, app, "/undo")
    assert s == 200 and "Undone" in h
    assert g.read_text() == before and not acc.exists()


def test_undo_refuses_when_file_changed_since(env):
    panel, app, _, g, _ = env
    post(panel, app, "/p/skills/save", agent="hermes", do="save", accept_licenses="1", accept_unknown="1",
         **{"skill.etioz": "1"})
    g.write_text(g.read_text() + "\n# edited by hand\n")
    s, h = post(panel, app, "/undo")
    assert s == 409 and "changed by something else" in h and "edited by hand" in g.read_text()


@pytest.mark.parametrize("agent,sid,why", [
    ("hermes", "goclaw-skills", "license-blocked"),
    ("hermes", "artemis-android-skill", "vendored"),
    ("android-fleet", "green-probe", "pentest roles never get"),
])
def test_skills_refused_with_reason(env, agent, sid, why):
    panel, app, _, g, _ = env
    before = g.read_text()
    s, h = app.route("GET", "/p/skills", {"agent": [agent]})
    assert why in h and 'name="skill.%s"' % sid not in h  # shown as a reason, not a control
    s, h = post(panel, app, "/p/skills/preview", agent=agent, **{"skill." + sid: "1"})
    assert s == 400 and why in h and "Nothing was saved" in h
    assert g.read_text() == before


def test_pentest_can_get_instruction_only_skill(env):
    panel, app, _, g, _ = env
    s, h = post(panel, app, "/p/skills/preview", agent="android-fleet", **{"skill.etioz": "1"})
    assert s == 200 and "Switch on etioz for android-fleet" in h


def test_licenses_page_attention_first_and_accept(env):
    panel, app, extra, g, acc = env
    s, h = app.route("GET", "/p/licenses")
    assert s == 200 and "Not accepted yet" in h
    assert h.index("Custom: not a standard") < h.index("Standard open source (MIT")
    import licenses
    items, digest = licenses.selection(str(g))
    s, h = post(panel, app, "/p/licenses/preview", digest=digest)
    assert s == 200 and "I have read the licenses" in h and not acc.exists()
    s, h = post(panel, app, "/p/licenses/save", digest="0" * 64, do="save", accept_licenses="1", accept_unknown="1")
    assert s == 400 and "selection changed" in h and not acc.exists()
    confirm = {"accept_licenses": "1"}
    if any(i["category"] == "unknown" for i in items):
        confirm["accept_unknown"] = "1"
    s, h = post(panel, app, "/p/licenses/save", digest=digest, do="save", **confirm)
    assert s == 200 and licenses.accepted(digest, items)
    assert json.loads(acc.read_text())["selection_sha256"] == digest


def test_hermes_page_builds_command_and_starts_nothing(env, monkeypatch):
    panel, app, extra, *_ = env
    mod = sys.modules["panel_extra"]
    monkeypatch.setattr(mod, "hermes_modes_supported", lambda: True)
    s, h = app.route("GET", "/p/hermes", {"mode": ["graph"]})
    assert "scripts/hermes.sh --graph-mode" in h
    s, h = app.route("GET", "/p/hermes", {"mode": ["model"], "model": ["coder"]})
    assert "scripts/hermes.sh --model coder" in h
    monkeypatch.setattr(mod, "hermes_modes_supported", lambda: False)
    s, h = app.route("GET", "/p/hermes", {})
    assert "not in this checkout yet" in h


def test_harness2_absent_is_off_and_never_offers_pentests(env, tmp_path, monkeypatch):
    panel, app, extra, g, _ = env
    mod = sys.modules["panel_extra"]
    monkeypatch.setattr(mod, "harness2_script", lambda: None)
    s, h = app.route("GET", "/p/harness2")
    assert "Not available yet" in h
    fake = tmp_path / "harness2.py"
    log = tmp_path / "h2.log"
    fake.write_text("import sys\nopen(%r,'a').write(' '.join(sys.argv[1:])+'\\n')\nprint('hermes: off')\n" % str(log))
    monkeypatch.setattr(mod, "harness2_script", lambda: str(fake))
    s, h = app.route("GET", "/p/harness2")
    assert 'name="h2.hermes"' in h and "android-fleet" not in h
    assert 'value="off" checked' in h
    s, h = post(panel, app, "/p/harness2/preview", **{"h2.hermes": "off", "h2.android-fleet": "apply"})
    assert s == 400 and "never touches pentest roles" in h
    s, h = post(panel, app, "/p/harness2/preview", **{"h2.hermes": "propose"})
    assert s == 200 and "Harness2 for hermes: off to propose" in h and "set --agent hermes --mode propose" in h
    s, h = post(panel, app, "/p/harness2/save", do="save", **{"h2.hermes": "propose"})
    assert s == 200, h
    assert "set --agent hermes --mode propose" in log.read_text()


def test_models_page_is_read_only_explain(env, monkeypatch):
    panel, app, extra, *_ = env
    monkeypatch.setattr(extra, "explain", lambda node: (0, "node %s\n  REQUIRED    --jinja" % node))
    s, h = app.route("GET", "/p/models", {"node": ["coder"]})
    assert s == 200 and "REQUIRED    --jinja" in h and "<form" not in h.split("<main")[1]
    s, h = post(panel, app, "/p/models/save", do="save")
    assert s == 400 and "nothing to save" in h


def test_proxy_help_and_a11y_cli():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "panel.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "ssh -L 9932:127.0.0.1:9932" in r.stdout
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "panel.py"), "--a11y-check"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "0 problem(s)" in r.stdout, r.stdout + r.stderr
