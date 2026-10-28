"""Model parameters (#51): verbatim card examples, llama.cpp flag parsing, translation of other
runners' examples, REQUIRED enforcement, the chat-template hash check, launch scripts."""
import json, os, shutil, stat, subprocess, sys, textwrap
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import llama_flags as lf  # noqa: E402
import model_params as mp  # noqa: E402

B = lf.load("b11374")

CARD = """---
license: apache-2.0
---
# Model

Run it:

```bash
./llama-cli -hf Org/M-GGUF:Q8_0 --jinja --color -ngl 99 -fa -sm row --temp 0.6 --top-k 20 \\
    -c 40960 -n 32768 --no-context-shift
```

- **Tool Call**:

    ```shell
    vllm serve Org/M --port 8000 --max-model-len 262144 --enable-auto-tool-choice --tool-call-parser qwen3_coder --speculative-config '{"method":"mtp","num_speculative_tokens":2}'
    ```

Use `--embedding --pooling none -c 16384 -b 16384 -ub 16384` for the tested configuration.

```bibtex
@article{x, title={y}}
```

```python
requests.post(url, json={"messages": m, "chat_template_kwargs": {"enable_thinking": False}, "temperature": 0.7})
```
"""


def test_extract_verbatim_with_line_ranges():
    ex = mp.extract_examples(CARD, "README.md", "Org/M-GGUF")
    fenced = [e for e in ex if e["kind"] != "inline"]
    assert [e["lines"] for e in fenced] == [[9, 10], [16, 16], [26, 26]]       # citation block skipped
    lines = CARD.split("\n")
    for e in fenced:                                                           # byte-exact text of those lines
        assert e["text"] == "\n".join(lines[e["lines"][0] - 1:e["lines"][1]])
    assert fenced[0]["tool"] == "llama.cpp" and fenced[1]["tool"] == "vllm" and fenced[0]["source"] == "Org/M-GGUF README.md:L9-10"
    inline = [e for e in ex if e["kind"] == "inline"]
    assert inline and inline[0]["text"] == "--embedding --pooling none -c 16384 -b 16384 -ub 16384" and inline[0]["lines"] == [19, 19]


def test_parse_llama_flags_against_build():
    (c,) = mp.parse_llama("./llama-cli -hf Org/M-GGUF:Q8_0 --jinja --color -ngl 99 -fa -sm row --temp 0.6 \\\n -c 40960 --no-context-shift --bogus 1", B)
    f = {x["canonical"]: x for x in c["flags"]}
    assert c["tool"] == "llama-cli"
    assert f["--ctx-size"]["value"] == "40960" and f["--gpu-layers"]["value"] == "99"
    assert f["--no-context-shift"]["value"] is None                  # a negative alias keeps its meaning
    assert f["--flash-attn"]["value"] is None and "older llama.cpp syntax" in f["--flash-attn"]["note"]
    assert f["--color"]["note"]                                      # -co takes on|off|auto in b11374
    assert f["--bogus"]["known"] is False and f["--temp"]["known"] is True
    (d,) = mp.parse_llama("GGML_X=1 SYSTEMONE_CONTEXT=32768 llama.cpp/build/bin/llama-server -m a.gguf --embedding --pooling none -ub 32768", B)
    assert d["env"] == {"GGML_X": "1", "SYSTEMONE_CONTEXT": "32768"} and d["tool"] == "llama-server"
    assert [x["canonical"] for x in d["flags"]] == ["--model", "--embedding", "--pooling", "--ubatch-size"]


