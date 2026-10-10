"""Build a transformers LlamaForCausalLM from a dense llama GGUF (F32/F16), undoing llama.cpp's q/k permute."""
import numpy as np
from gguf import GGUFReader
from lbformat import unpermute_rows, GGUF2HF

def gguf_kv(r, k, d=None):
    f = r.fields.get(k)
    return d if f is None else f.contents()

def dense_hf_from_gguf(path):
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM
    r = GGUFReader(path); a = gguf_kv(r, "general.architecture")
    if a != "llama": raise SystemExit(f"only arch llama is supported here, got {a!r}")
    T = {t.name: np.array(t.data, dtype=np.float32) for t in r.tensors}
    nh = gguf_kv(r, f"{a}.attention.head_count"); nkv = gguf_kv(r, f"{a}.attention.head_count_kv", nh)
    cfg = LlamaConfig(vocab_size=T["token_embd.weight"].shape[0], hidden_size=gguf_kv(r, f"{a}.embedding_length"),
                      intermediate_size=gguf_kv(r, f"{a}.feed_forward_length"), num_hidden_layers=gguf_kv(r, f"{a}.block_count"),
                      num_attention_heads=nh, num_key_value_heads=nkv, max_position_embeddings=gguf_kv(r, f"{a}.context_length"),
                      rms_norm_eps=gguf_kv(r, f"{a}.attention.layer_norm_rms_epsilon"),
                      rope_theta=gguf_kv(r, f"{a}.rope.freq_base", 10000.0), tie_word_embeddings="output.weight" not in T,
                      attn_implementation="eager", torch_dtype="float32")
    m = LlamaForCausalLM(cfg)
    sd = {"model.embed_tokens.weight": T["token_embd.weight"], "model.norm.weight": T["output_norm.weight"]}
    if "output.weight" in T: sd["lm_head.weight"] = T["output.weight"]
    for i in range(cfg.num_hidden_layers):
        for g, h in GGUF2HF.items():
            w = T[f"blk.{i}.{g}.weight"]
            if g == "attn_q": w = unpermute_rows(w, nh)
            if g == "attn_k": w = unpermute_rows(w, nkv)
            sd[f"model.layers.{i}.{h}.weight"] = w
    m.load_state_dict({k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in sd.items()}, strict=False)
    return m, cfg
