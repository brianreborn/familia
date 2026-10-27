"""Model database (#51): stdlib HF client, ingest, card defaults, graph checks, linking.
Offline: a local HTTP server stands in for huggingface.co."""
import hashlib, http.server, json, os, shutil, subprocess, sys, threading
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import add_model as am  # noqa: E402
import hf_fetch as hf  # noqa: E402
import model_db  # noqa: E402
from test_add_model import write_gguf  # noqa: E402

SHA = "a" * 40
BASE_SHA = "b" * 40
QUANT_CARD = """---
license: apache-2.0
base_model: org/Thing
---
# Thing-GGUF
Quantized with llama.cpp.
"""
BASE_CARD = """---
license: apache-2.0
---
# Thing
Thing operates in non-thinking mode by default.

- Thinking mode for text tasks: temperature=0.6, top_p=0.95, top_k=20, min_p=0.0
- Non-thinking mode for text tasks: temperature=0.7, top_p=0.8, top_k=20, min_p=0.0, presence_penalty=1.5

## Experimental settings
We evaluate with temperature=0.0, top_p=1.0, top_k=1.

The model supports a context length of 32,768 tokens.
"""


def blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class FakeHub:
    """repos: {repo: (sha, {path: (bytes, lfs?)}, {extra listed-only path: size})}"""
    def __init__(self, tmp_path):
        self.repos, self.seen = {}, []
        gg = tmp_path / "g.gguf"
        write_gguf(gg, {"general.architecture": "qwen3", "general.file_type": 15, "qwen3.context_length": 40960,
                        "general.base_model.0.organization": "org", "general.base_model.0.name": "Thing"})
        self.gguf = gg.read_bytes()
        self.repos["org/Thing-GGUF"] = (SHA, {"README.md": (QUANT_CARD.encode(), False),
                                              "Thing-Q4_K_M.gguf": (self.gguf, True)},
                                        {"Thing-F16.gguf": 2_000_000_000})
        self.repos["org/Thing"] = (BASE_SHA, {"README.md": (BASE_CARD.encode(), False),
                                              "config.json": (b'{"max_position_embeddings": 32768}', False),
                                              "generation_config.json": (b'{"temperature": 0.7, "top_p": 0.8, "top_k": 20}', False)},
                                   {"model.safetensors": 1_200_000_000})
        hub = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                hub.seen.append((self.path, self.headers.get("Authorization"), self.headers.get("Host")))
                p = self.path.split("?")[0].strip("/").split("/")
                if p[0] == "cdn":           # "another host": the redirect target
                    repo, path = p[1] + "/" + p[2], "/".join(p[3:])
                    return self.send(hub.repos[repo][1][path][0])
                if p[:2] == ["api", "models"]:
                    repo, rev = p[2] + "/" + p[3], p[5]
                    if repo not in hub.repos:
                        return self.send(b"no", 404)
                    sha, files, listed = hub.repos[repo]
                    if rev not in ("main", sha):
                        return self.send(b"no rev", 404)
                    sib = []
                    for path, (data, lfs) in files.items():
                        s = {"rfilename": path, "size": len(data), "blobId": blob(data)}
                        if lfs:
                            s["lfs"] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                        sib.append(s)
                    for path, size in listed.items():
                        sib.append({"rfilename": path, "size": size, "blobId": "0" * 40, "lfs": {"sha256": "f" * 64, "size": size}})
                    return self.send(json.dumps({"sha": sha, "siblings": sib, "gated": False}).encode())
                repo, rev, path = p[0] + "/" + p[1], p[3], "/".join(p[4:])
                data, lfs = hub.repos[repo][1][path]
                if lfs:   # LFS files redirect to a CDN on another host: the token must not follow
                    self.send_response(302)
                    self.send_header("Location", "http://localhost:%d/cdn/%s/%s" % (hub.port, repo, path))
                    self.end_headers()
                    return
                self.send(data)

            def send(self, data, code=200):
                rng = self.headers.get("Range")
                if rng and code == 200:
                    a, b = rng.split("=")[1].split("-")
                    data, code = data[int(a):int(b) + 1], 206
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h = FakeHub(tmp_path)
    monkeypatch.setattr(hf, "ENDPOINT", "http://127.0.0.1:%d" % h.port)
    monkeypatch.setenv("FAMILIA_HF_META", str(tmp_path / "meta"))
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)
    yield h
    h.srv.shutdown()


