"""Scale-down tests on a tiny GGUF (ggml-org/models tinyllamas/stories15M.gguf, F32, 94 MiB).
Set FAMILIA_TEST_GGUF and FAMILIA_LLAMA_BIN (dir with llama-quantize, llama-imatrix, llama-server); skipped otherwise.
Run: python3 -m unittest tests.test_scale_down -v"""
import json, os, shutil, subprocess, sys, tempfile, unittest
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GGUF, BIN = os.environ.get("FAMILIA_TEST_GGUF"), os.environ.get("FAMILIA_LLAMA_BIN")
PUB = {"repo": "ggml-org/models", "file": "tinyllamas/stories15M-q4_0.gguf",
       "sha256": os.environ.get("FAMILIA_TEST_PUB_SHA256")}

def run(*a): return subprocess.run([sys.executable, *a], capture_output=True, text=True, cwd=ROOT)

@unittest.skipUnless(GGUF and BIN, "set FAMILIA_TEST_GGUF and FAMILIA_LLAMA_BIN")
class ScaleDown(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.src = os.path.join(self.d, "src.gguf"); shutil.copy(GGUF, self.src)
        self.src_sha = subprocess.check_output(["sha256sum", self.src]).split()[0].decode()
        v = subprocess.run([os.path.join(BIN, "llama-server"), "--version"], capture_output=True, text=True)
        commit = (v.stdout + v.stderr).split("(")[1].split(")")[0]
        self.g = {"version": 1, "host": {"reserve_ram_mib": 0},
                  "runtimes": {"t": {"bin": os.path.join(BIN, "llama-server"), "tag": "t", "commit": commit, "archs": ["llama"]}},
                  "nodes": {"tiny": {"runtime": "t", "model": self.src, "arch": "llama", "ctx": 128, "parallel": 1,
                                     "kv_type": "f16", "port": 19990, "aliases": ["tiny"], "cache_ram_mib": 64}}, "agents": {}}
    def tearDown(self): shutil.rmtree(self.d)
    def write(self, sd):
        if sd is not None: self.g["nodes"]["tiny"]["scale_down"] = sd
        p = os.path.join(self.d, "graph.yaml"); yaml.safe_dump(self.g, open(p, "w")); return p

    def test_off_by_default(self):
        r = run("scripts/scale_down.py", "--graph", self.write(None))
        self.assertIn("nothing to do", r.stdout); self.assertFalse(os.path.exists(os.path.join(self.d, "graph.scaled.yaml")))

    def quant(self, qtype, **kw):
        out = os.path.join(self.d, f"tiny-{qtype}.gguf")
        sd = {"enabled": True, "backend": "llama-quantize", "type": qtype, "output": out,
              "quantize_bin": os.path.join(BIN, "llama-quantize"), "suffix": qtype.lower(), "port": 19991, **kw}
        return out, run("scripts/scale_down.py", "--graph", self.write(sd))

    def check_scaled(self, out):
        rec = json.load(open(out + ".scale-down.json"))
        self.assertEqual(rec["source_sha256"], self.src_sha)
        self.assertLess(rec["output_bytes"], rec["source_bytes"]); self.assertEqual(rec["arch"], "llama")
        self.assertEqual(subprocess.check_output(["sha256sum", self.src]).split()[0].decode(), self.src_sha)  # original untouched
        r = run("scripts/validate_graph.py", "--graph", os.path.join(self.d, "graph.scaled.yaml"))
        self.assertEqual(r.returncode, 0, r.stderr); return rec

    def test_q2_k(self):
        out, r = self.quant("Q2_K"); self.assertEqual(r.returncode, 0, r.stderr + r.stdout); self.check_scaled(out)

    def test_iq2_xxs_with_imatrix(self):
        out, r = self.quant("IQ2_XXS", imatrix_bin=os.path.join(BIN, "llama-imatrix"),
                            calibration=os.path.join(ROOT, "tests/fixtures/calib.txt"), imatrix_ctx=128, imatrix_chunks=8)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("imatrix_sha256", self.check_scaled(out)["params"])

    def test_iq_without_imatrix_refused(self):
        out, r = self.quant("IQ2_XXS"); self.assertNotEqual(r.returncode, 0); self.assertIn("importance matrix", r.stderr)

    def test_refuses_overwrite_and_self(self):
        out, r = self.quant("Q2_K"); self.assertEqual(r.returncode, 0)
        _, r = self.quant("Q2_K"); self.assertIn("refusing to overwrite", r.stderr)
        sd = {"enabled": True, "backend": "llama-quantize", "type": "Q2_K", "output": self.src, "quantize_bin": "x"}
        r = run("scripts/scale_down.py", "--graph", self.write(sd)); self.assertIn("must not be the original", r.stderr)

    def test_tampered_output_rejected(self):
        out, r = self.quant("Q2_K"); self.assertEqual(r.returncode, 0)
        open(out, "ab").write(b"\0" * 32)
        r = run("scripts/validate_graph.py", "--graph", os.path.join(self.d, "graph.scaled.yaml"))
        self.assertNotEqual(r.returncode, 0); self.assertIn("differs from scale-down manifest", r.stderr)

    def test_littlebit_tbd(self):
        sd = {"enabled": True, "backend": "littlebit", "output": os.path.join(self.d, "lb.gguf")}
        r = run("scripts/scale_down.py", "--graph", self.write(sd)); self.assertIn("TBD", r.stderr)

    @unittest.skipUnless(PUB["sha256"], "set FAMILIA_TEST_PUB_SHA256 to run the network test")
    def test_published(self):
        out = os.path.join(self.d, "tiny-pub.gguf")
        sd = {"enabled": True, "backend": "published", "output": out, "port": 19992, **PUB}
        r = run("scripts/scale_down.py", "--graph", self.write(sd)); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.check_scaled(out)["output_sha256"], PUB["sha256"])
        bad = dict(sd, output=os.path.join(self.d, "bad.gguf"), sha256="0" * 64)
        r = run("scripts/scale_down.py", "--graph", self.write(bad)); self.assertIn("sha256 mismatch", r.stderr)
        self.assertFalse(os.path.exists(bad["output"]))
