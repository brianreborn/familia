"""KV estimates for GGUFs with attention and recurrent layers."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import validate_graph as vg  # noqa: E402


def test_numeric_gguf_arrays_keep_small_values(tmp_path):
    path = tmp_path / "arrays.gguf"
    def string(value):
        raw = value.encode()
        return struct.pack("<Q", len(raw)) + raw
    path.write_bytes(
        b"GGUF" + struct.pack("<IQQ", 3, 0, 2)
        + string("hybrid.attention.head_count_kv") + struct.pack("<IIQ3I", 9, 4, 3, 0, 4, 4)
        + string("hybrid.attention.sliding_window_pattern") + struct.pack("<IIQ3?", 9, 7, 3, False, True, False)
    )
    meta = vg.gguf_meta(path)
    assert meta["hybrid.attention.head_count_kv"][3] == (0, 4, 4)
    assert meta["hybrid.attention.sliding_window_pattern"][3] == (False, True, False)


def test_per_layer_kv_estimate_charges_only_attention_windows():
    meta = {
        "hybrid.block_count": 3,
        "hybrid.embedding_length": 2048,
        "hybrid.attention.head_count": 16,
        "hybrid.attention.head_count_kv": ("array", 3, None, (0, 4, 4)),
        "hybrid.attention.sliding_window_pattern": ("array", 3, None, (False, True, False)),
        "hybrid.attention.sliding_window": 256,
        "hybrid.attention.key_length": 128,
        "hybrid.attention.value_length": 128,
    }
    ctx = 262144
    expected = 4 * (256 + ctx) * 256 * vg.KV_BYTES["q4_0"] / 2**20
    assert vg.kv_mib(meta, "hybrid", ctx, "q4_0") == expected
    del meta["hybrid.attention.sliding_window"]
    assert vg.kv_mib(meta, "hybrid", ctx, "q4_0") is None
