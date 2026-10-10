# C2C stage 1: slot KV shipping (#22)

Moves one llama-server slot's KV cache between two nodes that run the **same model**, using stock
llama-server features only:

- both servers start with `--slot-save-path DIR`
- source: `POST /slots/{id}?action=save {"filename": NAME}` writes `DIR/NAME`
- the file moves over a transport (`local` copy, SSH nexus, or BT from `feat/transport-poc`)
- destination: `POST /slots/{id}?action=restore {"filename": NAME}`

## Compatibility (refuse on any mismatch)

| Check | Graph (`kv_channels`, validator) | Live (`scripts/c2c/kv_ship.py`) |
|---|---|---|
| Same weights | same model `sha256` (must be measured unless planned) | sha256 of each GGUF file |
| Same runtime | same runtime `build` + `commit` | `/props` `build_info` |
| Same per-slot ctx | `ctx / parallel` equal | `/props` / `/slots` `n_ctx` |
| Same KV types | `kv_type` equal | `--src-kv` / `--dst-kv` (cache-type-k/v) |

The file sha256 is checked again after transfer, before restore. A `NAME.meta.json` sidecar records the fingerprint.

## Loopback test (box, verified 2026-10-09)

```
LD_LIBRARY_PATH=llama-b11539 sh scripts/c2c/loopback_test.sh llama-b11539/llama-server stories15M-q4_0.gguf
```
Result with ggml-org release b11539 (CPU) and `ggml-org/models` tinyllamas/stories15M-q4_0.gguf:
35 tokens saved (242,676 bytes), 35 restored, identical greedy output; server B processed 1 prompt
token instead of 20 (cache_n=19). Pytest runs it when `C2C_LLAMA_SERVER` and `C2C_GGUF` are set.

## Limits (stage 1)

- `kv_ship.py ship` runs in one process that can reach both servers and both slot dirs. For `--via nexus`
  it does `put` as `--src-host` and `get` as `--dst-host` from that same process, so cross-host use today
  means running on a host that holds both identities, or splitting into put on source / get + restore on dest
  by hand. The `bt` path calls `scripts/bt/{mktorrent.py,seed.sh,fetch.sh}`; it has **not** been tested here
  and the argument order should be checked against `feat/transport-poc` when the branches merge.
- Same model only. Cross-model KV projection is stage 2+.
- Mind the RAM rule: on miryam, don't run a second server next to the coder for this test.
