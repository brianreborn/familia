"""tests for scripts/add_model.py: works on temp copies only, never the real manifest."""
import json, os, shutil, struct, subprocess, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import add_model  # noqa: E402

MANIFEST = {"_comment": "test manifest", "llama_cpp": {"tag": "b1"}, "candidates": [
    {"role": "general", "pick": "default", "repo": "org/General-GGUF", "revision": "a" * 40,
     "file": "General-Q4_K_M.gguf", "quant": "Q4_K_M", "bytes": 1, "sha256": "0" * 64,
     "license": "apache-2.0", "ctx": 4096, "tested": True},
    {"role": "coder", "pick": "default", "repo": "org/Coder-GGUF", "revision": "b" * 40,
     "file": "Coder-Q4_K_M.gguf", "quant": "Q4_K_M", "bytes": 1, "sha256": "1" * 64,
     "license": "apache-2.0", "ctx": 4096, "tested": True, "roles": ["coder", "general (maybe)"]},
    {"role": "embed", "pick": "default", "repo": "org/Embed-GGUF", "revision": "c" * 40,
     "file": "Embed-Q8_0.gguf", "quant": "Q8_0", "sha256": "2" * 64, "license": "apache-2.0",
     "ctx": 2048, "tested": False}]}
PRESET = """; test preset
version = 1

[*]
temp = 0.8
ctx-size = 4096

[general]
; generic chat
temp     = 0.7

[coder]
; coder
model = models/coder/old.gguf
temp  = 0.6
reasoning = off

[decision]
ctx-size = 8192

[embed]
; embed route
"""


def write_gguf(path, kv, n_tokens=5):
    """Tiny GGUF v3 header: the given scalar/str kvs plus a token array, no tensors."""
    def s(x):
        b = x.encode()
        return struct.pack("<Q", len(b)) + b
    items = list(kv.items())
    out = [b"GGUF", struct.pack("<I", 3), struct.pack("<QQ", 0, len(items) + 2)]
    for k, v in items:
        out.append(s(k))
        if isinstance(v, bool):
            out.append(struct.pack("<I", 7) + struct.pack("<?", v))
        elif isinstance(v, int):
            out.append(struct.pack("<I", 4) + struct.pack("<I", v))
        elif isinstance(v, float):
            out.append(struct.pack("<I", 6) + struct.pack("<f", v))
        elif isinstance(v, list):
            out.append(struct.pack("<I", 9) + struct.pack("<IQ", 8, len(v)) + b"".join(s(x) for x in v))
        else:
            out.append(struct.pack("<I", 8) + s(v))
    out.append(s("tokenizer.ggml.tokens") + struct.pack("<I", 9) + struct.pack("<IQ", 8, n_tokens)
               + b"".join(s("tok%d" % i) for i in range(n_tokens)))
    out.append(s("tokenizer.ggml.scores") + struct.pack("<I", 9) + struct.pack("<IQ", 6, n_tokens)
               + struct.pack("<%df" % n_tokens, *([0.0] * n_tokens)))
    with open(path, "wb") as f:
        f.write(b"".join(out) + b"\0" * 64)


@pytest.fixture
def env(tmp_path):
    boot = tmp_path / "boot"
    (boot / "config").mkdir(parents=True)
    (boot / "config" / "models-manifest.json").write_text(json.dumps(MANIFEST, indent=4))
    (boot / "config" / "models-preset.ini").write_text(PRESET)
    return boot


def run(boot, *args):
    return add_model.main(["--bootstraps", str(boot), *map(str, args)])


def manifest(boot):
    return json.loads((boot / "config" / "models-manifest.json").read_text())


def preset(boot):
    return (boot / "config" / "models-preset.ini").read_text()


CODER_CARD = """---
license: apache-2.0
base_model: Org/Tiny-Coder-1B
pipeline_tag: text-generation
tags:
- code
- gguf
library_name: transformers
---

# Tiny-Coder-1B-GGUF

## Best practices

- For thinking mode (`enable_thinking=True`), use `Temperature=0.6`, `TopP=0.95`, `TopK=20`, and `MinP=0`.
- For non-thinking mode, we suggest `Temperature=0.7`, `TopP=0.8`, `TopK=20`, and `MinP=0`.
- presence_penalty between 0 and 2 helps with repetitions.

```bash
./llama-server -m Tiny-Coder-1B-Q4_K_M.gguf \\
  --jinja --temp 0.7 --top-p 0.8 \\
  -md Tiny-Coder-draft-Q8_0.gguf
```
"""