def test_translate_vllm_sglang_and_requests():
    t = mp.translate({"tool": "vllm", "text": "vllm serve Org/M --port 8000 --max-model-len 262144 --reasoning-parser qwen3 "
                      "--tool-call-parser qwen3_coder --tensor-parallel-size 8 --speculative-config '{\"method\":\"mtp\"}'"})
    got = {(p["flag"], p["value"]) for p in t["params"]}
    assert ("-c", "262144") in got and ("--reasoning-format", "deepseek") in got and ("--jinja", None) in got
    why = {u["arg"].split()[0]: u["why"] for u in t["untranslatable"]}
    assert "--tensor-parallel-size" in why and "MTP" in why["--speculative-config"]
    y = mp.translate({"tool": "vllm", "text": "VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 vllm serve ... --hf-overrides '{\"text_config\": {\"rope_parameters\": "
                      "{\"rope_type\": \"yarn\", \"factor\": 4.0, \"original_max_position_embeddings\": 262144}}}' --max-model-len 1010000"})
    assert [(p["flag"], p["value"]) for p in y["params"]][:3] == [("--rope-scaling", "yarn"), ("--rope-scale", "4"), ("--yarn-orig-ctx", "262144")]
    r = mp.translate({"tool": "python", "text": 'requests.post(u, json={"max_tokens": 200, "chat_template_kwargs": {"enable_thinking": False}})'})
    assert ("--chat-template-kwargs", '{"enable_thinking":false}') in {(p["flag"], p["value"]) for p in r["params"]}
    o = mp.translate({"tool": "ollama", "text": "FROM ./m.gguf\nPARAMETER num_ctx 16384\nPARAMETER temperature 0.7\n"})
    assert {(p["flag"], p["value"]) for p in o["params"]} == {("-c", "16384"), ("--temp", "0.7")}


def test_flag_table_from_arg_cpp():
    src = textwrap.dedent('''
        add_opt(common_arg(
            {"-ub", "--ubatch-size"}, "N",
            string_format("physical maximum batch size (default: %d)", params.n_ubatch),
            [](common_params & params, int value) {
                params.n_ubatch = value;
            }
        ).set_env("LLAMA_ARG_UBATCH"));
        add_opt(common_arg(
            {"--context-shift"},
            {"--no-context-shift"},
            "whether to use context shift",
            [](common_params & params, bool value) {
                params.ctx_shift = value;
            }
        ).set_examples({LLAMA_EXAMPLE_COMPLETION, LLAMA_EXAMPLE_SERVER}));
    ''')
    f = lf.parse_arg_cpp(src)
    assert f["-ub"]["nargs"] == 1 and f["-ub"]["env"] == "LLAMA_ARG_UBATCH" and f["--ubatch-size"] is f["-ub"]
    assert f["--no-context-shift"]["nargs"] == 0 and f["--no-context-shift"]["neg"] == ["--no-context-shift"]
    assert lf.supports({"flags": f}, "--context-shift") and not lf.supports({"flags": f}, "--context-shift", "LLAMA_EXAMPLE_PERPLEXITY")
    for name in ("b11374", "b11539", "b11540", "b11541"):        # pinned builds, read from source at their tags
        b = lf.load(name)
        assert b and b["commit"] and lf.supports(b, "--pooling") and lf.supports(b, "--chat-template-file") and lf.supports(b, "--rope-scaling")
    assert "gemma-embedding2" not in lf.load("b11374")["archs"] and "gemma-embedding2" in lf.load("b11539")["archs"]
    assert "edlm" in lf.load("nace-edlm-cdcf65d")["archs"]


EMBED_RP = {"kind": "embed", "native_ctx": 8192, "native_ctx_source": "card L45", "yarn": None, "items": [
    mp.item(mp.REQ, "--embeddings", None, "s", "w"), mp.item(mp.REQ, "--pooling", "mean", "s", "w"),
    mp.item(mp.REQ, "--ubatch-size", "${slot_ctx}", "s", "w"), mp.item(mp.REQ, "--batch-size", "${slot_ctx}", "s", "w"),
    mp.item(mp.REQ, "@prompt", "task: search result | query: ", "s", "w", client=True)]}


