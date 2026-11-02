# Draft-model speculative decoding (#91)

**Intent:** make `llama.cpp --spec-type draft-simple` a configurable familia
serving option (registry + graph → serve argv), with Race seatbelts so draft +
target cannot silently oversubscribe CPU/RAM. Contrast with model-free n-gram
([#82](https://github.com/brianreborn/familia/issues/82)): ngram needs no extra
weights; draft loads a second GGUF **inside** the target's `llama-server`
(`-md`). Prefer **not** to revive silent `ngram-simple` fleet-wide defaults.

## Opt-in

`graph.yaml` → `speculative.coder-draft` ships as `status: planned`. Nothing is
emitted until you set `experimental` or `active` (and leave at most one
`active` speculative edge per target). Planned edges are not counted in the RAM
estimate and never appear in `validate_graph.py --args`.

```yaml
speculative:
  coder-draft:
    experimental: true
    status: planned          # flip to experimental|active to enable
    mode: draft
    target: coder
    spec_type: draft-simple
    draft: qwen35-08b-q4km
    draft_max: 8
    draft_min: 0
    p_min: 0.75
    draft_ngl: 0
```

## Serve argv

When enabled, `scripts/validate_graph.py` `server_args` appends (verified on
b11374 / b11539 `--help`; old `--draft-max` / `--draft-min` were removed
upstream):

```
-md <draft.gguf>
--spec-type draft-simple
--spec-draft-n-max <draft_max>
--spec-draft-n-min <draft_min>
--spec-draft-p-min <p_min>
-ngld <draft_ngl>
# optional: -ctkd / -ctvd when draft_kv_type is set
```

`scripts/serve.sh`, `scripts/start_graph.py`, Harness² `--start-node`, and any
hermes path that starts a node via `server_args` all pick this up — there is no
separate draft daemon and no orphan spawn.

## Exact per-weight-file params shape

Recorded for the default coder pairing (also as JSON under
`registry/examples/specdec-coder-draft-params.json`):

| Role | Model key | GGUF (graph path) | sha256 (prefix) | Notes |
|------|-----------|-------------------|-----------------|-------|
| target | `qwen35-2b-q4km` | `~/.local/share/gguf/models/coder/Qwen3.5-2B-Q4_K_M.gguf` | `aaf42c8b7c3c…` | node `coder`, `-t 3`, ctx 65536, kv q8_0, ngl 0 |
| draft | `qwen35-08b-q4km` | `~/.local/share/gguf/models/draft/Qwen3.5-0.8B-Q4_K_M.gguf` | `bd258782e35f…` | same `qwen35` vocab; `draft_max=8`, `p_min=0.75`, `ngld=0` |

db ids: `unsloth--Qwen3.5-2B-GGUF--Qwen3.5-2B-Q4_K_M` +
`unsloth--Qwen3.5-0.8B-GGUF--Qwen3.5-0.8B-Q4_K_M`.

Dump the live shape:

```bash
python3 -c "import yaml,sys; sys.path.insert(0,'scripts'); import specdec_seatbelts as S; \
 g=yaml.safe_load(open('graph.yaml')); import json; print(json.dumps(S.params_shape(g,'coder-draft'), indent=2))"
```

## Race seatbelts (`scripts/specdec_seatbelts.py`)

| Check | Action |
|-------|--------|
| `status: planned` | no argv, no RAM charge |
| draft GGUF missing (experimental/active, `check_files`) | **refuse** |
| target `-t` > sprint 6, or same-host active threads + target > 6 | **refuse** (`cpu_oversubscribed`) |
| target `-t` > resident 4 (or host sum > 4) | **warn** |
| `parallel` > 6 with draft | **refuse**; > 4 **warn** |
| Cold start | draft is in-process (`-md`); never spawn a second server. If a start path is touched, keep `DETACH_MODE=screen-attached` only (this box: dry argv / unit tests only) |

Hooks: `preflight_node` from `start_graph.validate_local_nodes`,
`harness2.start_node`, and `validate` (warnings folded into `WARNINGS`; errors
into validate errs when files are checked). `serve.sh` also refuses if `-md`
path is missing.

## Hermes + Harness²

- **Harness²:** `scripts/harness2.py start_node` → `server_args` + `preflight_node`.
- **Hermes:** `scripts/hermes.sh` / modes start servers through the same graph
  serve path; enabled draft flags ride on the coder node's argv.
- **Bench:** `scripts/perf/spec_bench.py` A/B none vs draft-nN vs ngram on
  plain / hermes / Harness² workloads (greedy, byte-identical lossless check).

## Deferred live measure (CentOS + phone)

Not run from this PR / this box (no host access; no non-screen llama starts):

1. On CentOS and phone8 under `scripts/with-host-lock` (or host `big.lock`):
   ```bash
   DETACH_MODE=screen-attached python3 scripts/perf/spec_bench.py \
     --bin "$LLAMA_SERVER" --target "$TARGET_GGUF" --draft "$DRAFT_GGUF" \
     --n-max 4,8 --threads 3 --ctx 8192 --out /tmp/spec91
   ```
2. Record for each weight file: exact argv, tg/pp, draft acceptance,
   RSS delta, lossless sha match vs none.
3. Paste numbers into this doc (or `docs/perf/YYYY-MM-DD-spec-draft.md`) and
   flip `coder-draft` only after a measured win on that host.
4. Keep `#82` in mind: ngram-simple can make mixed turns ~6.8× slower on miryam;
   prefer `ngram-mod` if comparing.

Prior box CPU A/B (2026-10-19, Qwen3.5-2B + 0.8B draft) did **not** pay for
fresh answers (draft cost ≈ savings); re-measure on edit-heavy / CentOS /
phone before enabling fleet-wide. See `docs/perf/2026-10-19-tuning.md` §8.
