#!/usr/bin/env python3
"""familia LittleBit reference CPU runtime (numpy). Loads a .lbit.gguf (or a dense llama GGUF)
and runs a llama forward pass. Correctness reference, not a fast server.
  python3 lbref.py MODEL.gguf --prompt-ids 1,9038,2501 --n 32
"""
import argparse, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lbformat import SCALES, unpack_signs, lb_linear, FORMAT_VERSION

class Model:
    def __init__(self, path):
        import gguf
        r = gguf.GGUFReader(path); kv = lambda k, d=None: r.fields[k].contents() if k in r.fields else d
        self.arch = kv("general.architecture")
        if self.arch != "llama": raise SystemExit(f"lbref: arch {self.arch!r} not supported (llama only)")
        self.quant = kv("familia.quant", "dense")
        if self.quant == "littlebit" and kv("littlebit.format_version") != FORMAT_VERSION:
            raise SystemExit(f"lbref: littlebit.format_version {kv('littlebit.format_version')} != {FORMAT_VERSION}")
        a = self.arch
        self.nh = kv(f"{a}.attention.head_count"); self.nkv = kv(f"{a}.attention.head_count_kv", self.nh)
        self.nl = kv(f"{a}.block_count"); self.eps = kv(f"{a}.attention.layer_norm_rms_epsilon")
        self.theta = kv(f"{a}.rope.freq_base", 10000.0); self.ctx = kv(f"{a}.context_length")
        T = {t.name: np.array(t.data) for t in r.tensors}
        self.tokens = kv("tokenizer.ggml.tokens")
        self.lin = {}
        for name in {n.rsplit(".", 2)[0] for n in T if ".lb." in n}:
            L = {}
            for p in ("lb", "lbr"):
                if f"{name}.{p}.U" not in T: continue
                d = {s: T[f"{name}.{p}.{s}"].astype(np.float32) for s in SCALES}
                d["U"] = unpack_signs(T[f"{name}.{p}.U"], d["u2"].size); d["V"] = unpack_signs(T[f"{name}.{p}.V"], d["v2"].size)
                L[p] = d
            L["bias"] = T.get(f"{name}.bias"); self.lin[name] = L
        self.dense = {k: v.astype(np.float32) for k, v in T.items() if ".lb" not in k}
        self.d = self.dense["token_embd.weight"].shape[1]; self.hd = self.d // self.nh

    def linear(self, x, name):
        if name in self.lin:
            L = self.lin[name]; y = sum(lb_linear(x, L, p) for p in ("lb", "lbr") if p in L)
            return y + L["bias"] if L["bias"] is not None else y
        return x @ self.dense[name + ".weight"].T

    def rms(self, x, w): return x / np.sqrt((x * x).mean(-1, keepdims=True) + self.eps) * w

    def rope(self, x, pos):  # llama.cpp LLAMA_ROPE_TYPE_NORM: adjacent pairs, on GGUF-permuted q/k
        hd = x.shape[-1]; inv = self.theta ** (-np.arange(0, hd, 2) / hd)
        ang = pos[:, None] * inv[None]; c, s = np.cos(ang)[:, None], np.sin(ang)[:, None]
        x0, x1 = x[..., 0::2], x[..., 1::2]; o = np.empty_like(x)
        o[..., 0::2] = x0 * c - x1 * s; o[..., 1::2] = x0 * s + x1 * c; return o

    def forward(self, ids):
        """Full-sequence causal forward; returns logits [len(ids), vocab]."""
        ids = np.asarray(ids); n = len(ids); pos = np.arange(n, dtype=np.float64)
        x = self.dense["token_embd.weight"][ids]
        mask = np.triu(np.full((n, n), -np.inf, dtype=np.float32), 1)
        for i in range(self.nl):
            b = f"blk.{i}."; h = self.rms(x, self.dense[b + "attn_norm.weight"])
            q = self.rope(self.linear(h, b + "attn_q").reshape(n, self.nh, self.hd), pos).astype(np.float32)
            k = self.rope(self.linear(h, b + "attn_k").reshape(n, self.nkv, self.hd), pos).astype(np.float32)
            v = self.linear(h, b + "attn_v").reshape(n, self.nkv, self.hd)
            rep = self.nh // self.nkv; k = np.repeat(k, rep, 1); v = np.repeat(v, rep, 1)
            att = np.einsum("qhd,khd->hqk", q, k) / np.sqrt(self.hd) + mask
            att = np.exp(att - att.max(-1, keepdims=True)); att /= att.sum(-1, keepdims=True)
            o = np.einsum("hqk,khd->qhd", att, v).reshape(n, self.d)
            x = x + self.linear(o, b + "attn_output")
            h = self.rms(x, self.dense[b + "ffn_norm.weight"])
            g = self.linear(h, b + "ffn_gate"); u = self.linear(h, b + "ffn_up")
            x = x + self.linear(g / (1 + np.exp(-g)) * u, b + "ffn_down")
        x = self.rms(x, self.dense["output_norm.weight"])
        W = self.dense.get("output.weight", self.dense["token_embd.weight"])
        return x @ W.T

    def greedy(self, ids, n):
        ids = list(ids)
        for _ in range(n): ids.append(int(self.forward(ids[-self.ctx:])[-1].argmax()))
        return ids

    def detok(self, ids):
        return "".join(self.tokens[i] for i in ids).replace("\u2581", " ") if self.tokens else str(ids)

VERSION = "familia-lbref lbref-v1 (format 1, numpy reference, no HTTP server)"

def main():
    if "--version" in sys.argv: print(VERSION); return
    ap = argparse.ArgumentParser(); ap.add_argument("model"); ap.add_argument("--prompt-ids", default="1")
    ap.add_argument("--n", type=int, default=32); a = ap.parse_args()
    m = Model(a.model); out = m.greedy([int(t) for t in a.prompt_ids.split(",")], a.n)
    print(json.dumps({"quant": m.quant, "ids": out, "text": m.detok(out)}))

if __name__ == "__main__":
    main()