def test_required_enforcement():
    argv, errs, notes = mp.launch_items(EMBED_RP, 8192, 1, B)
    assert argv == ["--embeddings", "--pooling", "mean", "--ubatch-size", "8192", "--batch-size", "8192"] and not errs
    assert any("task: search result" in n for n in notes)                     # client requirement documented
    old = ["-m", "x.gguf", "-c", "8192", "-np", "1", "--embeddings"]            # the embed node before #51
    miss = mp.missing_required(EMBED_RP, old, 8192, 1, B)
    assert any(m.startswith("REQUIRED --pooling") for m in miss) and any("--ubatch-size" in m for m in miss)
    assert mp.missing_required(EMBED_RP, old + argv[1:], 8192, 1, B) == []
    assert mp.missing_required(EMBED_RP, old + ["--pooling", "cls"] + argv[3:], 8192, 1, B) == ["REQUIRED --pooling is cls, the card needs mean"]
    # past the native window: YaRN when the card documents it, else an error
    rp = dict(EMBED_RP, yarn={"type": "yarn", "factor": 4.0, "original_ctx": 8192}, yarn_source="card L1124")
    a, e, _ = mp.launch_items(rp, 16384, 1, B)
    assert e == [] and a[-6:] == ["--rope-scaling", "yarn", "--rope-scale", "4", "--yarn-orig-ctx", "8192"]
    a, e, _ = mp.launch_items(EMBED_RP, 16384, 1, B)
    assert e and "exceeds the model's native window 8192" in e[0]
    # an unsupported flag is a blocker, never dropped
    fake = {"name": "old", "flags": {k: v for k, v in B["flags"].items() if k != "--pooling"}}
    a, e, _ = mp.launch_items(EMBED_RP, 8192, 1, fake)
    assert "--pooling" not in a and any(x.startswith("BLOCKER: --pooling") for x in e)
    # RECOMMENDED: needed unless overridden; ">=" minimums are checked, not emitted
    rp = {"kind": "chat", "native_ctx": 262144, "items": [mp.item(mp.REC, "--temp", "1.0", "s", "w"), mp.item(mp.REC, "--ctx-size", ">=131072", "s", "w")]}
    assert mp.launch_items(rp, 32768, 1, B)[0] == ["--temp", "1.0"]
    miss = mp.missing_required(rp, ["-c", "32768"], 32768, 1, B)
    assert len(miss) == 2 and any("must be >=131072" in m for m in miss)
    assert mp.missing_required(rp, ["-c", "32768"], 32768, 1, B, {"temp": True, "ctx-size": True}) == []


def _inp(meta_tmpl, repo_tmpl, curated):
    return {"repo": "o/m-GGUF", "revision": "a" * 40, "file": "m-Q8_0.gguf", "entry": {}, "docs": {}, "doc_meta": [],
            "meta": {"general.architecture": "qwen3", "tokenizer.chat_template": meta_tmpl},
            "templates": {"o/m": {"text": repo_tmpl, "file": "chat_template.jinja", "path": "/x"}}, "curated": curated}


def test_template_hash_check():
    r = mp.analyze(_inp("{{ a }}", "{{ b }}", {}))
    assert r["template"]["same"] is False and any(p.startswith("chat template:") for p in r["problems"])
    sha = mp.sha256s("{{ b }}")
    r = mp.analyze(_inp("{{ a }}", "{{ b }}", {"template": {"use": "repo", "sha256": sha, "reason": "GGUF drops tool calls"}}))
    assert not r["problems"]
    tf = [i for i in r["required_params"]["items"] if i["flag"] == "--chat-template-file"]
    assert tf and tf[0]["class"] == "REQUIRED" and tf[0]["value"] == "${template:%s}" % sha
    r = mp.analyze(_inp("{{ a }}", "{{ c }}", {"template": {"use": "repo", "sha256": sha, "reason": "x"}}))
    assert any("neither the GGUF's nor the repo's" in p for p in r["problems"])        # upstream changed: decide again
    r = mp.analyze(_inp("{{ a }}", "{{ a }}", {}))
    assert r["template"]["same"] is True and not r["problems"] and r["template"]["use"] == "gguf"