def coder_dir(tmp_path):
    d = tmp_path / "Tiny-Coder-1B-GGUF"
    d.mkdir()
    (d / "README.md").write_text(CODER_CARD)
    (d / "config.json").write_text(json.dumps({"architectures": ["Qwen3ForCausalLM"], "model_type": "qwen3",
                                               "max_position_embeddings": 32768}))
    (d / "generation_config.json").write_text(json.dumps({"temperature": 0.6, "top_p": 0.95, "top_k": 20,
                                                          "eos_token_id": [7, 8]}))
    (d / "tokenizer_config.json").write_text(json.dumps({"eos_token": "<|im_end|>", "chat_template": "{{ x }}"}))
    write_gguf(d / "Tiny-Coder-1B-Q4_K_M.gguf", {"general.architecture": "qwen3", "general.name": "Tiny Coder 1B",
                                                 "general.file_type": 15, "qwen3.context_length": 40960,
                                                 "tokenizer.chat_template": "{{ x }}", "tokenizer.ggml.eos_token_id": 7})
    write_gguf(d / "mmproj-Tiny-Coder-F16.gguf", {"general.architecture": "clip", "general.file_type": 1})
    write_gguf(d / "Tiny-Coder-draft-Q8_0.gguf", {"general.architecture": "qwen3", "general.file_type": 7})
    return d


def test_gguf_header_skips_arrays(tmp_path):
    p = tmp_path / "x.gguf"
    write_gguf(p, {"general.architecture": "llama", "llama.context_length": 2048, "general.tags": ["a", "b"]}, n_tokens=1000)
    m = add_model.gguf_header(str(p))
    assert m["general.architecture"] == "llama" and m["llama.context_length"] == 2048
    assert m["general.tags"] == ["a", "b"]
    assert m["tokenizer.ggml.tokens"] == {"array": 1000} and m["tokenizer.ggml.scores"] == {"array": 1000}
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"NOPE" + b"\0" * 32)
    with pytest.raises(ValueError):
        add_model.gguf_header(str(bad))


def test_hf_dir_coder_inference_aux_and_card(env, tmp_path, capsys):
    d = coder_dir(tmp_path)
    assert run(env, d) == 0
    out = capsys.readouterr()
    e = [c for c in manifest(env)["candidates"] if c["file"] == "Tiny-Coder-1B-Q4_K_M.gguf"]
    assert len(e) == 1
    e = e[0]
    assert e["role"] == "coder" and e["pick"] == "local"
    assert e["quant"] == "Q4_K_M" and e["license"] == "apache-2.0" and e["base_model"] == "Org/Tiny-Coder-1B"
    assert e["ctx"] == 40960 and e["inferred"]["ctx"].startswith("GGUF")
    assert e["repo"] is None and e["revision"] is None
    assert len(e["sha256"]) == 64 and e["bytes"] == os.path.getsize(d / "Tiny-Coder-1B-Q4_K_M.gguf")
    modes = e["card_sampling_modes"]
    th = next(k for k in modes if k.startswith("For thinking mode"))
    nt = next(k for k in modes if k.startswith("For non-thinking mode"))
    assert modes[th] == {"temp": 0.6, "top-p": 0.95, "top-k": 20, "min-p": 0}
    assert modes[nt] == {"temp": 0.7, "top-p": 0.8, "top-k": 20, "min-p": 0}
    # two recommended sets, no stated default mode: generation_config.json (0.6/0.95/20) picks the thinking set
    assert e["card_defaults"] == modes[th] and e["card_default_set"] == th
    assert e["card_defaults_source"]["temp"].startswith("README.md:L")
    assert any(c["tool"] == "llama-server" and "--jinja" in c["command"] for c in e["card_commands"])
    kinds = sorted(a["kind"] for a in e["aux"])
    assert kinds == ["draft", "mmproj"]
    assert all(a["linked_to"] == "Tiny-Coder-1B-Q4_K_M.gguf" and len(a["sha256"]) == 64 for a in e["aux"])
    assert {a["arch"] for a in e["aux"]} == {"clip", "qwen3"}
    assert e["chat_template"]["same"] is True
    assert e["stop"]["eos_token"] == "<|im_end|>" and e["stop"]["eos_token_id"] == [7, 8]
    assert set(e["files"]) == {"README.md", "config.json", "generation_config.json", "tokenizer_config.json"}
    assert "role = coder" in out.out and "evidence: coder" in out.err
    # preset: [coder] model replaced, sections kept, non-thinking compared (reasoning = off)
    p = preset(env)
    assert "model = %s" % (d / "Tiny-Coder-1B-Q4_K_M.gguf") in p and "models/coder/old.gguf" not in p
    assert p.count("[") == PRESET.count("[") and "[decision]" in p and "; coder" in p
    assert "card temp" in out.err


