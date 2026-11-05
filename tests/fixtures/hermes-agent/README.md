Evidence for familia Android Hermes 64K floor (PR #321 R-2).

Fetched from upstream NousResearch/hermes-agent `main` on 2026-11-05:

- `agent/model_metadata.py`: `MINIMUM_CONTEXT_LENGTH = 64_000`
- `agent/agent_init.py` `_enforce_minimum_context`: rejects below the floor for
  custom/llama.cpp local endpoints; only LM Studio with an explicit positive
  `model.context_length` is exempt. No `HERMES_MIN_CONTEXT_LENGTH` env (PR #44932
  closed as not-planned). Maintainer: model.context_length cannot lower the floor
  (issues #11096, #8430).

This box did not have hermes-agent installed (`/snap/bin/hermes-agent` missing),
so a live `hermes` run at ctx=4096 was not possible here; the excerpts above are
the pinned upstream source of truth used by install-hermes-android.sh's gate.
