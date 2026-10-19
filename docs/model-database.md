# Model database (#51)

Every model familia serves has an entry built from its **full Hugging Face repo at a pinned
commit**, not just the `.gguf`. The entry decides the launch defaults (sampling, context),
and `scripts/validate_graph.py` fails when a node differs from it without a written reason.

## Where things live
| path | what |
|---|---|
| `registry/models/<id>.json` | one entry per model file. `<id>` = `ORG--NAME--<file stem>` |
| `~/.local/share/gguf/hf-meta/ORG--NAME/<sha>/` | the fetched repo snapshot (every file up to 50 MB, sha-verified) plus `snapshot.json`. `$GGUF_HOME/hf-meta` or `$FAMILIA_HF_META` when set. Not in git |
| `graph.yaml` `models.<m>.db` | the entry id of a graph model |
| `registry/records.jsonl` `model.db_id`, `model.revision`, `model.db_match` | the entry a measurement used. `db_id: null` with `db_note` when the record cannot be matched to one entry |
| code-bootstraps `config/models-manifest.json` | a compact copy of the card fields per candidate (`db_id`, `card_defaults`, `card_sampling_modes`, `card_ctx`, ...), one line per nested field so `scripts/lib/manifest.awk` still reads it |

## Fetching (stdlib only)
`scripts/hf_fetch.py` uses urllib, so nothing has to be installed:
- the file list comes from `https://huggingface.co/api/models/ORG/NAME/revision/REV?blobs=true` (size, LFS sha256, git blob id); downloads from `https://huggingface.co/ORG/NAME/resolve/<sha>/FILE`;
- a branch or tag is resolved to its commit SHA first and everything is stored and recorded under the SHA;
- files above `--max-bytes` (default 50 MB: the weights) are **not** downloaded. They are listed in `snapshot.json` / `repo_files` with size and LFS sha256 and `status: skipped`;
- every download is verified (LFS: sha256; others: git blob sha1) and written atomically; a rerun reuses verified files;
- `HF_TOKEN` is sent as a bearer token to huggingface.co only. It is dropped when a redirect leaves that host (CDN) and is never printed or logged;
- GGUF metadata of a remote file is read with HTTP Range requests (4 MB, growing up to 64 MB), so no weights are downloaded.

```
python3 scripts/hf_fetch.py ORG/NAME[@REV] [--max-bytes N] [--dry-run]   # snapshot only
python3 scripts/model_db.py ingest ORG/NAME[@REV] FILE [--local PATH] [--role ROLE]
python3 scripts/model_db.py backfill [--dry-run] [--only SUBSTR] [--skip-search] [--bootstraps DIR]
python3 scripts/model_db.py show ID | list
scripts/add-model.sh --fetch ORG/NAME[@REV] --quant Q4_K_M   # snapshot + that GGUF + manifest + entry
```

`backfill` collects every model already in use: code-bootstraps manifest candidates, `graph.yaml`
models, registry records, and GGUFs in the local model directories and the HF cache. A file that
names no repo is searched on Hugging Face and accepted only on an LFS sha256 match, or a unique
file name + size match (recorded in `match`). It then writes the entries, links `graph.yaml`
models and registry records, and projects the card fields into the manifest. Failures are listed
per repo and do not stop the other repos.

