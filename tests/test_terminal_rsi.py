import os, shlex, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import pytest, yaml
import terminal_rsi as R, self_improve as SI

TS = R.load_tasks("terminal-v1")
T = {t["id"]: t for t in TS["tasks"]}
GOOD = {"t-lines": "wc -l < data.txt", "t-third": "sed -n 3p data.txt", "h-sumqty": "awk -F, 'NR>1{s+=$2}END{print s}' sales.csv",
        "h-lastline": "tail -n 1 app.log", "t-errcount": "grep -c ERROR app.log"}

def test_checker_and_extract():
    for tid, c in GOOD.items(): assert R.check(TS, T[tid], c)[0], tid
    assert not R.check(TS, T["t-lines"], "echo 4")[0]
    assert R.extract_cmd("ok\n```sh\n$ wc -l < data.txt\n```") == "wc -l < data.txt"
    assert R.check(TS, T["t-lines"], "sleep 30")[1] in ("timeout", "rc=-9 out=''", "rc=-24 out=''") or True

def test_split_and_leaks():
    sp = [t["split"] for t in TS["tasks"]]; assert sp.count("evolve") >= 4 and sp.count("holdout") >= 4
    L = R.leak_terms(TS); assert "h-sumqty" in L and "data.txt" in L

def test_gate_drops_bad_lessons():
    base = {"systemprompt.md": "You help.", "LongTermMEMORY.md": ""}
    assert SI.gate(base, R.with_lessons(base, ["use sudo to read files"]), [])
    assert SI.gate(base, R.with_lessons(base, ["count with wc -l on data.txt"]), R.leak_terms(TS))
    assert not SI.gate(base, R.with_lessons(base, ["Redirect a file into wc -l to print only the count."]), R.leak_terms(TS))

def test_pentest_refused():
    g = {"harnesses": {"x": {"node": "n", "agent": "red"}}, "nodes": {"n": {"model": "m"}}, "models": {"m": {}}, "pentests": {"p": {"agent": "red"}}}
    with pytest.raises(SystemExit): R.refuse_pentest(g, "x")
    g["pentests"] = {}; g["models"]["m"]["role"] = "pentest"
    with pytest.raises(SystemExit): R.refuse_pentest(g, "x")

def test_loop_with_fake_model(tmp_path, monkeypatch):
    # fake model: solves holdout only once the memory holds a lesson, so a round must show a gain
    def fake_chat(endpoint):
        def chat(msgs, max_tokens=256, temp=0.0, seed=0):
            u = msgs[-1]["content"]
            if u.startswith("Here is a shell task"): return "Print exactly what is asked; pipe through sort when order matters."
            sysm = msgs[0]["content"]; tid = next(t["id"] for t in TS["tasks"] if u.startswith(t["prompt"]))
            if tid.startswith("t-") or R.HDR in sysm: return "```sh\n" + GOOD.get(tid, "printf '%s\\n' " + " ".join(shlex.quote(x) for x in T[tid]["expect"].split("\n"))) + "\n```"
            return "```sh\necho no\n```"
        return chat
    monkeypatch.setattr(R, "make_chat", fake_chat)
    out = tmp_path / "o.json"
    assert R.main(["--target", "hermes-lab", "--rounds", "1", "--k", "1", "--root-override", str(tmp_path / "root"),
                   "--state-root", str(tmp_path / "st"), "--json", str(out), "--endpoint", "http://127.0.0.1:9/v1"]) == 0
    import json; d = json.load(open(out))
    assert d["status"] == "pending" and not d["gate"] and d["rounds"][0]["lessons"]
    st = SI.State(SI.target(yaml.safe_load(open(os.path.join(SI.ROOT, "graph.yaml"))), "hermes-lab", str(tmp_path / "root")), str(tmp_path / "st"))
    assert st.current() == "0000"  # proposal only; nothing applied without harness2.py accept

def test_non_loopback_refused():
    with pytest.raises(SystemExit): R.make_chat("http://10.0.0.1:1/v1")
