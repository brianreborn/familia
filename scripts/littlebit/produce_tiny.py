#!/usr/bin/env python3
"""PIPELINE-EXERCISE ONLY. Makes a small LittleBit checkpoint in the upstream
SamsungLabs/LittleBit on-disk format from a dense llama GGUF (e.g. stories15M), on CPU.

This is NOT the paper's recipe (no real-data QAT, no multi-GPU KD). It runs upstream's own
LittleBitLinear init (Dual-SVID, optional --use-itq = LittleBit-2) and then optionally a short
self-distillation QAT (--qat-steps) against the dense model on sequences sampled from that
dense model. Every output is labeled `familia_provenance: pipeline-exercise`.

Needs: torch, transformers, safetensors, gguf, and a local checkout of SamsungLabs/LittleBit
(--upstream; CC BY-NC 4.0, not vendored into familia).
"""
import argparse, json, os, sys, time
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True); ap.add_argument("--upstream", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--eff-bit", type=float, default=1.0)
    ap.add_argument("--residual", action="store_true"); ap.add_argument("--use-itq", action="store_true")
    ap.add_argument("--kv-factor", type=float, default=1.0)
    ap.add_argument("--qat-steps", type=int, default=0); ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seq", type=int, default=64); ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0); ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    import torch
    torch.manual_seed(a.seed); torch.set_num_threads(a.threads)
    sys.path.insert(0, a.upstream)
    import quantization.utils  # upstream has a circular import; this order resolves it
    from quantization.modules import LittleBitLinear
    from quantization.functions import STEBinary, SmoothSign
    from safetensors.torch import save_file
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hfllama import dense_hf_from_gguf
    model, cfg = dense_hf_from_gguf(a.gguf)
    teacher, _ = dense_hf_from_gguf(a.gguf)
    model.train(); teacher.eval()
    # same as upstream quant_util.patch_inst(exclude_names=["lm_head"]) with kv_factor -> ratio_factor
    t0 = time.time()
    for name, mod in model.named_modules():
        if "lm_head" in name or type(mod) is not torch.nn.Linear: continue
        mod.__class__ = LittleBitLinear
        kw = dict(do_train=True, quant_func=SmoothSign if a.qat_steps else STEBinary, eff_bit=a.eff_bit,
                  residual=a.residual, use_itq=a.use_itq)
        if name.endswith(("k_proj", "v_proj")): kw["ratio_factor"] = a.kv_factor
        mod.__quant_convert__(**kw)
    init_s = time.time() - t0
    log = []
    if a.qat_steps:
        params = [p for p in model.parameters() if p.requires_grad]
        opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0)
        bos = 1
        for step in range(a.qat_steps):
            with torch.no_grad():  # self-distillation data: sample from the dense teacher
                ids = torch.full((a.batch, 1), bos)
                ids = teacher.generate(ids, max_new_tokens=a.seq - 1, do_sample=True, top_k=40,
                                       pad_token_id=0, eos_token_id=None) if hasattr(teacher, "generate") else ids
                tl = teacher(ids).logits
            sl = model(ids).logits
            loss = torch.nn.functional.kl_div(torch.log_softmax(sl, -1), torch.log_softmax(tl, -1),
                                              log_target=True, reduction="batchmean") / ids.shape[1]
            opt.zero_grad(); loss.backward(); opt.step()
            if step % 10 == 0 or step == a.qat_steps - 1:
                log.append((step, float(loss))); print(f"qat step {step} kl/token {float(loss):.4f}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    sd = {}
    for name, mod in model.named_modules():
        if isinstance(mod, LittleBitLinear):
            for k, v in mod.state_dict(prefix=name + ".").items(): sd[k] = v.detach().contiguous()
    for k, v in model.state_dict().items():  # dense leftovers (embed, norms, lm_head)
        if not any(k.startswith(n + ".") for n, m in model.named_modules() if isinstance(m, LittleBitLinear)):
            sd[k] = v.detach().contiguous()
    save_file(sd, os.path.join(a.out, "model.safetensors"))
    lbc = {"quant_func": "SmoothSign" if a.qat_steps else "STEBinary", "eff_bit": a.eff_bit, "split_dim": 1024,
           "residual": a.residual, "kv_factor": a.kv_factor, "min_split_dim": 8, "use_itq": a.use_itq, "itq_n_iter": 50}
    json.dump(lbc, open(os.path.join(a.out, "littlebit_config.json"), "w"), indent=2)
    cfg.save_pretrained(a.out)
    prov = {"familia_provenance": "pipeline-exercise", "not": "paper recipe; tiny CPU self-distillation only",
            "source_gguf": os.path.abspath(a.gguf), "init_seconds": round(init_s, 2), "qat_steps": a.qat_steps,
            "qat_log": log, "seed": a.seed, "args": vars(a)}
    json.dump(prov, open(os.path.join(a.out, "familia_provenance.json"), "w"), indent=2)
    print(f"wrote {a.out} ({sum(v.numel()*v.element_size() for v in sd.values())/2**20:.2f} MiB of tensors)")

if __name__ == "__main__":
    main()
