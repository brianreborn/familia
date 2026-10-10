"""LittleBit pipeline tests (no torch, no network): pack format, converter (incl. q/k rope permute),
numpy reference runtime, scale_down --method littlebit, validator rules.
Needs numpy, pyyaml and the gguf python package. Run: python3 -m unittest tests.test_littlebit -v"""
import json, os, struct, subprocess, sys, tempfile, shutil, unittest
import numpy as np, yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "littlebit"))
try:
    import gguf  # noqa
    from lbformat import pack_signs, unpack_signs, permute_rows, unpermute_rows
    from lbref import Model
    from convert import convert
except ImportError as e:
    gguf = None; IMPORT_ERR = e
LBREF = os.path.join(ROOT, "scripts", "littlebit", "lbref.py")
V, D, F, L, H = 64, 64, 96, 2, 4

def write_safetensors(path, tensors):
    dt = {np.float32: "F32", np.int32: "I32", np.int64: "I64"}
    hdr, off, blobs = {}, 0, []
    for k, a in tensors.items():
        a = np.ascontiguousarray(a); b = a.tobytes()
        hdr[k] = {"dtype": dt[a.dtype.type], "shape": list(a.shape), "data_offsets": [off, off + len(b)]}; off += len(b); blobs.append(b)
    h = json.dumps(hdr).encode(); h += b" " * (-len(h) % 8)
    with open(path, "wb") as f: f.write(struct.pack("<Q", len(h)) + h + b"".join(blobs))

def make_fixture(d, residual=False, seed=0):
    """Random tiny llama as an upstream-format LittleBit checkpoint + a dense GGUF holding the exact
    reconstructed weights (GGUF layout), so dense-GGUF and .lbit.gguf forwards must agree."""
    rng = np.random.default_rng(seed); sd, dense = {}, {}
    def lb(name, out_f, in_f, r):
        W = np.zeros((out_f, in_f))
        for suf in (("", "_R") if residual else ("",)):
            U = np.where(rng.random((out_f, r)) < .5, -1, 1); Vm = np.where(rng.random((r, in_f)) < .5, -1, 1)
            sc = {"u1": rng.random(out_f) * .1, "u2": rng.random(r), "v1": rng.random(r), "v2": rng.random(in_f) * .5}
            sd[f"{name}.U{suf}_packed"] = pack_signs(U); sd[f"{name}.V{suf}_packed"] = pack_signs(Vm)
            sd[f"{name}.U{suf}_shape"] = np.array(U.shape, np.int64); sd[f"{name}.V{suf}_shape"] = np.array(Vm.shape, np.int64)
            for k, v in sc.items(): sd[f"{name}.{k}{suf}"] = v.astype(np.float32)[None]
            W += (sc["u1"][:, None] * U) @ ((sc["v1"] * sc["u2"])[:, None] * Vm * sc["v2"][None])
        return W.astype(np.float32)
    emb = rng.standard_normal((V, D)).astype(np.float32); out = rng.standard_normal((V, D)).astype(np.float32) * .1
    sd["model.embed_tokens.weight"] = emb; sd["lm_head.weight"] = out; sd["model.norm.weight"] = np.ones(D, np.float32)
    dense.update({"token_embd.weight": emb, "output.weight": out, "output_norm.weight": np.ones(D, np.float32)})
    for i in range(L):
        p = f"model.layers.{i}."
        for hf, g, o, n in (("self_attn.q_proj", "attn_q", D, D), ("self_attn.k_proj", "attn_k", D, D), ("self_attn.v_proj", "attn_v", D, D),
                            ("self_attn.o_proj", "attn_output", D, D), ("mlp.gate_proj", "ffn_gate", F, D), ("mlp.up_proj", "ffn_up", F, D),
                            ("mlp.down_proj", "ffn_down", D, F)):
            W = lb(p + hf, o, n, 40)  # r=40: not a multiple of 32, exercises padding
            dense[f"blk.{i}.{g}.weight"] = permute_rows(W, H) if g in ("attn_q", "attn_k") else W
        for hf, g in (("input_layernorm", "attn_norm"), ("post_attention_layernorm", "ffn_norm")):
            w = (1 + .1 * rng.standard_normal(D)).astype(np.float32); sd[p + hf + ".weight"] = w; dense[f"blk.{i}.{g}.weight"] = w
    ck = os.path.join(d, "ck"); os.makedirs(ck); write_safetensors(os.path.join(ck, "model.safetensors"), sd)
    json.dump({"eff_bit": 1.0, "residual": residual, "kv_factor": 1.0}, open(os.path.join(ck, "littlebit_config.json"), "w"))
    json.dump({"num_attention_heads": H, "num_key_value_heads": H}, open(os.path.join(ck, "config.json"), "w"))
    w = gguf.GGUFWriter(os.path.join(d, "dense.gguf"), "llama")
    for k, v in (("llama.context_length", 32), ("llama.embedding_length", D), ("llama.feed_forward_length", F),
                 ("llama.attention.head_count", H), ("llama.block_count", L)): w.add_uint32(k, v)
    w.add_float32("llama.attention.layer_norm_rms_epsilon", 1e-5); w.add_string("general.name", "lb-test")
    for k, v in dense.items(): w.add_tensor(k, v)
    w.write_header_to_file(); w.write_kv_data_to_file(); w.write_tensors_to_file(); w.close()
    return ck, os.path.join(d, "dense.gguf")

