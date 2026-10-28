# Guardian weights (Dolphin3-Cyber-8B Q2_K)

Hermes Wiring follow-up for [familia#147](https://github.com/brianreborn/familia/issues/147).
Seatbelts and ready-check live with Boundary (`docs/guardian-nodes.md`,
`scripts/guardian_ready.py`). This page is only the **fetch → measure → planned→active**
path so the model server can reach READY.

## Expected pin

| Field | Value |
|---|---|
| `models.dolphin3-cyber-8b-q2k.gguf` | `~/.local/share/gguf/models/pentest/Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.gguf` |
| `models.dolphin3-cyber-8b-q2k.sha256` | registry HF LFS oid `8944d35b…ea91` (~3.0 GiB Q2_K) |
| Registry id | `RavichandranJ--Dolphin3-Cyber-8B-GGUF--Dolphin3.0-Llama3.1-8B-abliterated.Q2_K` |

Boundary ready-check should read **`models.dolphin3-cyber-8b-q2k.sha256`** (must not be
`unmeasured`). Nodes stay `planned` until local weights exist.

## Operator steps (host with disk + network)

Dry-run first (nothing written):

```sh
python3 scripts/activate_guardian_weights.py
# or: sh scripts/activate_guardian_weights.sh
```

1. **Fetch** (~3.0 GiB; not for CI):

   ```sh
   scripts/add-model.sh --fetch RavichandranJ/Dolphin3-Cyber-8B-GGUF \
     --quant Q2_K --role pentest --accept-licenses
   # equivalent: python3 scripts/activate_guardian_weights.py --fetch --write
   ```

2. **Measure** the local GGUF and pin sha (must match registry):

   ```sh
   python3 scripts/activate_guardian_weights.py \
     --measure ~/.local/share/gguf/models/pentest/Dolphin3.0-Llama3.1-8B-abliterated.Q2_K.gguf \
     --write
   ```

3. **Activate** (flips only status on nodes + pentests; never tools/scope/launch_test_only):

   ```sh
   python3 scripts/activate_guardian_weights.py --activate --write
   ```

   Touches: `nodes.miryam-pentest`, `nodes.angel-guardian`, and on a private graph
   `nodes.guardian`; `pentests.fleet`, `pentests.angel`. Leaves `tools.allow: []`
   and `launch_test_only: true`.

4. **Regenerate** private topologies:

   ```sh
   python3 scripts/generate_graph.py miryam
   python3 scripts/generate_graph.py angel
   ```

5. **Model-only start** (seatbelts still on):

   ```sh
   FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start
   ```

6. **Hermes READY** once llama-server reports READY for the guardian node:

   ```sh
   bash scripts/hermes.sh --agent pentest-ops
   # private angel: bash scripts/hermes.sh --graph generated/graph-angel.yaml --model guardian
   # fleet single:  bash scripts/hermes.sh --model miryam-pentest
   ```

`agents.pentest-ops` already aliases `main`/`auxiliary` → `guardian` with
`min_ctx: 8192` matching the guardian node ctx.

## galaxy1 / galaxy2

Fleet names for the A57 Termux phones (SSH via angel; legacy keys `phone7` /
`phone8`). Prefer those names in owned-fleet scope allowlists (Boundary). Place
and activate weights on **miryam** / **angel** first; phone guardian placement is
a later host-ready step after Termux disk + runtime are measured.

## Related

- [guardian-nodes.md](guardian-nodes.md) — seatbelts / launch-test
- [pentest-models.md](pentest-models.md) — model survey