def test_awk_reader_sees_flat_fields(env, tmp_path):
    awk = os.path.join(ROOT, "code-bootstraps-llama.cpp", "scripts", "lib", "manifest.awk")
    if not os.path.isfile(awk) or not shutil.which("awk"):
        pytest.skip("code-bootstraps-llama.cpp not checked out")
    assert run(env, coder_dir(tmp_path)) == 0
    mf = env / "config" / "models-manifest.json"
    got = subprocess.run(["awk", "-v", "match_kv=", "-v", "fields=role pick file sha256", "-f", awk, str(mf)],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    want = ["\t".join([c["role"], c["pick"], c["file"], c["sha256"]]) for c in manifest(env)["candidates"]]
    assert got == want


def test_embed_inferred_from_card_and_gguf(env, tmp_path):
    d = tmp_path / "emb"
    d.mkdir()
    (d / "README.md").write_text("---\nlicense: mit\npipeline_tag: sentence-similarity\nlibrary_name: sentence-transformers\n---\n# E\n")
    write_gguf(d / "e5-small-Q8_0.gguf", {"general.architecture": "bert", "bert.pooling_type": 1, "bert.context_length": 512})
    assert run(env, d, "--dry-run") == 0
    d2 = tmp_path / "emb2"     # no card at all: GGUF pooling_type alone decides
    d2.mkdir()
    write_gguf(d2 / "thing-Q8_0.gguf", {"general.architecture": "bert", "bert.pooling_type": 2})
    assert run(env, d2, "--no-preset") == 0
    e = manifest(env)["candidates"][-1]
    assert e["role"] == "embed" and e["license"] == "unknown" and "license" in e["unknown"]
    assert any(u.startswith("model card") for u in e["unknown"])


def test_general_inferred_and_ambiguity(env, tmp_path, capsys, monkeypatch):
    d = tmp_path / "gen"
    d.mkdir()
    (d / "README.md").write_text("---\nlicense: other\nlicense_name: lfm1.0\nlicense_link: LICENSE\npipeline_tag: text-generation\n---\n"
                                 "# G\n\nRecommended: temperature=0.3, min_p=0.15, repetition_penalty=1.05\n")
    write_gguf(d / "G-1B-Q4_0.gguf", {"general.architecture": "lfm2"})
    assert run(env, d, "--dry-run", "--json") == 0
    e = json.loads(capsys.readouterr().out)
    assert e["role"] == "general" and e["license"] == "lfm1.0 (LICENSE)"
    assert e["card_defaults"] == {"temp": 0.3, "min-p": 0.15, "repeat-penalty": 1.05}
    # nothing to go on: not a TTY -> exit 2 with a clear message
    d2 = tmp_path / "blank"
    d2.mkdir()
    (d2 / "mystery.gguf").write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 0))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert run(env, d2, "--dry-run") == 2
    assert "cannot infer the role" in capsys.readouterr().err
    # --type works as an alias of --role
    assert run(env, d2, "--dry-run", "--type", "decision") == 0


def test_legacy_role_file_and_idempotence(env, tmp_path):
    g = tmp_path / "Custom-Q5_K_M.gguf"
    write_gguf(g, {"general.architecture": "llama", "llama.context_length": 8192})
    assert run(env, "general", g) == 0
    n = len(manifest(env)["candidates"])
    e = manifest(env)["candidates"][-1]
    assert e["role"] == "general" and e["quant"] == "Q5_K_M" and e["ctx"] == 8192 and e["tested"] is False
    assert "model = %s" % g in preset(env)
    assert run(env, "general", g) == 0
    assert run(env, g, "--role", "general") == 0
    assert len(manifest(env)["candidates"]) == n
    # same file, another explicit role: a second entry (manifest allows one file in two roles)
    assert run(env, g, "--role", "coder", "--no-preset") == 0
    assert len(manifest(env)["candidates"]) == n + 1


