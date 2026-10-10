#!/usr/bin/env python3
"""M3 check: familia numpy runtime (lbref.py on .lbit.gguf) vs upstream PyTorch LittleBit
(HF Llama + upstream LittleBitLinear, weights loaded with upstream's own unpacking loader),
plus quality of the LittleBit model vs the dense original. Prints one JSON line."""
import argparse, json, os, sys
import numpy as np

def upstream_lb_model(ckpt, gguf_path, upstream):
    import torch
    sys.path.insert(0, upstream)
    import quantization.utils  # resolves upstream circular import
    from quantization.utils.quant_util import _load_and_process_state_dict
    from quantization.modules import LittleBitLinear
    from quantization.functions import STEBinary
    from hfllama import dense_hf_from_gguf
    lbc = json.load(open(os.path.join(ckpt, "littlebit_config.json")))
    m, _ = dense_hf_from_gguf(gguf_path)
    for name, mod in m.named_modules():
        if "lm_head" in name or type(mod) is not torch.nn.Linear: continue
        mod.__class__ = LittleBitLinear
        kw = dict(do_train=False, quant_func=STEBinary, eff_bit=lbc["eff_bit"], residual=lbc["residual"])
        if name.endswith(("k_proj", "v_proj")): kw["ratio_factor"] = lbc.get("kv_factor", 1.0)
        mod.__quant_convert__(**kw)
    sd, packed = _load_and_process_state_dict(ckpt, torch.float32)
    missing, unexpected = m.load_state_dict(sd, strict=False, assign=True)
    bad = [k for k in missing if "rotary" not in k]
    if bad or unexpected: raise SystemExit(f"upstream load mismatch: missing {bad[:5]} unexpected {unexpected[:5]}")
    for mod in m.modules():
        if isinstance(mod, LittleBitLinear): mod._binarized = True
    return m.eval()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--checkpoint", required=True); ap.add_argument("--lbit", required=True)
    ap.add_argument("--gguf", required=True); ap.add_argument("--upstream", required=True)
    ap.add_argument("--seqs", type=int, default=4); ap.add_argument("--len", type=int, default=64)
    a = ap.parse_args()
    import torch
    torch.manual_seed(0); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hfllama import dense_hf_from_gguf
    from lbref import Model
    dense, _ = dense_hf_from_gguf(a.gguf); dense.eval()
    up = upstream_lb_model(a.checkpoint, a.gguf, a.upstream); ref = Model(a.lbit)
    with torch.no_grad():  # eval text: sampled from the dense model (no external dataset on the box)
        ids = dense.generate(torch.ones((a.seqs, 1), dtype=torch.long), max_new_tokens=a.len - 1, do_sample=True,
                             top_k=40, pad_token_id=0, eos_token_id=None)
        tl = dense(ids).logits.numpy(); ul = up(ids).logits.numpy()
    nl = np.stack([ref.forward(s.tolist()) for s in ids])
    def lsm(x): x = x - x.max(-1, keepdims=True); return x - np.log(np.exp(x).sum(-1, keepdims=True))
    tgt = ids[:, 1:].numpy()
    def ppl(l): lp = lsm(l[:, :-1]); return float(np.exp(-np.take_along_axis(lp, tgt[..., None], -1).mean()))
    pd, pu = lsm(tl), lsm(ul)
    out = {"lbit": os.path.basename(a.lbit), "tokens": int(ids.numel()),
           "numpy_vs_upstream_max_abs_logit_diff": float(np.abs(nl - ul).max()),
           "numpy_vs_upstream_argmax_agree": float((nl.argmax(-1) == ul.argmax(-1)).mean()),
           "logit_abs_max": float(np.abs(ul).max()),
           "ppl_dense": ppl(tl), "ppl_littlebit_upstream": ppl(ul), "ppl_littlebit_numpy": ppl(nl),
           "top1_agree_vs_dense": float((ul.argmax(-1) == tl.argmax(-1)).mean()),
           "kl_dense_to_lb_per_token": float((np.exp(pd) * (pd - pu)).sum(-1).mean())}
    print(json.dumps(out))

if __name__ == "__main__":
    main()