def run(*a): return subprocess.run([sys.executable, *a], capture_output=True, text=True, cwd=ROOT)

@unittest.skipIf(gguf is None, "needs numpy + gguf")
class LittleBit(unittest.TestCase):
    def setUp(self): self.d = tempfile.mkdtemp()
    def tearDown(self): shutil.rmtree(self.d)

    def test_pack_matches_upstream_bit_order(self):
        m = np.ones((2, 33), np.int8); m[0, 0] = -1; m[1, 31] = -1; m[1, 32] = -1
        p = pack_signs(m)  # upstream binary_packer: LSB first, -1 -> bit 1, rows padded with +1
        self.assertEqual(p.shape, (2, 2)); self.assertEqual(p[0].tolist(), [1, 0]); self.assertEqual(p[1].tolist(), [-2**31, 1])
        self.assertTrue((unpack_signs(p, 33) == m).all())

    def test_permute_roundtrip(self):
        w = np.arange(64 * 3).reshape(64, 3); self.assertTrue((unpermute_rows(permute_rows(w, 4), 4) == w).all())

    def check_forward(self, residual):
        ck, dense = make_fixture(self.d, residual)
        out = os.path.join(self.d, "m.lbit.gguf"); convert(ck, dense, out)
        ids = [1, 5, 9, 2, 33, 7, 7, 60]
        a, b = Model(out).forward(ids), Model(dense).forward(ids)
        self.assertEqual(Model(out).quant, "littlebit")
        self.assertLess(np.abs(a - b).max(), 1e-3 * max(1, np.abs(b).max()))

    def test_converter_and_runtime_match_dense(self): self.check_forward(False)
    def test_residual(self): self.check_forward(True)

    def graph(self, **node):
        ck, dense = make_fixture(self.d)
        n = {"runtime": "lbref", "model": dense, "arch": "llama", "ctx": 32, "parallel": 1, "kv_type": "f16",
             "port": 19980, "aliases": ["t"], "cache_ram_mib": 1}
        n.update(node)
        g = {"version": 1, "host": {"reserve_ram_mib": 0},
             "runtimes": {"lbref": {"bin": LBREF, "tag": "lbref-v1", "commit": "lbref-v1", "archs": ["llama"],
                                    "quants": ["littlebit"], "kind": "reference"}},
             "nodes": {"t": n}, "agents": {}}
        p = os.path.join(self.d, "graph.yaml"); yaml.safe_dump(g, open(p, "w")); return p, ck

    def test_scale_down_from_checkpoint_and_validate(self):
        p, ck = self.graph()
        out = os.path.join(self.d, "t.lbit.gguf")
        r = run("scripts/scale_down.py", "--graph", p, "--node", "t", "--method", "littlebit", "--from-checkpoint", ck,
                "--output", out, "--runtime", "lbref", "--replace")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        rec = json.load(open(out + ".scale-down.json")); self.assertEqual(rec["backend"], "littlebit")
        sg = os.path.join(self.d, "graph.scaled.yaml"); g = yaml.safe_load(open(sg))
        self.assertEqual(g["nodes"]["t-sd"]["quant"], "littlebit")
        r = run("scripts/validate_graph.py", "--graph", sg); self.assertEqual(r.returncode, 0, r.stderr)
        r = run("scripts/validate_graph.py", "--graph", sg, "--args", "t-sd")
        self.assertNotEqual(r.returncode, 0); self.assertIn("not a llama-server", r.stderr + r.stdout)
        g["nodes"]["t-sd"].pop("quant"); yaml.safe_dump(g, open(sg, "w"))
        r = run("scripts/validate_graph.py", "--graph", sg); self.assertIn("must declare quant: littlebit", r.stderr)
        g["nodes"]["t-sd"]["quant"] = "littlebit"; g["runtimes"]["lbref"]["quants"] = []; yaml.safe_dump(g, open(sg, "w"))
        r = run("scripts/validate_graph.py", "--graph", sg); self.assertIn("does not declare quants", r.stderr)

    def test_dense_marked_littlebit_refused(self):
        p, _ = self.graph(quant="littlebit")
        r = run("scripts/validate_graph.py", "--graph", p); self.assertIn("no familia.quant=littlebit marker", r.stderr)

    def test_hf_jobs_planned_fails_loudly(self):
        p, _ = self.graph()
        r = run("scripts/scale_down.py", "--graph", p, "--node", "t", "--method", "littlebit", "--train-on", "hf-jobs",
                "--output", os.path.join(self.d, "x.lbit.gguf"), "--runtime", "lbref")
        self.assertNotEqual(r.returncode, 0); self.assertIn("planned", r.stderr)

    def test_littlebit_needs_runtime(self):
        p, ck = self.graph()
        r = run("scripts/scale_down.py", "--graph", p, "--node", "t", "--method", "littlebit", "--from-checkpoint", ck,
                "--output", os.path.join(self.d, "x.lbit.gguf"))
        self.assertNotEqual(r.returncode, 0); self.assertIn("needs 'runtime'", r.stderr)

if __name__ == "__main__":
    unittest.main()
