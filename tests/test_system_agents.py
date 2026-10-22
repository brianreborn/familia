"""Phone system agents (#80): schema, pentest guard, license rows, Termux adapter with a mock rish.
No phone is touched; live testing is pending (docs/system-agents.md)."""
import copy, json, os, stat, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "termux"))
import system_agents as sa  # noqa: E402
import system_agent as ad  # noqa: E402
from graph_types import validate_types  # noqa: E402
import validate_graph  # noqa: E402

ADAPTER = os.path.join(ROOT, "scripts", "termux", "system_agent.py")


def graph():
    g = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
    g = copy.deepcopy(g)
    g["hosts"]["testphone"] = {"kind": "phone", "measured": False, "gpus": []}
    return g


def entry(**kw):
    e = {"kind": "system-agent", "provider": "gemini", "backend": "app", "host": "testphone", "transport": "shizuku",
         "cloud": True, "consent": "ask", "status": "off", "experimental": True}
    e.update(kw); return e


def sa_errs(g):
    return [x for x in validate_types(g) if "system_agent" in x or "system agent" in x]


def test_off_by_default_graph_has_none():
    g = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
    assert not sa.enabled(g)
    assert sa.license_rows(g) == []


def test_valid_entry_passes():
    g = graph(); g["system_agents"] = {"gem": entry()}
    assert sa_errs(g) == []


def test_bixby_has_no_nano_and_cloud_must_match():
    g = graph(); g["system_agents"] = {"b": entry(provider="bixby", backend="nano", cloud=False),
                                       "n": entry(backend="nano", cloud=True)}
    e = sa_errs(g)
    assert any("no 'nano' backend" in x for x in e)
    assert any("system_agents.n: cloud must be false" in x for x in e)


def test_must_be_on_phone_and_experimental():
    g = graph(); h = next(n for n, x in g["hosts"].items() if x.get("kind") != "phone")
    e1 = entry(host=h); del e1["experimental"]
    g["system_agents"] = {"x": e1}
    e = sa_errs(g)
    assert any("system agents run on a phone" in x for x in e)
    assert any("experimental type" in x for x in validate_types(g))


def test_unknown_field_rejected():
    g = graph(); g["system_agents"] = {"x": entry(token="abc")}
    assert any("unknown field 'token'" in x for x in validate_types(g))


def test_pentests_never_get_system_agents():
    g = graph()
    pn = "test"
    p = {"agent": "hermes", "node": "coder", "name": "test", "status": "planned",
         "scope": {"allow": [], "deny": []}, "tools": {"allow": []},
         "report_to": "familia-issues", "requires_operator_confirm": True, "launch_test_only": True}
    g["pentests"] = {pn: p}
    g["system_agents"] = {"gem": entry(agents=[p["agent"]])}
    p["tools"] = {"allow": ["gem"]}
    e = validate_types(g)
    assert any("pentest roles never get system agents" in x and "agent" in x for x in e)
    assert any(f"pentests.{pn}.tools: names system agent 'gem'" in x for x in e)


def test_license_rows_for_enabled_entries():
    g = graph(); g["system_agents"] = {"gem": entry(status="planned"), "nano": entry(backend="nano", cloud=False, status="planned"),
                                       "off": entry(provider="bixby", status="off")}
    rows = sa.license_rows(g)
    ids = [r[1] for r in rows]
    assert ids[0].startswith("Shizuku") and rows[0][3] == "Apache-2.0"
    assert "gemini (app, cloud)" in ids and "gemini (nano, on-device)" in ids
    assert not any("bixby" in i for i in ids)  # status off -> not listed


def test_licenses_py_lists_them():
    import licenses
    g = graph(); g["system_agents"] = {"gem": entry(status="planned")}
    items = licenses.system_agent_items(g)
    cats = {i["id"]: i["category"] for i in items}
    assert cats["Shizuku + rish (RikkaApps)"] == "permissive"
    assert cats["gemini (app, cloud)"] == "restrictive"


# ---- Termux adapter with a mock rish ----------------------------------------
MOCK = r"""#!/bin/sh
# mock rish: log the command, answer like a phone would
[ "$1" = "-c" ] || exit 9
printf '%s\n' "$2" >> "$MOCK_LOG"
case "$MOCK_MODE" in stopped) echo "Shizuku is not running" >&2; exit 1 ;; esac
case "$2" in
  id) echo "uid=2000(shell) gid=2000(shell)" ;;
  "pm list packages") printf 'package:com.termux\npackage:com.google.android.apps.bard\npackage:com.samsung.android.bixby.agent\n' ;;
  "getprop ro.build.version.sdk") echo 34 ;;
  uiautomator*)
    n=$(cat "$MOCK_LOG.n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$MOCK_LOG.n"
    if [ $n -eq 1 ]; then
      echo '<hierarchy><node text="hello gemini" package="com.google.android.apps.bard" bounds="[0,0][10,10]"/><node text="" content-desc="Send message" package="com.google.android.apps.bard" bounds="[100,200][140,240]"/></hierarchy>'
    else
      echo '<hierarchy><node text="hello gemini" package="com.google.android.apps.bard" bounds="[0,0][10,10]"/><node text="Hi! How can I help?" package="com.google.android.apps.bard" bounds="[0,20][10,30]"/></hierarchy>'
    fi ;;
esac
exit 0
"""


