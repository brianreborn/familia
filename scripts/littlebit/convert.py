#!/usr/bin/env python3
"""Convert an upstream SamsungLabs/LittleBit checkpoint directory (model.safetensors[.index.json],
config.json, littlebit_config.json; packed signs as <name>.U_packed/.V_packed + <name>.U_shape/.V_shape)
into a familia .lbit.gguf (see lbformat.py). numpy + gguf only; no torch.

--base-gguf supplies tokenizer + metadata KVs (and dense tensors the checkpoint lacks); it must be
a GGUF of the same base model. Only llama-family HF names are mapped today; anything else fails loudly.
"""
import argparse, json, os, re, struct, sys
import numpy as np
import gguf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lbformat import FORMAT_VERSION, PACKING, SCALES, HF2GGUF, permute_rows, lb_bits

DT = {"F32": np.float32, "F16": np.float16, "I32": np.int32, "I64": np.int64, "I8": np.int8, "U8": np.uint8, "BOOL": np.bool_}

def read_safetensors(path):
    out = {}
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]; hdr = json.loads(f.read(n)); base = 8 + n
        for k, m in hdr.items():
            if k == "__metadata__": continue
            s, e = m["data_offsets"]; f.seek(base + s); buf = f.read(e - s)
            if m["dtype"] == "BF16":
                a = (np.frombuffer(buf, "<u2").astype(np.uint32) << 16).view(np.float32)
            elif m["dtype"] in DT: a = np.frombuffer(buf, DT[m["dtype"]])
            else: raise SystemExit(f"convert: unsupported safetensors dtype {m['dtype']} for {k}")
            out[k] = a.reshape(m["shape"]) if m["shape"] else a.reshape(())
    return out

def load_ckpt(d):
    idx = os.path.join(d, "model.safetensors.index.json")
    files = sorted(set(json.load(open(idx))["weight_map"].values())) if os.path.exists(idx) else ["model.safetensors"]
    sd = {}
    for f in files: sd.update(read_safetensors(os.path.join(d, f)))
    return sd

def hf_to_gguf_name(stem):
    if stem == "lm_head": return "output"
    if stem == "model.embed_tokens": return "token_embd"
    if stem == "model.norm": return "output_norm"
    m = re.fullmatch(r"model\.layers\.(\d+)\.(.+)", stem)
    if m and m.group(2) in HF2GGUF: return f"blk.{m.group(1)}.{HF2GGUF[m.group(2)]}"
    raise SystemExit(f"convert: no GGUF name mapping for {stem!r} (only llama-family names are supported)")

def convert(ckpt, base_gguf, out, provenance=None):
    sd = load_ckpt(ckpt)
    lbc = json.load(open(os.path.join(ckpt, "littlebit_config.json")))
    hfc = json.load(open(os.path.join(ckpt, "config.json")))
    nh, nkv = hfc["num_attention_heads"], hfc.get("num_key_value_heads", hfc["num_attention_heads"])
    residual = bool(lbc.get("residual"))
    base = gguf.GGUFReader(base_gguf)
    arch = base.fields["general.architecture"].contents()
    w = gguf.GGUFWriter(out + ".part", arch)
    for k, f in base.fields.items():
        if k.startswith("GGUF.") or k == "general.architecture": continue
        t = f.types[0]
        if t == gguf.GGUFValueType.ARRAY:
            w.add_array(k, f.contents())
        else:
            w.add_key_value(k, f.contents(), t)
    w.add_string("familia.quant", "littlebit")
    w.add_uint32("littlebit.format_version", FORMAT_VERSION)
    w.add_string("littlebit.sign_packing", PACKING)
    w.add_bool("littlebit.residual", residual)
    w.add_float32("littlebit.eff_bit_target", float(lbc.get("eff_bit", -1)))
    w.add_string("littlebit.upstream_config", json.dumps(lbc, sort_keys=True))
    if provenance: w.add_string("familia.provenance", provenance)
    stems = sorted({k[: -len(".U_packed")] for k in sd if k.endswith(".U_packed")})
    if not stems: raise SystemExit("convert: checkpoint has no LittleBit layers (*.U_packed)")
    written, lb_total, dense_equiv = set(), 0, 0
    for stem in stems:
        g = hf_to_gguf_name(stem)
        nhh = nh if g.endswith("attn_q") else nkv if g.endswith("attn_k") else None
        for src, dst in (("", "lb"), ("_R", "lbr")) if residual else (("", "lb"),):
            U = sd[f"{stem}.U{src}_packed"].astype(np.int32); V = sd[f"{stem}.V{src}_packed"].astype(np.int32)
            ush, vsh = [int(x) for x in sd[f"{stem}.U{src}_shape"]], [int(x) for x in sd[f"{stem}.V{src}_shape"]]
            sc = {s: sd[f"{stem}.{s}{src}"].astype(np.float32).reshape(-1) for s in SCALES}
            if not (ush[1] == vsh[0] == sc["u2"].size == sc["v1"].size and ush[0] == sc["u1"].size and vsh[1] == sc["v2"].size):
                raise SystemExit(f"convert: inconsistent shapes in {stem}{src}: U{ush} V{vsh}")
            if U.shape != (ush[0], (ush[1] + 31) // 32) or V.shape != (vsh[0], (vsh[1] + 31) // 32):
                raise SystemExit(f"convert: packed size mismatch in {stem}{src}")
            if nhh:  # HF -> llama.cpp rope layout: permute output rows (whole packed rows) and u1
                U = permute_rows(U, nhh); sc["u1"] = permute_rows(sc["u1"], nhh)
            w.add_tensor(f"{g}.{dst}.U", np.ascontiguousarray(U)); w.add_tensor(f"{g}.{dst}.V", np.ascontiguousarray(V))
            for s in SCALES: w.add_tensor(f"{g}.{dst}.{s}", np.ascontiguousarray(sc[s]))
        lb_total += lb_bits(ush[0], vsh[1], ush[1], residual); dense_equiv += ush[0] * vsh[1]
        b = f"{stem}.bias"
        if b in sd: w.add_tensor(f"{g}.bias", sd[b].astype(np.float32))
        written.add(g)
    dense_names = set()
    for k, v in sd.items():
        if k.endswith(".weight") and not any(k.startswith(s + ".") for s in stems):
            n = hf_to_gguf_name(k[: -len(".weight")]) + ".weight"
            w.add_tensor(n, np.ascontiguousarray(v.astype(np.float32))); dense_names.add(n)
    for t in base.tensors:  # dense tensors the checkpoint lacks (e.g. tied output)
        if t.name.endswith(".weight") and t.name[: -len(".weight")] not in written and t.name not in dense_names:
            w.add_tensor(t.name, np.ascontiguousarray(np.array(t.data, dtype=np.float32)))
    w.write_header_to_file(); w.write_kv_data_to_file(); w.write_tensors_to_file(); w.close()
    os.replace(out + ".part", out)
    return {"layers": len(stems), "linear_bpw_stored": lb_total / dense_equiv, "linear_params": dense_equiv}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--base-gguf", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    prov = os.path.join(a.checkpoint, "familia_provenance.json")
    r = convert(a.checkpoint, a.base_gguf, a.out, open(prov).read() if os.path.exists(prov) else None)
    print(json.dumps(r))

if __name__ == "__main__":
    main()