def test_snapshot_pins_verifies_and_skips_weights(hub, tmp_path):
    s = hf.snapshot("org/Thing-GGUF", "main", log=lambda m: None)
    assert s["revision"] == SHA and s["dir"].endswith("org--Thing-GGUF/" + SHA)
    f = s["files"]
    assert f["README.md"]["fetched"] and f["README.md"]["verified"] == "git-blob-sha1"
    # weights are never part of a snapshot, however small: a full run fetches them after the license
    assert not f["Thing-Q4_K_M.gguf"]["fetched"] and "weight file" in f["Thing-Q4_K_M.gguf"]["skipped"]
    assert f["Thing-Q4_K_M.gguf"]["sha256"] == hashlib.sha256(hub.gguf).hexdigest()
    assert not f["Thing-F16.gguf"]["fetched"] and "weight file" in f["Thing-F16.gguf"]["skipped"]
    s2 = hf.snapshot("org/Thing-GGUF", "main", keep=("Thing-Q4_K_M.gguf",), log=lambda m: None)
    assert s2["files"]["Thing-Q4_K_M.gguf"]["verified"] == "lfs-sha256"   # --keep: explicitly wanted
    assert f["Thing-F16.gguf"]["sha256"] == "f" * 64 and f["Thing-F16.gguf"]["size"] == 2_000_000_000
    assert json.load(open(os.path.join(s["dir"], "snapshot.json")))["revision"] == SHA
    n = len(hub.seen)
    hf.snapshot("org/Thing-GGUF", SHA, log=lambda m: None)                # rerun: only the API call
    assert len(hub.seen) == n + 1


def test_download_rejects_bad_hash(hub, tmp_path):
    sib = {"rfilename": "README.md", "size": len(QUANT_CARD), "blobId": "0" * 40}
    with pytest.raises(hf.HFError, match="git blob sha1"):
        hf.download("org/Thing-GGUF", SHA, sib, str(tmp_path / "x" / "README.md"))
    assert not os.path.exists(tmp_path / "x" / "README.md") and not os.path.exists(tmp_path / "x" / "README.md.part")
    sib = {"rfilename": "Thing-Q4_K_M.gguf", "size": len(hub.gguf), "lfs": {"sha256": "0" * 64}}
    with pytest.raises(hf.HFError, match="sha256"):
        hf.download("org/Thing-GGUF", SHA, sib, str(tmp_path / "x" / "t.gguf"))


