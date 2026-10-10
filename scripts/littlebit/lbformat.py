"""familia LittleBit on-disk format (.lbit.gguf), format_version 1. numpy + gguf only, no torch.

A .lbit.gguf is a normal GGUF v3 file (same general.architecture and tokenizer KVs as
the source model) in which every factorized linear layer `<name>.weight` is replaced by:

  <name>.lb.U   I32 [out, ceil(r/32)]   sign(U), bit-packed
  <name>.lb.V   I32 [r,   ceil(in/32)]  sign(V), bit-packed
  <name>.lb.u1  F32 [out]   row scale      <name>.lb.u2  F32 [r]  latent scale (U side)
  <name>.lb.v1  F32 [r]     latent scale   <name>.lb.v2  F32 [in] column scale
  and, if littlebit.residual, the same set under <name>.lbr.*

y = ((((x*v2) @ sign(V)^T) * (v1*u2)) @ sign(U)^T) * u1   (+ residual path)  (+ bias)

Bit packing is identical to SamsungLabs/LittleBit binary_packer: row-major int32 words,
LSB first, bit 1 = -1, bit 0 = +1, rows padded to a multiple of 32 with +1.
Non-factorized tensors (token_embd, output, norms) stay dense, as in upstream.
llama.cpp cannot load this file: KV familia.quant = "littlebit" marks it, and a graph
node using it must name a runtime that declares `quants: [littlebit]`.
"""
import numpy as np

FORMAT_VERSION = 1
PACKING = "i32-row-major-lsb-first-bit1=-1"
SCALES = ("u1", "u2", "v1", "v2")

def pack_signs(m):
    """m: 2-D array of {-1,+1} (or any real: sign, 0 -> +1). Returns int32 [rows, ceil(cols/32)]."""
    m = np.asarray(m); rows, cols = m.shape
    words = (cols + 31) // 32
    bits = np.zeros((rows, words * 32), dtype=np.uint8)
    bits[:, :cols] = (m < 0)
    b = bits.reshape(rows, words, 4, 8)
    by = np.packbits(b, axis=-1, bitorder="little")[..., 0]  # [rows, words, 4] bytes, little-endian
    return np.ascontiguousarray(by).view("<u4").reshape(rows, words).view(np.int32)

def unpack_signs(packed, cols, dtype=np.float32):
    packed = np.ascontiguousarray(packed, dtype=np.int32); rows, words = packed.shape
    by = packed.view(np.uint8).reshape(rows, words * 4)
    bits = np.unpackbits(by, axis=-1, bitorder="little")[:, :cols]
    return (1 - 2 * bits.astype(np.int8)).astype(dtype)

def lb_bits(out_f, in_f, r, residual):
    """Storage bits of one layer as stored here (signs 1 bit, scales F32 = 32 bit)."""
    paths = 2 if residual else 1
    return paths * (r * (out_f + in_f) + 32 * (out_f + in_f + 2 * r))

def upstream_eff_bits(out_f, in_f, r, residual):
    """Upstream LittleBitLinear._compute_eff_bits (scales counted as 16-bit)."""
    a, b = in_f, out_f
    num = r * 2 * (a + b + 16) + 32 * (a + b) if residual else r * (a + b + 16) + 16 * (a + b)
    return num / (a * b)

def lb_linear(x, L, path="lb"):
    """Reference forward. L: dict with U,V (unpacked float signs) and scales, per path prefix."""
    p = L[path]
    t = (x * p["v2"]) @ p["V"].T
    t = t * (p["v1"] * p["u2"])
    return (t @ p["U"].T) * p["u1"]

# llama.cpp's convert_hf_to_gguf permutes q/k rows for its rope layout.
def permute_rows(w, n_head):
    sh = w.shape
    return w.reshape(n_head, 2, sh[0] // n_head // 2, *sh[1:]).swapaxes(1, 2).reshape(sh)

def unpermute_rows(w, n_head):
    sh = w.shape
    return w.reshape(n_head, sh[0] // n_head // 2, 2, *sh[1:]).swapaxes(1, 2).reshape(sh)

HF2GGUF = {"self_attn.q_proj": "attn_q", "self_attn.k_proj": "attn_k", "self_attn.v_proj": "attn_v",
           "self_attn.o_proj": "attn_output", "mlp.gate_proj": "ffn_gate", "mlp.up_proj": "ffn_up",
           "mlp.down_proj": "ffn_down", "input_layernorm": "attn_norm", "post_attention_layernorm": "ffn_norm"}
GGUF2HF = {v: k for k, v in HF2GGUF.items()}
