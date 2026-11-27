# Embeddings status (2026-11-23)

Short answer: nothing in familia consumes embeddings today.

## What exists on main
- `graph.yaml:652-667`: node `embed` (embeddinggemma-2 Q8_0, miryam, port 9951)
  is `status: planned`. `start_graph` lists it as omitted, not started
  (`tests/test_start_graph.py:32`).
- Deferred by design: issue #38 "Defer EmbeddingGemma-2 (embed node) until
  further notice". DESIGN.md:271-277 describes the role only.
- Supporting code is validation only: `scripts/model_db.py:1109-1111`
  (embed nodes need `--embeddings`), `scripts/validate_graph.py:602`,
  `scripts/hermes_modes.py:44` (embed is not a chat mode),
  `scripts/model_params.py:335` (flag derivation).

## What does not exist
No caller of `/v1/embeddings`, and no vector store (faiss, sqlite-vec,
chroma), cosine/similarity search, retrieval, RAG or rerank code anywhere
on main. `rerank` is a DESIGN.md role name only.
Related ideas live only in issues: #38, #50 (embed role robustness),
#312 (RAG over raw history, research), #60 (memory survey).

## Running servers (read-only check, 2026-11-23 22:20 PT)
| host | pid | port | parent | RAM (RSS) | requests in log |
|---|---|---|---|---|---|
| angel | 98263 | 9932 | `sh scripts/serve.sh` (pid 66753, reparented to init, no screen) | ~277 MiB | 0 since start 16:38 |

Notes on the angel server: it is not in any screen session, uses
`--ctx-size 262144`, has no `--api-key` (bound to localhost only), and
port 9932 is also documented as the settings panel port
(`docs/announcements/CHANGELOG.md:59`).
No embed server was found on miryam, galaxy1 or galaxy2.

## Recommendation
Stop the idle angel server until a consumer lands (needs Brian's OK),
and keep the `embed` node `planned` per #38.