## Entry fields (schema 1)
| field | meaning |
|---|---|
| `id`, `repo`, `revision`, `file`, `sha256`, `bytes`, `quant`, `arch`, `roles` | the GGUF and the repo commit it came from (sha256 = the LFS oid) |
| `license`, `license_source` | from the card front matter, LICENSE file or base repo; `unknown` when none states it |
| `ctx`, `ctx_source` | trained context from the GGUF metadata |
| `card_ctx`, `card_ctx_source` | a context length the card states (file:line) |
| `base_model`, `base_revision`, `base_snapshot`, `base_repo_files` | the base repo (from `base_model` in the card), fetched the same way; sampling advice often lives only there |
| `card_sampling_sets` | every labelled parameter set the card contains, with `kind` (`recommended`, `example`, `benchmark`, `mention`), file:line and label |
| `card_sampling_modes` | the recommended sets by label (e.g. "Non-thinking mode for text tasks") |
| `card_defaults`, `card_defaults_source`, `card_default_set`, `card_defaults_how` | the set used as launch default, and why (see below). `null` when the card and `generation_config.json` state nothing |
| `card_default_mode`, `card_default_mode_source` | thinking / non-thinking default the card states |
| `card_commands`, `card_notes` | command lines (llama-server, llama-cli, ...) and usage notes (system prompt, stop tokens, chat template) quoted from the card |
| `chat_template`, `stop`, `rope`, `aux` | template hash and whether it differs from the base repo; stop tokens; RoPE/YaRN scaling; auxiliary files (mmproj, draft) |
| `gguf` | GGUF header metadata |
| `snapshot`, `repo_files` | snapshot path, fetched bytes, errors, gated flag; every repo file with size, sha256 and status |
| `found_in`, `match`, `local_check` | where backfill found the model; how a repo-less file was matched; local sha256 check (host, result, date) |
| `unknown`, `warnings` | what could not be determined, and disagreements (e.g. card ctx vs GGUF ctx) |
| `updated`, `by` | date and tool |

Card values are copied, never invented. Anything the card or config does not state stays `null`.

### How `card_defaults` is chosen
1. **Recommended sets** (a labelled set of at least 2 parameters, or a code block the card calls recommended). One set: it wins. Several: narrowed by the card's stated default mode (thinking / non-thinking), then by a "text"/"general" label, then by matching the repo's `generation_config.json`. Still several: ambiguous, `card_defaults` stays `null` and the node must pick one with `card_set`.
2. Otherwise the sampling values of `generation_config.json` (repo, then base repo).
3. Otherwise a single distinct code example from the card, flagged in `card_defaults_how`.

Benchmark settings ("Experimental settings", evaluation tables) and single values in prose are never used.

## Using the entry in the graph
```yaml
models:
  qwen35-2b-q4km:
    gguf: ...
    db: unsloth--Qwen3.5-2B-GGUF--Qwen3.5-2B-Q4_K_M
nodes:
  coder:
    model: qwen35-2b-q4km
    ctx: 65536
    override_reasons:
      ctx: "7270 MiB host with a 3072 reserve ..."
    # card_set: "Thinking mode for VL"   # another of the card's sets (needs override_reasons.card_set)
    # sampling: {temp: 0.6}              # explicit values (each needs override_reasons.<key>)
```
`validate_graph.py --args` (used by `scripts/serve.sh` and `scripts/hermes_harness.py`) adds the
card's sampling flags (`--temp`, `--top-p`, `--top-k`, `--min-p`, `--repeat-penalty`,
`--presence-penalty`, `--frequency-penalty`) for every non-embedding node; `sampling` values replace them.

`validate_graph.py` fails when:
- a model has no `db`, the entry file is missing, or the entry has no pinned 40-hex `revision`;
- the graph model's sha256, trained_ctx or arch disagrees with the entry;
- node `ctx` (per slot) differs from the card's context (or the GGUF's when the card states none) without `override_reasons.ctx`;
- a `sampling` key differs from the card without `override_reasons.<key>`;
- `card_set` is not exactly one of the card's sets, or is not the default set without `override_reasons.card_set`;
- the card's defaults are ambiguous and the node picks no `card_set`.

Each reason must be at least 10 characters and say why (a measurement, a RAM budget, a host limit).
A reason that is no longer needed is a warning.

code-bootstraps applies the same rule to `config/models-preset.ini` with
`scripts/check-card-defaults.py` (run by `scripts/check-manifests.sh`): `; override KEY: reason`
and `; card-set: LABEL` comments in the section; keys the preset leaves unset are compared at
llama.cpp's defaults.