def test_existing_entry_updated_not_duplicated(env, tmp_path, capsys):
    d = tmp_path / "models" / "coder"
    d.mkdir(parents=True)
    write_gguf(d / "Coder-Q4_K_M.gguf", {"general.architecture": "qwen3"})
    sha = add_model.sha256_file(str(d / "Coder-Q4_K_M.gguf"))
    m = manifest(env)
    m["candidates"][1]["sha256"] = sha
    (env / "config" / "models-manifest.json").write_text(json.dumps(m, indent=4))
    assert run(env, d, "--no-preset") == 0
    c = manifest(env)["candidates"]
    assert len(c) == 3
    assert c[1]["repo"] == "org/Coder-GGUF" and c[1]["pick"] == "default" and c[1]["tested"] is True
    assert c[1]["roles"] == ["coder", "general (maybe)"] and c[1]["ctx"] == 4096
    assert "role = coder" in capsys.readouterr().out


def test_dry_run_writes_nothing(env, tmp_path, capsys):
    before = ((env / "config" / "models-manifest.json").read_bytes(), preset(env))
    assert run(env, coder_dir(tmp_path), "--dry-run") == 0
    assert "dry run: nothing written" in capsys.readouterr().out
    assert before == ((env / "config" / "models-manifest.json").read_bytes(), preset(env))


def test_manifest_roundtrip_is_byte_identical(env):
    raw = (env / "config" / "models-manifest.json").read_text()
    assert add_model.dump_manifest(json.loads(raw)) == raw


def test_hf_cache_snapshot_and_flags(env, tmp_path):
    snap = tmp_path / "hub" / "models--org--Snap-GGUF" / "snapshots" / ("d" * 40)
    snap.mkdir(parents=True)
    write_gguf(snap / "Snap-Q8_0.gguf", {"general.architecture": "llama"})
    write_gguf(snap / "Snap-Q4_K_M.gguf", {"general.architecture": "llama"})
    assert run(env, snap, "--role", "general", "--no-preset") == 2       # two quants: must choose
    assert run(env, snap, "--role", "general", "--quant", "Q8_0", "--no-preset") == 0
    e = manifest(env)["candidates"][-1]
    assert e["repo"] == "org/Snap-GGUF" and e["revision"] == "d" * 40 and e["file"] == "Snap-Q8_0.gguf"
    # (b) explicit flags, no directory; --aux KIND=PATH
    card = tmp_path / "card.md"
    card.write_text("---\nlicense: apache-2.0\ntags: [code]\n---\n# X\n")
    aux = tmp_path / "tok.json"
    aux.write_text("{}")
    f = tmp_path / "X-Q4_K_M.gguf"
    write_gguf(f, {"general.architecture": "llama", "general.name": "X"})
    assert run(env, "--repo", "org/X-GGUF", "--revision", "e" * 40, "--file", f, "--card", card,
               "--aux", "tokenizer=%s" % aux, "--no-preset") == 0
    e = manifest(env)["candidates"][-1]
    assert e["role"] == "coder" and e["repo"] == "org/X-GGUF" and e["aux"][0]["kind"] == "tokenizer"
    assert run(env, f, "--aux", "bogus=%s" % aux, "--dry-run") == 2


def test_hf_local_dir_metadata(env, tmp_path):
    d = tmp_path / "local"
    md = d / ".cache" / "huggingface" / "download"
    md.mkdir(parents=True)
    write_gguf(d / "L-Q4_K_M.gguf", {"general.architecture": "llama"})
    sha = add_model.sha256_file(str(d / "L-Q4_K_M.gguf"))
    (md / "L-Q4_K_M.gguf.metadata").write_text("f" * 40 + "\n" + sha + "\n1.0\n")
    assert run(env, d, "--role", "general", "--repo", "org/L-GGUF", "--no-preset") == 0
    e = manifest(env)["candidates"][-1]
    assert e["revision"] == "f" * 40 and e["repo"] == "org/L-GGUF"


def test_preset_set_keeps_sections():
    lines = PRESET.split("\n")
    out = add_model.preset_set(lines, "embed", {"model": "x.gguf"})
    t = "\n".join(out)
    assert "[embed]\n; embed route\nmodel = x.gguf\n" in t and t.endswith("\n")
    out = add_model.preset_set(lines, "general", {"temp": "0.3", "min-p": "0.15"})
    t = "\n".join(out)
    assert "temp     = 0.3" in t and "min-p = 0.15\n\n[coder]" in t


def test_no_args_not_a_tty(env, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert add_model.main([]) == 2
    assert "Usage" in capsys.readouterr().err


def test_wrapper_help():
    r = subprocess.run(["bash", os.path.join(ROOT, "scripts", "add-model.sh"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--aux KIND=PATH" in r.stdout and "ROLE FILE.gguf" in r.stdout