def mock_env(tmp_path, mode="ok"):
    (tmp_path / "mock").mkdir(exist_ok=True)
    r = tmp_path / "mock" / "rish"; r.write_text(MOCK); r.chmod(r.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, FAMILIA_RISH=str(r), MOCK_LOG=str(tmp_path / "log"), MOCK_MODE=mode,
               FAMILIA_SYSTEM_AGENT_STATE=str(tmp_path / "state.json"),
               FAMILIA_SYSTEM_AGENT_CONSENT=str(tmp_path / "consent.json"), HOME=str(tmp_path))
    env.pop("FAMILIA_ROLE", None)
    return env


def run(env, *a):
    return subprocess.run([sys.executable, ADAPTER, *a], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)


def test_probe_running_writes_state(tmp_path):
    env = mock_env(tmp_path)
    p = run(env, "probe", "--json")
    assert p.returncode == 0, p.stderr
    r = json.loads(p.stdout)
    assert r["shizuku"] == "running" and r["uid"] == 2000 and r["sdk"] == 34
    assert r["providers"]["gemini"]["app"] and r["providers"]["bixby"]["app"] and not r["providers"]["gemini"]["aicore"]
    assert json.load(open(tmp_path / "state.json"))["shizuku"] == "running"


def test_probe_detects_stop_after_reboot(tmp_path):
    env = mock_env(tmp_path, "stopped")
    json.dump({"shizuku": "running", "boot_id": "an-older-boot"}, open(tmp_path / "state.json", "w"))
    p = run(env, "probe", "--json")
    assert p.returncode == 4
    r = json.loads(p.stdout)
    if ad.boot_id():  # Linux test hosts have one
        assert r["shizuku"] == "stopped-after-reboot" and "reboot" in r["hint"]


def test_probe_absent_without_rish(tmp_path):
    env = mock_env(tmp_path); env["FAMILIA_RISH"] = str(tmp_path / "nope"); env["PREFIX"] = str(tmp_path)
    p = run(env, "probe", "--json")
    assert p.returncode == 4 and json.loads(p.stdout)["shizuku"] == "absent"


def test_ask_refuses_without_consent_and_sends_nothing(tmp_path):
    env = mock_env(tmp_path)
    p = run(env, "ask", "--provider", "gemini", "--text", "hello gemini")
    assert p.returncode == 3 and "CLOUD" not in p.stdout and "consent" in p.stderr
    assert not (tmp_path / "log").exists()


def test_ask_with_consent_reads_reply(tmp_path):
    env = mock_env(tmp_path)
    assert run(env, "consent", "--provider", "gemini", "--grant").returncode == 0
    p = run(env, "ask", "--provider", "gemini", "--text", "hello gemini", "--json", "--timeout", "10")
    assert p.returncode == 0, p.stderr
    r = json.loads(p.stdout)
    assert r["reply"] == "Hi! How can I help?" and r["cloud"] is True
    log = open(tmp_path / "log").read()
    assert "android.intent.action.SEND" in log and "'hello gemini'" in log and "input tap 120 220" in log
    assert run(env, "consent", "--provider", "gemini", "--revoke").returncode == 0
    assert run(env, "ask", "--provider", "gemini", "--text", "x").returncode == 3


def test_ask_quotes_hostile_text(tmp_path):
    env = mock_env(tmp_path)
    p = run(env, "ask", "--provider", "gemini", "--text", "a'; reboot; echo '", "--dry-run")
    assert p.returncode == 0
    import shlex
    line = next(l for l in p.stdout.splitlines() if "android.intent.action.SEND" in l)
    rish, c, cmd = shlex.split(line)
    argv = shlex.split(cmd)  # what the phone's sh will see
    assert argv[argv.index("android.intent.extra.TEXT") + 1] == "a'; reboot; echo '"
    assert not (tmp_path / "log").exists()  # dry run never calls rish


def test_dry_run_needs_no_consent_and_unwired_paths(tmp_path):
    env = mock_env(tmp_path)
    assert run(env, "ask", "--provider", "gemini", "--text", "hi", "--dry-run").returncode == 0
    assert run(env, "ask", "--provider", "bixby", "--text", "hi").returncode == 5
    assert run(env, "ask", "--provider", "gemini", "--backend", "nano", "--text", "hi").returncode == 5


def test_pentest_role_refused_and_usage(tmp_path):
    env = mock_env(tmp_path); env["FAMILIA_ROLE"] = "pentest"
    assert run(env, "probe").returncode == 2
    env = mock_env(tmp_path)
    assert run(env, "ask", "--provider", "siri", "--text", "x").returncode == 2
    assert run(env, "probe", "--bogus").returncode == 2
    assert run(env, "--help").returncode == 0


def test_status_cli(tmp_path):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "system_agents.py"), "status"], capture_output=True, text=True)
    assert p.returncode == 0 and "off by default" in p.stdout


def test_monitor_shows_shizuku_state(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "scripts", "monitor"))
    import probe, monitor
    d = tmp_path / ".cache" / "familia"; d.mkdir(parents=True)
    json.dump({"shizuku": "stopped-after-reboot", "providers": {"gemini": {"app": True}, "bixby": {"app": False}},
               "time": 0, "boot_id": "secret-ish"}, open(d / "system-agent.json", "w"))
    monkeypatch.setenv("HOME", str(tmp_path))
    st = probe.system_agent_state()
    assert st["shizuku"] == "stopped-after-reboot" and "boot_id" not in st
    line = monitor.system_agents_line(st)
    assert "STOPPED after reboot" in line and "gemini" in line


def test_shizuku_state_dry_run_no_match_does_not_crash():
    class Sh:
        dry, rish = True, None
        def run(self, *a, **k):
            return ""
    sh = Sh()
    for name in ("run", "out", "check", "sh"):
        setattr(sh, name, lambda *a, **k: "")
    st, uid = ad.shizuku_state(sh)
    assert st == "unknown" and uid is None