def test_curated_quotes_are_verified():
    docs = {"o/m": {"README.md": "a\nThe recommended serving context is 16,384 tokens.\n"}}
    assert mp.verify_quote("o/m README.md:L2", "serving context is 16,384", docs)[0]
    ok, why = mp.verify_quote("o/m README.md:L1", "serving context is 16,384", docs)
    assert not ok and "quote not found" in why
    assert not mp.verify_quote("o/m README.md:L2", None, docs)[0]


def test_stop_tokens():
    st = mp.stop_analysis({"eos_token_id": [7, 9]}, {"added_tokens_decoder": {"7": {"content": "<|im_end|>"}, "9": {"content": "<|weird|>"}}},
                          {"tokenizer.ggml.eos_token_id": 7}, B["eog"])
    assert [w["eog_by"] for w in st["tokens"]] == ["GGUF tokenizer.ggml.eos_token_id", None] and st["missing"][0]["text"] == "<|weird|>"


def test_registered_model_parameter_entries_are_analyzed():
    """Every registered entry was analyzed; prospective curations need not be registered yet."""
    entries = {f[:-5]: json.load(open(os.path.join(ROOT, "registry", "models", f), encoding="utf-8"))
               for f in os.listdir(os.path.join(ROOT, "registry", "models")) if f.endswith(".json")}
    for eid, e in entries.items():
        assert e.get("required_params"), eid
        if str(e.get("weights") or "").startswith("absent"):
            continue                    # damp-run (survey) entries: classified later, not runnable
        assert not [p for p in e.get("params_problems") or [] if p.startswith(("curated", "chat template:"))], (eid, e.get("params_problems"))


def test_validate_graph_args_and_usage():
    import validate_graph as vg
    with pytest.raises(SystemExit) as ex:
        vg.parse_argv(["--bogus"])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        vg.parse_argv(["--args"])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        vg.parse_argv(["--help"])
    assert ex.value.code == 0
    g = vg.load(os.path.join(ROOT, "graph.yaml"))
    g["_path"] = os.path.join(ROOT, "graph.yaml")
    a = vg.server_args(g, "embed")
    s = " ".join(a)
    assert "--embeddings" in a and "--pooling mean" in s and "--ubatch-size 8192" in s and "--batch-size 8192" in s


def test_hermes_harness_rejects_unknown_and_helps(capsys):
    import hermes_harness as hh
    with pytest.raises(SystemExit) as ex:
        hh.parse_argv(["--help"])
    assert ex.value.code == 0 and "usage:" in capsys.readouterr().out
    with pytest.raises(SystemExit) as ex:
        hh.parse_argv(["--bogus"])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        hh.parse_argv(["chat"])          # a stray word is not passed to hermes silently
    assert ex.value.code == 2
    assert hh.parse_argv(["--render-only", "--", "chat", "-q", "x"])[2:] == ("render", None, True, ["chat", "-q", "x"])
    hh.ACCEPT_LICENSES = False
    hh.parse_argv(["--accept-licenses"])
    assert hh.ACCEPT_LICENSES is True
    hh.ACCEPT_LICENSES = False