def test_token_sent_to_hub_only_and_never_printed(hub, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HF_TOKEN", "hf_SECRETSECRET")
    s = hf.snapshot("org/Thing-GGUF", None, keep=("Thing-Q4_K_M.gguf",), log=print)
    api = [a for p, a, h in hub.seen if p.startswith("/api/")]
    cdn = [a for p, a, h in hub.seen if p.startswith("/cdn/")]
    assert api and all(a == "Bearer hf_SECRETSECRET" for a in api)
    assert cdn and all(a is None for a in cdn)                           # dropped on the cross-host redirect
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    assert "SECRET" not in open(os.path.join(s["dir"], "snapshot.json")).read()


def test_missing_repo_is_a_clear_error(hub):
    with pytest.raises(hf.HFError) as e:
        hf.repo_info("org/Nope", "main")
    assert e.value.status == 404 and "not found" in str(e.value)


def test_ingest_uses_base_card_and_records_everything(hub, tmp_path):
    db = tmp_path / "db"
    e = model_db.ingest("org/Thing-GGUF", None, "Thing-Q4_K_M.gguf", db_dir=str(db))
    assert e["id"] == "org--Thing-GGUF--Thing-Q4_K_M" and e["revision"] == SHA
    assert e["sha256"] == hashlib.sha256(hub.gguf).hexdigest()
    assert e["base_model"] == "org/Thing" and e["base_revision"] == BASE_SHA
    # the card's stated default mode picks the non-thinking set; benchmark settings are not used
    assert e["card_defaults"] == {"temp": 0.7, "top-p": 0.8, "top-k": 20, "min-p": 0.0, "presence-penalty": 1.5}
    assert e["card_default_set"].startswith("Non-thinking") and e["card_default_mode"] == "non-thinking"
    assert len(e["card_sampling_modes"]) == 2
    assert any(s["kind"] == "benchmark" for s in e["card_sampling_sets"])
    assert e["ctx"] == 40960 and e["card_ctx"] == 32768 and e["warnings"]   # card vs GGUF recorded
    assert e["repo_files"]["Thing-F16.gguf"]["skipped"]
    assert e["base_repo_files"]["model.safetensors"]["sha256"] == "f" * 64
    assert json.load(open(db / (e["id"] + ".json")))["id"] == e["id"]


def test_ingest_unknown_file(hub, tmp_path):
    with pytest.raises(hf.HFError, match="has no file"):
        model_db.ingest("org/Thing-GGUF", None, "Other.gguf", db_dir=str(tmp_path / "db"))


def test_add_model_fetch_end_to_end(hub, tmp_path, monkeypatch, capsys):
    from test_add_model import MANIFEST, PRESET
    boot = tmp_path / "boot"
    (boot / "config").mkdir(parents=True)
    (boot / "config" / "models-manifest.json").write_text(json.dumps(MANIFEST, indent=4))
    (boot / "config" / "models-preset.ini").write_text(PRESET)
    monkeypatch.setattr(model_db, "DB_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("FAMILIA_MODEL_LICENSE_ACCEPT_FILE", str(tmp_path / "acc.json"))
    monkeypatch.setenv("FAMILIA_NO_TTY", "1")
    monkeypatch.delenv("FAMILIA_ACCEPT_LICENSES", raising=False)
    import model_license
    monkeypatch.setattr(model_license, "ACCEPT_FILE", str(tmp_path / "acc.json"))
    args = ["--bootstraps", str(boot), "--role", "coder", "--fetch", "org/Thing-GGUF", "--quant", "Q4_K_M"]
    # no terminal, no --accept-licenses: the license is shown and nothing is downloaded
    assert am.main(args) == 2
    assert "license of org--Thing-GGUF--Thing-Q4_K_M" in capsys.readouterr().err
    assert not os.path.isfile(tmp_path / "meta" / "org--Thing-GGUF" / SHA / "Thing-Q4_K_M.gguf")
    rc = am.main(args + ["--accept-licenses"])
    accepted_output = capsys.readouterr()
    assert rc == 0
    assert "stored in " in accepted_output.err and "accepted-licenses" in accepted_output.err
    records = list(tmp_path.rglob("*.md"))
    assert records and any('"license": "apache-2.0"' in record.read_text() for record in records)
    m = json.loads((boot / "config" / "models-manifest.json").read_text())
    c = next(c for c in m["candidates"] if c["file"] == "Thing-Q4_K_M.gguf")
    assert c["repo"] == "org/Thing-GGUF" and c["revision"] == SHA and c["sha256"] == hashlib.sha256(hub.gguf).hexdigest()
    assert os.path.isfile(tmp_path / "meta" / "org--Thing-GGUF" / SHA / "Thing-Q4_K_M.gguf")
    assert os.path.isfile(tmp_path / "db" / "org--Thing-GGUF--Thing-Q4_K_M.json")
    assert not any(p.endswith("Thing-F16.gguf") for p, a, h in hub.seen)


def test_add_model_fetch_needs_a_choice(hub, tmp_path, capsys):
    hub.repos["org/Thing-GGUF"][1]["Thing-Q8_0.gguf"] = (hub.gguf + b"x", True)
    boot = tmp_path / "boot"
    (boot / "config").mkdir(parents=True)
    from test_add_model import MANIFEST
    (boot / "config" / "models-manifest.json").write_text(json.dumps(MANIFEST))
    rc = am.main(["--bootstraps", str(boot), "--fetch", "org/Thing-GGUF"])
    assert rc == 2 and "choose one GGUF with --quant or --file" in capsys.readouterr().err


# ---------------------------------------------------------------- card defaults
def sset(label, params, kind="recommended"):
    mode = "non-thinking" if "non-thinking" in label.lower() else "thinking" if "thinking" in label.lower() else None
    return {"label": label, "params": params, "kind": kind, "mode": mode, "source": "README.md:L1"}


def test_choose_card_defaults_rules():
    one = {"sets": [sset("Generation parameters", {"temp": 0.1, "top-k": 50})], "default_mode": None}
    d, src, label, modes, how = am.choose_card_defaults([("", one)], [])
    assert d == {"temp": 0.1, "top-k": 50} and label == "Generation parameters"
    two = {"sets": [sset("Thinking mode", {"temp": 0.6, "top-p": 0.95}), sset("Non-thinking mode", {"temp": 0.7, "top-p": 0.8})],
           "default_mode": None}
    d, src, label, modes, how = am.choose_card_defaults([("", two)], [])
    assert d is None and len(modes) == 2                                  # ambiguous: node must choose
    dual = {"sets": [sset("Agentic and tool-use tasks", {"temp": 1.0, "top-p": 0.95}),
                     sset("Reasoning and chat tasks", {"temp": 0.6, "top-p": 0.95})],
            "default_mode": None}
    d, src, label, modes, how = am.choose_card_defaults([("", dual)], [])
    assert d == {"temp": 0.6, "top-p": 0.95} and "soft-prefer" in how and len(modes) == 2
    d, *_ = am.choose_card_defaults([("", two)], [("", {"temperature": 0.7, "top_p": 0.8})])
    assert d == {"temp": 0.7, "top-p": 0.8}                               # generation_config breaks the tie
    two["default_mode"] = "thinking"
    d, *_ = am.choose_card_defaults([("", two)], [])
    assert d == {"temp": 0.6, "top-p": 0.95}
    bench = {"sets": [sset("Experimental settings", {"temp": 0.0, "top-k": 1}, "benchmark")], "default_mode": None}
    d, src, label, modes, how = am.choose_card_defaults([("", bench)], [("", {"temperature": 0.3})])
    assert d == {"temp": 0.3} and "generation_config" in how
    d, *_ = am.choose_card_defaults([("", bench)], [])
    assert d is None


# ---------------------------------------------------------------- graph checks
def entry(**kw):
    e = {"id": "org--Thing-GGUF--Thing-Q4_K_M", "repo": "org/Thing-GGUF", "revision": SHA, "file": "Thing-Q4_K_M.gguf",
         "sha256": "c" * 64, "arch": "qwen3", "ctx": 40960, "card_ctx": 32768,
         "card_defaults": {"temp": 0.7, "top-p": 0.8}, "card_default_set": "Non-thinking mode",
         "card_sampling_modes": {"Thinking mode": {"temp": 0.6, "top-p": 0.95}, "Non-thinking mode": {"temp": 0.7, "top-p": 0.8}},
         "required_params": {"kind": "chat", "native_ctx": 40960, "native_ctx_source": "GGUF", "yarn": None,
                             "items": [{"class": "REQUIRED", "flag": "--jinja", "value": None, "source": "chat model",
                                        "why_required": "the chat template is only applied with --jinja"}]}}
    e.update(kw)
    return e


def graph(node=None, model=None):
    m = {"gguf": "Thing-Q4_K_M.gguf", "sha256": "c" * 64, "arch": "qwen3", "trained_ctx": 40960, "db": "org--Thing-GGUF--Thing-Q4_K_M"}
    m.update(model or {})
    n = {"model": "thing", "host": "h", "ctx": 32768, "parallel": 1}
    n.update(node or {})
    return {"models": {"thing": {k: v for k, v in m.items() if v is not None}}, "nodes": {"n": n}}


@pytest.fixture
def db(tmp_path):
    d = str(tmp_path / "db")
    model_db.save(entry(), d)
    return d


def errs(g, d):
    return model_db.check_graph(g, d)


def test_check_graph_ok_and_sampling(db):
    e, w = errs(graph(), db)
    assert e == [] and w == []
    assert model_db.launch_sampling(entry(), graph()["nodes"]["n"]) == {"temp": 0.7, "top-p": 0.8}


def test_check_graph_missing_entry_and_revision(db, tmp_path):
    e, _ = errs(graph(model={"db": None}), db)
    assert any("no model database entry" in x for x in e)
    e, _ = errs(graph(model={"db": "nope"}), db)
    assert any("no entry nope" in x for x in e)
    model_db.save(entry(revision="main"), db)
    e, _ = errs(graph(), db)
    assert any("no pinned revision" in x for x in e)


def test_check_graph_ctx_needs_reason(db):
    e, _ = errs(graph({"ctx": 8192}), db)
    assert any("ctx 8192 differs" in x and "override_reasons.ctx" in x for x in e)
    e, _ = errs(graph({"ctx": 8192, "override_reasons": {"ctx": "short"}}), db)
    assert any("needs a real reason" in x for x in e)
    e, w = errs(graph({"ctx": 8192, "override_reasons": {"ctx": "RAM budget on a 4 GB host"}}), db)
    assert e == []
    e, w = errs(graph({"override_reasons": {"ctx": "RAM budget on a 4 GB host"}}), db)
    assert e == [] and any("stale" in x for x in w)


def test_check_graph_sampling_and_card_set(db):
    e, _ = errs(graph({"sampling": {"temp": 0.2}}), db)
    assert any("sampling.temp = 0.2 contradicts" in x for x in e)
    e, _ = errs(graph({"sampling": {"temp": 0.2}, "override_reasons": {"temp": "measured: 0.2 halves tool-call errors"}}), db)
    assert e == []
    e, _ = errs(graph({"sampling": {"tempo": 1}}), db)
    assert any("unknown key" in x for x in e)
    e, _ = errs(graph({"card_set": "Thinking mode"}), db)               # exact label wins over "Non-thinking mode"
    assert any("'Thinking mode' is not the card's default" in x for x in e)
    e, _ = errs(graph({"card_set": "Thinking mode", "override_reasons": {"card_set": "tool calls tested with this set"}}), db)
    assert e == []
    assert model_db.launch_sampling(entry(), {"card_set": "Thinking mode"}) == {"temp": 0.6, "top-p": 0.95}
    e, _ = errs(graph({"card_set": "mode"}), db)
    assert any("matches 2" in x for x in e)
    e, _ = errs(graph({"card_set": "Non-thinking"}), db)
    assert e == []
    model_db.save(entry(card_defaults=None, card_default_set=None), db)
    e, _ = errs(graph(), db)
    assert any("none is the default" in x for x in e)


def test_check_graph_sha_and_trained_ctx(db):
    e, _ = errs(graph(model={"sha256": "d" * 64, "trained_ctx": 4096}), db)
    assert any("sha256" in x for x in e) and any("trained_ctx 4096" in x for x in e)
    e, _ = errs(graph(model={"sha256": "unmeasured"}), db)
    assert e == []


def test_embedding_nodes_get_no_sampling(db):
    rp = {"kind": "embed", "native_ctx": 40960, "yarn": None, "items": [
        {"class": "REQUIRED", "flag": "--embeddings", "value": None, "source": "s", "why_required": "w"},
        {"class": "REQUIRED", "flag": "--pooling", "value": "mean", "source": "s", "why_required": "w"}]}
    model_db.save(entry(card_defaults=None, card_default_set=None, card_sampling_modes=None, required_params=rp), db)
    e, _ = errs(graph({"embeddings": True}), db)
    assert e == []
    e, _ = errs(graph(), db)              # an embedder served as chat
    assert any("embed" in x for x in e)


def test_entry_without_required_params_is_an_error(db):
    model_db.save(entry(required_params=None), db)
    e, _ = errs(graph(), db)
    assert any("has no required_params" in x for x in e)


# ---------------------------------------------------------------- linking
def test_record_match():
    a = entry()
    b = entry(id="other--Thing-GGUF--Thing-Q4_K_M", repo="other/Thing-GGUF", sha256="e" * 64)
    for x in (a, b):
        x["quant"] = "Q4_K_M"
    ents = {a["id"]: a, b["id"]: b}
    g = {"models": {}, "nodes": {}}
    assert model_db.record_match({"model": {"sha256": "c" * 64}}, ents, g)[0]["id"] == a["id"]
    hit, why = model_db.record_match({"model": {"repo": "Thing", "quant": "Q4_K_M"}}, ents, g)
    assert hit is None and "ambiguous" in why or hit is None
    assert model_db.record_match({}, ents, g) == (None, "record has no model")


def test_link_graph_idempotent(tmp_path):
    p = tmp_path / "graph.yaml"
    p.write_text("version: 2\nmodels:\n  thing:   # a comment\n    gguf: Thing-Q4_K_M.gguf\n\n  other:\n    gguf: o.gguf\nnodes:\n  n:\n    model: thing\n")
    built = {"x": (entry(), {"graph_models": ["thing"]})}
    model_db.link_graph(built, str(p))
    once = p.read_text()
    assert "  thing:   # a comment\n    gguf: Thing-Q4_K_M.gguf\n    db: org--Thing-GGUF--Thing-Q4_K_M\n" in once
    assert "  other:\n    gguf: o.gguf\n" in once and once.count("db:") == 1
    model_db.link_graph(built, str(p))
    assert p.read_text() == once


def test_manifest_projection_stays_awk_readable(tmp_path):
    awk = os.path.join(ROOT, "code-bootstraps-llama.cpp", "scripts", "lib", "manifest.awk")
    if not (os.path.isfile(awk) and shutil.which("awk")):
        pytest.skip("code-bootstraps checkout or awk not available")
    c = {"role": "coder", "pick": "default", "repo": "org/Thing-GGUF", "revision": SHA, "file": "Thing-Q4_K_M.gguf",
         "sha256": "c" * 64, "tested": True}
    c.update(model_db.manifest_projection(entry(card_defaults_source={"temp": "README.md:L5"})))
    text = am.dump_manifest({"candidates": [c]})
    assert json.loads(text)["candidates"][0]["card_sampling_modes"]["Thinking mode"] == {"temp": 0.6, "top-p": 0.95}
    f = tmp_path / "m.json"
    f.write_text(text)
    out = subprocess.run(["awk", "-v", "match_kv=", "-v", "fields=role repo revision file sha256 tested", "-f", awk, str(f)],
                         capture_output=True, text=True).stdout
    assert out.strip() == "coder\torg/Thing-GGUF\t%s\tThing-Q4_K_M.gguf\t%s\tyes" % (SHA, "c" * 64)


def test_repo_graph_launch_args_carry_card_sampling():
    """The real graph.yaml: every node links an entry and serve.sh / hermes get card flags."""
    import validate_graph as vg
    g = vg.load(os.path.join(ROOT, "graph.yaml")) if hasattr(vg, "load") else None
    if g is None:
        pytest.skip("validate_graph has no load()")
    e, _ = model_db.check_graph(g)
    assert e == []
    for name, n in g["nodes"].items():
        ent = model_db.load(g["models"][n["model"]]["db"])
        try:
            args = " ".join(map(str, vg.server_args(g, name)))
        except SystemExit:          # not a llama-server runtime (e.g. sm11-legacy): no launch args
            continue
        for k, v in model_db.launch_sampling(ent, n).items() if not n.get("embeddings") else []:
            assert "--%s %s" % (k, v) in args, (name, k)


# ---------------------------------------------------------------- run modes (#51): dry / damp
def test_dry_run_writes_nothing(hub, tmp_path, capsys):
    rc = model_db.main(["--db-dir", str(tmp_path / "db"), "damp", "org/Thing-GGUF", "--dry-run"])
    err = capsys.readouterr().err
    assert rc == 0 and "dry run: plan for org/Thing-GGUF" in err
    assert "skip-weight" in err and "fetch" in err and "README.md" in err
    assert not os.path.exists(tmp_path / "meta") and not os.path.exists(tmp_path / "db")
    assert not [p for p, a, h in hub.seen if "/resolve/" in p]           # only the API was read


def test_damp_run_entry_is_not_runnable(hub, tmp_path, capsys):
    db = str(tmp_path / "db")
    rc = model_db.main(["--db-dir", db, "--max-file-mb", "0.5", "damp", "org/Thing-GGUF", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out[0]["weights"] == "absent (damp)" and out[0]["id"] == "org--Thing-GGUF--Thing-Q4_K_M"
    e = model_db.load("org--Thing-GGUF--Thing-Q4_K_M", db)
    assert e["weights"] == "absent (damp)" and e["bytes"] == len(hub.gguf) and e["sha256"] == hashlib.sha256(hub.gguf).hexdigest()
    assert e["license_info"]["id"] == "apache-2.0" and e["role_inference"]["evidence"]
    assert not os.path.isfile(tmp_path / "meta" / "org--Thing-GGUF" / SHA / "Thing-Q4_K_M.gguf")   # header read by Range only
    g = graph()
    e2, _ = model_db.check_graph(g, db)
    assert any("not runnable yet" in x and "absent (damp)" in x for x in e2)
    g["nodes"]["n"]["status"] = "planned"
    e3, w3 = model_db.check_graph(g, db)
    assert not any("not runnable" in x for x in e3) and any("not runnable" in x for x in w3)


def test_model_license_gate(tmp_path, monkeypatch, capsys):
    import model_license as ml
    monkeypatch.setattr(ml, "ACCEPT_FILE", str(tmp_path / "acc.json"))
    monkeypatch.setenv("FAMILIA_NO_TTY", "1")
    monkeypatch.delenv("FAMILIA_ACCEPT_LICENSES", raising=False)
    monkeypatch.setattr(ml, "licenses_py_has_models", lambda: False)
    e = entry(license="cc-by-nc-4.0", license_info={"id": "cc-by-nc-4.0", "id_source": "card", "link": "https://x/LICENSE",
              "obligations": [{"quote": "NonCommercial: not for commercial purposes", "source": "o/m LICENSE:L3"}]})
    assert ml.gate([e], dry_run=True) == 0 and not os.path.exists(tmp_path / "acc.json")
    assert "NonCommercial" in capsys.readouterr().err
    assert ml.gate([e]) == 2                      # no terminal: refused, explained
    assert ml.gate([e], yes=True) == 0 and ml.accepted(e)
    e["license_info"]["id"] = "other"             # the license changed: asked again
    assert not ml.accepted(e)
    u = entry(license="unknown", license_info={"id": "unknown", "unknown": True})
    ml.summary(u)
    assert "UNKNOWN" in capsys.readouterr().err


def test_plan_rows_statuses(tmp_path):
    info = {"id": "o/m", "sha": "c" * 40, "siblings": [
        {"rfilename": "README.md", "size": 10, "blobId": "b"},
        {"rfilename": "m-Q4_K_M.gguf", "size": 10 ** 9, "lfs": {"sha256": "d" * 64, "size": 10 ** 9}},
        {"rfilename": "big.json", "size": 60 * 10 ** 6, "blobId": "e"}]}
    rows = {r["path"]: r["status"] for r in hf.plan_rows(info, (), 50 * 10 ** 6, root=str(tmp_path), want=("m-Q4_K_M.gguf",))}
    assert rows == {"README.md": "fetch", "m-Q4_K_M.gguf": "weight-wanted", "big.json": "skip-large"}


def test_add_model_damp_needs_fetch(capsys, tmp_path, monkeypatch):
    assert am.main(["--damp-run", "x.gguf"]) == 2
    assert "--damp-run needs --fetch" in capsys.readouterr().err
    # a usage error, whatever the environment: no code-bootstraps manifest reachable
    monkeypatch.setenv("CODE_BOOTSTRAPS", str(tmp_path / "none"))
    assert am.main(["--damp-run", "x.gguf"]) == 2
    assert "--damp-run needs --fetch" in capsys.readouterr().err


def test_license_info_quotes_obligations(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    (d / "LICENSE").write_text("THING LICENSE\nYou must retain this notice in all copies of the Model.\n")
    (d / "README.md").write_text("---\nlicense: other\nlicense_name: thing\n---\n# T\nAcceptable use: see the policy.\n")
    snap = {"dir": str(d), "revision": "a" * 40, "card_data": {"license": "other", "license_name": "thing"}}
    e = entry(descriptor={})
    li = model_db.license_info(e, snap, None)
    assert li["id"] == "thing" and li["id_source"].endswith("license_name")
    assert li["texts"][0]["file"].endswith("/LICENSE") and li["texts"][0]["sha256"]
    q = {x["source"]: x["quote"] for x in li["obligations"]}
    assert q["org/Thing-GGUF LICENSE:L2"].startswith("You must retain") and "org/Thing-GGUF README.md:L6" in q


def test_damp_never_downgrades_an_existing_entry(hub, tmp_path, capsys):
    db = str(tmp_path / "db")
    model_db.ingest("org/Thing-GGUF", SHA, "Thing-Q4_K_M.gguf", db_dir=db)
    assert model_db.main(["--db-dir", db, "damp", "org/Thing-GGUF"]) == 0
    assert "weights" not in model_db.load("org--Thing-GGUF--Thing-Q4_K_M", db)


def test_speech_model_gets_no_text_role(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "README.md").write_text("---\npipeline_tag: automatic-speech-recognition\n---\n# ASR\n")
    e = entry(file="asr-Q8_0.gguf", gguf_meta={"general.architecture": "parakeet"})
    role, ev = model_db.infer_role(e, {"dir": str(d), "card_data": {"pipeline_tag": "automatic-speech-recognition"}})
    assert role is None and "no familia role" in ev[-1]