# ------------------------------------------------------------------ scripts/serve.sh
def _serve_env(tmp_path, args, server_body):
    d = tmp_path / "repo"
    (d / "scripts").mkdir(parents=True)
    shutil.copy(os.path.join(ROOT, "scripts", "serve.sh"), d / "scripts" / "serve.sh")
    shutil.copytree(os.path.join(ROOT, "lib"), d / "lib")
    (d / "graph.yaml").write_text("{}\n")
    srv = tmp_path / "fake-server"
    srv.write_text("#!/bin/sh\n" + server_body)
    srv.chmod(srv.stat().st_mode | stat.S_IEXEC)
    model = tmp_path / "m.gguf"
    model.write_text("x")
    (d / "scripts" / "validate_graph.py").write_text("print(%r)\n" % (str(srv) + " -m " + str(model) + " " + args))
    # licenses.py stub: exit status from LICENSE_RC (0 = accepted)
    (d / "scripts" / "licenses.py").write_text("import os, sys\nsys.exit(int(os.environ.get('LICENSE_RC', '0')))\n")
    env = dict(os.environ, FAMILIA_MEMCAP="0", FAMILIA_LOG_DIR=str(tmp_path / "logs"), CALLS=str(tmp_path / "calls"))
    env.pop("GGML_VK_VISIBLE_DEVICES", None)
    return d, env


LOGGER = """
log=""; prev=""
for a in "$@"; do [ "$prev" = "--log-file" ] && log="$a"; prev="$a"; done
printf 'vk=%s|%s\\n' "${GGML_VK_VISIBLE_DEVICES-unset}" "$*" >> "$CALLS"
"""


def _calls(tmp_path):
    p = tmp_path / "calls"
    return p.read_text().splitlines() if p.exists() else []


def test_serve_vulkan_failure_retries_on_cpu_with_vulkan_hidden(tmp_path):
    body = LOGGER + """n=$(wc -l < "$CALLS")
if [ "$n" -eq 1 ]; then echo "ggml_vulkan: Error: device lost" > "$log"; exit 1; fi
exit 0
"""
    d, env = _serve_env(tmp_path, "-ngl 99 --jinja", body)
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "coder"], env=env, capture_output=True, text=True)
    c = _calls(tmp_path)
    assert r.returncode == 0 and len(c) == 2, (r.stderr, c)
    assert "-ngl 99" in c[0] and c[0].startswith("vk=unset|")
    assert "-ngl 0" in c[1] and c[1].startswith("vk=|")             # Vulkan hidden (set, empty), not unset


def test_serve_other_failure_is_not_retried(tmp_path):
    d, env = _serve_env(tmp_path, "-ngl 99", LOGGER + 'echo "ggml_vulkan: Found 1 Vulkan devices" > "$log"; echo "error: bad arg" >> "$log"; exit 1\n')
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "coder"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and len(_calls(tmp_path)) == 1
    d, env = _serve_env(tmp_path / "b", "-ngl 0", LOGGER + 'echo "ggml_vulkan: Error: x" > "$log"; exit 1\n')
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "coder"], env=env, capture_output=True, text=True)
    c = _calls(tmp_path / "b")
    assert r.returncode == 1 and len(c) == 1 and c[0].startswith("vk=|")   # -ngl 0: Vulkan hidden, no pointless retry


def test_serve_embed_needs_pooling_and_model(tmp_path):
    d, env = _serve_env(tmp_path, "-ngl 0 --embeddings -ub 8192", LOGGER + "exit 0\n")
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "embed"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "without --pooling" in r.stderr and not _calls(tmp_path)
    d, env = _serve_env(tmp_path / "b", "-ngl 0 --embeddings --pooling mean", LOGGER + "exit 0\n")
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "embed"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and len(_calls(tmp_path / "b")) == 1
    (tmp_path / "b" / "m.gguf").unlink()
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "embed"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "not found" in r.stderr
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "--help"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "Launch a graph node" in r.stdout


def test_serve_needs_accepted_licenses(tmp_path):
    d, env = _serve_env(tmp_path, "-ngl 0", LOGGER + "exit 0\n")
    env["LICENSE_RC"] = "1"
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "coder"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "licenses not accepted" in r.stderr and not _calls(tmp_path)
    (d / "scripts" / "licenses.py").unlink()
    r = subprocess.run(["sh", str(d / "scripts" / "serve.sh"), "coder"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "licenses.py not found" in r.stderr and not _calls(tmp_path)
